// Self-checking testbench for mux4to1.
// Drives every combination of i and s (16 x 4 = 64 vectors), compares the
// DUT output with a reference model, and ends with PASS or FAIL.
// On failure it calls $fatal, so the simulator exits with a non-zero code.
`timescale 1ns/1ps

module tb_mux4to1;

reg  [3:0] i;
reg  [1:0] s;
wire       ow;

integer errors = 0;
integer checks = 0;
integer vi, vs;
reg     expected;

mux4to1 dut (
    .i  (i),
    .s  (s),
    .ow (ow)
);

initial begin
    $dumpfile("waves.vcd");
    $dumpvars(0, tb_mux4to1);

    for (vi = 0; vi < 16; vi = vi + 1) begin
        for (vs = 0; vs < 4; vs = vs + 1) begin
            i = vi;
            s = vs;
            #10;
            expected = i[s];
            checks = checks + 1;
            if (ow !== expected) begin
                errors = errors + 1;
                $display("ERROR: i=%b s=%b ow=%b expected=%b", i, s, ow, expected);
            end
        end
    end

    if (errors == 0) begin
        $display("TEST PASSED: %0d/%0d checks", checks, checks);
        $finish;
    end else begin
        $fatal(1, "TEST FAILED: %0d errors in %0d checks", errors, checks);
    end
end

endmodule
