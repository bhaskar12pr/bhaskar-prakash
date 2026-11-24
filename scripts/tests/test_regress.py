"""Unit tests for scripts/regress.py using fake simulators (shell commands).
Run: make selftest"""
import os
import shutil
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET

import regress

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(HERE, "..", "patterns", "default.txt")
UVM = os.path.join(HERE, "..", "patterns", "uvm.txt")


class RegressTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.junit = os.path.join(self.tmp, "junit.xml")
        self._stdout = sys.stdout
        sys.stdout = open(os.devnull, "w")       # keep test output quiet

    def tearDown(self):
        sys.stdout.close()
        sys.stdout = self._stdout

    def run_regress(self, run, *extra, **kw):
        argv = ["--name", "blk", "--run", run, "--outdir", os.path.join(self.tmp, "out"),
                "--patterns", kw.get("patterns", DEFAULT), "--junit", self.junit,
                "--tests"] + list(kw.get("tests", ["t1"])) + list(extra)
        return regress.main(argv)

    def cases(self):
        root = ET.parse(self.junit).getroot()
        return {c.get("name"): c.find("failure") for c in root.iter("testcase")}

    # -- pass/fail rules ---------------------------------------------------
    def test_pass(self):
        self.assertEqual(self.run_regress("echo TEST PASSED"), 0)
        self.assertEqual(list(self.cases()), ["t1.seed1"])

    def test_no_pass_message_fails(self):
        self.assertEqual(self.run_regress("echo all good"), 1)

    def test_error_line_fails_even_with_pass_message(self):
        self.assertEqual(self.run_regress("echo 'ERROR: bad'; echo TEST PASSED"), 1)
        self.assertIn("ERROR: bad", self.cases()["t1.seed1"].get("message"))

    def test_nonzero_exit_fails(self):
        self.assertEqual(self.run_regress("echo TEST PASSED; exit 3"), 1)
        self.assertEqual(self.run_regress("echo TEST PASSED; exit 3", "--ignore-exit-code"), 0)

    def test_simulator_error_formats(self):
        for line in ["# ** Error: tb.sv(10): oops", "Error-[SE] Syntax error", "xmvlog: *E,EXPSMC (a.sv,1|2)",
                     "** Fatal: stop"]:
            self.assertEqual(self.run_regress("echo '%s'; echo TEST PASSED" % line), 1, line)

    def test_warnings_do_not_fail(self):
        self.assertEqual(self.run_regress("echo '# ** Warning: w'; echo 'xmsim: *W,ABC'; echo TEST PASSED"), 0)

    def test_ignore_patterns(self):
        pats = os.path.join(self.tmp, "p.txt")
        with open(pats, "w") as f:
            f.write("pass: TEST PASSED\nfail: ERROR\nignore: ERROR.*known issue 42\n")
        self.assertEqual(self.run_regress("echo 'ERROR: known issue 42'; echo TEST PASSED", patterns=pats), 0)

    def test_uvm_patterns(self):
        ok = "echo 'UVM_INFO @ 0: hi'; echo 'UVM_WARNING :    1'; echo 'UVM_ERROR :    0'; echo 'UVM_FATAL :    0'"
        self.assertEqual(self.run_regress(ok, patterns=UVM), 0)
        bad = "echo 'UVM_ERROR tb.sv(5) @ 10: scoreboard mismatch'; echo 'UVM_ERROR :    1'"
        self.assertEqual(self.run_regress(bad, patterns=UVM), 1)

    # -- running -----------------------------------------------------------
    def test_timeout_kills_whole_process_group(self):
        start = time.time()
        rc = self.run_regress("sleep 30 & sleep 30; echo TEST PASSED", "--timeout", "1")
        self.assertEqual(rc, 1)
        self.assertLess(time.time() - start, 15)
        self.assertIn("timeout", self.cases()["t1.seed1"].get("message"))

    def test_placeholders_env_and_rundir(self):
        rc = self.run_regress("[ \"$TEST\" = {test} ] && [ \"$SEED\" = {seed} ] && [ \"$PWD\" = {rundir} ] "
                              "&& echo TEST PASSED {block}", tests=["a", "b"], *["--seeds", "2"])
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(self.cases()), ["a.seed1", "a.seed2", "b.seed1", "b.seed2"])
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "out", "a_s2", "sim.log")))

    def test_shell_braces_are_left_alone(self):
        self.assertEqual(self.run_regress("X=ok; echo TEST PASSED ${X}"), 0)

    def test_seed_options(self):
        self.run_regress("echo TEST PASSED", "--seed", "77")
        self.assertEqual(list(self.cases()), ["t1.seed77"])
        self.run_regress("echo TEST PASSED", "--seeds", "2", "--base-seed", "10")
        self.assertEqual(sorted(self.cases()), ["t1.seed10", "t1.seed11"])
        self.run_regress("echo TEST PASSED", "--seeds", "3", "--random-seeds")
        self.assertEqual(len(self.cases()), 3)

    def test_only_failing_runs_fail(self):
        rc = self.run_regress("if [ {seed} = 2 ]; then echo 'ERROR: x'; fi; echo TEST PASSED", "--seeds", "3")
        self.assertEqual(rc, 1)
        failed = sorted(k for k, v in self.cases().items() if v is not None)
        self.assertEqual(failed, ["t1.seed2"])

    def test_parallel_runs(self):
        start = time.time()
        self.assertEqual(self.run_regress("sleep 1; echo TEST PASSED", "--seeds", "4", "--jobs", "4"), 0)
        self.assertLess(time.time() - start, 3.5)

    def test_compile_failure_reported_in_junit(self):
        rc = self.run_regress("echo TEST PASSED", "--compile", "echo 'syntax error'; exit 1")
        self.assertEqual(rc, 1)
        self.assertEqual(list(self.cases()), ["compile"])
        self.assertIsNotNone(self.cases()["compile"])

    def test_bad_pattern_file(self):
        pats = os.path.join(self.tmp, "p.txt")
        with open(pats, "w") as f:
            f.write("passes TEST\n")
        self.assertEqual(self.run_regress("echo TEST PASSED", patterns=pats), 2)


if __name__ == "__main__":
    unittest.main()
