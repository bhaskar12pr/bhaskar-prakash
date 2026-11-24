#!/usr/bin/env python3
"""Build a dashboard from a copy of the Orion sample whose names are script-injection payloads.

Used by browser_safety_check.js to prove that names coming from CSV files are shown as text
and never run as HTML or script, on every page and in the quick-search palette.

    python3 checks/make_hostile_project.py OUT_DIR
writes OUT_DIR/projects/hostile_soc and builds OUT_DIR/site.
"""
import csv
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import socdash  # noqa: E402

# Each payload sets window.__pwned if it ever runs.
TEST = '<img src=x onerror="window.__pwned=1">'
OWNER = '"><svg onload="window.__pwned=2">'
SIG = '</script><script>window.__pwned=3</script>'
PROJECT = 'Evil<script>window.__pwned=4</script> SoC'


def rewrite(path: Path, fn):
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
        fields = list(rows[0].keys())
    rows = [fn(dict(r)) for r in rows]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main(out: Path) -> None:
    proj = out / "projects" / "hostile_soc"
    if proj.exists():
        shutil.rmtree(proj)
    shutil.copytree(HERE / "projects" / "orion_soc", proj)

    def runs(r):
        if r["test"] == "smoke_boot":
            r["test"] = TEST
        if r["status"] != "PASS":
            r["signature"] = SIG
        return r
    rewrite(proj / "regression_runs.csv", runs)
    rewrite(proj / "owners.csv", lambda r: {**r, "owner": OWNER if r["owner"] == "Dana" else r["owner"]})
    for name in ("owner_targets.csv", "engineer_activity.csv", "worklog.csv"):  # every file that names owners
        if (proj / name).exists():
            rewrite(proj / name, lambda r: {**r, "owner": OWNER if r["owner"] == "Dana" else r["owner"]})
    cfg = json.loads((proj / "config.json").read_text())
    cfg["project"] = PROJECT
    (proj / "config.json").write_text(json.dumps(cfg, indent=2))

    code = socdash.build_all(out / "projects", out / "site", "Hostile check")
    print(f"built {out / 'site'} (build exit {code})")
    if code == 1:  # a broken input means the hostile pages were not built, so nothing was proven
        sys.exit("hostile project failed to build; the safety check would not cover it")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
