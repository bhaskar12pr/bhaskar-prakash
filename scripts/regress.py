#!/usr/bin/env python3
"""Compile once, then run every test x seed in parallel and judge the results.

Simulator independent: the compile and run commands are templates that come
from scripts/sim/<sim>.mk. These placeholders are replaced before running:
    {test}  {seed}  {rundir}  {block}
(Plain replacement, so shell syntax such as ${HOME} is left alone.)

Each test runs in its own directory  <outdir>/<test>_s<seed>/  with its
output in sim.log, and with TEST and SEED also set in its environment.

A test passes only when ALL of these hold:
  * it finished before --timeout (otherwise its whole process group is killed)
  * the simulator exit code is 0 (unless --ignore-exit-code)
  * no line matches a "fail:" pattern (after removing "ignore:" lines)
  * some line matches a "pass:" pattern, if any are defined. This catches
    tests that stop early without reporting anything.

Patterns come from a file (see scripts/patterns/). Results go to the console,
to a JUnit XML file, and failures print the exact command to rerun them.
Exit code: 0 all passed, 1 something failed, 2 bad arguments.
"""
import argparse
import collections
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

Result = collections.namedtuple("Result", "test seed status reason seconds log tail")
_running = set()
MARK = "#regress# "   # lines written by this script into sim.log; never checked
_lock = threading.Lock()


# -- patterns ----------------------------------------------------------------
def load_patterns(paths):
    pats = {"pass": [], "fail": [], "ignore": []}
    for path in paths:
        with open(path) as f:
            for no, line in enumerate(f, 1):
                line = line.rstrip("\n")
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                kind, sep, rx = line.partition(":")
                kind = kind.strip().lower()
                if not sep or kind not in pats:
                    raise ValueError("%s:%d: expected 'pass: REGEX', 'fail: REGEX' or 'ignore: REGEX'" % (path, no))
                try:
                    pats[kind].append(re.compile(rx.strip()))
                except re.error as e:
                    raise ValueError("%s:%d: bad regex: %s" % (path, no, e))
    return pats


def check_log(log_path, pats, tail_lines=30):
    """Return (passed, reason, tail). Reads line by line, so huge logs are fine."""
    tail = collections.deque(maxlen=tail_lines)
    first_fail, saw_pass = None, False
    try:
        with open(log_path, errors="replace") as f:
            for no, line in enumerate(f, 1):
                line = line.rstrip("\n")
                if line.startswith(MARK):
                    continue
                tail.append(line)
                if any(p.search(line) for p in pats["ignore"]):
                    continue
                if first_fail is None and any(p.search(line) for p in pats["fail"]):
                    first_fail = "line %d: %s" % (no, line.strip()[:200])
                if not saw_pass and any(p.search(line) for p in pats["pass"]):
                    saw_pass = True
    except IOError:
        return False, "no log file", ""
    text = "\n".join(tail)
    if first_fail:
        return False, first_fail, text
    if pats["pass"] and not saw_pass:
        return False, "no pass message in log (test stopped early or did not self-check)", text
    return True, "", text


# -- running -----------------------------------------------------------------
def fill(template, **values):
    for k, v in values.items():
        template = template.replace("{%s}" % k, str(v))
    return template


def run_cmd(cmd, cwd, log_path, timeout, env):
    """Run cmd in a shell in its own process group. Return (exit_code, timed_out)."""
    with open(log_path, "w") as log:
        log.write("%scwd: %s\n%scmd: %s\n" % (MARK, cwd, MARK, cmd))
        log.flush()
        proc = subprocess.Popen(cmd, shell=True, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                                env=env, start_new_session=True)
        with _lock:
            _running.add(proc)
        try:
            return proc.wait(timeout=timeout or None), False
        except subprocess.TimeoutExpired:
            kill(proc)
            return None, True
        finally:
            with _lock:
                _running.discard(proc)


def kill(proc):
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
    except OSError:
        pass


def run_one(args, pats, test, seed):
    rundir = os.path.join(args.outdir, "%s_s%s" % (test, seed))
    if os.path.isdir(rundir):
        shutil.rmtree(rundir)
    os.makedirs(rundir)
    log = os.path.join(rundir, "sim.log")
    cmd = fill(args.run, test=test, seed=seed, rundir=rundir, block=args.name)
    env = dict(os.environ, TEST=test, SEED=str(seed))
    start = time.time()
    code, timed_out = run_cmd(cmd, rundir, log, args.timeout, env)
    secs = time.time() - start
    passed, reason, tail = check_log(log, pats, args.tail)
    if timed_out:
        passed, reason = False, "timeout after %ss (process killed)" % args.timeout
        with open(log, "a") as f:
            f.write("\n%sTIMEOUT after %ss, process killed\n" % (MARK, args.timeout))
    elif code != 0 and not args.ignore_exit_code:
        passed, reason = False, "simulator exit code %s%s" % (code, "; " + reason if reason else "")
    return Result(test, seed, "PASS" if passed else "FAIL", reason, secs, log, tail)


