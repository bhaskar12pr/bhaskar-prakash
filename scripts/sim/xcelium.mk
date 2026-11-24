# Simulator adapter: Cadence Xcelium. NOT TESTED HERE (no licence);
# check it once on your setup, then the rest of the flow is unchanged.
# For UVM, add to project.mk:
#   SIM_COMPILE_FLAGS += -uvm
#   SIM_RUN_FLAGS     += +UVM_TESTNAME={test}
#   <block>_PATTERNS  := scripts/patterns/uvm.txt

SIM_TOOLS   := xrun
SIM_COMPILE  = xrun -elaborate -sv -timescale 1ns/1ps $(SIM_COMPILE_FLAGS) -top $(2) -f $(1) -xmlibdirname xcelium.d
SIM_RUN      = xrun -R -xmlibdirname $(3)/xcelium.d -svseed {seed} +TEST={test} +SEED={seed} $(SIM_RUN_FLAGS)
