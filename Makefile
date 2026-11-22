# Verification flow for the designs in rtl/ and testbenches in tb/.
# The CI files (GitHub Actions and GitLab CI) only call these targets,
# so the same flow runs locally, on GitHub, and on GitLab.
#
#   make lint    Verilator lint (-Wall) + Icarus compile check of the RTL
#   make sim     run every tb/tb_*.v with Icarus; fails if any check fails
#   make synth   Yosys generic synthesis of every rtl/*.v; fails on latches
#   make junit   turn simulation logs into build/junit.xml (for CI reports)
#   make ci      lint + sim + synth + junit
#   make clean   remove build outputs
#
# Convention: rtl/<name>.v holds module <name>; tb/tb_<name>.v holds tb_<name>.

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

.PHONY: all ci lint sim synth junit clean
.PRECIOUS: $(BUILD)/%.vvp
all: ci
ci: lint sim synth junit

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

# Pass = log has "TEST PASSED" and no "ERROR".
$(BUILD)/%.log: $(BUILD)/%.vvp
	$(VVP) -n $< | tee $@
	@grep -q "TEST PASSED" $@ && ! grep -q "ERROR" $@ || (echo "FAILED: $*"; exit 1)

sim: $(SIMLOGS)

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
	rm -rf $(BUILD)
