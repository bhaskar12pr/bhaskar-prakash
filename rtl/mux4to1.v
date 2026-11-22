// 4-to-1 multiplexer
// s selects which bit of i drives ow.
`timescale 1ns/1ps

module mux4to1 (
    input  wire [3:0] i,
    input  wire [1:0] s,
    output reg        ow
);

always @(*) begin
    case (s)
        2'b00:   ow = i[0];
        2'b01:   ow = i[1];
        2'b10:   ow = i[2];
        2'b11:   ow = i[3];
        default: ow = 1'bx;
    endcase
end

endmodule
