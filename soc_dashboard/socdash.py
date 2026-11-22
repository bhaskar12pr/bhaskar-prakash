#!/usr/bin/env python3
"""SoC verification dashboard.

Each project lives in its own folder with a config.json and four CSV files.
`build` makes one project's dashboard; `build-all` makes a dashboard for every
project folder plus an overview page; `collect` turns UVM logs into CSV rows.

    python3 socdash.py build     --data projects/orion_soc --out dashboard.html
    python3 socdash.py build-all --projects projects --out site
    python3 socdash.py collect   --logs sim/logs --run-id nightly_42 --date 2026-11-21 \
                                 --out projects/orion_soc/regression_runs.csv

Only the Python standard library is used, so it runs on any CI machine.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"

# Input files a project folder holds. config.json may rename any of them under "files".
DEFAULT_FILES = {"regression": "regression_runs.csv", "coverage": "coverage.csv",
                 "bugs": "bugs.csv", "testplan": "testplan.csv", "owners": "owners.csv",
                 "testplan_history": "testplan_history.csv", "owner_targets": "owner_targets.csv"}
# A project without one of these files simply goes without the views that need it.
OPTIONAL_FILES = {"owners", "testplan_history", "owner_targets"}
TESTPLAN_HISTORY_COLS = ("date", "id", "status")
OWNER_TARGET_COLS = ("owner", "week_end", "target_passing")
OWNER_COLS = ("owner", "scope")
UNASSIGNED = "(unassigned)"
# Tunable settings a project may override under "settings" in config.json.
DEFAULT_SETTINGS = {"intermittent_window": 7, "bug_trend_weeks": 10, "stale_after_days": 3,
                    "test_history_runs": 10, "weeks": 6, "forecast_runs": 10, "stuck_days": 7}
UNGROUPED = "(no subsystem)"

STATUSES = ("PASS", "FAIL", "TIMEOUT", "ERROR")
SEVERITIES = ("S1", "S2", "S3", "S4")
BUG_STATES = ("open", "fixed", "closed")  # fixed = fix in RTL, awaiting regression proof
UNRESOLVED = ("open", "fixed")
TESTPLAN_STATES = ("planned", "written", "passing")
METRICS = ("line", "branch", "toggle", "fsm", "assertion", "functional")

REGRESSION_COLS = ("run_id", "date", "block", "test", "seed", "status", "duration_s", "signature")
COVERAGE_COLS = ("block", "metric", "covered", "total", "target_pct")
BUG_COLS = ("id", "title", "block", "severity", "status", "opened", "closed")
TESTPLAN_COLS = ("id", "block", "feature", "item", "milestone", "status", "test")


class InputError(Exception):
    """Raised when an input file is missing or malformed."""


# --------------------------------------------------------------------------- loading

def _date(value: str, where: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise InputError(f"{where}: '{value}' is not a YYYY-MM-DD date") from None


def _num(value: str, where: str, kind=float):
    try:
        return kind(value)
    except ValueError:
        raise InputError(f"{where}: '{value}' is not a number") from None


def read_csv(path: Path, required: tuple[str, ...]) -> list[dict]:
    if not path.exists():
        raise InputError(f"{path}: file not found")
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in required if c not in (reader.fieldnames or [])]
        if missing:
            raise InputError(f"{path.name}: missing column(s): {', '.join(missing)}")
        rows = []
        for line, raw in enumerate(reader, start=2):
            row = {k: (v or "").strip() for k, v in raw.items() if k}
            row["_where"] = f"{path.name}:{line}"
            rows.append(row)
    return rows


def _choice(row: dict, col: str, allowed: tuple[str, ...], *, upper=False) -> str:
    value = row[col].upper() if upper else row[col].lower()
    if value not in allowed:
        raise InputError(f"{row['_where']}: {col} '{row[col]}' must be one of {', '.join(allowed)}")
    return value


def load(data_dir: Path) -> dict:
    data_dir = Path(data_dir)
    config_path = data_dir / "config.json"
    if not config_path.exists():
        raise InputError(f"{config_path}: file not found")
    config = load_config(config_path)
    files = {k: data_dir / v for k, v in config["files"].items()}

    runs = []
    for r in read_csv(files["regression"], REGRESSION_COLS):
        runs.append({
            "run_id": r["run_id"],
            "date": _date(r["date"], r["_where"]),
            "block": r["block"],
            "test": r["test"],
            "seed": r["seed"],
            "status": _choice(r, "status", STATUSES, upper=True),
            "duration_s": _num(r["duration_s"], r["_where"]) if r["duration_s"] else None,
            "signature": r["signature"],
            # Optional hierarchy: subsystem > block (module) > instance.
            "subsystem": r.get("subsystem", ""),
            "instance": r.get("instance", ""),
        })
    if not runs:
        raise InputError("regression_runs.csv: no rows")

    # coverage.csv may hold one snapshot, or several told apart by an optional date column.
    coverage_history = []
    for r in read_csv(files["coverage"], COVERAGE_COLS):
        covered = _num(r["covered"], r["_where"], int)
        total = _num(r["total"], r["_where"], int)
        if total <= 0 or covered > total:
            raise InputError(f"{r['_where']}: need 0 <= covered <= total and total > 0")
        coverage_history.append({
            "date": _date(r["date"], r["_where"]) if r.get("date") else None,
            "block": r["block"],
            "metric": _choice(r, "metric", METRICS),
            "covered": covered,
            "total": total,
            "target": _num(r["target_pct"], r["_where"]),
        })
    latest_cov = {}
    for c in coverage_history:
        key = (c["block"], c["metric"])
        if key not in latest_cov or (c["date"] or dt.date.min) >= (latest_cov[key]["date"] or dt.date.min):
            latest_cov[key] = c
    coverage = list(latest_cov.values())

    bugs = []
    for r in read_csv(files["bugs"], BUG_COLS):
        status = _choice(r, "status", BUG_STATES)
        closed = _date(r["closed"], r["_where"]) if r["closed"] else None
        if status == "closed" and closed is None:
            raise InputError(f"{r['_where']}: closed bug needs a closed date")
        bugs.append({
            "id": r["id"], "title": r["title"], "block": r["block"],
            "severity": _choice(r, "severity", SEVERITIES, upper=True),
            "status": status,
            "opened": _date(r["opened"], r["_where"]),
            "closed": closed,
            "owner": r.get("owner", ""),  # optional; otherwise the block's owner from owners.csv
        })

    milestones = [m["name"] for m in config.get("milestones", [])]
    testplan = []
    for r in read_csv(files["testplan"], TESTPLAN_COLS):
        if milestones and r["milestone"] not in milestones:
            raise InputError(f"{r['_where']}: milestone '{r['milestone']}' is not in config.json")
        testplan.append({
            "id": r["id"], "block": r["block"], "feature": r["feature"], "item": r["item"],
            "milestone": r["milestone"], "status": _choice(r, "status", TESTPLAN_STATES),
            "test": r["test"],
        })

    owners = []
    if files["owners"].exists() or "owners" in config.get("_explicit_files", ()):
        seen = {}
        for r in read_csv(files["owners"], OWNER_COLS):
            scope = r["scope"].strip("/")
            if not r["owner"] or not scope:
                raise InputError(f"{r['_where']}: owner and scope are both required")
            if scope in seen and seen[scope][0] != r["owner"]:
                raise InputError(f"{r['_where']}: scope '{scope}' is already owned by {seen[scope][0]} "
                                 f"({seen[scope][1]})")
            seen[scope] = (r["owner"], r["_where"])
            owners.append({"owner": r["owner"], "scope": scope, "_where": r["_where"]})
        check_owner_scopes(owners, runs, config)

    def optional(key):
        return files[key].exists() or key in config.get("_explicit_files", ())

    testplan_history = []
    if optional("testplan_history"):
        ids = {t["id"] for t in testplan}
        for r in read_csv(files["testplan_history"], TESTPLAN_HISTORY_COLS):
            if r["id"] not in ids:
                raise InputError(f"{r['_where']}: id '{r['id']}' is not in the testplan")
            testplan_history.append({"date": _date(r["date"], r["_where"]), "id": r["id"],
                                     "status": _choice(r, "status", TESTPLAN_STATES)})

    owner_targets = {}
    if optional("owner_targets"):
        names = {o["owner"] for o in owners}
        for r in read_csv(files["owner_targets"], OWNER_TARGET_COLS):
            if r["owner"] not in names:
                raise InputError(f"{r['_where']}: owner '{r['owner']}' is not in owners.csv")
            week_end = _date(r["week_end"], r["_where"]).isoformat()
            owner_targets[(r["owner"], week_end)] = _num(r["target_passing"], r["_where"], int)

    return {"config": config, "dir": data_dir, "runs": runs, "coverage": coverage,
            "coverage_history": coverage_history, "bugs": bugs, "testplan": testplan,
            "testplan_history": testplan_history, "owners": owners, "owner_targets": owner_targets}


def check_owner_scopes(owners, runs, config):
    """Every owners.csv scope must name something in the regression results."""
    known = set()
    for r in runs:
        ss, mod, inst = hierarchy_path(r, config["block_subsystem"])
        known.update((ss, mod, f"{mod}/{inst}", f"{mod}/{inst}/{r['test']}"))
    for o in owners:
        if o["scope"] not in known:
            raise InputError(f"{o['_where']}: scope '{o['scope']}' matches no subsystem, module, "
                             f"module/instance or module/instance/test in the regression results")


def owner_lookup(owners):
    """Return owner(ss, module, instance, test): the most specific matching scope wins."""
    rules = {o["scope"]: o["owner"] for o in owners}

    def owner(ss, mod, inst=None, test=None):
        for scope in (f"{mod}/{inst}/{test}" if inst and test else None,
                      f"{mod}/{inst}" if inst else None, mod, ss):
            if scope and scope in rules:
                return rules[scope]
        return UNASSIGNED
    return owner


def load_config(path: Path) -> dict:
    """Read a project's config.json, check it, and fill in defaults."""
    try:
        config = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise InputError(f"{path}: invalid JSON at line {e.lineno}: {e.msg}") from None
    if not isinstance(config, dict):
        raise InputError(f"{path}: must be a JSON object")
    config["_explicit_files"] = sorted(config.get("files", {}))
    unknown_files = set(config.get("files", {})) - set(DEFAULT_FILES)
    if unknown_files:
        raise InputError(f"{path}: unknown key(s) in \"files\": {', '.join(sorted(unknown_files))}; "
                         f"use {', '.join(DEFAULT_FILES)}")
    unknown_settings = set(config.get("settings", {})) - set(DEFAULT_SETTINGS)
    if unknown_settings:
        raise InputError(f"{path}: unknown key(s) in \"settings\": {', '.join(sorted(unknown_settings))}; "
                         f"use {', '.join(DEFAULT_SETTINGS)}")
    names = [m.get("name") for m in config.get("milestones", [])]
    if any(not n for n in names) or len(set(names)) != len(names):
        raise InputError(f"{path}: every milestone needs a unique \"name\"")
    if config.get("current_milestone") and config["current_milestone"] not in names:
        raise InputError(f"{path}: current_milestone '{config['current_milestone']}' is not in milestones")
    subsystems = config.get("subsystems", {})
    if not isinstance(subsystems, dict) or not all(isinstance(v, list) for v in subsystems.values()):
        raise InputError(f"{path}: \"subsystems\" must map a subsystem name to a list of blocks")
    owner = {}
    for ss, blocks in subsystems.items():
        for b in blocks:
            if b in owner:
                raise InputError(f"{path}: block '{b}' is listed under both '{owner[b]}' and '{ss}'")
            owner[b] = ss
    config["block_subsystem"] = owner
    config["project"] = config.get("project") or path.parent.name
    config["files"] = {**DEFAULT_FILES, **config.get("files", {})}
    config["settings"] = {**DEFAULT_SETTINGS, **config.get("settings", {})}
    return config


