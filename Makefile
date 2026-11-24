# =============================================================================
# RTL verification flow: lint, simulation regression, cocotb, formal, synthesis.
#
# This file is the ENGINE. Copy it as is with scripts/ into any repo.
# Put everything project-specific in project.mk (blocks, file lists, tests,
# simulator, flags). Run "make help" for usage.
# Requires: GNU Make 3.82+, bash, Python 3.6+, and the tools for the stages you use.
# =============================================================================

SHELL         := /bin/bash
.SHELLFLAGS   := -eu -o pipefail -c
.DEFAULT_GOAL := help
.DELETE_ON_ERROR:
MAKEFLAGS     += --no-builtin-rules --no-print-directory

PROJECT_MK ?= project.mk
ifeq ($(wildcard $(PROJECT_MK)),)
$(error $(PROJECT_MK) not found. Copy the example project.mk and list your blocks in it)
endif
include $(PROJECT_MK)

# ---- defaults (override in project.mk, the environment, or the command line)
# Priority for TIMEOUT: command line > <block>_TIMEOUT > project.mk/environment.
KIT               ?= scripts
SIM               ?= icarus
PYTHON            ?= python3
BUILD             ?= build
JOBS              ?= $(shell nproc 2>/dev/null || echo 4)
SEEDS             ?= 1
SEED              ?=
BASE_SEED         ?= 1
RANDOM_SEEDS      ?= 0
TIMEOUT           ?= 600
COMPILE_TIMEOUT   ?= 1800
TEST              ?=
PATTERNS          ?= $(KIT)/patterns/default.txt
FILELIST_RELATIVE ?= file
LINT_TOOL         ?= verilator
VERILATOR         ?= verilator
LINT_FLAGS        ?= -Wall
YOSYS             ?= yosys
COCOTB_SIM        ?= $(SIM)

