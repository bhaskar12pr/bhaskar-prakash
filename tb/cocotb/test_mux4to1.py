"""cocotb tests for rtl/mux4to1.v.

Python drives the Verilog design through the simulator (Icarus by default).
Each @cocotb.test() function becomes one test case in the JUnit report.
Run with:  make cocotb   (from the repo root)
"""
import random

import cocotb
from cocotb.triggers import Timer


def model(i: int, s: int) -> int:
    """Reference model: the output is bit s of i."""
    return (i >> s) & 1


async def apply(dut, i: int, s: int) -> None:
    """Drive one input vector and wait for the combinational output to settle."""
    dut.i.value = i
    dut.s.value = s
    await Timer(1, unit="ns")


@cocotb.test()
async def test_exhaustive(dut):
    """Every combination of i (16 values) and s (4 values): 64 checks."""
    for i in range(16):
        for s in range(4):
            await apply(dut, i, s)
            got = int(dut.ow.value)
            assert got == model(i, s), f"i={i:04b} s={s:02b}: ow={got}, expected {model(i, s)}"
    dut._log.info("64/64 exhaustive checks passed")


@cocotb.test()
async def test_one_hot(dut):
    """Only one input is high. The output must be 1 only when s selects it."""
    for hot in range(4):
        for s in range(4):
            await apply(dut, 1 << hot, s)
            assert int(dut.ow.value) == int(hot == s), f"hot=i[{hot}] s={s}"


@cocotb.test()
async def test_random(dut):
    """1000 random vectors, seeded from cocotb's seed so failures can be replayed."""
    rng = random.Random(cocotb.RANDOM_SEED)
    for _ in range(1000):
        i, s = rng.randrange(16), rng.randrange(4)
        await apply(dut, i, s)
        assert int(dut.ow.value) == model(i, s), f"i={i:04b} s={s:02b} (seed {cocotb.RANDOM_SEED})"
