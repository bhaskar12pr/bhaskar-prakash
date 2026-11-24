# Simulator adapter: Siemens Questa / ModelSim. NOT TESTED HERE (no licence);
# check it once on your setup, then the rest of the flow is unchanged.
# For UVM, add to project.mk:
#   SIM_COMPILE_FLAGS += -L $(QUESTA_HOME)/uvm-1.2      (or your site's UVM library)
#   SIM_RUN_FLAGS     += +UVM_TESTNAME={test}
#   <block>_PATTERNS  := scripts/patterns/uvm.txt

SIM_TOOLS   := vlib vlog vopt vsim
SIM_COMPILE  = vlib work && vlog -sv -timescale 1ns/1ps $(SIM_COMPILE_FLAGS) -f $(1) && vopt +acc=npr $(2) -o $(2)_opt
SIM_RUN      = vsim -c -lib $(3)/work $(2)_opt -sv_seed {seed} +TEST={test} +SEED={seed} -l sim_vsim.log -do "run -all; quit -f" $(SIM_RUN_FLAGS)