def discover_projects(root: Path) -> list[Path]:
    """Project folders under `root`: every immediate subfolder that holds a config.json."""
    root = Path(root)
    if not root.is_dir():
        raise InputError(f"{root}: folder not found")
    found = sorted(d for d in root.iterdir() if d.is_dir() and (d / "config.json").exists())
    if not found:
        raise InputError(f"{root}: no project folders with a config.json")
    return found


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"


# --------------------------------------------------------------------------- analysis

def run_order(runs: list[dict]) -> list[tuple[str, dt.date]]:
    """Distinct (run_id, date) pairs, oldest first."""
    seen = {}
    for r in runs:
        seen.setdefault(r["run_id"], r["date"])
    return sorted(seen.items(), key=lambda kv: (kv[1], kv[0]))


def regression_trend(runs, order):
    by_run = defaultdict(Counter)
    for r in runs:
        by_run[r["run_id"]][r["status"]] += 1
    trend = []
    for run_id, date in order:
        c = by_run.get(run_id, Counter())
        total = sum(c.values())
        trend.append({
            "run": run_id, "date": date.isoformat(), "total": total,
            **{s.lower(): c[s] for s in STATUSES},
            "rate": (c["PASS"] / total) if total else None,
        })
    return trend


def failure_signatures(runs, order, limit=10):
    if not order:
        return []
    latest = order[-1][0]
    index = {run_id: i for i, (run_id, _) in enumerate(order)}
    first_seen, runs_seen = {}, defaultdict(set)
    for r in runs:
        if r["status"] == "PASS":
            continue
        sig = r["signature"] or "(no signature)"
        i = index[r["run_id"]]
        if sig not in first_seen or i < index[first_seen[sig]]:
            first_seen[sig] = r["run_id"]
        runs_seen[sig].add(r["run_id"])
    groups = {}
    for r in runs:
        if r["run_id"] != latest or r["status"] == "PASS":
            continue
        sig = r["signature"] or "(no signature)"
        g = groups.setdefault(sig, {"signature": sig, "count": 0, "tests": set(), "blocks": set(),
                                    "statuses": Counter()})
        g["count"] += 1
        g["tests"].add(r["test"])
        g["blocks"].add(r["block"])
        g["statuses"][r["status"]] += 1
    out = []
    for g in sorted(groups.values(), key=lambda g: (-g["count"], g["signature"])):
        out.append({
            "signature": g["signature"], "count": g["count"],
            "tests": sorted(g["tests"]), "blocks": sorted(g["blocks"]),
            "status": g["statuses"].most_common(1)[0][0],
            "first_seen": first_seen[g["signature"]],
            "runs_seen": len(runs_seen[g["signature"]]),
        })
    return out[:limit]


