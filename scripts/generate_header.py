#!/usr/bin/env python3.7

import argparse
import json
import string
import sys
import textwrap
import typing as t
from dataclasses import dataclass
from pathlib import Path
from collections import Counter

PlainJSONType = t.Union[dict, list, t.AnyStr, float, bool]
JSONType = t.Union[PlainJSONType, t.Iterator[PlainJSONType]]

NAME_COLLISION_DICT = Counter()

# Json utility


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


# Data Classes
# we pull RegisterFields, Interrupts, and Devices from the Object Model.
# These are the data classes we use to represent them

@dataclass(frozen=True)
class RegisterField:
    """
    data class to hold information about a register field.
    """
    name: str
    offset: int  # in bits
    width: int  # in bits
    regFieldGroup: str
    all_registers: t.ClassVar = {}

    @staticmethod
    def make_register(name: str, offset: int, width: int, group: str) \
            -> "RegisterField":
        key = f'{name}-{group}'
        if name != 'reserved' and key in RegisterField.all_registers:
            register_field = RegisterField(name, offset, width, group)
            if RegisterField.all_registers[key] != register_field:
                raise Exception(f'Non matching register fields {key}')
            else:
                return RegisterField.all_registers[key]

        RegisterField.all_registers[key] = RegisterField(name, offset, width, group)
        return RegisterField.all_registers[key]


@dataclass(frozen=True)
class Interrupt:
    """
    Data class to hold information about an interrupt. May be
    unnamed, in which case the name is and empty string.
    """
    number: int
    name: str
    all_interrupts: t.ClassVar = {}

    @staticmethod
    def make_interrupt(number, name=''):
        if name and name in Interrupt.all_interrupts:
            an_interrupt = Interrupt(number, name)
            if Interrupt.all_interrupts[name] != an_interrupt:
                raise Exception(f"duplicate interrupt {name}")
            else:
                return Interrupt.all_interrupts[name]

        Interrupt.all_interrupts[name] = Interrupt(number, name)
        return Interrupt.all_interrupts[name]


@dataclass(frozen=True)
class DeviceBase:
    """
    Data class to hold information about a device on the SOC. Include all
    register fields and interrupts for the device.
    """
    name: str
    index: int
    base_interrupt: int
    base_address: int
    interrupts: t.List[Interrupt]
    registers: t.List[RegisterField]

###
# templates
###

# This is the base template for the header we generate.


METAL_BASE_HDR_TMPL = \
    """
    #include <metal/compiler.h>
    #include <metal/io.h>

    #ifndef ${vendor}_${device}_h
    #define ${vendor}_${device}_h
    
    #define ${capitalized_device}_COUNT ${dev_count}

    // To use ${capitalized_device}_INTERRUPT_BASES, use it as the
    // initializer to an array of ints, i.e.
    // int interrupt_bases[${capitalized_device}_COUNT] = ${capitalized_device}_INTERRUPT_BASES;
    // there are ${capitalized_device}_INTERRUPT_COUNT interrupts per
    // device.
    
    ${interrupts}

    // To use ${capitalized_device}_BASES, use it as the
    // initializer to an array of ints, i.e.
    // int bases[${capitalized_device}_COUNT] = ${capitalized_device}_BASES;

    #define ${capitalized_device}_BASES {${base_address}}

    // : these macros have control_base as a hidden input
    // use with the _BYTE #define's
    #define METAL_${capitalized_device}_REG(offset) ((unsigned long)control_base + (offset))
    #define METAL_${capitalized_device}_REGW(offset) \\
       (__METAL_ACCESS_ONCE((__metal_io_u32 *)METAL_${capitalized_device}_REG(offset)))

    #define METAL_${capitalized_device}_REGBW(offset) \\
       (__METAL_ACCESS_ONCE((uint8_t *)METAL_${capitalized_device}_REG(offset)))

    // METAL_NAME => bit offset from base
    // METAL_NAME_BYTE => (uint8_t *) offset from base
    // METAL_NAME_BIT => number of bits into METAL_NAME_BYTE
    // METAL_NAME_WIDTH => bit width

    ${register_offsets}

    #endif
    """


# sub templates
# generate sub parts of template
def generate_offsets(device_name: str, dev_list: t.List[DeviceBase]) -> str:
    """
    Generate the register offset macros

    :param device_name: the name of the device
    :param dev_list: the list of devices for the SOC
    :return:The offset c macros for the device and registers
    """
    rv: t.List[str] = []

    capitalized_device = device_name.upper()
    if dev_list:
        # only need to check the first device
        for a_reg in dev_list[0].registers:
            if a_reg.name == 'reserved':
                continue
            name = a_reg.name.upper().strip().replace(" ", "")
            group = a_reg.regFieldGroup.upper().strip().replace(" ", "")
            offset = a_reg.offset
            width = a_reg.width

            if name.startswith(group.split('_')[-1] + "_"):
                group = "_".join(group.split('_')[:-1])

            infix = ''
            if group is not "":
                infix = f'_{group}'

            prefix = f'{capitalized_device}_REGISTER{infix}_{name}'

            NAME_COLLISION_DICT[prefix] += 1
            macro_line =  f'#define {prefix} {offset}\n'
            macro_line += f'#define {prefix}_BYTE {offset >> 3}\n'
            macro_line += f'#define {prefix}_BIT {offset & 0x7}\n'
            macro_line += f'#define {prefix}_WIDTH {width}\n'

            rv.append(macro_line)

    return '\n'.join(rv)


