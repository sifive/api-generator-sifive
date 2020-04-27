#!/usr/bin/env python3.7

import argparse
import string
import sys
import textwrap
import typing as t
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import json5
import jsonref

PlainJSONType = t.Union[dict, list, t.AnyStr, float, bool]
JSONType = t.Union[PlainJSONType, t.Iterator[PlainJSONType]]


@dataclass(frozen=True)
class AddressBlock:
    """
    A DUH address block.

    Note that for legacy reasons, this does not include the registers in the
    address block. The previous code in this script primarily operated on
    registers, and introducing a level of hierarchy for the address blocks
    would require essentially a rewrite of this entire script.
    """
    name: str
    baseAddress: int
    range: int
    width: int

@dataclass(frozen=True)
class RegisterField:
    """
    Description of a bit field within a register.
    """
    name: str
    bit_offset: int  # Bit offset relative to the register containing this field
    bit_width: int

    @classmethod
    def make_field(cls, name: str, bit_offset: int, bit_width: int) -> "RegisterField":
        return cls(name, bit_offset, bit_width)


@dataclass(frozen=True)
class Register:
    """
    Description of memory-mapped control register within a device
    """
    name: str
    offset: int  # in bytes
    width: int  # in bits
    fields: t.List[RegisterField]
    address_block: AddressBlock

    @classmethod
    def make_register(
        cls,
        name: str,
        offset: int,
        width: int,
        fields: t.List[RegisterField],
        address_block: AddressBlock,
    ) -> "Register":
        if width not in (8, 16, 32, 64):
            raise Exception(f'Invalid register width {width}, for register '
                            f'{name}.\n'
                            f'Width should be not 8, 16, 32, or 64.\n'
                            f'Please fix the register width in DUH document.')
        return cls(name, offset, width, fields, address_block)


###
# templates
###
def generate_vtable_declarations(device_name: str,
                                 reg_list: t.List[Register]) -> str:
    """
    Generate the vtable entries for a device and set of registers. This
    creates the declarations for function pointers for all the driver functions.
    This is used to provide a single point for all functions that can be used
    for multiple devices.
    :param device_name: the name of the device
    :param reg_list: a list of Register objects for the device
    :return: the c code for the vtable entries
    """

    rv = []

    for a_reg in reg_list:
        for field in a_reg.fields:
            reg_name = a_reg.name.lower()
            field_name = field.name.lower()
            size = a_reg.width

            func_name_prefix = f'v_{device_name}_{reg_name}_{field_name}'

            write_func = f'    void (*{func_name_prefix}_write)(uint32_t * {device_name}_base, uint{size}_t data);'
            read_func = f'    uint{size}_t (*{func_name_prefix}_read)(uint32_t  *{device_name}_base);'

            rv.append(write_func)
            rv.append(read_func)

    return '\n'.join(rv)


def generate_metal_vtable_definition(devices_name: str) -> str:
    """
    Generate the vtable and base address variable definitions
    for the given device name

    :param devices_name:
    :return: The c code for the metal device
    """

    return f'    uint32_t *{devices_name}_base;\n' + \
           f'    struct metal_{devices_name}_vtable vtable;'


def generate_protos(device_name: str, reg_list: t.List[Register]) -> str:
    """
    Generate the function prototypes for a given device and register list.

    :param device_name: The device name
    :param reg_list: the list of registers for the device
    :return: the c language prototypes for the device
    """

    rv = []

    dev_struct = f'const struct metal_{device_name} *{device_name}'

    for a_reg in reg_list:
        for field in a_reg.fields:
            reg_name = a_reg.name.lower()
            field_name = field.name.lower()
            size = a_reg.width

            func_name_prefix = f'metal_{device_name}_{reg_name}_{field_name}'
            write_func = f'void {func_name_prefix}_write({dev_struct}, uint{size}_t data);'
            read_func = f'uint{size}_t {func_name_prefix}_read({dev_struct});'

            rv.append(write_func)
            rv.append(read_func)

    get_device = f'const struct metal_{device_name} *get_metal_{device_name}' \
                 f'(uint8_t index);'
    rv.append(get_device)

    return '\n'.join(rv)


# The template for the .h file

METAL_DEV_HDR_TMPL = \
    """
    #include <metal/compiler.h>
    #include <stdint.h>
    #include <stdlib.h>
    #include <bsp_${device}/${vendor}_${device}.h>

    #ifndef ${vendor}_${device}${index}_h
    #define ${vendor}_${device}${index}_h

    struct metal_${device};

    struct metal_${device}_vtable {
    ${vtable}
    };

    struct metal_${device} {
    ${metal_device}
    };

    //__METAL_DECLARE_VTABLE(metal_${device})
        
    ${protos}
    #endif
    """


