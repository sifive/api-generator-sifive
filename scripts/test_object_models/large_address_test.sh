#!/bin/sh

# This is a basic command to test that generate header works with an address greater
# than 0xFFFFFFFF being correctly suffixed with ULL
# Running this file shouldn't raise an exception, the generated header file
# should have the address for PIO_BASE is marked correctly

# Must be from from the directory 'scripts/test_object_models' of an api-generator-sifive repo
if [ ! -x ../generate_header.py ]
then
    echo "This test must be from from the directory 'scripts/test_object_models' of an api-generator-sifive repo"
    exit 2
fi

../generate_header.py --object-model large_address.json --vendor sifive --device pio --bsp-dir large_address --overwrite-existing

grep --quiet '#define PIO_BASES {0x700000000ULL}' large_address/bsp_pio/sifive_pio.h

if [ $? -eq 0 ]
then
    echo PASS
    exit 0
else
    echo FAIL
    exit 1
fi