ifeq ($(strip $(BLOCKS)),)
$(error BLOCKS is empty in $(PROJECT_MK))
endif
ADAPTER := $(KIT)/sim/$(SIM).mk
ifeq ($(wildcard $(ADAPTER)),)
$(error Unknown SIM=$(SIM): no $(ADAPTER). Available: $(notdir $(basename $(wildcard $(KIT)/sim/*.mk))))
endif
include $(ADAPTER)

ABS_BUILD := $(abspath $(BUILD))
# The command printed to rerun a failure ("make -f verif.mk" if this file was renamed)
THIS_MAKEFILE := $(firstword $(MAKEFILE_LIST))
RERUN_MAKE    := make$(if $(filter-out Makefile makefile GNUmakefile,$(THIS_MAKEFILE)), -f $(THIS_MAKEFILE))$(if $(filter-out project.mk,$(PROJECT_MK)), PROJECT_MK=$(PROJECT_MK))
RESOLVE    = $(PYTHON) $(KIT)/filelist.py --relative-to $(FILELIST_RELATIVE)
REGRESS    = $(PYTHON) $(KIT)/regress.py

# ---- which blocks take part in which stage (decided by project.mk) ----------
SIM_BLOCKS    := $(foreach b,$(BLOCKS),$(if $($(b)_TB_TOP),$(b)))
COCOTB_BLOCKS := $(foreach b,$(BLOCKS),$(if $($(b)_COCOTB_MODULE),$(b)))
FORMAL_BLOCKS := $(foreach b,$(BLOCKS),$(if $($(b)_FORMAL),$(b)))
SYNTH_BLOCKS  := $(foreach b,$(BLOCKS),$(if $(filter 1 yes true,$($(b)_SYNTH)),$(b)))

# ---- check project.mk early, with clear messages ----------------------------
$(foreach b,$(BLOCKS),\
  $(if $($(b)_RTL_F),,$(error $(PROJECT_MK): $(b)_RTL_F is not set (design file list for block $(b))))\
  $(if $(wildcard $($(b)_RTL_F)),,$(error $(PROJECT_MK): $(b)_RTL_F=$($(b)_RTL_F) does not exist)))
$(foreach b,$(SIM_BLOCKS),\
  $(if $($(b)_TB_F),,$(error $(PROJECT_MK): $(b)_TB_TOP is set but $(b)_TB_F (testbench file list) is not))\
  $(if $($(b)_TESTS),,$(error $(PROJECT_MK): $(b)_TESTS is empty; use "default" for a single test)))

.PHONY: help list ci lint sim cocotb formal synth selftest check-env clean FORCE
FORCE:

help:
	@echo "Usage: make <target> [VAR=value ...]"
	@echo
	@echo "Targets"
	@echo "  ci          lint + sim + cocotb + formal + synth"
	@echo "  lint        $(LINT_TOOL) lint of each block's design"
	@echo "  sim         compile and run each block's tests with SIM=$(SIM)"
	@echo "  cocotb      run each block's cocotb (Python) tests"
	@echo "  formal      Yosys proof of each block's formal properties"
	@echo "  synth       Yosys synthesis of each block (fails on latches)"
	@echo "  <stage>-<block>   one stage for one block, e.g. sim-$(firstword $(SIM_BLOCKS))"
	@echo "  list        show blocks, tests and what each stage covers"
	@echo "  check-env   check tools and file lists (STAGES=\"sim lint\" to check only some)"
	@echo "  selftest    unit tests of the flow scripts"
	@echo "  clean       delete $(BUILD)/"
	@echo
	@echo "Variables (also settable in project.mk or the environment)"
	@echo "  BLOCKS='a b'     only these blocks          TEST='t1 t2'   only these tests"
	@echo "  SEEDS=N          seeds per test ($(SEEDS))           SEED=N         one exact seed"
	@echo "  RANDOM_SEEDS=1   random instead of 1,2,3..   JOBS=N         parallel runs ($(JOBS))"
	@echo "  TIMEOUT=sec      per test ($(TIMEOUT))            SIM=name       $(notdir $(basename $(wildcard $(KIT)/sim/*.mk)))"

list:
	@printf "%-16s %-8s %-8s %-8s %-8s %s\n" BLOCK SIM COCOTB FORMAL SYNTH TESTS
	@$(foreach b,$(BLOCKS),printf "%-16s %-8s %-8s %-8s %-8s %s\n" $(b) \
	  $(if $(filter $(b),$(SIM_BLOCKS)),yes,-) $(if $(filter $(b),$(COCOTB_BLOCKS)),yes,-) \
	  $(if $(filter $(b),$(FORMAL_BLOCKS)),yes,-) $(if $(filter $(b),$(SYNTH_BLOCKS)),yes,-) "$(strip $($(b)_TESTS))";)

ci: lint sim cocotb formal synth

lint:   $(if $(filter-out none,$(LINT_TOOL)),$(addprefix lint-,$(BLOCKS)))
sim:    $(addprefix sim-,$(SIM_BLOCKS))
cocotb: $(addprefix cocotb-,$(COCOTB_BLOCKS))
formal: $(addprefix formal-,$(FORMAL_BLOCKS))
synth:  $(addprefix synth-,$(SYNTH_BLOCKS))

# ---- per-block rules ----------------------------------------------------------
# $(1) = block name. $$ delays expansion until the rule runs.
define BLOCK_RULES
.PHONY: resolve-$(1) lint-$(1) sim-$(1) cocotb-$(1) formal-$(1) synth-$(1)

# Design-only file list -> build/<block>/rtl.{f,sources,yosys,cocotb.mk}
resolve-$(1):
	@$(RESOLVE) --out $(ABS_BUILD)/$(1)/rtl $($(1)_RTL_F)

lint-$(1): tools-lint resolve-$(1)
	@echo "[$(1)] lint ($(LINT_TOOL))"
	@cd $(ABS_BUILD)/$(1) && $(VERILATOR) --lint-only $(LINT_FLAGS) $($(1)_LINT_FLAGS) \
	  --top-module $(or $($(1)_TOP),$(1)) -f rtl.f 2>&1 | tee lint.log

sim-$(1): tools-sim
	@$(RESOLVE) --out $(ABS_BUILD)/$(1)/tb $($(1)_TB_F)
	@$(REGRESS) --name $(1) --outdir $(ABS_BUILD)/$(1)/sim \
	  --compile '$(call SIM_COMPILE,$(ABS_BUILD)/$(1)/tb.f,$($(1)_TB_TOP),$(ABS_BUILD)/$(1)/sim) $($(1)_COMPILE_FLAGS)' \
	  --run '$(call SIM_RUN,$(ABS_BUILD)/$(1)/tb.f,$($(1)_TB_TOP),$(ABS_BUILD)/$(1)/sim) $($(1)_RUN_FLAGS)' \
	  --tests $(or $(TEST),$($(1)_TESTS)) --seeds $(SEEDS) $(if $(SEED),--seed $(SEED)) --base-seed $(BASE_SEED) \
	  $(if $(filter 1 yes true,$(RANDOM_SEEDS)),--random-seeds) \
	  --jobs $(JOBS) --timeout $(if $(filter command line,$(origin TIMEOUT)),$(TIMEOUT),$(or $($(1)_TIMEOUT),$(TIMEOUT))) --compile-timeout $(COMPILE_TIMEOUT) \
	  $(foreach p,$(or $($(1)_PATTERNS),$(PATTERNS)),--patterns $(p)) \
	  --junit $(ABS_BUILD)/$(1)/junit_sim.xml \
	  --rerun '$(RERUN_MAKE) sim-$(1) TEST={test} SEED={seed}'

cocotb-$(1): tools-cocotb resolve-$(1)
	@echo "[$(1)] cocotb ($(COCOTB_SIM))"
	@rm -f $(ABS_BUILD)/$(1)/junit_cocotb.xml
	@$(MAKE) -f $(abspath $(KIT)/cocotb.mk) -C $($(1)_COCOTB_DIR) \
	  SOURCES_MK=$(ABS_BUILD)/$(1)/rtl.cocotb.mk SIM=$(COCOTB_SIM) \
	  COCOTB_TOPLEVEL=$(or $($(1)_TOP),$(1)) COCOTB_TEST_MODULES=$($(1)_COCOTB_MODULE) \
	  SIM_BUILD=$(ABS_BUILD)/$(1)/cocotb_build COCOTB_RESULTS_FILE=$(ABS_BUILD)/$(1)/junit_cocotb.xml \
	  $(if $(SEED),COCOTB_RANDOM_SEED=$(SEED)) $(if $(TEST),COCOTB_TEST_FILTER="$(subst $(eval) ,|,$(strip $(TEST)))") \
	  > $(ABS_BUILD)/$(1)/cocotb.log 2>&1 \
	  && grep -E "TESTS=" $(ABS_BUILD)/$(1)/cocotb.log \
	  || { tail -n 40 $(ABS_BUILD)/$(1)/cocotb.log; echo "[$(1)] cocotb FAILED (log: $(BUILD)/$(1)/cocotb.log)"; exit 1; }

# One-step SAT proof: complete for blocks without state (combinational logic).
formal-$(1): tools-formal resolve-$(1)
	@echo "[$(1)] formal"
	@$(YOSYS) -l $(ABS_BUILD)/$(1)/formal.log -p "read_verilog -formal -sv $$$$(cat $(ABS_BUILD)/$(1)/rtl.yosys) \
	  $$$$(tr '\n' ' ' < $(ABS_BUILD)/$(1)/rtl.sources) $(abspath $($(1)_FORMAL)); \
	  prep -top $(or $($(1)_FORMAL_TOP),$(1)_props); flatten; sat -prove-asserts -show-inputs" > /dev/null
	@if grep -q "SUCCESS!" $(ABS_BUILD)/$(1)/formal.log; then echo "[$(1)] PROVEN"; \
	 else sed -n '/model found: FAIL/p;/Signal Name/,/^$$$$/p' $(ABS_BUILD)/$(1)/formal.log; \
	      echo "[$(1)] formal FAILED (log: $(BUILD)/$(1)/formal.log)"; exit 1; fi

synth-$(1): tools-synth resolve-$(1)
	@echo "[$(1)] synth"
	@$(YOSYS) -q -l $(ABS_BUILD)/$(1)/synth.log -p "read_verilog -sv $$$$(cat $(ABS_BUILD)/$(1)/rtl.yosys) \
	  $$$$(tr '\n' ' ' < $(ABS_BUILD)/$(1)/rtl.sources); \
	  synth -top $(or $($(1)_TOP),$(1)); write_json $(ABS_BUILD)/$(1)/synth.json"
	@if grep -qE "^Latch inferred|\$$$$_DLATCH" $(ABS_BUILD)/$(1)/synth.log; then \
	   grep -E "^Latch inferred" $(ABS_BUILD)/$(1)/synth.log || true; \
	   echo "[$(1)] synth FAILED: latch inferred"; exit 1; fi
	@sed -n '/Number of cells/,/^$$$$/p' $(ABS_BUILD)/$(1)/synth.log | head -20
endef
$(foreach b,$(BLOCKS),$(eval $(call BLOCK_RULES,$(b))))

# ---- tool checks --------------------------------------------------------------
# Each stage checks its own tools first, so a missing tool gives one clear line.
TOOLS_lint   := $(if $(filter-out none,$(LINT_TOOL)),$(VERILATOR))
TOOLS_sim    := $(SIM_TOOLS)
TOOLS_cocotb := cocotb-config
TOOLS_formal := $(YOSYS)
TOOLS_synth  := $(YOSYS)
STAGES_USED  := $(if $(TOOLS_lint),lint) $(if $(SIM_BLOCKS),sim) $(if $(COCOTB_BLOCKS),cocotb) \
                $(if $(FORMAL_BLOCKS),formal) $(if $(SYNTH_BLOCKS),synth)
STAGES       ?= $(STAGES_USED)

# Not marked .PHONY on purpose: GNU Make skips pattern rules for phony targets.
tools-%:
	@for t in $(TOOLS_$*); do command -v $$t > /dev/null || { \
	  echo "make $*: '$$t' was not found on PATH. Load it (e.g. 'module load ...') or run 'make check-env'."; exit 1; }; done

check-env:
	@echo "Project: $(PROJECT_MK)   SIM=$(SIM)   blocks: $(BLOCKS)   stages: $(strip $(STAGES))"
	@$(PYTHON) -c 'import sys; v=sys.version_info; print("  ok       python %d.%d.%d" % v[:3]); sys.exit(0 if v >= (3, 6) else "Python 3.6+ is required")'
	@missing=0; for t in $(sort $(foreach s,$(STAGES),$(TOOLS_$(s)))); do \
	  if p=$$(command -v $$t); then printf "  ok       %-14s %s\n" $$t "$$p"; \
	  else printf "  MISSING  %s\n" $$t; missing=1; fi; done; \
	  if [ $$missing = 1 ]; then echo "Some tools are missing: load them, or remove those stages from project.mk"; exit 1; fi
	@$(foreach b,$(BLOCKS),$(RESOLVE) --quiet --out $(ABS_BUILD)/$(b)/rtl $($(b)_RTL_F) && \
	  $(if $($(b)_TB_F),$(RESOLVE) --quiet --out $(ABS_BUILD)/$(b)/tb $($(b)_TB_F) &&) echo "  ok       file lists of $(b)";)

selftest:
	@$(PYTHON) -m unittest discover -s $(KIT)/tests -t $(KIT) -v

# Deletes BUILD only when it is a folder inside this repo (never the repo itself or /).
clean:
	@case "$(ABS_BUILD)/" in "$(CURDIR)"/?*/) rm -rf -- "$(ABS_BUILD)";; \
	  *) echo "refusing to delete BUILD=$(BUILD): it must be a folder inside $(CURDIR)"; exit 1;; esac
