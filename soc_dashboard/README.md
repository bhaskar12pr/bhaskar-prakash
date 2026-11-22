# SoC verification dashboard

`socdash.py` turns regression results, coverage, bugs and testplan status into a
self-contained HTML dashboard for each SoC project, plus an overview page that compares all
projects side by side. Each project's page answers five questions on one screen:

| Section     | Shows |
|-------------|-------|
| Regression  | Pass rate per nightly run against the milestone bar, failing sims by fail/timeout/error, per-block table, failure signatures in the latest run, and tests that flip between pass and fail over the last 7 runs |
| Coverage    | Line, branch, toggle, FSM, assertion and functional coverage per metric (bullet bars against target) and as a block × metric matrix |
| Bugs        | Unresolved bugs by severity, weekly unresolved trend, and the open/fixed list with age |
| Testplan    | Planned / written / passing items per feature |
| Sign-off    | Each milestone's criteria evaluated as met or not, with the current milestone highlighted |

Each project also gets a **regression page** (`<project>-regression.html`) that drills down
subsystem → module → instance → test:

* **Progress at every level.** Tests passing / failing / not run in the latest run, simulation
  pass rate with its change and trend, new failures and fixes since the previous run, and
  failing simulations by fail / timeout / error.
* **Progress over time.** Pass rate against the milestone bar, and tests passing vs failing
  in every nightly run, so suite growth and closure both show.
* **Failing tests grouped by signature**, with the instances they hit.
* **Per-test detail.** The last N runs as a strip, seeds passing, when the current outcome
  started, and the first error. Filter by failing, new failures, fixed, flipping (pass/fail
  changed at least twice) or not run, or search by name.

* **Owner progress by week**, when the project has an `owners.csv`. Pick a week; each owner's
  row shows tests passing at the start and end of the week, new failures, fixes, tests added,
  the week's sim pass rate and its change from the week before, bugs opened and closed, bugs
  still open at week end, and a small chart of tests passing at the end of each week. "Show
  tests" lists that owner's tests below. The tree and test list also gain an owner column.

Select any subsystem, module or instance in the tree and every panel follows; the URL keeps
the selection (`orion-soc-regression.html#memory-ss--ddr-ctrl--u-ddr1`) so you can share it.
A test passes a run only if every seed passed.

Every section of the project dashboard can be narrowed to one block with the chips at the top, or by selecting a row in
the block table. The URL hash keeps the choice (`dashboard.html#ddr-ctrl`).

Only the Python 3.9+ standard library is needed.

## Quick start

```sh
cd soc_dashboard
python3 socdash.py build-all --projects projects --out site
```

Open `site/index.html`. It lists every project with its next milestone, sign-off status,
pass rate trend, coverage, open S1/S2 bugs and testplan progress; select a project name to
open its dashboard (`site/<project>.html`), which links back to the overview.

## Projects

Every project is its own folder under `projects/`, with its own `config.json` and data
files. `build-all` treats each subfolder that contains a `config.json` as a project and
ignores the rest, so adding a project means adding a folder:

```
projects/
├── orion_soc/           8 blocks, working toward DV 0.8
│   ├── config.json
│   ├── regression_runs.csv
│   ├── coverage.csv
│   ├── bugs.csv
│   └── testplan.csv
├── lyra_soc/            6 blocks, close to DV 1.0; uses custom settings
└── nova_io_hub/         4 blocks, DV 1.0 met; renames its regression file
```

These three are fictional samples made by `make_sample_data.py`. Delete them and add your own.

If one project's files are broken, `build-all` still builds the others, shows the broken
project on the overview with the error, and exits with status 1.

To build a single project:

```sh
python3 socdash.py build --data projects/orion_soc --out orion.html
```

## Project files

Each project folder holds the files below; `owners.csv` is optional.

### `regression_runs.csv` — one row per simulation

| column | example | notes |
|---|---|---|
| run_id | `nightly_1121` | groups sims into a regression run |
| date | `2026-11-21` | orders the runs |
| block | `ddr_ctrl` | |
| test | `ecc_double_bit` | |
| seed | `1849302` | |
| status | `PASS` | `PASS`, `FAIL`, `TIMEOUT` or `ERROR` |
| duration_s | `412.5` | may be empty |
| signature | `[ECC_CHK] double-bit error not flagged addr=<HEX>` | first error, with numbers masked so the same failure groups together |
| subsystem | `memory_ss` | optional; overrides `subsystems` in config.json |
| instance | `u_ddr1` | optional; defaults to the block (module) name |

`block` is the module. The regression page groups results as subsystem → block → instance.
Give the hierarchy either as the two optional columns above or, for data without them, as a
`subsystems` map in `config.json`. Blocks in neither land under "(no subsystem)".

You don't have to write this by hand. `collect` reads UVM logs and appends rows:

```sh
python3 socdash.py collect --logs sim/out --run-id nightly_1122 --date 2026-11-22 \
    --out projects/orion_soc/regression_runs.csv
```

