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
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"

# Input files a project folder holds. config.json may rename any of them under "files".
DEFAULT_FILES = {"regression": "regression_runs.csv", "coverage": "coverage.csv",
                 "bugs": "bugs.csv", "testplan": "testplan.csv"}
# Tunable settings a project may override under "settings" in config.json.
DEFAULT_SETTINGS = {"intermittent_window": 7, "bug_trend_weeks": 10, "stale_after_days": 3}

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
        })
    if not runs:
        raise InputError("regression_runs.csv: no rows")

    coverage = []
    for r in read_csv(files["coverage"], COVERAGE_COLS):
        covered = _num(r["covered"], r["_where"], int)
        total = _num(r["total"], r["_where"], int)
        if total <= 0 or covered > total:
            raise InputError(f"{r['_where']}: need 0 <= covered <= total and total > 0")
        coverage.append({
            "block": r["block"],
            "metric": _choice(r, "metric", METRICS),
            "covered": covered,
            "total": total,
            "target": _num(r["target_pct"], r["_where"]),
        })

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

    return {"config": config, "dir": data_dir, "runs": runs, "coverage": coverage, "bugs": bugs,
            "testplan": testplan}


def load_config(path: Path) -> dict:
    """Read a project's config.json, check it, and fill in defaults."""
    try:
        config = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise InputError(f"{path}: invalid JSON at line {e.lineno}: {e.msg}") from None
    if not isinstance(config, dict):
        raise InputError(f"{path}: must be a JSON object")
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
    }


# --------------------------------------------------------------------------- rendering

def render(payload: dict, fragment: bool = False) -> str:
    return _render("project.html", f"{payload['project']} Verification", payload, fragment)


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


def collect(logs: Path, run_id: str, date: str, out: Path, block: str | None, pattern: str) -> int:
    _date(date, "--date")
    files = sorted(Path(logs).rglob(pattern))
    if not files:
        raise InputError(f"{logs}: no files match '{pattern}'")
    new = not out.exists() or out.stat().st_size == 0
    with out.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(REGRESSION_COLS)
        for path in files:
            res = parse_log(path.read_text(errors="replace"))
            rel = path.relative_to(logs)
            blk = block or (rel.parts[0] if len(rel.parts) > 1 else "top")
            w.writerow([run_id, date, blk, res["test"] or path.stem, res["seed"], res["status"],
                        res["duration_s"], res["signature"]])
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
    c.add_argument("--pattern", default="*.log")

    args = p.parse_args(argv)
    try:
        if args.cmd == "collect":
            n = collect(args.logs, args.run_id, args.date, args.out, args.block, args.pattern)
            print(f"Appended {n} result(s) to {args.out}")
            return 0
        if args.cmd == "build-all":
            return build_all(args.projects, args.out, args.title, args.fail_on_signoff)
        payload = build_payload(load(args.data))
        args.out.write_text(render(payload, args.fragment))
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
    cards, errors, unmet, used = [], 0, 0, set()
    for folder in discover_projects(projects_root):
        slug = slugify(folder.name)
        while slug in used:
            slug += "-x"
        used.add(slug)
        href = f"{slug}.html"
        try:
            payload = build_payload(load(folder), home="index.html")
        except InputError as e:
            errors += 1
            print(f"error: {folder.name}: {e}", file=sys.stderr)
            cards.append({"name": folder.name, "href": None, "error": str(e)})
            continue
        (out / href).write_text(render(payload))
        card = project_card(payload, href)
        cards.append(card)
        unmet += not card["met"]
        print_summary(payload)
    overview = {"title": title, "projects": cards,
                "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    (out / "index.html").write_text(render_overview(overview))
    print(f"Wrote {out / 'index.html'} and {len(cards) - errors} project page(s)")
    if errors:
        return 1
    return 2 if fail_on_signoff and unmet else 0


if __name__ == "__main__":
    sys.exit(main())
