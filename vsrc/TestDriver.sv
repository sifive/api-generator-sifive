// VCS coverage exclude_file

localparam integer unsigned STDERR_fh = 32'h80000002;

// *Verilator* does not support syntax related to the stratified event scheduler
`ifdef VCS
  `define ASSERT_FINAL assert final
`else
  `define ASSERT_FINAL assert
`endif

module TestDriver (
`ifdef VERILATOR
    clock,
    reset
`endif // VERILATOR
);
  timeunit 1ns;
 `ifdef VCS
  export "DPI" function plusarg_value;
 // test if a plusarg is set and return its string value
  function string plusarg_value(input string p);
    string s;
    if ($value$plusargs(p, s)) begin
      return s;
    end else begin
      return "";
    end
  endfunction
`endif
 // *Verilator* drives (clock, reset) from C-main
//   while Verilog-simulators generate (clock, reset)
`ifdef VERILATOR
  input bit clock /*verilator clocker*/;
  input bit reset;
`else
  bit clock = 1'b0;
  bit reset = 1'b1;

  initial begin
    #(`RESET_DELAY)  reset = 1'b0;
  end
  always  #(`CLOCK_PERIOD/2.0)            clock = !clock;
`endif // VERILATOR


`ifndef VERILATOR
  initial begin
    $assertkill;
    #1
    $asserton;
  end
`endif


  // Read input arguments and initialize
  bit               verbose     = |($test$plusargs("verbose"));
  bit               genfsdb     = |($test$plusargs("genfsdb"));
  bit               printf_cond;
  longint unsigned  max_cycles  = '1; // default value is max-longint
  string            vcdplusfile = "";
  bit [99:0] [7:0]  vcdfile     = "";

  assign printf_cond = verbose && !reset;

  // flush waves from memory to disk and optionally close the file
  function void flush_waves(
    bit close = 0
  );

    // NOTE: verilator does not support these functions
    `ifndef VERILATOR
      `ifdef DEBUG
        `ifdef VCS
          // flush or write all the simulation results in memory to the VPD file
          if (genfsdb == 1'b1) begin
          `ifdef DEBUGFSDB
            $fsdbDumpflush();
          `endif
          end else $vcdplusflush();
          if (close == 1'b1) begin
            // mark the current VPD file as completed and close the file
            if (genfsdb == 1'b1) begin
            `ifdef DEBUGFSDB
              $fsdbDumpoff;
              $fsdbDumpFinish();
            `endif
            end else $vcdplusclose();
          end

        `else // ~VCS
          // Empties the VCD file buffer and writes all this data to the VCD
          // file
          $dumpflush;
          if (close == 1'b1) begin
            $dumpall;
          end
        `endif // ~VCS

      `else // ~DEBUG
        $warning("...`DEBUG` is not defined; nothing to flush");
      `endif // ~DEBUG
    `endif // ~VERILATOR

  endfunction : flush_waves


  initial
  begin
    // if present, get value from +max-cycles, otherwise reset to default
    if ($value$plusargs("max-cycles=%d", max_cycles) === 0) begin
      max_cycles = '1;
    end

`ifdef DEBUG

    if ($value$plusargs("vcdplusfile=%s", vcdplusfile))
    begin
`ifdef VCS
      if (genfsdb == 1'b1) begin
      `ifdef DEBUGFSDB
        string            fsdbfilename = "";
        if ($value$plusargs("fsdbfile=%s", fsdbfilename)) $fsdbDumpfile(fsdbfilename);
        else $fsdbDumpfile("sim.fsdb");
        $fsdbDumpvars(0);
      `endif
      end else begin
        $vcdplusfile(vcdplusfile);
        $vcdpluson(0);
        $vcdplusmemon(0);
        // flush or write all the simulation results in memory to the VPD file
        // whenever there is an interrupt, such as when VCS executes a $stop
        // system task
        $vcdplusautoflushon();
      end
`else
      $fdisplay(STDERR_fh, "Error: +vcdplusfile is VCS-only; use +vcdfile instead");
      $fatal(1);
`endif
    end

    if ($value$plusargs("vcdfile=%0s", vcdfile))
    begin
`ifndef VERILATOR
      // *verilator* dumping is enabled in csrc/verilator-main.cpp because these PLI functions
      // are not supported in verilator
      $dumpfile(vcdfile);
      $dumpvars(0, testHarness);
      $dumpon;
`endif
    end
`else
  // No +define+DEBUG

    if (|($test$plusargs("vcdplusfile=") | $test$plusargs("vcdfile=")))
    begin
      $fdisplay(STDERR_fh, "Error: +vcdfile or +vcdplusfile requested but compile did not have +define+DEBUG enabled");
      $fatal(1);
    end

`endif

  end

  longint unsigned trace_count;
  always_ff @(posedge clock) begin : cycle_counter
    if ($time() < 1) begin
      trace_count <= '0;
    end else begin
      trace_count <= trace_count + 64'd1;
    end

`ifdef DEBUG
  `ifdef VCS
     //  Automatically flush waves every 500us of simulation time or so
     //  Note that more frequent dumping further slows the simulations
     //  Also note that there is apparently no way to get VCS to dump
     //  intermediate results based on simulation time rather than buffer
     //  size.
     if (verbose && (trace_count%10000<1)) begin
        if (verbose &&
           ((trace_count % 100000 < 1) ||
           ((trace_count % 10000 < 1)  && (trace_count < 50000)))) begin
          if (genfsdb == 1'b1) begin
          `ifdef DEBUGFSDB
            $fsdbDumpflush();
          `endif
          end else $vcdplusflush();
        end
     end
  `endif
`endif

    // max_cycle_error assertion can be disabled with assertion control
    max_cycle_error : `ASSERT_FINAL (trace_count < max_cycles) else begin
      $fdisplay(STDERR_fh, "\n*** FAILED *** timeout after %0d simulation cycles (in %m)", trace_count);
      $fatal(2, "\n*** FAILED *** timeout after %0d simulation cycles (in %m)", trace_count);
    end
  end : cycle_counter

  reg [1023:0] testfile = 0;
  bit has_testfile = |($value$plusargs("testfile=%s", testfile));
  bit armed = 1'b1;
  initial begin
    armed = has_testfile && 1'b1;
  end
  bit armed_trigger;
  assign armed_trigger = armed && !reset;
  always_ff @(posedge armed_trigger)  begin
    if ($value$plusargs("testfile=%s", testfile))
    begin
      $readmemh(testfile, testHarness.dut.main_mem_sram.mem.mem_ext.ram);
    end
  end

  // Instantiate Chisel-testHarness, which wraps around the DUT
  `MODEL testHarness(
    .clock(clock),
    .reset(reset)
  );

  // Final cleanup
  `ifdef DEBUG
    final begin : close_waves
      flush_waves(.close(1));
    end : close_waves
  `endif

endmodule : TestDriver