def intermittent_tests(runs, order, window=7, limit=10):
    """Tests that both passed and failed within the last `window` runs."""
    recent = [run_id for run_id, _ in order[-window:]]
    outcome = defaultdict(dict)  # (block, test) -> run -> PASS/FAIL
    for r in runs:
        if r["run_id"] not in recent:
            continue
        key = (r["block"], r["test"])
        # A run counts as failed for the test if any of its seeds failed.
        if outcome[key].get(r["run_id"], "PASS") == "PASS":
            outcome[key][r["run_id"]] = r["status"]
    out = []
    for (block, test), per_run in outcome.items():
        history = [per_run.get(run_id, "") for run_id in recent]
        ran = [h for h in history if h]
        fails = sum(1 for h in ran if h != "PASS")
        if 0 < fails < len(ran):
            out.append({"block": block, "test": test, "history": history,
                        "fails": fails, "ran": len(ran)})
    out.sort(key=lambda t: (-t["fails"], t["block"], t["test"]))
    return out[:limit]


def block_table(runs, order):
    if not order:
        return []
    latest = order[-1][0]
    prev = order[-2][0] if len(order) > 1 else None
    stats = defaultdict(lambda: {"latest": Counter(), "prev": Counter()})
    for r in runs:
        if r["run_id"] == latest:
            stats[r["block"]]["latest"][r["status"]] += 1
        elif r["run_id"] == prev:
            stats[r["block"]]["prev"][r["status"]] += 1
    rows = []
    for block, s in sorted(stats.items()):
        lt, pt = sum(s["latest"].values()), sum(s["prev"].values())
        rows.append({
            "block": block, "sims": lt,
            "rate": s["latest"]["PASS"] / lt if lt else None,
            "prev_rate": s["prev"]["PASS"] / pt if pt else None,
            "fail": s["latest"]["FAIL"] + s["latest"]["ERROR"],
            "timeout": s["latest"]["TIMEOUT"],
        })
    return rows


def coverage_summary(cells, scale=1.0):
    by_metric = {}
    for m in METRICS:
        mc = [c for c in cells if c["metric"] == m]
        if not mc:
            continue
        covered, total = sum(c["covered"] for c in mc), sum(c["total"] for c in mc)
        target = sum(c["target"] * c["total"] for c in mc) / total
        by_metric[m] = {"pct": 100 * covered / total, "target": target}
    met = sum(1 for c in cells if 100 * c["covered"] / c["total"] >= c["target"] * scale)
    return {"metrics": by_metric, "cells_met": met, "cells": len(cells)}


def bug_trend(bugs, as_of: dt.date, weeks=10):
    points = []
    for w in range(weeks - 1, -1, -1):
        end = as_of - dt.timedelta(days=7 * w)
        start = end - dt.timedelta(days=7)
        unresolved = sum(1 for b in bugs if b["opened"] <= end and (b["closed"] is None or b["closed"] > end))
        points.append({
            "date": end.isoformat(),
            "unresolved": unresolved,
            "found": sum(1 for b in bugs if start < b["opened"] <= end),
            "closed": sum(1 for b in bugs if b["closed"] and start < b["closed"] <= end),
        })
    return points


def testplan_rollup(items):
    features = {}
    for it in items:
        f = features.setdefault((it["block"], it["feature"]),
                                {"block": it["block"], "feature": it["feature"],
                                 **{s: 0 for s in TESTPLAN_STATES}})
        f[it["status"]] += 1
    totals = Counter(it["status"] for it in items)
    return {"features": list(features.values()),
            "totals": {s: totals[s] for s in TESTPLAN_STATES}, "items": len(items)}


def signoff(config, latest_rate, cells, bugs, testplan):
    """Evaluate every milestone's criteria. Returns a list of milestones."""
    names = [m["name"] for m in config.get("milestones", [])]
    out = []
    for i, m in enumerate(config.get("milestones", [])):
        crit = m.get("criteria", {})
        checks = []
        if "min_pass_rate" in crit:
            need = crit["min_pass_rate"]
            checks.append({"label": "Latest regression pass rate",
                           "need": f"≥ {need:.0%}",
                           "actual": "no runs" if latest_rate is None else f"{latest_rate:.1%}",
                           "ok": latest_rate is not None and latest_rate >= need})
        if "coverage_target_scale" in crit:
            scale = crit["coverage_target_scale"]
            short = [c for c in cells if 100 * c["covered"] / c["total"] < c["target"] * scale]
            checks.append({"label": "Coverage at target in every block and metric" if scale >= 1
                           else f"Coverage at {scale:.0%} of target in every block and metric",
                           "need": f"{len(cells)} of {len(cells)}",
                           "actual": f"{len(cells) - len(short)} of {len(cells)}",
                           "ok": not short,
                           "detail": [f"{c['block']} {c['metric']}" for c in short][:6]})
        for sev, limit in sorted(crit.get("max_unresolved_bugs", {}).items()):
            n = sum(1 for b in bugs if b["severity"] == sev and b["status"] in UNRESOLVED)
            checks.append({"label": f"Unresolved {sev} bugs", "need": f"≤ {limit}",
                           "actual": str(n), "ok": n <= limit})
        scope = [t for t in testplan if t["milestone"] in names[: i + 1]]
        for key, states, label in (("min_testplan_written", ("written", "passing"), "written"),
                                   ("min_testplan_passing", ("passing",), "passing")):
            if key in crit:
                need = crit[key]
                frac = (sum(1 for t in scope if t["status"] in states) / len(scope)) if scope else 1.0
                checks.append({"label": f"Testplan items up to {m['name']} {label}",
                               "need": f"≥ {need:.0%}", "actual": f"{frac:.0%} of {len(scope)}",
                               "ok": frac >= need})
        out.append({"name": m["name"], "date": m.get("date", ""), "checks": checks,
                    "met": all(c["ok"] for c in checks)})
    return out


