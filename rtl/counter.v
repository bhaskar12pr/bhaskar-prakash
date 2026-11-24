// Up counter with synchronous enable and asynchronous active-low reset.
// q wraps from all-ones back to zero; wrap pulses for one cycle when it does.
`timescale 1ns/1ps
`include "counter_defs.vh"

module counter #(
    parameter WIDTH = `COUNTER_WIDTH
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire             en,
    output reg  [WIDTH-1:0] q,
    output reg              wrap
);

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        q    <= {WIDTH{1'b0}};
        wrap <= 1'b0;
    end else begin
        wrap <= en && (q == {WIDTH{1'b1}});
        if (en)
            q <= q + 1'b1;
    end
end

endmodule
