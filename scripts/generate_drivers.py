#!/usr/bin/env python3.7

import argparse
import string
import sys
import textwrap
import typing as t
from dataclasses import dataclass
from pathlib import Path

import json5

PlainJSONType = t.Union[dict, list, t.AnyStr, float, bool]
JSONType = t.Union[PlainJSONType, t.Iterator[PlainJSONType]]


def walk(j_obj: JSONType) -> t.Iterator[JSONType]:
    """
    Walk a parsed json object, returning inner nodes.
    This allows the object to be parse in a pipeline like fashion.

    :param j_obj: The object being parsed, or an iterator
    :return: an iterator of matching objects
    """
    if isinstance(j_obj, dict):
        yield j_obj
        for v in j_obj.values():
            yield from walk(v)
    elif isinstance(j_obj, (list, t.Iterator)):
        yield j_obj
        for j in j_obj:
            yield from walk(j)


@dataclass(frozen=True)
class Register:
    """
    Description of memory-mapped control register within a device
    """
    name: str
    offset: int  # in bytes
    width: int  # in bits

    @staticmethod
    def make_register(name: str, offset: int, width: int) -> "Register":
        if width not in (8, 16, 32, 64):
            raise Exception(f'Invalid register width {width}, for register '
                            f'{name}.\n'
                            f'Width should be not 8, 16, 32, or 64.\n'
                            f'Please fix the register width in DUH document.')
        return Register(name, offset, width)


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
        reg_name = a_reg.name.lower()
        size = a_reg.width

        write_func = f'    void (*v_{device_name}_{reg_name}_write)(uint32_t * {device_name}_base, uint{size}_t data);'
        read_func = f'    uint{size}_t (*v_{device_name}_{reg_name}_read)(uint32_t  *{device_name}_base);'

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
        reg_name = a_reg.name.lower()
        size = a_reg.width

        write_func = f'void metal_{device_name}_{reg_name}_write({dev_struct}, uint{size}_t data);'
        read_func = f'uint{size}_t metal_{device_name}_{reg_name}_read({dev_struct});'

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

    ${base_functions}

    ${metal_functions}

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
        reg_name = a_reg.name.lower()
        write_func = f'{" " * 8}metal_{device}s[i].vtable.v_{device}_{reg_name}_write = {device}_{reg_name}_write;'
        read_func = f'{" " * 8}metal_{device}s[i].vtable.v_{device}_{reg_name}_read = {device}_{reg_name}_read;'
        rv.append(write_func)
        rv.append(read_func)

    return '\n'.join(rv)


def generate_base_functions(device: str, reg_list: t.List[Register]) -> str:
    """
    Generates the basic, not exported register access functions for
    a given device and register list.

    :param device: the name of the device
    :param reg_list: the list of registers for the device.
    :return:  the c code for the register access functions
    """
    cap_device = device.upper()
    rv: t.List[str] = []

    for a_reg in reg_list:
        name = a_reg.name.lower()
        cap_name = a_reg.name.upper()
        size = a_reg.width

        write_func = f"""
            void {device}_{name}_write(uint32_t *{device}_base, uint{size}_t data)
            {{
                volatile uint32_t *control_base = {device}_base;
                METAL_{cap_device}_REGW(METAL_{cap_device}_{cap_name}) = data;
            }}
            """

        rv.append(textwrap.dedent(write_func))

        read_func = f"""
            uint{size}_t {device}_{name}_read(uint32_t *{device}_base)
            {{
                volatile uint32_t *control_base = {device}_base;
                return METAL_{cap_device}_REGW(METAL_{cap_device}_{cap_name});
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
        name = a_reg.name.lower()
        size = a_reg.width

        write_func = f"""
            void metal_{device}_{name}_write(const struct metal_{device} *{device}, uint{size}_t data)
            {{
                if ({device} != NULL)
                    {device}->vtable.v_{device}_{name}_write({device}->{device}_base, data);
            }}
            """
        rv.append(textwrap.dedent(write_func))

        read_func = f"""
            uint{size}_t metal_{device}_{name}_read(const struct metal_{device} *{device})
            {{
                if ({device} != NULL)
                    return {device}->vtable.v_{device}_{name}_read({device}->{device}_base);
                return (uint{size}_t)-1;
            }}
            """

        rv.append(textwrap.dedent(read_func))

    return '\n'.join(rv)


def generate_metal_dev_drv(vendor, device, index, reglist):
    """
    Generate the driver source file contents for a given device
    and register list

    :param vendor: the vendor creating the device
    :param device: the device
    :param index: the index of the device used
    :param reglist: the list of registers
    :return: a string containing of the c code for the basic driver
    """
    template = string.Template(textwrap.dedent(METAL_DEV_DRV_TMPL))

    return template.substitute(
        vendor=vendor,
        device=device,
        cap_device=device.upper(),
        index=str(index),
        base_functions=generate_base_functions(device, reglist),
        metal_functions=generate_metal_function(device, reglist),
        def_vtable=generate_def_vtable(device, reglist)
    )


# ###
# Support for parsing duh file
# ###

def walkfile_j5(f_name: str) -> JSONType:
    "Returns iterator over named json5 file"
    return walk(json5.load(open(f_name)))


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

    return parser.parse_args()


def main():
    args = handle_args()

    vendor = args.vendor
    device = args.device
    m_dir_path = args.metal_dir
    overwrite_existing = args.overwrite_existing

    duh_info = json5.load(open(args.duh_document))

    # ###
    # process pSchema (in duh document) to create symbol table
    # ###
    p = walkfile_j5(args.duh_document)
    p = filter(lambda x: 'pSchema' in x, p)
    p = map(lambda x: x['pSchema'], p)
    p = filter(lambda x: 'properties' in x, p)
    p = map(lambda x: x['properties'], p)

    duh_symbol_table = {}

    for prop in p:
        duh_symbol_table.update(**prop)

    # ###
    # process register info from duh
    # ###
    def interpret_register(a_reg: dict) -> Register:
        name = a_reg['name']
        offset = a_reg['addressOffset'] // 8
        width = a_reg['size']
        if isinstance(offset, str):
            offset = duh_symbol_table[offset]['default']
        if isinstance(width, str):
            width = duh_symbol_table[width]['default']
        return Register.make_register(name, offset, width)

    p = walk(duh_info)
    p = filter(lambda x: 'name' in x and x['name'] == 'csrAddressBlock', p)
    p = map(lambda x: x['registers'], p)
    p = (j for i in p for j in i)  # flatten
    reglist: t.List[Register] = list(map(interpret_register, p))

    m_hdr_path = m_dir_path / device
    m_hdr_path.mkdir(exist_ok=True, parents=True)

    driver_file_path = m_dir_path / f'{vendor}_{device}.c'
    header_file_path = m_hdr_path / f'{vendor}_{device}{0}.h'

    if overwrite_existing or not driver_file_path.exists():
        driver_file_path.write_text(
            generate_metal_dev_drv(vendor, device, 0, reglist))
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
