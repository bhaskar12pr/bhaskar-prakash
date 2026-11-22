# bhaskar-prakash

Verilog designs with self-checking testbenches, run automatically by a GitLab CI/CD pipeline.

## Layout

```
rtl/            synthesizable designs (mux4to1.v)
tb/             testbenches, one per design, named tb_<design>.v
Makefile        build and run with Icarus Verilog
.gitlab-ci.yml  GitLab pipeline: lint -> test
```

## Run locally

Install Icarus Verilog (`sudo apt install iverilog make`), then run:

```sh
make lint    # compile the RTL with warnings on
make sim     # run every tb/tb_*.v; fails if any check fails
make clean
```

The waveform goes to `build/tb_mux4to1.vcd`. You can open it with GTKWave: `gtkwave build/tb_mux4to1.vcd`.

## CI/CD on GitLab

1. Push this repo to a GitLab project (`git remote add gitlab <url>` then `git push gitlab <branch>`).
2. GitLab finds `.gitlab-ci.yml` and runs the pipeline on every push and merge request:
   - **lint**: compiles all RTL.
   - **simulate**: runs every testbench. Logs and VCD waveforms are saved as job artifacts for one week.
3. If any testbench check fails, the job and the pipeline turn red.

Shared runners on gitlab.com work as is, because the jobs install `iverilog` inside an `ubuntu:24.04` container.

## Adding a new design

1. Put the module in `rtl/<name>.v`.
2. Write `tb/tb_<name>.v`. The top module must be named `tb_<name>`. It should print `ERROR: ...` for each mismatch and `TEST PASSED` at the end.
3. Run `make sim`. CI picks up the new testbench automatically.