It expects `sim/out/<block>/<anything>.log` (or pass `--block NAME`). If your logs are
organised by hierarchy, say so with `--layout`, for example
`--layout subsystem/block/instance` for `sim/out/memory_ss/ddr_ctrl/u_ddr1/<test>.log`;
the subsystem and instance columns are then filled in. For each log it takes the
test from `+UVM_TESTNAME=` or `Running test`, the seed from `ntb_random_seed` / `svseed` /
`+seed`, and classifies it:

* `TIMEOUT` if `[PH_TIMEOUT]` appears
* `ERROR` if the UVM report summary is missing (crash, killed job, compile failure)
* `FAIL` if `UVM_ERROR` or `UVM_FATAL` counts are non-zero
* `PASS` otherwise

### `coverage.csv` — one row per block and metric

`block, metric, covered, total, target_pct` where metric is `line`, `branch`, `toggle`, `fsm`,
`assertion` or `functional`. Export bins/points covered and total from your coverage tool
(for example `urg -report` or `imc -exec` merged results).

### `bugs.csv`

`id, title, block, severity, status, opened, closed`

* severity: `S1` (blocks tape-out) to `S4` (cosmetic)
* status: `open`, `fixed` (RTL fix is in, waiting for a clean regression) or `closed`.
  Both `open` and `fixed` count as unresolved for sign-off.

### `owners.csv` (optional)

Who owns what, one row per area:

```csv
owner,scope
Asha,memory_ss
Elif,ddr_ctrl/u_ddr1
Ben,connectivity_ss
Asha,pcie_ctrl/u_pcie0/completion_timeout
```

`scope` is a subsystem, a module, `module/instance`, or `module/instance/test`. The most
specific match wins, so above Elif owns `u_ddr1` while Asha owns the rest of `memory_ss`.
Anything no row covers is shown as "(unassigned)". A scope that matches nothing in the
regression results, or the same scope given to two owners, is rejected with the file and line.

Bugs go to the owner of their block. To assign a bug to someone else (for example the owner of
one instance), add an optional `owner` column to `bugs.csv`.

Weeks end on the project's as-of date (the latest run date unless `as_of` is set) and step
back 7 days at a time; weeks without runs are skipped. A week's "start" is the last run before
it began and its "end" is its last run.

### `testplan.csv`

`id, block, feature, item, milestone, status, test` with status `planned`, `written` or
`passing`. The milestone must be one of the names in `config.json`.

### `config.json`

Everything about a project that is not data lives here, so projects can differ in
milestones, criteria, file names and settings.

```json
{
  "project": "Orion SoC",
  "current_milestone": "DV 0.8",
  "files": {"regression": "nightly_results.csv"},
  "settings": {"intermittent_window": 10, "bug_trend_weeks": 12, "stale_after_days": 3},
  "subsystems": {"memory_ss": ["ddr_ctrl", "dma_engine"], "connectivity_ss": ["pcie_ctrl", "usb3_ctrl"]},
  "milestones": [
    {"name": "DV 0.8", "date": "2026-12-11",
     "criteria": {
       "min_pass_rate": 0.90,
       "coverage_target_scale": 0.9,
       "max_unresolved_bugs": {"S1": 0, "S2": 5},
       "min_testplan_written": 0.95,
       "min_testplan_passing": 0.8}}
  ]
}
```

| key | meaning | default |
|---|---|---|
| `project` | name shown on the pages | the folder name |
| `current_milestone` | milestone the KPI strip and overview track | none |
| `files` | rename any of `regression`, `coverage`, `bugs`, `testplan`; paths are relative to the project folder | `regression_runs.csv`, `coverage.csv`, `bugs.csv`, `testplan.csv` |
| `settings.intermittent_window` | runs examined for tests that both pass and fail | 7 |
| `settings.bug_trend_weeks` | weeks shown in the bug trend | 10 |
| `settings.stale_after_days` | overview flags a project whose latest run is older than this | 3 |
| `settings.test_history_runs` | runs shown in each test's history strip on the regression page | 10 |
| `settings.owner_weeks` | weeks offered in the owner progress picker | 6 |
| `subsystems` | group blocks into subsystems when the regression CSV has no `subsystem` column | none |
| `milestones` | ordered list of `name`, `date` and `criteria` | none |

Misspelled keys under `files` or `settings`, duplicate milestone names, and a
`current_milestone` that is not in the list are rejected with a clear message.

Every criterion is optional:

* `min_pass_rate` — pass rate of the latest run
* `coverage_target_scale` — every block × metric cell must reach `target_pct × scale`
* `max_unresolved_bugs` — limit per severity
* `min_testplan_written` / `min_testplan_passing` — share of testplan items tagged with this
  milestone or an earlier one

Add `"as_of": "YYYY-MM-DD"` to fix the date used for bug ages and trends; it defaults to the
latest run's date.

## In CI

```sh
python3 socdash.py build-all --projects projects --out public --fail-on-signoff
```

The command prints a summary per project and, with `--fail-on-signoff`, exits with status 2
while any project's current milestone criteria are not all met (`build --fail-on-signoff` does
the same for one project). Malformed input exits with status 1 and names the file and line.
`--title` sets the overview page's heading.

`--fragment` writes the page without `<html>`, `<head>` and `<body>` so it can be embedded in
another page.

## Tests

```sh
python3 -m unittest -v test_socdash
```
