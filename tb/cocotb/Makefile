# cocotb flow for mux4to1. Called by the top-level Makefile: make cocotb
#   make -C tb/cocotb              run with Icarus (default)
#   make -C tb/cocotb SIM=verilator
#   make -C tb/cocotb WAVES=1      also dump a waveform

SIM               ?= icarus
TOPLEVEL_LANG     ?= verilog
VERILOG_SOURCES   := $(abspath ../../rtl/mux4to1.v)
COCOTB_TOPLEVEL   := mux4to1
COCOTB_TEST_MODULES := test_mux4to1
COCOTB_RESULTS_FILE ?= $(abspath ../../build/cocotb_results.xml)

include $(shell cocotb-config --makefiles)/Makefile.sim