def generate_metal_dev_hdr(vendor, device, index, reglist):
    """

    :param vendor: The name of the vendor creating the device
    :param device: the name of the device created.
    :param index: the index of the device
    :param reglist: the list of registers for the device
    :return: a string which is the .h for file the device driver
    """
    template = string.Template(textwrap.dedent(METAL_DEV_HDR_TMPL))

    return template.substitute(
        vendor=vendor,
        device=device,
        cap_device=device.upper(),
        index=str(index),
        # base_address=hex(base_address),
        vtable=generate_vtable_declarations(device, reglist),
        metal_device=generate_metal_vtable_definition(device),
        protos=generate_protos(device, reglist)
    )


# the template for the driver .c file
METAL_DEV_DRV_TMPL = \
    """
    #include <stdint.h>
    #include <stdlib.h>

    #include <${device}/${vendor}_${device}${index}.h>
    #include <metal/compiler.h>
    #include <metal/io.h>

    // Private utility functions

    // Write data into register field by only changing bits within that field.
    static inline void write_field(
        volatile uint32_t *register_base,
        uint32_t field_offset,
        uint32_t field_width,
        uint32_t field_data
    ) {
        const uint32_t shifted_field_data = field_data << field_offset;
        const uint32_t mask = (field_width == 32) ? 0xffffffff : ((1 << field_width) - 1) << field_offset;
        const uint32_t original_data = *register_base;

        const uint32_t cleared_data = original_data & (~mask);
        const uint32_t new_data = cleared_data | shifted_field_data;

        *register_base = new_data;
    }

    // Read data from register field by shifting and masking only that field.
    static inline uint32_t read_field(
        volatile uint32_t *register_base,
        uint32_t field_offset,
        uint32_t field_width
    ) {
        const uint32_t original_data = *register_base;
        const uint32_t mask = (field_width == 32) ? 0xffffffff : (1 << field_width) - 1;
        return (original_data >> field_offset) & mask;
    }

    // Private register field access functions
    ${base_functions}

    // Public register field access functions
    ${metal_functions}

    // Static data
    struct metal_${device} metal_${device}s[${cap_device}_COUNT];
    
    struct metal_${device}* ${device}_tables[${cap_device}_COUNT];
    uint8_t ${device}_tables_cnt = ${cap_device}_COUNT;

    void init_devices()
    {
        uint32_t bases[]=${cap_device}_BASES;
        int i;
        
        for (i = 0; i < ${cap_device}_COUNT; i++){
            ${def_vtable}
            ${device}_tables[i] = &metal_${device}s[i];
        }
    }

    const struct metal_${device}* get_metal_${device}(uint8_t idx)
    {
        static uint8_t initted = 0;
        
        if (!initted){
            init_devices();
            initted = 1;
        }
        
        if (idx >= ${device}_tables_cnt)
            return NULL;
        return ${device}_tables[idx];
    }
    """


def generate_def_vtable(device: str, reg_list: t.List[Register]) -> str:
    """
    Generate vtable settings for vtable declaration in .c file

    :param device: the name of the device
    :param reg_list: the register list for the device
    :return: the declarations in the vtable for the driver .c file
    """
    rv: t.List[str] = []
    head = f'metal_{device}s[i].{device}_base = bases[i];'
    rv.append(head)
    for a_reg in reg_list:
        for field in a_reg.fields:
            reg_name = a_reg.name.lower()
            field_name = field.name.lower()
            vtable_prefix = f'v_{device}_{reg_name}_{field_name}'
            base_func_prefix = f'{device}_{reg_name}_{field_name}'
            write_func = f'{" " * 8}metal_{device}s[i].vtable.{vtable_prefix}_write = {base_func_prefix}_write;'
            read_func = f'{" " * 8}metal_{device}s[i].vtable.{vtable_prefix}_read = {base_func_prefix}_read;'
            rv.append(write_func)
            rv.append(read_func)

    return '\n'.join(rv)


