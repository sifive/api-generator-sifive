#!/bin/sh

# This is a basic command to test that generate header works with no interrupts defined.
# Running this file shouldn't raise an exception

# Must be from from the directory 'scripts/test_object_models' of an api-generator-sifive repo
if [ ! -x ../generate_header.py ]
then
    echo "This test must be from from the directory 'scripts/test_object_models' of an api-generator-sifive repo"
    exit 2
fi

../generate_header.py --object-model no_interrupts.json --vendor sifive --device pio --bsp-dir no_interrupts --overwrite-existing

if [ $? -eq 0 ]
then
    echo PASS
    exit 0
else
    echo FAIL
    exit 1
fi
