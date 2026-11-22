# SoC verification dashboard

`socdash.py` turns regression results, coverage, bugs and testplan status into
self-contained HTML pages: an overview of all projects, a dashboard per project, and a
regression drill-down per project. Every page is built to show progress: where things
stand, how fast they are moving, and whether they will be done in time.

### Overview (`index.html`)

* One row per project: next milestone and which criteria are short, pass rate with its trend
  and **forecast**, coverage, open S1/S2 bugs, testplan progress and latest run.
* **Owners across projects**: each person's latest week in every project they work on —
  tests passing start → end, weekly target met or missed, new failures, fixes, longest
  failing test, open bugs and forecast.

### Project dashboard (`<project>.html`)

| Section     | Shows |
|-------------|-------|
| Regression  | Pass rate per nightly run against the milestone bar with a **forecast**, failing sims by fail/timeout/error, per-block table, failure signatures, intermittent tests |
| Coverage    | Each metric against target, a block × metric matrix, and **coverage over time** per metric with the pace needed to reach target |
| Bugs        | Unresolved bugs by severity, weekly trend, the open list with age, and **time to fix** per severity (median, 90th percentile, oldest open) |
| Testplan    | **Items by status at the end of each week**, and planned / written / passing per feature |
| Sign-off    | Each milestone's criteria evaluated as met or not |

Every section can be narrowed to one block with the chips at the top or the block table.
The URL hash keeps the choice (`orion-soc.html#ddr-ctrl`).

### Regression drill-down (`<project>-regression.html`)

Drills down subsystem → module → instance → test. Select any node and every panel follows;
the URL keeps the selection (`#memory-ss--ddr-ctrl--u-ddr1`).

* **Run picker.** View any past nightly run and compare it with any other (the run before,
  by default). Counts, the tree, failures and the test list all follow.
* **Forecast** for every subsystem, module, instance and owner: when the sim pass rate will
  reach the milestone bar, and whether that is before the due date — *met*, *on track*,
  *at risk*, *stalled* (not improving) or *projected* (no due date).
* **This week.** Pick a week: passing start → end, fixed, new failures, tests added, still
  failing, stuck (failing for `stuck_days` or more), the parts that improved or slipped most,
  and the longest-failing tests.
* **Burn-up**: tests run vs tests passing over time, with the recent pace projected to the
  milestone date. Next to it, the pass rate with its trend line to the target.
* **Failures**: failing tests grouped by first error, and how long they have been failing.
* **Owners** (with `owners.csv`): per week, tests passing start → end, the weekly target
  (`owner_targets.csv`), new failures, fixes, tests added, longest failing test, sim pass rate,
  functional coverage start → end, bugs opened / closed / open, median days to fix, forecast,
  and a weekly bar chart with target ticks. "Show tests" lists that owner's tests.
* **Tree** with tests passing, pass rate, change, trend, new failures, fixes, forecast and owner.
* **Tests** as a table (history strip, seeds, status, days failing, since, owner, first error)
  or as a **heatmap** of tests × runs. Filters: failing, new failures, fixed, stuck, flipping
  (pass/fail changed at least twice in the last runs), not run; plus search.

A test passes a run only if every seed passed. Forecasts fit a straight line to the last
`forecast_runs` runs; treat them as a guide.

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
├── orion_soc/              8 blocks, 4 weeks of runs, working toward DV 0.8
│   ├── config.json
│   ├── regression_runs.csv    with subsystem and instance columns
│   ├── coverage.csv           weekly dated snapshots
│   ├── bugs.csv               with an owner column for two bugs
│   ├── testplan.csv
│   ├── testplan_history.csv   optional
│   ├── owners.csv             optional
│   └── owner_targets.csv      optional
├── lyra_soc/                 6 blocks, close to DV 1.0; subsystems in config.json
└── nova_io_hub/              4 blocks, DV 1.0 met; no owners; renames its regression file
```

These three are fictional samples made by `make_sample_data.py`. Delete them and add your own.

If one project's files are broken, `build-all` still builds the others, shows the broken
project on the overview with the error, and exits with status 1.

To build a single project:

```sh
python3 socdash.py build --data projects/orion_soc --out orion.html
```

## Project files

Each project folder holds the files below. `owners.csv`, `owner_targets.csv` and
`testplan_history.csv` are optional; without them the views that need them are hidden.

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

Add an optional `date` column and append a snapshot each week (or each night) to get
**coverage over time**. The latest snapshot of each block and metric is the current value;
a block missing from a later snapshot keeps its previous value. Owners get the functional
coverage of the modules they own.

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

### `owner_targets.csv` (optional)

```csv
owner,week_end,target_passing
Asha,2026-11-21,16
Elif,2026-11-21,10
```

The number of an owner's tests expected to pass at the end of a week. `week_end` must match a
week end on the page (the as-of date, then every 7 days back). Owners must be in `owners.csv`.

### `testplan_history.csv` (optional)

```csv
date,id,status
2026-10-02,TP-014,written
2026-10-20,TP-014,passing
```

One row per status change. An item's status at a date is its latest change on or before that
date; before its first change it counts as planned. Items with no changes keep their current
status from `testplan.csv`. This drives **items by status at the end of each week**.

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
| `settings.weeks` | weeks offered in the week picker (weekly digest and owners) | 6 |
| `settings.forecast_runs` | recent runs the forecast line is fitted to | 10 |
| `settings.stuck_days` | a test failing this many days or more counts as stuck | 7 |
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
