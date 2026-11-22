#!/usr/bin/env python3
"""Convert testbench logs into a JUnit XML report.

Each tb/tb_<name>.v becomes one test case. It passes when build/tb_<name>.log
contains "TEST PASSED" and no "ERROR" line. A missing log means the testbench
did not compile or run, and counts as a failure.

GitHub Actions and GitLab CI both read JUnit XML. With --summary, a Markdown
table is also appended to that file (pass $GITHUB_STEP_SUMMARY on GitHub).
"""
import argparse
import os
import sys
import xml.etree.ElementTree as ET


def check(log_path):
    """Return (passed, message, log_text) for one testbench log."""
    if not os.path.exists(log_path):
        return False, "no log: testbench did not compile or run", ""
    with open(log_path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    errors = [line for line in text.splitlines() if "ERROR" in line]
    if errors:
        return False, f"{len(errors)} error(s): {errors[0]}", text
    if "TEST PASSED" not in text:
        return False, "no 'TEST PASSED' line in log", text
    return True, "", text


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("testbenches", nargs="*", help="tb/tb_*.v files")
    ap.add_argument("--build", default="build")
    ap.add_argument("--out", default="build/junit.xml")
    ap.add_argument("--summary", help="append a Markdown summary to this file")
    args = ap.parse_args()

    suite = ET.Element("testsuite", name="rtl-testbenches")
    rows, failures = [], 0
    for tb in sorted(args.testbenches):
        name = os.path.splitext(os.path.basename(tb))[0]
        passed, msg, text = check(os.path.join(args.build, name + ".log"))
        case = ET.SubElement(suite, "testcase", classname="tb", name=name)
        if not passed:
            failures += 1
            ET.SubElement(case, "failure", message=msg).text = text
        ET.SubElement(case, "system-out").text = text
        rows.append((name, "✅ pass" if passed else "❌ fail", msg))

    suite.set("tests", str(len(rows)))
    suite.set("failures", str(failures))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    ET.ElementTree(suite).write(args.out, encoding="utf-8", xml_declaration=True)

    print(f"{len(rows) - failures}/{len(rows)} testbenches passed -> {args.out}")
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as f:
            f.write("### Testbench results\n\n| Testbench | Result | Details |\n|---|---|---|\n")
            for row in rows:
                f.write("| %s | %s | %s |\n" % row)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
