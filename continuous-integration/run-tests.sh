#!/usr/bin/env bash

set -euvo pipefail

# This script assumes that it is running from the root of the Wit workspace.

api_firrtl_sifive_path=./api-firrtl-sifive

wake --init .

# Just check to see if the Wake code type checks.
wake -x Unit
