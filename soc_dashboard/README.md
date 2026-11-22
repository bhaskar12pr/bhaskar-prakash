# SoC verification dashboard

`socdash.py` turns regression results, coverage, bugs and testplan status into a single
self-contained HTML page. It answers five questions on one screen:

| Section     | Shows |
|-------------|-------|
| Regression  | Pass rate per nightly run against the milestone bar, failing sims by fail/timeout/error, per-block table, failure signatures in the latest run, and tests that flip between pass and fail over the last 7 runs |
| Coverage    | Line, branch, toggle, FSM, assertion and functional coverage per metric (bullet bars against target) and as a block × metric matrix |
| Bugs        | Unresolved bugs by severity, weekly unresolved trend, and the open/fixed list with age |
| Testplan    | Planned / written / passing items per feature |
| Sign-off    | Each milestone's criteria evaluated as met or not, with the current milestone highlighted |

Every section can be narrowed to one block with the chips at the top, or by selecting a row in
the block table. The URL hash keeps the choice (`dashboard.html#ddr-ctrl`).

Only the Python 3.9+ standard library is needed.

## Quick start

```sh
cd soc_dashboard
python3 socdash.py build --data sample_data --out dashboard.html
```

`sample_data/` holds a fictional SoC ("Orion SoC", 8 blocks, 14 nightly runs) made by
`make_sample_data.py`. Open `dashboard.html` in a browser to see it.

## Using your own data

Make a folder with the five files below and point `--data` at it.

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

You don't have to write this by hand. `collect` reads UVM logs and appends rows:

```sh
python3 socdash.py collect --logs sim/out --run-id nightly_1122 --date 2026-11-22 \
    --out my_data/regression_runs.csv
```

It expects `sim/out/<block>/<anything>.log` (or pass `--block NAME`). For each log it takes the
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

### `testplan.csv`

`id, block, feature, item, milestone, status, test` with status `planned`, `written` or
`passing`. The milestone must be one of the names in `config.json`.

### `config.json`

```json
{
  "project": "Orion SoC",
  "current_milestone": "DV 0.8",
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
python3 socdash.py build --data results/ --out public/dashboard.html --fail-on-signoff
```

The command prints a summary and, with `--fail-on-signoff`, exits with status 2 while the
current milestone's criteria are not all met. Malformed input exits with status 1 and names the
file and line.

`--fragment` writes the page without `<html>`, `<head>` and `<body>` so it can be embedded in
another page.

## Tests

```sh
python3 -m unittest -v test_socdash
```