def generate_base_functions(device: str, reg_list: t.List[Register], include_address_block: bool) -> str:
    """
    Generates the basic, not exported register access functions for
    a given device and register list.

    :param device: the name of the device
    :param reg_list: the list of registers for the device.
    :param include_address_block: If True, include the address block name in
        the generated C macros.
    :return:  the c code for the register access functions
    """
    cap_device = device.upper()
    rv: t.List[str] = []

    for a_reg in reg_list:
        address_block = a_reg.address_block
        cap_addr_block_name = address_block.name.upper()
        for field in a_reg.fields:
            name = a_reg.name.lower()
            cap_name = a_reg.name.upper()
            field_name = field.name.lower()
            cap_field_name = field.name.upper()
            size = a_reg.width

            # Compute actual register offset by assuming 32-bit registers,
            # since the existing header macros do not directly tell you the
            # offset of the registers.

            if include_address_block:
                macro_prefix = f"{cap_device}_REGISTER_{cap_addr_block_name}_{cap_name}_{cap_field_name}"
            else:
                macro_prefix = f"{cap_device}_REGISTER_{cap_name}_{cap_field_name}"

            # Bit offset of field relative to base of device register block
            field_bit_offset_from_base = macro_prefix

            # Byte offset of register relative to base of device register block
            reg_byte_offset = f"(({field_bit_offset_from_base} / 32) * 4)"

            # Bit offset of field relative to base of register
            field_bit_offset_from_register = f"({field_bit_offset_from_base} % 32)"
            field_width = f"{macro_prefix}_WIDTH"

            write_func = f"""
                void {device}_{name}_{field_name}_write(uint32_t *{device}_base, uint{size}_t data)
                {{
                    uintptr_t control_base = (uintptr_t){device}_base;
                    volatile uint32_t *register_base = (uint32_t *)(control_base + {reg_byte_offset});
                    write_field(register_base, {field_bit_offset_from_register}, {field_width}, data);
                }}
                """

            rv.append(textwrap.dedent(write_func))

            read_func = f"""
                uint{size}_t {device}_{name}_{field_name}_read(uint32_t *{device}_base)
                {{
                    uintptr_t control_base = (uintptr_t){device}_base;
                    volatile uint32_t *register_base = (uint32_t *)(control_base + {reg_byte_offset});
                    return read_field(register_base, {field_bit_offset_from_register}, {field_width});
                }}
                """

            rv.append(textwrap.dedent(read_func))

    return '\n'.join(rv)


def generate_metal_function(device: str, reg_list: t.List[Register]) -> str:
    """
    Generates the exported register access functions for
    a given device and register list.

    :param device: the name of the device
    :param reg_list: the list of registers for the device.
    :return:  the c code for the exported register access functions
    """

    rv: t.List[str] = []

    for a_reg in reg_list:
        for field in a_reg.fields:
            name = a_reg.name.lower()
            field_name = field.name.lower()
            size = a_reg.width

            write_func = f"""
                void metal_{device}_{name}_{field_name}_write(const struct metal_{device} *{device}, uint{size}_t data)
                {{
                    if ({device} != NULL)
                        {device}->vtable.v_{device}_{name}_{field_name}_write({device}->{device}_base, data);
                }}
                """
            rv.append(textwrap.dedent(write_func))

            read_func = f"""
                uint{size}_t metal_{device}_{name}_{field_name}_read(const struct metal_{device} *{device})
                {{
                    if ({device} != NULL)
                        return {device}->vtable.v_{device}_{name}_{field_name}_read({device}->{device}_base);
                    return (uint{size}_t)-1;
                }}
                """

            rv.append(textwrap.dedent(read_func))

    return '\n'.join(rv)


def generate_metal_dev_drv(vendor, device, index, reglist, include_address_block):
    """
    Generate the driver source file contents for a given device
    and register list

    :param vendor: the vendor creating the device
    :param device: the device
    :param index: the index of the device used
    :param reglist: the list of registers
    :param include_address_block: If True, include the address block name in
        the generated C macros.
    :return: a string containing of the c code for the basic driver
    """
    template = string.Template(textwrap.dedent(METAL_DEV_DRV_TMPL))

    return template.substitute(
        vendor=vendor,
        device=device,
        cap_device=device.upper(),
        index=str(index),
        base_functions=generate_base_functions(device, reglist,
                                               include_address_block),
        metal_functions=generate_metal_function(device, reglist),
        def_vtable=generate_def_vtable(device, reglist)
    )


# ###
# Support for parsing duh file
# ###

def _jsonref_loader(uri: str, **kwargs) -> JSONType:
    """
    Custom jsonref loader that can handle relative file paths.

    If the value of a JSON reference is a relative file path, load it relative
    to the parent file containing the reference. Otherwise, delegate to the
    normal jsonref loader.
    """
    parsed_uri = urlparse(uri)
    # Assume that if netloc is present, then the URI is a web URI, and
    # otherwise that the URI refers to a relative file path.
    if parsed_uri.netloc:
        return jsonref.jsonloader(uri, **kwargs)
    else:
        return json5.loads(Path(uri).read_text())


