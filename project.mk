# =============================================================================
# Project settings for the verification flow. This is the ONLY file to edit
# when you copy the flow (Makefile + scripts/ + .gitlab-ci.yml) to another repo.
#
# Use ?= so the environment (e.g. GitLab CI variables) or the command line
# (make sim SIM=questa) can override a value.
# =============================================================================

# Simulator: icarus (tested here), questa, vcs, xcelium -> scripts/sim/<name>.mk
SIM ?= icarus

# Extra flags for every block. They can use {test} and {seed}.
# Example for UVM on Questa:  SIM_RUN_FLAGS ?= +UVM_TESTNAME={test} +UVM_VERBOSITY=UVM_LOW
SIM_COMPILE_FLAGS ?=
SIM_RUN_FLAGS     ?=

# Defaults for regressions (all can be overridden per run, see "make help")
SEEDS   ?= 1
TIMEOUT ?= 600

# Lint tool: verilator or none
LINT_TOOL ?= verilator

# The blocks in this repo. For each block <b> set:
#   <b>_RTL_F          design file list (.f)                          required
#   <b>_TOP            design top module                              default: <b>
#   <b>_TB_F           design + testbench file list                   enables "make sim"
#   <b>_TB_TOP         testbench top module                           enables "make sim"
#   <b>_TESTS          test names, passed as +TEST=<name>             use "default" for one test
#   <b>_TIMEOUT        seconds per test                               default: TIMEOUT
#   <b>_PATTERNS       pass/fail pattern file(s)                      default: scripts/patterns/default.txt
#   <b>_COMPILE_FLAGS  <b>_RUN_FLAGS  <b>_LINT_FLAGS                  extra flags for this block
#   <b>_COCOTB_DIR     folder with the cocotb test module             enables "make cocotb"
#   <b>_COCOTB_MODULE  cocotb test module (Python file name, no .py)
#   <b>_FORMAL         formal properties file, module <b>_props       enables "make formal"
#   <b>_SYNTH          1 to run Yosys synthesis                       enables "make synth"
BLOCKS ?= mux4to1 counter

mux4to1_RTL_F         := filelists/mux4to1_rtl.f
mux4to1_TB_F          := filelists/mux4to1_tb.f
mux4to1_TB_TOP        := tb_mux4to1
mux4to1_TESTS         := default
mux4to1_COCOTB_DIR    := tb/cocotb
mux4to1_COCOTB_MODULE := test_mux4to1
mux4to1_FORMAL        := formal/mux4to1_props.sv
mux4to1_SYNTH         := 1

counter_RTL_F         := filelists/counter_rtl.f
counter_TB_F          := filelists/counter_tb.f
counter_TB_TOP        := tb_counter
counter_TESTS         := reset count wrap
counter_TIMEOUT       := 60
counter_SYNTH         := 1
