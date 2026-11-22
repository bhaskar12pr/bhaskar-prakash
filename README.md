# bhaskar-prakash

[![RTL CI](https://github.com/bhaskar12pr/bhaskar-prakash/actions/workflows/ci.yml/badge.svg)](https://github.com/bhaskar12pr/bhaskar-prakash/actions/workflows/ci.yml)

Verilog designs with self-checking testbenches and a CI/CD pipeline.
The pipeline runs on **GitHub Actions** today and is ready for **GitLab CI** later.

## Layout

```
rtl/                       designs: rtl/<name>.v holds module <name>
tb/                        Verilog testbenches: tb/tb_<name>.v holds module tb_<name>
tb/cocotb/                 Python (cocotb) testbenches
formal/                    formal properties: formal/<name>_props.sv
requirements.txt           Python packages (cocotb)
scripts/logs_to_junit.py   turns Verilog testbench logs into a JUnit test report
scripts/junit_summary.py   prints a pass/fail table from a JUnit report
Makefile                   the whole flow; the CI files only call make
.github/workflows/ci.yml   GitHub Actions pipeline (active now)
.github/dependabot.yml     keeps the GitHub Actions versions up to date
.gitlab-ci.yml             GitLab CI pipeline (used after moving to GitLab)
```

## Flow

```
push / PR or MR
   │
   ▼
lint      Verilator -Wall + Icarus compile        make lint
   │
   ├──► simulate   Icarus runs every tb/tb_*.v    make sim  → JUnit report, logs, .vcd
   ├──► cocotb     Python tests on Icarus         make cocotb → JUnit report
   ├──► formal     Yosys SAT proof                make formal → proof, or the failing input
   └──► synth      Yosys generic synthesis        make synth → cell count, fails on latches
```

| Tool | Used for |
|---|---|
| Icarus Verilog | simulation |
| Verilator | strict lint |
| Yosys | synthesis check, formal proof |
| cocotb | Python testbenches |

## Run locally

```sh
sudo apt install iverilog verilator yosys make python3 python3-venv
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt

make ci      # lint + sim + cocotb + formal + synth + junit
make sim     # just the Verilog testbenches
make cocotb  # just the Python testbenches
make formal  # just the formal proofs
make clean
```

Waveforms are written to `build/tb_<name>.vcd`. Open one with `gtkwave build/tb_mux4to1.vcd`.

## Results in CI

- **GitHub:** open the Actions tab and pick a run. The summary page shows a pass/fail table for each testbench. The `simulation` and `synthesis` artifacts hold the logs and waveforms.
- **GitLab:** go to Build → Pipelines. Merge requests show the results in their **Tests** tab, and each job keeps its artifacts for one week.

## Moving to GitLab later

1. Create a blank project on gitlab.com.
2. Push the code:
   ```sh
   git remote add gitlab https://gitlab.com/<you>/<project>.git
   git push gitlab --all
   ```
3. GitLab picks up `.gitlab-ci.yml` automatically. Nothing else needs to change, because both pipelines run the same Makefile.
4. Optional: under Settings → Merge requests, turn on "Pipelines must succeed".

You can also keep GitHub as the main repo and set up GitLab's **pull mirroring**. GitLab then copies every GitHub push and runs its own pipeline.

## cocotb (Python testbenches)

`tb/cocotb/test_mux4to1.py` tests the same mux from Python. Each `@cocotb.test()` function is reported as its own test:

| Test | What it checks |
|---|---|
| `test_exhaustive` | all 64 input combinations against a Python reference model |
| `test_one_hot` | only one input high; the output is high only when it is selected |
| `test_random` | 1000 random vectors |

Random tests print their seed. To replay a failure, run `make cocotb COCOTB_RANDOM_SEED=<seed>`.
To also dump a waveform, run `make -C tb/cocotb WAVES=1`.

## Formal verification

Simulation checks the inputs you try. A formal proof checks **every** possible input.
`formal/mux4to1_props.sv` wraps the design and states the rule `assert (ow == i[s]);`.
`make formal` asks Yosys's SAT solver to find any input that breaks the rule:

- If none exists, it prints `PROVEN: mux4to1`.
- If one exists, it prints that input as a counterexample and the job fails, for example:
  ```
  Signal Name    Dec  Hex   Bin
  \i               1    1  0001
  \s               3    3    11
  FAILED: formal proof of mux4to1
  ```

This one-step proof covers designs without a clock. Designs with registers need a multi-step proof, which SymbiYosys (`sby`) handles.

## Good practices used here

| Practice | Where it comes from | Here |
|---|---|---|
| One build script, thin CI files | Most mature HDL repos | The `Makefile` does the work; CI files only call `make` |
| One test folder per design, cocotb, Icarus as the default simulator | cocotb examples and docs, alexforencich's verilog-* repos | `tb/cocotb/`, `SIM ?= icarus` |
| Seeded random tests that can be replayed | cocotb | `COCOTB_RANDOM_SEED` |
| Formal proofs next to simulation | YosysHQ, ZipCPU | `formal/`, `make formal` |
| Self-checking testbenches that fail by exit code | Common DV practice | `$fatal` plus a `TEST PASSED` check |
| Strict lint before simulating | lowRISC and other large RTL projects | Verilator `-Wall` in the first stage |
| Machine-readable test reports | GitHub and GitLab CI | JUnit XML, the run summary, the MR Tests tab |
| CI hygiene | GitHub and GitLab docs | Cancel outdated runs, read-only token, timeouts, no duplicate MR pipelines, pip cache, Dependabot |

## Adding a new design

1. Create `rtl/<name>.v` containing `module <name>`.
2. Create `tb/tb_<name>.v` containing `module tb_<name>`. It should print `ERROR: ...` for each mismatch, end with `TEST PASSED` and `$finish` on success, and call `$fatal` on failure. Use `tb/tb_mux4to1.v` as a template.
3. Run `make ci`. Both pipelines pick up the new files automatically.
4. Optional, formal: add `formal/<name>_props.sv` with module `<name>_props`, which instantiates the design and contains `assert` statements.
5. Optional, cocotb: copy `tb/cocotb/` to a new folder. Change `VERILOG_SOURCES`, `COCOTB_TOPLEVEL` and `COCOTB_TEST_MODULES` in its Makefile, then add a target for it in the top-level Makefile.
