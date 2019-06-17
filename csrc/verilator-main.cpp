#include <iostream>
#include <fstream>
#include <sys/types.h>
#include <unistd.h>
#include <iomanip>
#include <memory>
#include <string>
#include <cstring>
#include "verilated.h"
#include "VTestDriver.h"
#include "verilated_vcd_c.h"

#include "svdpi.h"
//#include "VTestDriver__Dpi.h"

static uint64_t main_time = 0;

double sc_time_stamp()
{
  return main_time;
}

// hooks used for external debug agents
extern "C" {
char const * plusarg_value(char const * plusarg)
{
    std::string format = plusarg;
    format += "%s";

    std::string plusargvalue;
    VL_VALUEPLUSARGS_INN(-1, format, plusargvalue);

    static char buffer[1024];
    std::strcpy(buffer, plusargvalue.c_str());

    return buffer;
}
}

int main(int argc, char **argv, char **env) {

  // process plusargs
  Verilated::commandArgs(argc, argv);


  uint32_t randomSeed;
  if (VL_VALUEPLUSARGS_INI(32 ,"random_seed=%d", randomSeed)) {
    srand48(randomSeed);
    std::cout << "INFO(" << __FILE__ << "): Random seed is " << randomSeed << std::endl;
  } else {
    std::cout << "ERROR(" << __FILE__ << "): +random_seed=<int> must be specified" << std::endl;
    exit(44);
  }

  VTestDriver* top = new VTestDriver("top");

#if VM_TRACE == 1
  std::unique_ptr<VerilatedVcdC> tfp;
  std::string vcdfile;
  if (VL_VALUEPLUSARGS_INN(-1, "vcdfile=%s", vcdfile)) {
    Verilated::traceEverOn(true);
    tfp = std::unique_ptr<VerilatedVcdC>(new VerilatedVcdC);
    top->trace (tfp.get(), 99);
    tfp->open (vcdfile.c_str());
    std::cout << "INFO(" << __FILE__ << "): dump vcd to " << vcdfile << std::endl;
  }
#endif // VM_TRACE

  top->reset = 1;           // Set some inputs
  top->clock = 1;

  int const heartbeat = VL_TESTPLUSARGS_I("heartbeat");

  while (!Verilated::gotFinish()) {
    if (top->reset == 1 && main_time >= (770 << 1)) {
      std::cout << "time: " << main_time << " Deasserting 'reset'" << std::endl;
      top->reset = 0;   // Deassert reset
    }

    // print simulation heartbeat
    if ((main_time % 2) == 0) {
      top->clock = 1;
      if (heartbeat && (main_time % 1000) == 0) {
        std::cout << "INFO(" << __FILE__ << ")@" << main_time << ": simulation-heartbeat" << std::endl;
      }
    } else {
      top->clock = 0;
    }

    top->eval();            // Evaluate model
    fflush(stdout);
    main_time++;            // Time passes...
#if VM_TRACE == 1
    if (tfp) {
      tfp->dump(main_time);
    }
#endif // VM_TRACE
  }

    top->final();               // Done simulating
    fflush(stdout);

#if VM_TRACE == 1
    if (tfp) {
      tfp->close();
    }
#endif // VM_TRACE

#if VM_COVERAGE
    VerilatedCov::write("coverage.dat");
#endif // VM_COVERAGE

    delete top;

    // Read process statistics to report cputime on stderr
    std::ifstream ps("/proc/" + std::to_string(getpid()) + "/stat", std::ios::in);
    std::string throw_away_token;
    uint32_t utime, stime, cutime, cstime;

    // fields described in the process information pseudo-filesystem, proc(5),
    //   man-page
    ps >> throw_away_token; // ( 1) pid
    ps >> throw_away_token; // ( 2) comm
    ps >> throw_away_token; // ( 3) state
    ps >> throw_away_token; // ( 4) ppid
    ps >> throw_away_token; // ( 5) pgrp
    ps >> throw_away_token; // ( 6) session
    ps >> throw_away_token; // ( 7) tty_nr
    ps >> throw_away_token; // ( 8) tpgid
    ps >> throw_away_token; // ( 9) flags
    ps >> throw_away_token; // (10) minflt
    ps >> throw_away_token; // (11) cminflt
    ps >> throw_away_token; // (12) majflt
    ps >> throw_away_token; // (13) cmajflt
    ps >> utime;            // (14) utime, clock ticks
    ps >> stime;            // (15) stime, clock ticks
    ps >> cutime;           // (16) cutime, clock ticks
    ps >> cstime;           // (17) cstime, clock ticks
    float cputime_secs = (utime*1000.0/sysconf(_SC_CLK_TCK) + stime*1000.0/sysconf(_SC_CLK_TCK))/1000.0;
    std::cerr << "CPU Time: " << std::fixed << std::setprecision(4) << cputime_secs << " seconds;" << std::endl;

    exit(0); // TODO: exit 0 on pass, exit 1 on fail
}
