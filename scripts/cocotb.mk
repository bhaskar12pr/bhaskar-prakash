# Generic cocotb runner, called by the top-level Makefile for each block:
#   make -f scripts/cocotb.mk -C <cocotb dir> SOURCES_MK=... COCOTB_TOPLEVEL=... COCOTB_TEST_MODULES=... SIM=...
# SOURCES_MK is generated from the block's file list by scripts/filelist.py.

ifeq ($(SOURCES_MK),)
$(error SOURCES_MK is not set: run this through the top-level Makefile (make cocotb))
endif
include $(SOURCES_MK)

TOPLEVEL_LANG ?= verilog
COCOTB_MAKEFILES := $(shell cocotb-config --makefiles 2>/dev/null)
ifeq ($(COCOTB_MAKEFILES),)
$(error cocotb is not installed. Run: pip install -r requirements.txt)
endif
include $(COCOTB_MAKEFILES)/Makefile.sim
