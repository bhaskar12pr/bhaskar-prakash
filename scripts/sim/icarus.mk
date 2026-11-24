# Simulator adapter: Icarus Verilog (open source). TESTED.
#
# Every adapter defines two templates used by scripts/regress.py:
#   SIM_COMPILE  runs once in build/<block>/sim/
#   SIM_RUN      runs per test in its own directory; may use {test} {seed} {rundir} {block}
#   Both get $(1) = flat file list, $(2) = top module, $(3) = compile directory.
# Extra flags come from project.mk: SIM_COMPILE_FLAGS, SIM_RUN_FLAGS, <block>_COMPILE_FLAGS, <block>_RUN_FLAGS.
# Icarus has no seed option: the testbench reads +SEED (see tb/tb_counter.v).

SIM_TOOLS   := iverilog vvp
SIM_COMPILE  = iverilog -g2012 -Wall $(SIM_COMPILE_FLAGS) -s $(2) -o sim.vvp -f $(1)
SIM_RUN      = vvp -n $(3)/sim.vvp +TEST={test} +SEED={seed} $(SIM_RUN_FLAGS)
