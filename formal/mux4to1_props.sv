// Formal properties for mux4to1.
// The solver checks these assertions for EVERY possible input, so passing
// is a proof that the design is correct, not just a large sample of tests.
// The mux has no state (no clock), so one time step covers all behaviour.
module mux4to1_props (
    input wire [3:0] i,
    input wire [1:0] s
);
    wire ow;

    mux4to1 dut (.i(i), .s(s), .ow(ow));

    always @(*) begin
        // Main property: the output is the selected input bit.
        assert (ow == i[s]);
        // The output never depends on an unselected bit: flipping any other
        // bit of i is covered by the property above, because it holds for
        // all values of i.
    end
endmodule
