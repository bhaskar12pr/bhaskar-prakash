# Verification flow for the designs in rtl/ and testbenches in tb/.
# The CI files (GitHub Actions and GitLab CI) only call these targets,
# so the same flow runs locally, on GitHub, and on GitLab.
#
#   make lint    Verilator lint (-Wall) + Icarus compile check of the RTL
#   make sim     run every tb/tb_*.v with Icarus; fails if any check fails
#   make synth   Yosys generic synthesis of every rtl/*.v; fails on latches
#   make formal  Yosys SAT proof of every formal/<name>_props.sv
#   make cocotb  run the Python (cocotb) tests in tb/cocotb -> build/cocotb_results.xml
#   make junit   turn simulation logs into build/junit.xml (for CI reports)
#   make ci      lint + sim + cocotb + formal + synth + junit
#   make clean   remove build outputs
#
# Convention: rtl/<name>.v holds module <name>; tb/tb_<name>.v holds tb_<name>;
#             formal/<name>_props.sv holds module <name>_props.

IVERILOG  ?= iverilog
VVP       ?= vvp
VERILATOR ?= verilator
YOSYS     ?= yosys
PYTHON    ?= python3

IVFLAGS := -g2012 -Wall
BUILD   := build

RTL     := $(wildcard rtl/*.v)
TBS     := $(wildcard tb/tb_*.v)
MODULES := $(basename $(notdir $(RTL)))
SIMLOGS := $(patsubst tb/%.v,$(BUILD)/%.log,$(TBS))
SYNLOGS := $(patsubst %,$(BUILD)/synth_%.log,$(MODULES))
LINTS   := $(patsubst %,$(BUILD)/lint_%.ok,$(MODULES))
PROPS   := $(wildcard formal/*_props.sv)
FMLOGS  := $(patsubst formal/%_props.sv,$(BUILD)/formal_%.log,$(PROPS))

.PHONY: all ci lint sim cocotb formal synth junit clean
.PRECIOUS: $(BUILD)/%.vvp
all: ci
ci: lint sim cocotb formal synth junit

$(BUILD):
	mkdir -p $(BUILD)

# ---- lint ------------------------------------------------------------------
$(BUILD)/lint_%.ok: rtl/%.v $(RTL) | $(BUILD)
	$(VERILATOR) --lint-only -Wall -Irtl --top-module $* $<
	$(IVERILOG) $(IVFLAGS) -s $* -o /dev/null $(RTL)
	@touch $@

lint: $(LINTS)

# ---- simulation ------------------------------------------------------------
$(BUILD)/%.vvp: tb/%.v $(RTL) | $(BUILD)
	$(IVERILOG) $(IVFLAGS) -s $* -o $@ $< $(RTL)

# Pass = simulator exits 0 ($$fatal makes it non-zero), the log has
# "TEST PASSED", and no line contains "ERROR".
$(BUILD)/%.log: $(BUILD)/%.vvp
	@$(VVP) -n $< > $@ 2>&1; status=$$?; cat $@; \
	if [ $$status -ne 0 ] || ! grep -q "TEST PASSED" $@ || grep -q "ERROR" $@; then \
	  echo "FAILED: $*"; exit 1; fi

sim: $(SIMLOGS)

# ---- cocotb (Python testbenches) ------------------------------------------
cocotb: | $(BUILD)
	$(MAKE) -C tb/cocotb COCOTB_RESULTS_FILE=$(abspath $(BUILD))/cocotb_results.xml

# ---- formal ----------------------------------------------------------------
# Proves the assertions in formal/<name>_props.sv for every possible input.
# On failure, Yosys prints the counterexample (the inputs that break it).
$(BUILD)/formal_%.log: formal/%_props.sv $(RTL) | $(BUILD)
	@$(YOSYS) -l $@ -p "read_verilog -formal $(RTL) $<; prep -top $*_props; flatten; sat -prove-asserts -show-inputs" > /dev/null
	@if grep -q "SUCCESS!" $@; then echo "PROVEN: $*"; \
	else sed -n '/model found: FAIL/,/^$$/p;/Signal Name/,/^$$/p' $@; echo "FAILED: formal proof of $*"; exit 1; fi

formal: $(FMLOGS)

# ---- synthesis -------------------------------------------------------------
# Generic (technology-independent) synthesis: proves the RTL is synthesizable,
# reports the cell count, and fails if any latch was inferred.
$(BUILD)/synth_%.log: rtl/%.v $(RTL) | $(BUILD)
	$(YOSYS) -q -l $@ -p "read_verilog -sv $(RTL); synth -top $*; stat; write_json $(BUILD)/synth_$*.json"
	@! grep -qE "^Latch inferred|\$$_DLATCH" $@ || (echo "FAILED: latch inferred in $*"; exit 1)
	@sed -n '/Number of cells/,/^$$/p' $@

synth: $(SYNLOGS)

# ---- reports ---------------------------------------------------------------
junit: | $(BUILD)
	$(PYTHON) scripts/logs_to_junit.py $(TBS) --build $(BUILD) --out $(BUILD)/junit.xml

clean:
	rm -rf $(BUILD) tb/cocotb/sim_build tb/cocotb/results.xml
