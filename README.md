# api-generator-sifive
Wake build descriptions of hardware generators

# Overview
This repo is for:
- running the rocket-chip generator and firrtl to generate RTL
  - `wake makeRTL $dut`
- compiling test programs with freedom-metal
- running integration tests on SoCs in simulation
  - `wake runSim $dut`
- creating bitstreams with vivado
  - `wake runBitstream $dut`
