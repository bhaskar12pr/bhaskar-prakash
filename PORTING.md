# Porting the verification flow to another repo

The flow is split into an **engine** that you copy unchanged and **settings** that you edit.

| Copy as is (engine) | Edit for your project (settings) |
|---|---|
| `Makefile` | `project.mk`: blocks, file lists, tests, simulator, flags |
| `scripts/` (Python 3.6+, standard library only) | `.gitlab-ci.yml`: only the `SITE SETTINGS` block |
| `.gitlab-ci.yml` | your `.f` file lists |
| `requirements.txt` (only if you use cocotb) | |

## Step by step

1. **Copy** `Makefile`, `scripts/`, `.gitlab-ci.yml` and `project.mk` into the root of your work repo.
   - If your repo already has a `Makefile`, rename this one to `verif.mk` and run `make -f verif.mk ...`.
     Rerun commands printed on failure include the `-f verif.mk` automatically.
   - If your repo already has a `scripts/` folder, put the kit somewhere else (e.g. `verif/kit/`) and set
     `KIT ?= verif/kit` at the top of `project.mk`.
2. **Check your environment** on a machine where you normally run simulations:
   ```sh
   make check-env SIM=questa        # or vcs / xcelium / icarus
   make selftest                    # unit tests of the flow scripts (Python only)
   ```
3. **Describe your blocks** in `project.mk`. You need at least a design file list:
   ```make
   SIM    ?= questa
   BLOCKS ?= uart_tx
   uart_tx_RTL_F  := verif/uart_tx/rtl.f
   uart_tx_TB_F   := verif/uart_tx/tb.f
   uart_tx_TB_TOP := tb_top
   uart_tx_TESTS  := smoke baud_sweep parity_err
   ```
   Then `make list` shows what each stage will run.
4. **Check the simulator adapter once** (`scripts/sim/<sim>.mk`). Icarus is tested here. The Questa,
   VCS and Xcelium adapters use the standard commands but could not be run here without licences.
   Run one test, read `build/<block>/sim/compile.log` and the test's `sim.log`, and adjust the
   two lines in the adapter if your site uses different options.
5. **Run locally**: `make lint`, then `make sim-uart_tx TEST=smoke`, then `make sim SEEDS=5`.
6. **Set up CI**: edit the `SITE SETTINGS` block in `.gitlab-ci.yml` (see below), push, and open a merge request.

## Your testbench and the pass/fail rules

`scripts/regress.py` runs each test as `+TEST=<name> +SEED=<n>`. A test **passes only if** all of these hold:
- it exits with code 0 before the timeout (a hung test is killed, including child processes),
- no log line matches a `fail:` pattern,
- at least one line matches a `pass:` pattern. A test that stops silently is a failure.

Pattern files are in `scripts/patterns/`:
- `default.txt` is for self-checking testbenches. Print `TEST PASSED` at the end, use `ERROR`/`$fatal` for problems.
  It also catches Questa `** Error`, VCS `Error-[...]` and Xcelium `*E,` messages.
- `uvm.txt` is for UVM. It passes on `UVM_ERROR : 0` in the report summary and fails on any `UVM_ERROR`/`UVM_FATAL` message.
  Use it per block with `<block>_PATTERNS := scripts/patterns/uvm.txt`, plus `SIM_RUN_FLAGS ?= +UVM_TESTNAME={test}`.
- To waive a known message, copy a pattern file and add `ignore: <regex>`.

## File lists

`scripts/filelist.py` reads your `.f` files once and produces the same file set for every tool.
It supports nested `-f`/`-F`, `+incdir+`, `+define+`, `-I`, `-D`, `-v`, `-y`, comments, and `$VAR`/`${VAR}`.
- Relative paths are resolved against the **file list's own folder** by default. If your existing lists are
  written relative to the repo root, set `FILELIST_RELATIVE ?= cwd` in `project.mk`.
- A missing file or unset `$VAR` stops the run with the file name and line number.
- Vendor libraries given with `-v`/`-y` reach the simulator only. Yosys and cocotb get a warning.

## GitLab CI at work

Edit only the `SITE SETTINGS` block:
```yaml
variables:
  SIM: questa
  TOOL_SETUP: >-
    source /etc/profile.d/modules.sh &&
    module load questa/2024.2 &&
    export LM_LICENSE_FILE=1717@licserver
  COCOTB_SETUP: >-
    python3 -m venv .venv && . .venv/bin/activate &&
    pip install -q --index-url https://pypi.mycompany.local/simple -r requirements.txt
```
and under `default:` uncomment `tags: [your-runner-tag]`.

- **Runner**: commercial simulators need a self-hosted runner (shell or Docker executor) on a machine
  that can reach the licence server. Ask your CI/CAD team which tag to use. `image:` is ignored by shell runners.
- **Nightly regression**: in GitLab, go to Build → Pipeline schedules → New schedule. The `sim` job then
  runs `NIGHTLY_SEEDS` random seeds per test. Every failure prints its exact `make ... SEED=` rerun command.
- **Results**: merge requests show every test in the **Tests** tab (JUnit). Logs and waveforms are
  job artifacts for one week.
- **Unused stages**: a stage with no blocks configured does nothing and passes. You can also delete its job.

## Things to agree with your team first

- Company RTL must stay on company systems. Copy the flow *into* the work repo; never copy RTL out.
- Licence use: `JOBS` sets how many simulations run in parallel per job, and each one uses a licence.
- Where waveforms go: big `.vcd`/`.wlf`/`.fsdb` files as artifacts may need a size limit or `when: on_failure`.

## Command reference

```
make help                          all targets and variables
make list                          blocks, tests, enabled stages
make sim BLOCKS=uart_tx TEST=smoke one block, one test
make sim SEEDS=20 RANDOM_SEEDS=1   small local regression
make sim-uart_tx TEST=smoke SEED=1838 rerun a failure exactly
make sim TIMEOUT=30                command-line timeout beats <block>_TIMEOUT
make -j4 sim                       blocks in parallel (and JOBS tests per block)
```
