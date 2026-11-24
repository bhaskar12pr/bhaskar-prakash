# Simulator adapter: Synopsys VCS. NOT TESTED HERE (no licence);
# check it once on your setup, then the rest of the flow is unchanged.
# For UVM, add to project.mk:
#   SIM_COMPILE_FLAGS += -ntb_opts uvm-1.2
#   SIM_RUN_FLAGS     += +UVM_TESTNAME={test}
#   <block>_PATTERNS  := scripts/patterns/uvm.txt

SIM_TOOLS   := vcs
SIM_COMPILE  = vcs -full64 -sverilog -timescale=1ns/1ps $(SIM_COMPILE_FLAGS) -top $(2) -f $(1) -o simv
SIM_RUN      = $(3)/simv +ntb_random_seed={seed} +TEST={test} +SEED={seed} $(SIM_RUN_FLAGS)
