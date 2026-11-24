# bhaskar-prakash

[![RTL CI](https://github.com/bhaskar12pr/bhaskar-prakash/actions/workflows/ci.yml/badge.svg)](https://github.com/bhaskar12pr/bhaskar-prakash/actions/workflows/ci.yml)

A portable RTL verification flow (lint, simulation regression, cocotb, formal, synthesis) with CI for
**GitHub Actions** (used now) and **GitLab CI** (ready). It comes with two example blocks.

To use the flow in another repo, see **[PORTING.md](PORTING.md)**.

## Layout

```
Makefile              engine: all stages and per-block rules (copy as is)
project.mk            settings: blocks, file lists, tests, simulator (edit this)
scripts/
  filelist.py         resolves .f file lists (nested -f, +incdir+, +define+, $VARS) for every tool
  regress.py          compiles once, runs tests x seeds in parallel, timeouts, pass/fail, JUnit, rerun commands
  junit_summary.py    Markdown table of results (GitHub run summary)
  sim/*.mk            simulator adapters: icarus (tested), questa, vcs, xcelium
  patterns/*.txt      pass/fail rules: default (self-checking TBs) and uvm
  cocotb.mk           generic cocotb runner
  tests/              unit tests of the scripts (make selftest)
.gitlab-ci.yml        GitLab pipeline; site-specific parts in one SITE SETTINGS block
.github/workflows/    GitHub Actions pipeline (same stages)

filelists/            .f files for the example blocks
rtl/  tb/  formal/    example designs: mux4to1 (combinational), counter (clocked, 3 tests)
```

## Quick start

```sh
sudo apt install make python3 iverilog verilator yosys      # cocotb: pip install -r requirements.txt
make help          # targets and variables
make list          # blocks, tests and enabled stages
make check-env     # are the tools installed? do the file lists resolve?
make ci            # lint + sim + cocotb + formal + synth
```

## Stages

| Stage | Command | What it does | Fails when |
|---|---|---|---|
| lint | `make lint` | Verilator `-Wall` on each block's design | any lint warning or error |
| sim | `make sim` | compiles once, runs every test x seed in parallel with `SIM=` | error/fatal in the log, non-zero exit, no `TEST PASSED`, timeout |
| cocotb | `make cocotb` | Python testbenches | any cocotb test fails |
| formal | `make formal` | Yosys SAT proof of `formal/<block>_props.sv` | an input breaks an assertion; that input is printed |
| synth | `make synth` | Yosys generic synthesis, cell count | a latch is inferred |

Each stage also runs for a single block, e.g. `make sim-counter`.

## Running regressions

```sh
make sim BLOCKS=counter TEST=count         # one block, one test
make sim SEEDS=10                          # seeds 1..10 for every test
make sim SEEDS=10 RANDOM_SEEDS=1           # 10 random seeds per test
make sim-counter TEST=count SEED=1838      # rerun a failure exactly
```

Every failure prints its reason, the last lines of its log, and the exact rerun command:

```
[counter] [2/6] FAIL  count seed=1  (0.0s)
    reason: simulator exit code 1; line 5: ERROR: t=300000 q=15 wrap=1, expected q=15 wrap=0
    log:    build/counter/sim/count_s1/sim.log
    rerun:  make sim-counter TEST=count SEED=1
```

Each test runs in its own folder `build/<block>/sim/<test>_s<seed>/` with `sim.log` and its waveform.

## CI

| | GitHub Actions | GitLab CI |
|---|---|---|
| Push / PR or MR | selftest + lint, then sim, cocotb, formal and synth in parallel, 1 seed per test | same |
| Nightly | scheduled, 20 random seeds per test | create a pipeline schedule; `NIGHTLY_SEEDS` random seeds |
| Results | run summary table + artifacts | MR **Tests** tab + artifacts |

## How the flow is checked

- `make selftest` runs 24 unit tests of the scripts. They cover nested file lists, env vars, missing files,
  include loops, every pass/fail rule (including Questa, VCS, Xcelium and UVM message formats), timeouts that
  kill child processes, seeds, parallel runs and compile failures.
- RTL bugs, hung tests, compile errors, missing files and config mistakes were each injected on purpose and
  confirmed to fail with a clear message.
- The kit was also copied into a separate test repo with its own `Makefile` and `scripts/`, a different
  layout, and `$VAR` file lists. It ran there without changes to the engine.
- The scripts need only Python 3.6+ and the standard library. That minimum was checked with a static
  analyser, not by running Python 3.6.
- The Questa, VCS and Xcelium adapters have not been run (no licences here). Check them once at your site.
