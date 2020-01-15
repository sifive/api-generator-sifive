#!/bin/sh

set -e

# Short script to run all the tests

for i in *_test.sh ; do
    echo ${i}
    ./$i
    echo
done
