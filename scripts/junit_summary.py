#!/usr/bin/env python3
"""Print a Markdown pass/fail table from a JUnit XML file (e.g. cocotb results).

Usage: junit_summary.py results.xml [--title TEXT] >> "$GITHUB_STEP_SUMMARY"
"""
import argparse
import os
import sys
import xml.etree.ElementTree as ET

ap = argparse.ArgumentParser()
ap.add_argument("xml")
ap.add_argument("--title", default="Test results")
args = ap.parse_args()

print(f"### {args.title}\n")
if not os.path.exists(args.xml):
    print(f"❌ `{args.xml}` was not created: the tests did not run.")
    sys.exit(0)

print("| Test | Result | Details |\n|---|---|---|")
for case in ET.parse(args.xml).getroot().iter("testcase"):
    problem = case.find("failure")
    if problem is None:
        problem = case.find("error")
    if case.find("skipped") is not None:
        result, detail = "⏭️ skipped", ""
    elif problem is not None:
        result = "❌ fail"
        detail = (problem.get("message") or "").splitlines()[0] if problem.get("message") else ""
    else:
        result, detail = "✅ pass", ""
    print(f"| {case.get('name')} | {result} | {detail.replace('|', '/')} |")