def generate_interrupt_defines(bases: t.List[DeviceBase],
                               device: str) -> str:
    """
    generate interrupt sec of file

    :param bases: list of devices
    :param device: the name of the device
    :return: the interrupt section of the header file.
    """
    rv = []
    dev = device.upper().replace(' ', '')

    if bases[0].interrupts:
        generic_interrupts = bases[0].interrupts
        int_base = "#define ABSOLUTE_INTERRUPT(base, relative) ((base) + (relative))"

        int_bases = ','.join(str(i.base_interrupt) for i in bases)

        rv.append(textwrap.dedent(int_base))
        rv.append(f'#define {dev}_INTERRUPT_BASES {{ {int_bases} }}')
        rv.append(f'#define {dev}_INTERRUPT_COUNT {len(generic_interrupts)}\n')

        interrupts = []
        if bases:
            for an_interrupt in bases[0].interrupts:
                number = an_interrupt.number - bases[0].base_interrupt
                if an_interrupt.name:
                    name = an_interrupt.name.upper().replace(' ', '')
                    rv.append(f'#define {dev}_INTERRUPT_OFFSET_{name} {number}')
                interrupts.append(an_interrupt.number)

    return '\n'.join(rv)


def generate_base_hdr(vendor: str,
                      device: str,
                      devlist: t.List[DeviceBase]):
    """
    Master function to generate the include file.

    :param vendor:  string of the vendor name
    :param device:  string of the device name
    :param devlist: list of devices
    :return: a string for the header file
    """
    template = string.Template(textwrap.dedent(METAL_BASE_HDR_TMPL))

    base = ", ".join(hex(i.base_address) for i in devlist)
    interrupts = generate_interrupt_defines(devlist, device)

    return template.substitute(
        base_address=base,
        dev_count=len(devlist),
        vendor=vendor,
        device=device,
        capitalized_device=device.upper(),
        register_offsets=generate_offsets(device, devlist),
        interrupts=interrupts,
    )


# parsing the OM file

def find_interrupts(object_model: JSONType, device: str) \
        -> t.List[Interrupt]:
    """
    given a parsed device, return the interrupts for the device

    :param object_model: a device parsed from the object model
    :param device: a string name of the device
    :return: a list of the interrupts
    """

    def type_match(dev: str, types: t.List[str]):
        d_str = dev.lower()
        for a_type in types:
            if a_type.lower().endswith(d_str):
                return True
        return False

    p = walk(object_model)
    p = filter(lambda x: '_types' in x, p)
    p = filter(lambda x: type_match(device, x['_types']), p)
    p = list(p)

    for dev_om in p:
        p = walk(dev_om)
        p = filter(lambda x: '_types' in x, p)
        p = filter(lambda x: 'OMInterrupt' in x['_types'], p)

    rv = []
    for an_interrupt in p:
        number = an_interrupt['numberAtReceiver']
        name = an_interrupt.get('name', '')
        if '@' in name:
            name = ''
        int_data = Interrupt.make_interrupt(number, name)
        rv.append(int_data)

    return rv


def find_registers(object_model: JSONType) -> t.List[RegisterField]:
    """
    given a parsed device, return the register fields for the device

    :param object_model: a device parsed from the object model
    :return: a list of register fields
    """
    reglist: t.List[RegisterField] = []
    for mr in object_model['memoryRegions']:
        # get base address for each memory region
        if len(mr['addressSets']) != 1:
            raise Exception("Can't handle multiple addressSets in a "
                            "region")

        # get regs for every memory region
        for aReg in mr['registerMap']['registerFields']:
            r_name = aReg['description']['name']
            r_group = aReg['description']['group']
            r_offset = aReg['bitRange']['base']
            r_width = aReg['bitRange']['size']
            r = RegisterField.make_register(r_name,
                                            r_offset,
                                            r_width,
                                            r_group)

            reglist.append(r)

    return reglist


def find_devices(object_model: JSONType,
                 device: str) -> JSONType:
    """

    :param object_model: The full object model for the soc
    :param device: the name of the device in question
    :return: a list of the devices in the soc
    """
    p = walk(object_model)
    p = filter(lambda x: '_types' in x, p)
    p = filter(lambda x: f'OM{device}' in x['_types'], p)
    return list(enumerate(p))

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

    devlist: t.List[DeviceBase] = []

    devices_om = find_devices(object_model, device)

    for index, dev_om in devices_om:
        reglist = find_registers(dev_om)
        intlist = find_interrupts(dev_om, device)
        base_int = min(i.number for i in intlist)
        base_address = dev_om['memoryRegions'][0]['addressSets'][0]['base']

        devlist.append(DeviceBase(name=device,
                                  index=index,
                                  base_interrupt=base_int,
                                  base_address=base_address,
                                  interrupts=intlist,
                                  registers=reglist))

    base_hdr_path = bsp_dir_path / f'bsp_{device}'
    base_hdr_path.mkdir(exist_ok=True, parents=True)
    base_header_file_path = base_hdr_path / f'{vendor}_{device}.h'

    if overwrite_existing or not base_header_file_path.exists():
        base_header_file_path.write_text(
            generate_base_hdr(vendor,
                              device,
                              devlist))
    else:
        print(f"{str(base_header_file_path)} exists, not creating.",
              file=sys.stderr)

    for k, v in NAME_COLLISION_DICT.items():
        if v > 1:
            print(f'Variable {k} repeated', file=sys.stderr)

    return 0


if __name__ == '__main__':
    sys.exit(main())