def pick_seeds(args):
    if args.seed is not None:
        return [args.seed]
    if args.random_seeds:
        rng = random.SystemRandom()
        return [rng.randint(1, 2**31 - 1) for _ in range(args.seeds)]
    return [args.base_seed + i for i in range(args.seeds)]


# -- reporting ---------------------------------------------------------------
def write_junit(path, name, results, compile_result=None):
    suite = ET.Element("testsuite", name=name)
    cases = ([compile_result] if compile_result else []) + results
    for r in cases:
        case_name = r.test if r.seed is None else "%s.seed%s" % (r.test, r.seed)
        case = ET.SubElement(suite, "testcase", classname=name, name=case_name, time="%.2f" % r.seconds)
        if r.status != "PASS":
            ET.SubElement(case, "failure", message=r.reason).text = r.tail
        ET.SubElement(case, "system-out").text = "log: %s\n%s" % (r.log, r.tail)
    suite.set("tests", str(len(cases)))
    suite.set("failures", str(sum(r.status != "PASS" for r in cases)))
    suite.set("time", "%.2f" % sum(r.seconds for r in cases))
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def report_failure(args, r):
    print("    reason: %s" % r.reason)
    print("    log:    %s" % r.log)
    if args.rerun:
        print("    rerun:  %s" % fill(args.rerun, test=r.test, seed=r.seed, block=args.name))
    if r.tail:
        print("    ---- last lines of log ----")
        for line in r.tail.splitlines()[-args.tail:]:
            print("    | " + line)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="block name (JUnit suite name)")
    ap.add_argument("--compile", help="compile command, run once in --outdir before the tests")
    ap.add_argument("--run", required=True, help="run command template")
    ap.add_argument("--tests", nargs="+", required=True)
    ap.add_argument("--seeds", type=int, default=1, help="seeds per test (default 1)")
    ap.add_argument("--seed", type=int, help="use exactly this seed")
    ap.add_argument("--base-seed", type=int, default=1, help="seeds are base, base+1, ... (default 1)")
    ap.add_argument("--random-seeds", action="store_true", help="pick random seeds (nightly runs)")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--timeout", type=float, default=600, help="seconds per test; 0 = none")
    ap.add_argument("--compile-timeout", type=float, default=1800)
    ap.add_argument("--patterns", action="append", required=True, help="pattern file (repeatable)")
    ap.add_argument("--ignore-exit-code", action="store_true")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--junit", help="write JUnit XML here")
    ap.add_argument("--rerun", help="template printed for each failure, e.g. 'make sim TEST={test} SEED={seed}'")
    ap.add_argument("--tail", type=int, default=30, help="log lines shown for a failure")
    args = ap.parse_args(argv)

    if args.seeds < 1 or args.jobs < 1:
        ap.error("--seeds and --jobs must be at least 1")
    try:
        pats = load_patterns(args.patterns)
    except (IOError, ValueError) as e:
        print("regress: %s" % e, file=sys.stderr)
        return 2
    args.outdir = os.path.abspath(args.outdir)
    if not os.path.isdir(args.outdir):
        os.makedirs(args.outdir)

    def on_signal(signum, frame):
        with _lock:
            for p in list(_running):
                kill(p)
        sys.exit(130)
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    # Compile
    if args.compile:
        log = os.path.join(args.outdir, "compile.log")
        print("[%s] compile ..." % args.name)
        start = time.time()
        code, timed_out = run_cmd(args.compile, args.outdir, log, args.compile_timeout, dict(os.environ))
        ok, reason, tail = check_log(log, {"pass": [], "fail": [], "ignore": []}, args.tail)
        if timed_out or code != 0:
            reason = "compile timeout" if timed_out else "compile failed (exit code %s)" % code
            r = Result("compile", None, "FAIL", reason, time.time() - start, log, tail)
            print("[%s] COMPILE FAILED" % args.name)
            report_failure(args, r)
            if args.junit:
                write_junit(args.junit, args.name, [], r)
            return 1

    # Run
    seeds = pick_seeds(args)
    jobs = [(t, s) for t in args.tests for s in seeds]
    total, done, results = len(jobs), [0], []
    width = len(str(total))
    print("[%s] running %d test(s) x %d seed(s) = %d run(s), %d in parallel, timeout %ss"
          % (args.name, len(args.tests), len(seeds), total, min(args.jobs, total), args.timeout))

    def task(job):
        r = run_one(args, pats, *job)
        with _lock:
            done[0] += 1
            print("[%s] [%*d/%d] %s  %s seed=%s  (%.1fs)"
                  % (args.name, width, done[0], total, r.status, r.test, r.seed, r.seconds))
            if r.status != "PASS":
                report_failure(args, r)
            sys.stdout.flush()
        return r

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(task, jobs))

    failed = [r for r in results if r.status != "PASS"]
    print("[%s] %d/%d passed" % (args.name, total - len(failed), total))
    for r in failed:
        print("[%s]   FAILED %s seed=%s: %s" % (args.name, r.test, r.seed, r.reason))
    if args.junit:
        write_junit(args.junit, args.name, results)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