def summarize(data: dict, block: str | None) -> dict:
    """Everything the page shows for one scope: the whole SoC (None) or a block."""
    pick = (lambda rows: rows) if block is None else (lambda rows: [r for r in rows if r["block"] == block])
    runs, cells, bugs, plan = (pick(data[k]) for k in ("runs", "coverage", "bugs", "testplan"))
    order = run_order(data["runs"])  # keep every run on the axis, even ones a block skipped
    settings = data["config"]["settings"]
    trend = regression_trend(runs, order)
    latest_rate = trend[-1]["rate"] if trend else None
    current = data["config"].get("current_milestone")
    milestones = signoff(data["config"], latest_rate, cells, bugs, plan)
    scale = next((m.get("criteria", {}).get("coverage_target_scale", 1.0)
                  for m in data["config"].get("milestones", []) if m["name"] == current), 1.0)
    return {
        "trend": trend,
        "signatures": failure_signatures(runs, order),
        "intermittent": intermittent_tests(runs, order, window=settings["intermittent_window"]),
        "blocks": block_table(runs, order) if block is None else [],
        "coverage": coverage_summary(cells, scale),
        "bugs": {
            "unresolved": {s: sum(1 for b in bugs if b["severity"] == s and b["status"] in UNRESOLVED)
                           for s in SEVERITIES},
            "awaiting_verify": sum(1 for b in bugs if b["status"] == "fixed"),
            "trend": bug_trend(bugs, data["as_of"], weeks=settings["bug_trend_weeks"]),
        },
        "testplan": testplan_rollup(plan),
        "signoff": milestones,
        "forecast": forecast([d for _, d in order], [t["rate"] for t in trend], current_milestone(data["config"])["need"],
                             current_milestone(data["config"])["due"], settings["forecast_runs"]),
        "coverage_trend": coverage_trend(pick(data["coverage_history"])),
        "testplan_trend": testplan_trend(plan, data["testplan_history"], data["as_of"], settings["bug_trend_weeks"]),
        "fix_speed": fix_speed(bugs, data["as_of"]),
    }


def coverage_trend(history):
    """Percent covered per metric at each coverage snapshot date (None if fewer than two)."""
    dated = sorted({c["date"] for c in history if c["date"]})
    if len(dated) < 2:
        return None
    points = []
    for day in dated:
        snap = {}
        for c in history:
            if c["date"] and c["date"] <= day:
                key = (c["block"], c["metric"])
                if key not in snap or c["date"] >= snap[key]["date"]:
                    snap[key] = c
        metrics = {}
        for m in METRICS:
            cells = [c for (b, mm), c in snap.items() if mm == m]
            if cells:
                total = sum(c["total"] for c in cells)
                metrics[m] = {"pct": 100 * sum(c["covered"] for c in cells) / total,
                              "target": sum(c["target"] * c["total"] for c in cells) / total,
                              "met": sum(1 for c in cells if 100 * c["covered"] / c["total"] >= c["target"]),
                              "cells": len(cells)}
        points.append({"date": day.isoformat(), "metrics": metrics})
    return points


def testplan_trend(items, history, as_of, weeks):
    """Planned / written / passing counts at the end of each week (None without history).

    An item's status on a day is its latest change on or before that day. Before its first
    recorded change it counts as planned; an item with no recorded changes keeps its
    current status throughout.
    """
    if not history:
        return None
    ids = {t["id"] for t in items}
    changes = defaultdict(list)
    for h in sorted(history, key=lambda h: h["date"]):
        if h["id"] in ids:
            changes[h["id"]].append(h)
    points = []
    for w in range(weeks - 1, -1, -1):
        day = as_of - dt.timedelta(days=7 * w)
        counts = Counter()
        for t in items:
            past = [h for h in changes.get(t["id"], []) if h["date"] <= day]
            counts[past[-1]["status"] if past else "planned" if changes.get(t["id"]) else t["status"]] += 1
        points.append({"date": day.isoformat(), **{s: counts[s] for s in TESTPLAN_STATES}})
    return points


