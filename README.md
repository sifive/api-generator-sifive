# api-generator-sifive
Wake build descriptions of hardware generators

# Overview
This repo is for:
- running the rocket-chip generator and firrtl to generate RTL
  - `wake -x 'makeRTL $dut'`
  - e.g. `wake -x 'makeRTL pioDUT'`
- compiling test programs with freedom-metal
- running integration tests on SoCs in simulation
  - `wake -x 'runSim $dut'`
  - e.g. `wake -x 'runSim pioDUT`
- running simulations with a specific simulator
  - `wake -x 'runSimWith $dut $simulator'`
  - e.g. `wake -x 'runSimWith pioDUT VCS'`
- running a single integration tests by name
  - `wake -x 'runSingleSim $dut $testName'`
  - e.g. `wake -x 'runSingleSim pioDUT "demo"'`
- running a single integration tests by name and with a specific simulator
  - `wake -x 'runSingleSimWith $dut $testName $simulator'`
  - e.g. `wake -x 'runSingleSimWith pioDUT "demo" VCS_Waves'`
- creating bitstreams with vivado
  - `wake -x 'runBitstream $dut'`
  - e.g. `wake -x 'runBitstream pioDUT'`
