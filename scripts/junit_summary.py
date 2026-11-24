#!/usr/bin/env python3
"""Print a Markdown pass/fail table from JUnit XML files.

Usage: junit_summary.py build/*/junit_*.xml [--title TEXT] >> "$GITHUB_STEP_SUMMARY"
Files that do not exist are listed as "not run".
"""
import argparse
import glob
import os
import xml.etree.ElementTree as ET


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="JUnit XML files or glob patterns")
    ap.add_argument("--title", default="Test results")
    args = ap.parse_args()

    files = []
    for pattern in args.files:
        files += sorted(glob.glob(pattern)) or [pattern]

    rows, failed = [], 0
    for path in files:
        if not os.path.exists(path):
            rows.append((path, "", "⚠️ not run", "file was not created"))
            continue
        root = ET.parse(path).getroot()
        for suite in [root] if root.tag == "testsuite" else root.iter("testsuite"):
            for case in suite.iter("testcase"):
                problem = case.find("failure")
                if problem is None:
                    problem = case.find("error")
                if case.find("skipped") is not None:
                    result, detail = "⏭️ skipped", ""
                elif problem is not None:
                    failed += 1
                    result = "❌ fail"
                    detail = (problem.get("message") or "").splitlines()[0] if problem.get("message") else ""
                else:
                    result, detail = "✅ pass", ""
                block = suite.get("name") or case.get("classname") or ""
                rows.append((block, case.get("name"), result, detail.replace("|", "/")[:150]))

    print("### %s\n" % args.title)
    print("%d run(s), %d failed\n" % (len(rows), failed))
    print("| Block | Test | Result | Details |\n|---|---|---|---|")
    for row in rows:
        print("| %s | %s | %s | %s |" % row)


if __name__ == "__main__":
    main()