def fix_speed(bugs, as_of):
    """Days from opened to closed per severity, and the age of what is still open."""
    out = []
    for sev in SEVERITIES:
        closed = sorted((b["closed"] - b["opened"]).days for b in bugs if b["severity"] == sev and b["closed"])
        open_ages = [(as_of - b["opened"]).days for b in bugs if b["severity"] == sev and b["status"] in UNRESOLVED]
        out.append({"severity": sev, "closed": len(closed),
                    "median": closed[len(closed) // 2] if closed else None,
                    "p90": closed[min(len(closed) - 1, int(len(closed) * 0.9))] if closed else None,
                    "open": len(open_ages), "oldest_open": max(open_ages) if open_ages else None})
    return out


STATUS_CHAR = {"PASS": "P", "FAIL": "F", "TIMEOUT": "T", "ERROR": "E"}


def node_slug(path: tuple) -> str:
    """Hash-safe id for a hierarchy node: letters, digits and hyphens only."""
    return "--".join(re.sub(r"[^A-Za-z0-9]+", "-", p).strip("-") or "x" for p in path) or "all"


def hierarchy_path(row: dict, block_subsystem: dict) -> tuple[str, str, str]:
    """(subsystem, module, instance) for a regression row.

    The CSV's subsystem column wins, then config.json "subsystems", then a catch-all group.
    A row without an instance is treated as the module's only instance.
    """
    ss = row.get("subsystem") or block_subsystem.get(row["block"], UNGROUPED)
    return ss, row["block"], row.get("instance") or row["block"]


def regression_tree(data: dict) -> dict:
    """Roll regression results up a subsystem > module > instance > test hierarchy.

    A test's result in a run is PASS only if every seed passed; otherwise it takes the
    status of its first non-passing seed. Progress at every level is counted in tests.
    Each test carries its full run history so the page can show any run, compare two
    runs, and draw a heatmap without another build.
    """
    cfg = data["config"]
    settings = cfg["settings"]
    order = run_order(data["runs"])
    run_ids = [r for r, _ in order]
    dates = [d for _, d in order]
    idx = {r: i for i, r in enumerate(run_ids)}
    n, latest, prev = len(run_ids), len(run_ids) - 1, len(run_ids) - 2
    history = settings["test_history_runs"]
    milestone = current_milestone(cfg)
    need, due = milestone["need"], milestone["due"]

    tests = {}  # (ss, module, instance, test) -> per-run results
    for r in data["runs"]:
        key = (*hierarchy_path(r, cfg["block_subsystem"]), r["test"])
        t = tests.setdefault(key, {"status": {}, "seeds": defaultdict(lambda: [0, 0]), "sig": {}})
        i = idx[r["run_id"]]
        if t["status"].get(i, "PASS") == "PASS":
            t["status"][i] = r["status"]
        seeds = t["seeds"][i]
        seeds[0] += r["status"] == "PASS"
        seeds[1] += 1
        if r["status"] != "PASS" and i not in t["sig"]:
            t["sig"][i] = r["signature"] or "(no signature)"

    def new_node(path):
        return {"id": node_slug(path), "name": path[-1] if path else cfg["project"],
                "level": ("project", "subsystem", "module", "instance")[len(path)],
                "path": list(path), "children": [],
                "sims": [Counter() for _ in range(n)], "tp": [0] * n, "tf": [0] * n,
                "tests": 0, "not_run": 0, "new_fail": 0, "fixed": 0, "always_fail": 0}

    nodes = {(): new_node(())}
    test_rows = []
    has_owners = bool(data.get("owners"))
    owner_of = owner_lookup(data.get("owners", []))
    sig_list, sig_ids = [], {}

    def sig_id(text):
        if text not in sig_ids:
            sig_ids[text] = len(sig_list)
            sig_list.append(text)
        return sig_ids[text]

    for key in sorted(tests):
        ss, mod, inst, name = key
        t = tests[key]
        paths = [(), (ss,), (ss, mod), (ss, mod, inst)]
        for depth in range(1, 4):
            if paths[depth] not in nodes:
                nodes[paths[depth]] = new_node(paths[depth])
                nodes[paths[depth - 1]]["children"].append(paths[depth])
        st = t["status"]
        cur, before = st.get(latest), st.get(prev)
        since = None
        if cur is not None:
            i = latest
            while i - 1 >= 0 and st.get(i - 1) is not None and (st[i - 1] == "PASS") == (cur == "PASS"):
                i -= 1
            since = run_ids[i]
        for path in paths:
            node = nodes[path]
            node["tests"] += 1
            for i, s in st.items():
                node["tp" if s == "PASS" else "tf"][i] += 1
            if cur is None:
                node["not_run"] += 1
            elif cur != "PASS" and before == "PASS":
                node["new_fail"] += 1
            elif cur == "PASS" and before is not None and before != "PASS":
                node["fixed"] += 1
            if st and all(s != "PASS" for s in st.values()):
                node["always_fail"] += 1
        seeds = t["seeds"].get(latest)
        hist = "".join(STATUS_CHAR.get(st.get(i), "-") for i in range(n))
        test_rows.append({
            "n": node_slug(paths[3]), "ss": ss, "mod": mod, "inst": inst, "test": name,
            "hist": hist,  # one character per run: P pass, F fail, T timeout, E error, - not run
            "fs": [[i, sig_id(sig)] for i, sig in sorted(t["sig"].items())],  # first error per failing run
            "status": cur or "NOT RUN",
            "seeds": f"{seeds[0]}/{seeds[1]}" if seeds else "",
            "since": since,
            "fail_days": fail_age(st, latest, dates),
            "new": cur is not None and cur != "PASS" and before == "PASS",
            "fixed": cur == "PASS" and before is not None and before != "PASS",
            "sig": t["sig"].get(latest, ""),
            "o": owner_of(ss, mod, inst, name) if has_owners else "",
        })

    for r in data["runs"]:
        path = hierarchy_path(r, cfg["block_subsystem"])
        i = idx[r["run_id"]]
        for depth in range(4):
            nodes[path[:depth]]["sims"][i][r["status"]] += 1

    out = []
    for path, node in nodes.items():
        sims = node.pop("sims")
        node["total"] = [sum(c.values()) for c in sims]
        node["pass"] = [c["PASS"] for c in sims]
        node["fail"] = [c["FAIL"] for c in sims]
        node["timeout"] = [c["TIMEOUT"] for c in sims]
        node["error"] = [c["ERROR"] for c in sims]
        last = sims[latest]
        node["latest"] = {"fail": last["FAIL"], "timeout": last["TIMEOUT"], "error": last["ERROR"]}
        node["children"] = [node_slug(c) for c in sorted(node["children"])]
        node["owners"] = sorted({t["o"] for t in test_rows if t["o"] and
                                 [t["ss"], t["mod"], t["inst"]][:len(path)] == list(path)})
        rates = [p / t if t else None for p, t in zip(node["pass"], node["total"])]
        node["forecast"] = forecast(dates, rates, need, due, settings["forecast_runs"])
        node["burn"] = burn_slope(dates, node["tp"], node["total"], settings["forecast_runs"])
        out.append(node)
    out.sort(key=lambda nd: nd["path"])
    weeks = run_weeks(dates, project_as_of(cfg, dates), settings["weeks"])
    return {"runs": [{"run": r, "date": d.isoformat()} for r, d in order],
            "nodes": out, "tests": test_rows, "sigs": sig_list, "history": min(history, n),
            "weeks": [{k: v for k, v in w.items() if k != "in"} for w in weeks],
            "stuck_days": settings["stuck_days"],
            "owners": owner_weeks(data, tests, order, owner_of, weeks) if has_owners else None}


def current_milestone(cfg) -> dict:
    """The milestone the project is working toward: name, due date and pass-rate bar."""
    m = next((m for m in cfg.get("milestones", []) if m["name"] == cfg.get("current_milestone")), None) or {}
    return {"name": m.get("name"), "due": dt.date.fromisoformat(m["date"]) if m.get("date") else None,
            "need": m.get("criteria", {}).get("min_pass_rate")}


def project_as_of(cfg, dates) -> dt.date:
    return dt.date.fromisoformat(cfg["as_of"]) if cfg.get("as_of") else dates[-1]


def run_weeks(dates, as_of, count):
    """Weeks of runs, oldest first, each ending `as_of - 7k` days and covering the 7 days before.

    `s` is the last run before the week began (None for the first week of data), `e` the
    week's last run, `in` the indexes of the week's runs. Weeks without runs are left out.
    """
    weeks = []
    for w in range(count - 1, -1, -1):
        end = as_of - dt.timedelta(days=7 * w)
        start = end - dt.timedelta(days=7)
        in_week = [i for i, d in enumerate(dates) if start < d <= end]
        if not in_week:
            continue
        before = [i for i, d in enumerate(dates) if d <= start]
        weeks.append({"start": start.isoformat(), "end": end.isoformat(), "runs": len(in_week),
                      "s": before[-1] if before else None, "e": in_week[-1], "in": set(in_week)})
    return weeks


def fail_age(status: dict, at: int, dates) -> int | None:
    """Days a test has been failing as of run `at` (runs it skipped don't break the streak)."""
    if status.get(at) in (None, "PASS"):
        return None
    first = at
    for j in range(at - 1, -1, -1):
        s = status.get(j)
        if s is None:
            continue
        if s == "PASS":
            break
        first = j
    return (dates[at] - dates[first]).days


def fit_line(xs, ys):
    """Least-squares line: returns (intercept, slope) or None if it can't be fitted."""
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - b * mx, b


def forecast(dates, rates, need, due, window):
    """When will the pass rate reach `need`? Fits a line to the last `window` runs that ran.

    status: met (last three runs average at or above the bar), on_track (projected before `due`),
    at_risk (projected after `due`, or `due` has passed), stalled (not improving),
    projected (no due date to compare with), unknown (too little data or no bar).
    """
    pts = [(d, r) for d, r in zip(dates, rates) if r is not None][-window:]
    if need is None or len(pts) < 3:
        return {"status": "unknown"}
    last_date, last = pts[-1]
    recent = sum(r for _, r in pts[-3:]) / 3
    if recent >= need:  # the last three runs average at or above the bar
        return {"status": "met", "eta": last_date.isoformat()}
    xs = [(d - pts[0][0]).days for d, _ in pts]
    fit = fit_line(xs, [r for _, r in pts])
    if fit is None:
        return {"status": "unknown"}
    a, b = fit
    per_week = b * 7
    if per_week < 0.002:  # under 0.2 points a week: call it stalled
        return {"status": "stalled", "per_week": per_week}
    now = a + b * xs[-1]
    eta = last_date + dt.timedelta(days=max(1, math.ceil((need - now) / b - 1e-9)))  # 1e-9: float noise
    if due is None:
        status = "projected"
    else:
        status = "on_track" if eta <= due and last_date <= due else "at_risk"
    return {"status": status, "eta": eta.isoformat(), "per_week": per_week,
            "due": due.isoformat() if due else None}


def burn_slope(dates, passing, totals, window):
    """Tests gained per day over the last `window` runs, for the burn-up projection."""
    pts = [(d, p) for d, p, t in zip(dates, passing, totals) if t][-window:]
    if len(pts) < 3:
        return None
    fit = fit_line([(d - pts[0][0]).days for d, _ in pts], [p for _, p in pts])
    return fit[1] if fit else None


def owner_weeks(data, tests, order, owner_of, weeks):
    """Week-by-week progress for every owner, plus a pass-rate forecast per owner.

    "Start" is the last run before the week began (or nothing in the first week of data);
    "end" is the week's last run.
    """
    cfg = data["config"]
    dates = [d for _, d in order]
    run_ids = [r for r, _ in order]
    milestone = current_milestone(cfg)
    stuck = cfg["settings"]["stuck_days"]

    def blank():
        return {k: 0 for k in ("tp_s", "tp_e", "ran_s", "ran_e", "fail_e", "added", "new_fail", "fixed",
                               "sims", "sims_pass", "bug_opened", "bug_closed", "bug_unresolved", "stuck")}
    stats = defaultdict(lambda: [blank() for _ in weeks])
    scopes = defaultdict(list)
    for o in data["owners"]:
        scopes[o["owner"]].append(o["scope"])
    current_tests = Counter()
    oldest = defaultdict(lambda: [None for _ in weeks])

    for (ss, mod, inst, name), t in tests.items():
        o = owner_of(ss, mod, inst, name)
        st = t["status"]
        current_tests[o] += 1
        first = min(st)
        for wi, wk in enumerate(weeks):
            s = st.get(wk["s"]) if wk["s"] is not None else None
            e = st.get(wk["e"])
            x = stats[o][wi]
            x["tp_s"] += s == "PASS"
            x["tp_e"] += e == "PASS"
            x["ran_s"] += s is not None
            x["ran_e"] += e is not None
            x["fail_e"] += e is not None and e != "PASS"
            x["added"] += first in wk["in"]
            x["new_fail"] += s == "PASS" and e is not None and e != "PASS"
            x["fixed"] += s is not None and s != "PASS" and e == "PASS"
            age = fail_age(st, wk["e"], dates)
            if age is not None:
                x["stuck"] += age >= stuck
                if oldest[o][wi] is None or age > oldest[o][wi]["days"]:
                    oldest[o][wi] = {"days": age, "test": name, "where": f"{mod}/{inst}"}

    idx = {r: i for i, r in enumerate(run_ids)}
    sims = defaultdict(lambda: ([0] * len(order), [0] * len(order)))
    for r in data["runs"]:
        ss, mod, inst = hierarchy_path(r, cfg["block_subsystem"])
        o = owner_of(ss, mod, inst, r["test"])
        i = idx[r["run_id"]]
        sims[o][0][i] += 1
        sims[o][1][i] += r["status"] == "PASS"
        for wi, wk in enumerate(weeks):
            if i in wk["in"]:
                stats[o][wi]["sims"] += 1
                stats[o][wi]["sims_pass"] += r["status"] == "PASS"

    block_ss = {}
    for r in data["runs"]:
        block_ss.setdefault(r["block"], hierarchy_path(r, cfg["block_subsystem"])[0])

    def block_owner(block):
        return owner_of(block_ss.get(block, cfg["block_subsystem"].get(block, UNGROUPED)), block)

    fix_days = defaultdict(list)  # owner -> [(closed date, days to fix)]
    for b in data["bugs"]:
        o = b.get("owner") or block_owner(b["block"])
        if b["closed"]:
            fix_days[o].append((b["closed"], (b["closed"] - b["opened"]).days))
        for wi, wk in enumerate(weeks):
            start, end = dt.date.fromisoformat(wk["start"]), dt.date.fromisoformat(wk["end"])
            x = stats[o][wi]
            x["bug_opened"] += start < b["opened"] <= end
            x["bug_closed"] += b["closed"] is not None and start < b["closed"] <= end
            x["bug_unresolved"] += b["opened"] <= end and (b["closed"] is None or b["closed"] > end)

    # Functional coverage of the blocks each owner owns at module level, at each week's end.
    cov = defaultdict(lambda: defaultdict(dict))  # owner -> date -> block -> (covered, total)
    for c in data.get("coverage_history", []):
        if c["metric"] == "functional" and c["date"]:
            cov[block_owner(c["block"])][c["date"]][c["block"]] = (c["covered"], c["total"])

    def coverage_at(o, day):
        snap = {}
        for d in sorted(cov[o]):
            if d <= day:
                snap.update(cov[o][d])
        if not snap:
            return None
        return 100 * sum(c for c, _ in snap.values()) / sum(t for _, t in snap.values())

    for o in list(stats):
        for wi, wk in enumerate(weeks):
            x = stats[o][wi]
            end = dt.date.fromisoformat(wk["end"])
            start = dt.date.fromisoformat(wk["start"])
            x["target"] = data.get("owner_targets", {}).get((o, wk["end"]))
            x["cov_s"] = coverage_at(o, start) if wk["s"] is not None else None
            x["cov_e"] = coverage_at(o, end)
            done = sorted(days for closed, days in fix_days[o] if closed <= end)
            x["fix_median"] = done[len(done) // 2] if done else None
            x["oldest"] = oldest[o][wi]

    names = sorted(stats, key=lambda o: (o == UNASSIGNED, o.lower()))
    return {
        "list": [{"owner": o, "scopes": sorted(scopes.get(o, [])), "tests": current_tests[o],
                  "weeks": stats[o],
                  "forecast": forecast(dates, [p / t if t else None for t, p in zip(*sims[o])],
                                       milestone["need"], milestone["due"], cfg["settings"]["forecast_runs"])}
                 for o in names],
    }


def build_regression_payload(data: dict, links: dict) -> dict:
    cfg = data["config"]
    milestone = current_milestone(cfg)
    order = run_order(data["runs"])
    return {
        "project": cfg["project"],
        "latest_run": order[-1][0],
        "as_of": project_as_of(cfg, [d for _, d in order]).isoformat(),
        "milestone": milestone["name"],
        "due": milestone["due"].isoformat() if milestone["due"] else None,
        "need": milestone["need"],
        "links": links,
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        **regression_tree(data),
    }


def build_payload(data: dict, home: str | None = None) -> dict:
    order = run_order(data["runs"])
    data["as_of"] = dt.date.fromisoformat(data["config"]["as_of"]) if data["config"].get("as_of") else order[-1][1]
    blocks = sorted({r["block"] for k in ("runs", "coverage", "bugs", "testplan") for r in data[k]})
    cfg = data["config"]
    return {
        "project": cfg.get("project", "SoC"),
        "as_of": data["as_of"].isoformat(),
        "latest_run": order[-1][0],
        "current_milestone": cfg.get("current_milestone"),
        "milestones": [{"name": m["name"], "date": m.get("date", "")} for m in cfg.get("milestones", [])],
        "metrics": [m for m in METRICS if any(c["metric"] == m for c in data["coverage"])],
        "blockList": blocks,
        "scopes": {"all": summarize(data, None), **{b: summarize(data, b) for b in blocks}},
        "cells": [{k: c[k] for k in ("block", "metric", "covered", "total", "target")} for c in data["coverage"]],
        "bugList": [{**b, "opened": b["opened"].isoformat(),
                     "closed": b["closed"].isoformat() if b["closed"] else ""} for b in data["bugs"]],
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "window": cfg["settings"]["intermittent_window"],
        "stale_after_days": cfg["settings"]["stale_after_days"],
        "sources": [*cfg["files"].values(), "config.json"],
        "home": home,
        "regression_href": None,
        # block -> its module node on the regression page, so block links land in the right place
        "block_nodes": {r["block"]: node_slug(hierarchy_path(r, cfg["block_subsystem"])[:2]) for r in data["runs"]},
    }


def project_card(payload: dict, href: str) -> dict:
    """The one-line summary of a project that the overview page shows."""
    top = payload["scopes"]["all"]
    current = next((m for m in top["signoff"] if m["name"] == payload["current_milestone"]), None)
    due = next((m["date"] for m in payload["milestones"] if m["name"] == payload["current_milestone"]), "")
    last_run = top["trend"][-1]
    return {
        "name": payload["project"], "href": href, "as_of": payload["as_of"],
        "latest_run": payload["latest_run"], "latest_date": last_run["date"],
        "blocks": len(payload["blockList"]),
        "rates": [t["rate"] for t in top["trend"]],
        "rate": last_run["rate"], "sims": last_run["total"],
        "cov_met": top["coverage"]["cells_met"], "cov_cells": top["coverage"]["cells"],
        "bugs": top["bugs"]["unresolved"],
        "tp_passing": top["testplan"]["totals"]["passing"], "tp_items": top["testplan"]["items"],
        "milestone": current["name"] if current else None, "due": due,
        "checks_ok": sum(c["ok"] for c in current["checks"]) if current else 0,
        "checks": len(current["checks"]) if current else 0,
        "failing": [c["label"] for c in current["checks"] if not c["ok"]] if current else [],
        "met": bool(current and current["met"]),
        "stale_after_days": payload["stale_after_days"],
        "forecast": top["forecast"],
    }


def owner_rows(project: str, href: str, reg: dict) -> list[dict]:
    """Each owner's latest week in one project, for the cross-project owner table."""
    if not reg.get("owners") or not reg["weeks"]:
        return []
    week = reg["weeks"][-1]
    rows = []
    for o in reg["owners"]["list"]:
        if o["owner"] == UNASSIGNED:
            continue
        x = o["weeks"][-1]
        rows.append({"owner": o["owner"], "project": project, "href": href, "week_end": week["end"],
                     "first_week": week["s"] is None, "tp_s": x["tp_s"], "tp_e": x["tp_e"], "ran_e": x["ran_e"],
                     "target": x["target"], "new_fail": x["new_fail"], "fixed": x["fixed"],
                     "stuck": x["stuck"], "oldest": x["oldest"], "bug_unresolved": x["bug_unresolved"],
                     "forecast": o["forecast"]})
    return rows


# --------------------------------------------------------------------------- rendering

def render(payload: dict, fragment: bool = False) -> str:
    return _render("project.html", f"{payload['project']} Verification", payload, fragment)


def render_regression(payload: dict, fragment: bool = False) -> str:
    return _render("regression.html", f"{payload['project']} Regression", payload, fragment)


def render_overview(overview: dict, fragment: bool = False) -> str:
    return _render("overview.html", overview["title"], overview, fragment)


def _render(template_name: str, title: str, payload: dict, fragment: bool) -> str:
    template = (TEMPLATES / template_name).read_text().replace("/*__CSS__*/", (TEMPLATES / "base.css").read_text())
    head, body = template.split("<!--BODY-->", 1)
    blob = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    head = head.replace("__TITLE__", _html_escape(title))
    body = body.replace("__SOCDASH_DATA__", blob)
    if fragment:
        return head + body
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            f"{head}</head>\n<body>\n{body}</body>\n</html>\n")


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------------------- log collection

RE_TEST = re.compile(r"(?:\+UVM_TESTNAME=|Running test\s+)([A-Za-z_]\w*)")
RE_SEED = re.compile(r"(?:ntb_random_seed|sv_seed|svseed|\+seed)\s*[=\s]\s*(\d+)", re.I)
RE_COUNT = re.compile(r"^\s*(UVM_ERROR|UVM_FATAL)\s*:\s*(\d+)\s*$", re.M)
RE_MSG = re.compile(r"^(UVM_ERROR|UVM_FATAL)\s+\S+\(\d+\)\s*@\s*[\d.]+\s*\w*:\s*\S+\s*\[([^\]]+)\]\s*(.*)$", re.M)
RE_MSG_LOOSE = re.compile(r"^(UVM_ERROR|UVM_FATAL)\b.*?\[([^\]]+)\]\s*(.*)$", re.M)
RE_CPU = re.compile(r"CPU Time:\s*([\d.]+)\s*seconds", re.I)


def normalize_message(msg: str) -> str:
    msg = re.sub(r"0x[0-9a-fA-F_]+|'h[0-9a-fA-F_]+", "<HEX>", msg)
    msg = re.sub(r"\b\d+(\.\d+)?\b", "<N>", msg)
    return re.sub(r"\s+", " ", msg).strip()[:120]


def parse_log(text: str) -> dict:
    """Classify one simulation log. Returns test, seed, status, duration_s, signature."""
    test = RE_TEST.search(text)
    seed = RE_SEED.search(text)
    counts = {k: int(v) for k, v in RE_COUNT.findall(text)}
    cpu = RE_CPU.search(text)
    first = RE_MSG.search(text) or RE_MSG_LOOSE.search(text)
    if "[PH_TIMEOUT]" in text or "TIMEOUT" in (first.group(2) if first else ""):
        status = "TIMEOUT"
    elif not counts:
        status = "ERROR"  # no report summary: crash, compile failure or killed job
    elif counts.get("UVM_FATAL", 0) or counts.get("UVM_ERROR", 0):
        status = "FAIL"
    else:
        status = "PASS"
    signature = ""
    if status != "PASS":
        if first:
            signature = f"[{first.group(2)}] {normalize_message(first.group(3))}".strip()
        elif status == "ERROR":
            signature = "no UVM report summary (crash or killed)"
    return {
        "test": test.group(1) if test else "",
        "seed": seed.group(1) if seed else "",
        "status": status,
        "duration_s": cpu.group(1) if cpu else "",
        "signature": signature,
    }


LAYOUT_LEVELS = ("subsystem", "block", "instance")


def collect(logs: Path, run_id: str, date: str, out: Path, block: str | None, pattern: str,
            layout: str = "block") -> int:
    """Append one row per log file to a regression CSV.

    `layout` names the folders between `logs` and each log file, e.g. "subsystem/block/instance"
    for logs/<subsystem>/<block>/<instance>/<test>.log. Levels may be any of subsystem,
    block and instance, and block is required.
    """
    _date(date, "--date")
    levels = [x for x in layout.split("/") if x]
    if "block" not in levels or any(x not in LAYOUT_LEVELS for x in levels) or len(set(levels)) != len(levels):
        raise InputError(f"--layout '{layout}': use folder levels from {', '.join(LAYOUT_LEVELS)}, including block")
    files = sorted(Path(logs).rglob(pattern))
    if not files:
        raise InputError(f"{logs}: no files match '{pattern}'")
    wanted = list(REGRESSION_COLS) + [x for x in ("subsystem", "instance") if x in levels]
    if out.exists() and out.stat().st_size:
        with out.open(newline="") as f:
            header = next(csv.reader(f), [])
        missing = [c for c in wanted if c not in header]
        if missing:
            raise InputError(f"{out}: existing header lacks column(s) {', '.join(missing)} needed by --layout; "
                             f"add them to the header or write to a new file")
        new = False
    else:
        header, new = wanted, True
    with out.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore", restval="")
        if new:
            w.writeheader()
        for path in files:
            res = parse_log(path.read_text(errors="replace"))
            folders = path.relative_to(logs).parts[:-1]
            if len(folders) < len(levels) and not block:
                raise InputError(f"{path}: expected {len(levels)} folder level(s) ({'/'.join(levels)}) above the log")
            row = dict(zip(levels, folders))
            if block:
                row["block"] = block
            w.writerow({**row, "run_id": run_id, "date": date, "test": res["test"] or path.stem,
                        "seed": res["seed"], "status": res["status"], "duration_s": res["duration_s"],
                        "signature": res["signature"]})
    return len(files)


# --------------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build the HTML dashboard")
    b.add_argument("--data", type=Path, default=HERE / "projects" / "orion_soc",
                   help="project folder with config.json and the CSV files")
    b.add_argument("--out", type=Path, default=Path("dashboard.html"))
    b.add_argument("--fragment", action="store_true", help="omit <html>/<head>/<body> for embedding")
    b.add_argument("--fail-on-signoff", action="store_true",
                   help="exit 2 if the current milestone's sign-off criteria are not met")

    a = sub.add_parser("build-all", help="build every project's dashboard plus an overview page")
    a.add_argument("--projects", type=Path, default=HERE / "projects",
                   help="folder whose subfolders are projects (each with a config.json)")
    a.add_argument("--out", type=Path, default=Path("site"), help="output folder")
    a.add_argument("--title", default="SoC verification portfolio", help="overview page title")
    a.add_argument("--fail-on-signoff", action="store_true",
                   help="exit 2 if any project's current milestone criteria are not met")

    c = sub.add_parser("collect", help="append results from UVM logs to regression_runs.csv")
    c.add_argument("--logs", type=Path, required=True, help="folder of logs; first subfolder is the block")
    c.add_argument("--run-id", required=True)
    c.add_argument("--date", required=True, help="YYYY-MM-DD")
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--block", help="use this block name for every log instead of the subfolder")
    c.add_argument("--layout", default="block",
                   help="folder levels above each log, e.g. subsystem/block/instance (default: block)")
    c.add_argument("--pattern", default="*.log")

    args = p.parse_args(argv)
    try:
        if args.cmd == "collect":
            n = collect(args.logs, args.run_id, args.date, args.out, args.block, args.pattern, args.layout)
            print(f"Appended {n} result(s) to {args.out}")
            return 0
        if args.cmd == "build-all":
            return build_all(args.projects, args.out, args.title, args.fail_on_signoff)
        data = load(args.data)
        payload = build_payload(data)
        reg_out = args.out.with_name(f"{args.out.stem}-regression{args.out.suffix or '.html'}")
        payload["regression_href"] = reg_out.name
        args.out.write_text(render(payload, args.fragment))
        reg_out.write_text(render_regression(build_regression_payload(data, {"project": args.out.name}),
                                             args.fragment))
        print(f"Wrote {reg_out}")
    except InputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(f"Wrote {args.out}")
    current = print_summary(payload)
    if args.fail_on_signoff and current and not current["met"]:
        return 2
    return 0


def print_summary(payload: dict):
    top = payload["scopes"]["all"]
    rate = top["trend"][-1]["rate"]
    print(f"{payload['project']}: run {payload['latest_run']}, as of {payload['as_of']}")
    print(f"  pass rate {rate:.1%}  |  coverage cells at target {top['coverage']['cells_met']}/{top['coverage']['cells']}"
          f"  |  unresolved S1 {top['bugs']['unresolved']['S1']}, S2 {top['bugs']['unresolved']['S2']}")
    current = next((m for m in top["signoff"] if m["name"] == payload["current_milestone"]), None)
    if current:
        ok = sum(c["ok"] for c in current["checks"])
        print(f"  {current['name']} sign-off: {ok}/{len(current['checks'])} criteria met")
        for chk in current["checks"]:
            print(f"    [{'x' if chk['ok'] else ' '}] {chk['label']}: {chk['actual']} (need {chk['need']})")
    return current


def build_all(projects_root: Path, out: Path, title: str, fail_on_signoff: bool = False) -> int:
    """Build <out>/index.html (overview) and <out>/<project-slug>.html for each project.

    A project whose inputs are broken still appears on the overview, marked with the
    error, so one bad file does not hide every other project. Returns the exit code.
    """
    out.mkdir(parents=True, exist_ok=True)
    cards, errors, unmet, used, owners = [], 0, 0, set(), []
    for folder in discover_projects(projects_root):
        slug = slugify(folder.name)
        while slug in used:
            slug += "-x"
        used.add(slug)
        href, reg_href = f"{slug}.html", f"{slug}-regression.html"
        try:
            data = load(folder)
            payload = build_payload(data, home="index.html")
            reg = build_regression_payload(data, {"home": "index.html", "project": href})
        except InputError as e:
            errors += 1
            print(f"error: {folder.name}: {e}", file=sys.stderr)
            cards.append({"name": folder.name, "href": None, "error": str(e)})
            continue
        payload["regression_href"] = reg_href
        (out / href).write_text(render(payload))
        (out / reg_href).write_text(render_regression(reg))
        card = project_card(payload, href)
        card["regression_href"] = reg_href
        owners.extend(owner_rows(payload["project"], reg_href, reg))
        cards.append(card)
        unmet += not card["met"]
        print_summary(payload)
    overview = {"title": title, "projects": cards, "owners": owners,
                "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    (out / "index.html").write_text(render_overview(overview))
    print(f"Wrote {out / 'index.html'} and {len(cards) - errors} project page(s)")
    if errors:
        return 1
    return 2 if fail_on_signoff and unmet else 0


if __name__ == "__main__":
    sys.exit(main())
