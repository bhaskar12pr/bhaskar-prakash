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
| Milestone gates | Every block against 7 gates (TB bring-up, first test passes, all features tested, code coverage ≥ 90%, functional coverage ≥ 95%, no open critical bugs, DV sign-off): done, in progress, at risk or not started, with the date passed or the due date |
| Team health | Open work per person against the team average with an overload flag, triage turnaround (failure to root cause), and planned vs unplanned team hours |
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

Each project folder holds the files below. `owners.csv`, `owner_targets.csv`,
`testplan_history.csv`, `gates.csv`, `triage.csv` and `worklog.csv` are optional; without
them the views that need them are hidden (gates still show what the data can decide).

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

### `gates.csv` (optional)

```csv
block,gate,status,date,note
ddr_ctrl,tb_bringup,done,2026-09-22,
ddr_ctrl,code_cov,,2026-11-25,
ddr_ctrl,signoff,not_started,2026-12-11,
```

Five of the default gates are worked out from the data and need no row: `first_pass`
(a test passed), `features_tested` (every testplan item passing), `code_cov` (line, branch,
toggle and FSM all at or above 90%), `func_cov` (functional at or above 95%) and
`no_critical` (no unresolved S1 bug). Rows give the manual gates (`tb_bringup`, `signoff`)
their status and date, and give any gate not yet done its **due date**. A gate that is not
done and is due within `gate_risk_days` (default 7), or overdue, shows as **at risk**. Status
is `done`, `in_progress`, `at_risk` or `not_started`; `note` is optional. To use different
gates, set `"gates"` in `config.json` to a list of `{"id", "name"}`, adding `"auto"` (one of
`first_pass`, `testplan_passing`, `code_coverage`, `functional_coverage`,
`no_open_critical`) and `"threshold"` for automatic ones.

### `triage.csv` (optional)

```csv
id,block,signature,failed_at,triaged_at
TRI-001,ddr_ctrl,[DDR_SCB] read data mismatch,2026-11-20 02:14,2026-11-20 16:40
TRI-002,pcie_ctrl,[PH_TIMEOUT] ...,2026-11-21 03:05,
```

One row per regression failure: when it failed and when a root cause was assigned (empty
while still waiting). Shown as the team's weekly median hours to root cause and the queue of
failures still waiting.

### `worklog.csv` (optional)

```csv
week_end,owner,kind,label,hours
2026-11-21,Asha,planned,coverage closure,22
2026-11-21,Asha,unplanned,regression firefighting,9
```

Hours per person per week, `kind` `planned` or `unplanned` (for example from Jira labels).
Shown only as team totals: planned vs unplanned hours per week and where the unplanned time
went.

### Workload

Derived from data you already have, so it needs no file: per person, testplan items not
passing in the blocks they own, unresolved bugs (their `owner` column, or the block's owner)
and failing tests in the latest run. People are listed by name, never ranked, and flagged
only when their total is more than `overload_factor` (default 1.5) times the team average
and at least 5 items above it. Compare people with their own trend; compare across people
only to rebalance work.

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
| `settings.gate_risk_days` | a gate not done and due within this many days (or overdue) is at risk | 7 |
| `settings.overload_factor` | flag a person whose open work is this many times the team average | 1.5 |
| `gates` | the milestone gates and their order | the 7 gates above |
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

## Charts and accessibility

* **Colours are checked, not eyeballed.** The pass / fail / error / timeout colours were
  validated for colour-blind and normal-vision separation in both themes, in the order they
  stack. Text uses darker "ink" steps of the same colours so it stays at 4.5:1 contrast or
  better, including on the tinted pills.
* **Every chart has a hover layer and a table.** Line charts show a crosshair with every
  value at that run; bars show their own values. With a chart focused, the arrow keys, Home
  and End move along it. "Show … as a table" under each chart lists the same numbers, so
  nothing is hover-only.
* **Marks:** 2px lines, ringed end dots, bars at most 24px wide with rounded ends and 2px
  gaps between stacked parts; one y-axis per chart.
* **Structure:** one `main` landmark, headings in order, labelled controls and history
  strips, toggles that report their state, focus rings everywhere, 24px or larger targets,
  live announcements when a filter changes the list. No sideways page scroll at phone width
  or 200% zoom. Checked with axe-core (WCAG 2.1 AA): no violations.

The chart helpers live in `templates/viz.js` and are inlined into each page at build time.

## Motion

Animation is used to show what changed, never as decoration, and it is short:
* **Numbers glide** from their old value to the new one when you change the run, block or
  selection, and the tile that changed flashes once (about half a second).
* **Chart lines redraw** when the data under them changes.
* **Run waveform**: a logic-analyzer style sample-and-hold trace of the pass rate per
  nightly run, with the milestone bar as a threshold. It heads the regression page (following
  the selected subsystem, module or instance) and the project dashboard (following the block
  chips), and a compact version sits in each project row on the overview.
* **Panels slide up into place** as they scroll into view (browsers with scroll-driven
  animation), the quick search pops open, buttons give a small press, and "At risk"
  forecasts pulse twice on load.

Everything is off when the device asks for reduced motion, and nothing starts hidden, so a
page that never animates is complete. Nothing fades, so text keeps full contrast throughout.

## Quick search

On every page press **Ctrl+K** (**⌘K** on a Mac), **/**, or the **Search** button, then
type a name. The overview finds projects, their regression pages and owners; a project
dashboard finds sections, blocks, open bugs and testplan features; the regression page
finds subsystems, modules, instances, tests and owners. Arrow keys move,
Enter opens, Esc closes. Choosing a test filters the test list to it; choosing an owner shows
their tests; choosing a part of the design selects it in the tree. Everything searched is
already in the page, so nothing is sent anywhere.

## Safety checks

The pages are static files with no external scripts and no network calls apart from Google
Fonts. Names from your CSV files (tests, owners, signatures, project names) are always shown
as text, never run as HTML or script. Two layers prove it:

* `python3 -m unittest test_socdash` (no extra tools needed) checks that no template loads an
  external script or uses `fetch`, `XMLHttpRequest`, `WebSocket`, `eval` and the like, that the
  quick-search code builds its results with `textContent`, and that a project whose names are
  script-injection payloads builds into pages where those payloads stay escaped.
* `checks/browser_safety_check.js` repeats this in a real browser (needs Node and Playwright;
  axe-core optional):

  ```sh
  python3 socdash.py build-all --out site
  python3 checks/make_hostile_project.py /tmp/hostile
  node checks/browser_safety_check.js site /tmp/hostile/site
  ```

  It serves every page under a strict Content-Security-Policy, blocks and reports any request
  that leaves the machine, confirms the injected payloads never run, drives the quick search
  with the keyboard, and runs an axe-core WCAG 2.1 AA scan with it open.

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
