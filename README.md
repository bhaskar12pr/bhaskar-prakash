# bhaskar-prakash

Verilog designs with self-checking testbenches and a CI/CD pipeline.
The pipeline runs on **GitHub Actions** today and is ready for **GitLab CI** later.

## Layout

```
rtl/                       designs: rtl/<name>.v holds module <name>
tb/                        Verilog testbenches: tb/tb_<name>.v holds module tb_<name>
tb/cocotb/                 Python (cocotb) testbenches
requirements.txt           Python packages (cocotb)
scripts/logs_to_junit.py   turns Verilog testbench logs into a JUnit test report
scripts/junit_summary.py   prints a pass/fail table from a JUnit report
Makefile                   the whole flow; the CI files only call make
.github/workflows/ci.yml   GitHub Actions pipeline (active now)
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
   └──► synth      Yosys generic synthesis        make synth → cell count, fails on latches
```

| Tool | Used for |
|---|---|
| Icarus Verilog | simulation |
| Verilator | strict lint |
| Yosys | synthesis check |
| cocotb | Python testbenches |

## Run locally

```sh
sudo apt install iverilog verilator yosys make python3 python3-venv
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt

make ci      # lint + sim + cocotb + synth + junit
make sim     # just the Verilog testbenches
make cocotb  # just the Python testbenches
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

## Adding a new design

1. Create `rtl/<name>.v` containing `module <name>`.
2. Create `tb/tb_<name>.v` containing `module tb_<name>`. It should print `ERROR: ...` for each mismatch and `TEST PASSED` at the end. Use `tb/tb_mux4to1.v` as a template.
3. Run `make ci`. Both pipelines pick up the new files automatically.
4. Optional, cocotb: copy `tb/cocotb/` to a new folder. Change `VERILOG_SOURCES`, `COCOTB_TOPLEVEL` and `COCOTB_TEST_MODULES` in its Makefile, then add a target for it in the top-level Makefile.
