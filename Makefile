# Build and run the Verilog testbenches with Icarus Verilog.
#   make sim    compile and run every testbench in tb/
#   make lint   compile only, warnings enabled
#   make clean  remove build outputs

IVERILOG ?= iverilog
VVP      ?= vvp
FLAGS    := -g2012 -Wall

RTL   := $(wildcard rtl/*.v)
TBS   := $(wildcard tb/tb_*.v)
BUILD := build
LOGS  := $(patsubst tb/%.v,$(BUILD)/%.log,$(TBS))

.PHONY: all sim lint clean
.PRECIOUS: $(BUILD)/%.vvp
all: sim

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/%.vvp: tb/%.v $(RTL) | $(BUILD)
	$(IVERILOG) $(FLAGS) -s $* -o $@ $< $(RTL)

# Run a testbench; the target fails if the log has no PASS line or any ERROR.
$(BUILD)/%.log: $(BUILD)/%.vvp
	$(VVP) -n $< | tee $@
	@grep -q "TEST PASSED" $@ && ! grep -q "ERROR" $@ || (echo "FAILED: $*"; exit 1)

sim: $(LOGS)

lint: | $(BUILD)
	$(IVERILOG) $(FLAGS) -o $(BUILD)/lint.out $(RTL)

clean:
	rm -rf $(BUILD)