def load_json5_with_refs(f_name: str) -> JSONType:
    with open(f_name) as fp:
        return jsonref.JsonRef.replace_refs(
            json5.load(fp),
            base_uri=f_name,
            loader=_jsonref_loader,
        )


###
# main
###


def handle_args():
    """
    :return:
    """
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "-d",
        "--duh-document",
        help="The path to the DUH document",
        required=True
    )

    parser.add_argument(
        "--vendor",
        help="The vendor name",
        required=True,
    )

    parser.add_argument(
        "-D",
        "--device",
        help="The device name",
        required=True,
    )

    parser.add_argument(
        "-m",
        "--metal-dir",
        help="The path to the drivers/metal directory",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "-x",
        "--overwrite-existing",
        action="store_true",
        default=False,
        help="overwrite existing files"
    )

    parser.add_argument(
        "--always-include-address-block-in-macros",
        action="store_true",
        default=False,
        help=(
            "If set, always include the address block name in the C macro "
            " names. By default, the address block name is only included when "
            "there are multiple address blocks in order to preserve the "
            "legacy C macro names generated for the single-address block case."
        )
    )

    return parser.parse_args()


def main():
    args = handle_args()

    vendor = args.vendor
    device = args.device
    m_dir_path = args.metal_dir
    overwrite_existing = args.overwrite_existing
    always_include_address_block = args.always_include_address_block_in_macros

    duh_info = load_json5_with_refs(args.duh_document)

    # ###
    # process pSchema (in duh document) to create symbol table
    # ###
    if 'pSchema' in duh_info['component']:
        duh_symbol_table = duh_info['component']['pSchema']['properties']
    else:
        duh_symbol_table = {}

    # ###
    # process register info from duh
    # ###
    def interpret_register_field(a_reg_field: dict) -> RegisterField:
        try:
            name = a_reg_field["name"]
        except KeyError:
            raise Exception(f"Missing required register field property 'name': {a_reg_field}")
        bit_offset = a_reg_field["bitOffset"]
        bit_width = a_reg_field["bitWidth"]
        if isinstance(bit_offset, str):
            bit_offset = duh_symbol_table[bit_offset]['default']
        if isinstance(bit_width, str):
            bit_width = duh_symbol_table[bit_width]['default']
        return RegisterField.make_field(name, bit_offset, bit_width)

    def interpret_register(a_reg: dict, address_block: AddressBlock) -> Register:
        name = a_reg['name']
        offset = a_reg['addressOffset']
        width = a_reg['size']
        fields = a_reg.get('fields', [])
        if isinstance(offset, str):
            offset = duh_symbol_table[offset]['default']
        if isinstance(width, str):
            width = duh_symbol_table[width]['default']
        interpreted_fields = [interpret_register_field(field) for field in fields]
        return Register.make_register(name, offset, width, interpreted_fields, address_block)

    def interpret_address_block(duh_addr_block: dict) -> AddressBlock:
        return AddressBlock(
            name=duh_addr_block['name'],
            baseAddress=duh_addr_block['baseAddress'],
            range=duh_addr_block['range'],
            width=duh_addr_block['width'],
        )

    reglist: t.List[Register] = [
        interpret_register(register, interpret_address_block(address_block))
        for memory_map in duh_info['component'].get('memoryMaps', [])
        for address_block in memory_map['addressBlocks']
        for register in address_block.get('registers', [])
    ]

    # When multiple address blocks are present, include the address block name
    # in the C macros in order to distinguish between registers in different
    # address blocks.
    num_address_blocks = len([
        address_block
        for memory_map in duh_info['component'].get('memoryMaps', [])
        for address_block in memory_map['addressBlocks']
    ])
    if num_address_blocks > 1 or always_include_address_block:
        include_address_block = True
    else:
        include_address_block = False

    m_hdr_path = m_dir_path / device
    m_hdr_path.mkdir(exist_ok=True, parents=True)

    driver_file_path = m_dir_path / f'{vendor}_{device}.c'
    header_file_path = m_hdr_path / f'{vendor}_{device}{0}.h'

    if overwrite_existing or not driver_file_path.exists():
        driver_file_path.write_text(
            generate_metal_dev_drv(
                vendor,
                device,
                0,
                reglist,
                include_address_block=include_address_block,
            )
        )
    else:
        print(f"{str(driver_file_path)} exists, not creating.",
              file=sys.stderr)

    if overwrite_existing or not header_file_path.exists():
        header_file_path.write_text(
            generate_metal_dev_hdr(vendor, device, 0, reglist))
    else:
        print(f"{str(header_file_path)} exists, not creating.",
              file=sys.stderr)

    return 0


if __name__ == '__main__':
    sys.exit(main())
