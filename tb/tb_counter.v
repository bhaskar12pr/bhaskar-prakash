// Self-checking testbench for counter, with several tests and a seed.
//   +TEST=reset  reset clears the counter, and it holds while en=0
//   +TEST=count  random enable pattern (from +SEED) against a reference model
//   +TEST=wrap   counts past the maximum value and checks the wrap pulse
// Prints "TEST PASSED" on success; calls $fatal on failure.
`timescale 1ns/1ps
`include "counter_defs.vh"

module tb_counter;

localparam W = `COUNTER_WIDTH;

reg          clk = 1'b0;
reg          rst_n = 1'b0;
reg          en = 1'b0;
wire [W-1:0] q;
wire         wrap;

reg  [W-1:0] exp_q;
reg          exp_wrap;
integer      errors = 0;
integer      seed = 1;      // value of +SEED, printed in messages
integer      rng;           // random state; $random changes it
integer      n;
reg  [255:0] test;

counter #(.WIDTH(W)) dut (.clk(clk), .rst_n(rst_n), .en(en), .q(q), .wrap(wrap));

always #5 clk = ~clk;

// Reference model, updated on the same clock edge as the DUT.
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        exp_q    <= 0;
        exp_wrap <= 1'b0;
    end else begin
        exp_wrap <= en && (exp_q == {W{1'b1}});
        if (en) exp_q <= exp_q + 1'b1;
    end
end

// Compare on the falling edge, when everything is stable.
always @(negedge clk) begin
    if (rst_n && (q !== exp_q || wrap !== exp_wrap)) begin
        errors = errors + 1;
        $display("ERROR: t=%0t q=%0d wrap=%b, expected q=%0d wrap=%b", $time, q, wrap, exp_q, exp_wrap);
    end
end

task finish_test;
    begin
        if (errors == 0) begin
            $display("TEST PASSED: %0s seed=%0d", test, seed);
            $finish;
        end else begin
            $fatal(1, "TEST FAILED: %0s seed=%0d, %0d errors", test, seed, errors);
        end
    end
endtask

initial begin
    $dumpfile("waves.vcd");
    $dumpvars(0, tb_counter);
    if (!$value$plusargs("TEST=%s", test)) test = "count";
    if (!$value$plusargs("SEED=%d", seed)) seed = 1;
    rng = seed;
    $display("Running test %0s with seed %0d", test, seed);

    repeat (2) @(posedge clk);
    @(negedge clk) rst_n = 1'b1;

    if (test == "reset") begin
        en = 1'b1;
        repeat (5) @(negedge clk);
        if (q == 0) begin
            errors = errors + 1;
            $display("ERROR: counter did not count before reset");
        end
        en = 1'b0;
        repeat (3) @(negedge clk);          // must hold
        rst_n = 1'b0;
        #1;
        if (q !== 0) begin
            errors = errors + 1;
            $display("ERROR: q=%0d right after asynchronous reset, expected 0", q);
        end
        @(negedge clk) rst_n = 1'b1;
        repeat (3) @(negedge clk);
    end else if (test == "count") begin
        for (n = 0; n < 200; n = n + 1) begin
            @(negedge clk) en = $random(rng);
        end
    end else if (test == "wrap") begin
        en = 1'b1;
        repeat ((1 << W) * 2 + 3) @(negedge clk);
    end else begin
        $fatal(1, "TEST FAILED: unknown test '%0s' (use reset, count or wrap)", test);
    end

    @(negedge clk);
    finish_test;
end

endmodule
