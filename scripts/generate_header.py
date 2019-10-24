#!/usr/bin/env python3.7

import argparse
import json
import string
import sys
import textwrap
import typing as t
from dataclasses import dataclass
from pathlib import Path

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
           f'    const struct metal_{devices_name}_vtable vtable;'


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


###
# templates
###

METAL_BASE_HDR_TMPL = \
    """
    #include <metal/compiler.h>
    #include <metal/io.h>

    #ifndef ${vendor}_${device}_h
    #define ${vendor}_${device}_h
 
    // To use ${cap_device}_BASES, use it as the
    // initializer to an array of ints, i.e.
    // int bases[] = ${cap_device}_BASES;

    #define ${cap_device}_COUNT ${dev_count} 
    #define ${cap_device}_BASES {${base_address}}
    

    // : these macros have control_base as a hidden input
    #define METAL_${cap_device}_REG(offset) (((unsigned long)control_base + offset))
    #define METAL_${cap_device}_REGW(offset) \\
       (__METAL_ACCESS_ONCE((__metal_io_u32 *)METAL_${cap_device}_REG(offset)))

    ${register_offsets}
    
    ${register_widths}

    #endif
    """


def generate_offsets(device_name: str, reg_list: t.List[Register]) -> str:
    """
    Generate the register offset macros

    :param device_name: the name of the device
    :param reg_list: the list of registers for the device.
    :return:The offset c macros for the device and registers
    """
    rv: t.List[str] = []

    cap_device = device_name.upper()
    for a_reg in reg_list:
        name = a_reg.name.upper()
        offset = a_reg.offset
        macro_line = f'#define METAL_{cap_device}_{name} {offset}'
        rv.append(macro_line)

    return '\n'.join(rv)


def generate_widths(device_name: str, reg_list: t.List[Register]) -> str:
    rv: t.List[str] = []

    cap_device = device_name.upper()
    for a_reg in reg_list:
        name = a_reg.name.upper()
        width = a_reg.width
        macro_line = f'#define METAL_{cap_device}_{name}_WIDTH {width}'
        rv.append(macro_line)

    return '\n'.join(rv)


def generate_base_hdr(vendor: str,
                      device: str,
                      base_addresses: t.List[int],
                      reglist: t.List[Register]):
    template = string.Template(textwrap.dedent(METAL_BASE_HDR_TMPL))

    base = ", ".join(map(str, map(hex, base_addresses)))

    return template.substitute(
        base_address=base,
        dev_count=len(base_addresses),
        vendor=vendor,
        device=device,
        cap_device=device.upper(),
        register_offsets=generate_offsets(device, reglist),
        register_widths=generate_widths(device, reglist)
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
        "-o",
        "--object-model",
        help="The path to the object model file",
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
        "-b",
        "--bsp-dir",
        help="The path to the bsp directory",
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


def main() -> int:
    args = handle_args()
    vendor = args.vendor
    device = args.device
    overwrite_existing = args.overwrite_existing
    object_model = json.load(open(args.object_model))
    bsp_dir_path = args.bsp_dir

    # ###
    # parse OM to find base address of all devices
    # ###

    p = walk(object_model)
    p = filter(lambda x: '_types' in x, p)
    p = filter(lambda x: f'OM{device}' in x['_types'], p)

    reglist: t.List[Register] = []
    bases = []
    for index, dev in enumerate(p):
        for m_idx, mr in enumerate(dev['memoryRegions']):
            # get base address for each memory region

            if len(mr['addressSets']) == 1:
                bases.append(mr['addressSets'][0]['base'])
            else:
                raise Exception("Can't handle multiple addressSets in a "
                                "region")

            # get regs for every memory region
            for aReg in mr['registerMap']['registerFields']:
                r_name = aReg['description']['group']
                r_offset = aReg['bitRange']['base'] // 8
                r_width = aReg['bitRange']['size']
                r = Register.make_register(r_name,
                                           r_offset,
                                           r_width)
                reglist.append(r)

    base_hdr_path = bsp_dir_path / f'bsp_{device}'
    base_hdr_path.mkdir(exist_ok=True, parents=True)
    base_header_file_path = base_hdr_path / f'{vendor}_{device}.h'
    if overwrite_existing or not base_header_file_path.exists():
        base_header_file_path.write_text(
            generate_base_hdr(vendor, device, bases, reglist)
        )
    else:
        print(f"{str(base_header_file_path)} exists, not creating.",
              file=sys.stderr)

    return 0


if __name__ == '__main__':
    sys.exit(main())
