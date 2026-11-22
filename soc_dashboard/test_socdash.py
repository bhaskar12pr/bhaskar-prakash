"""Tests for socdash.py. Run with: python3 -m unittest -v test_socdash"""
import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import socdash

HERE = Path(__file__).resolve().parent
ORION = HERE / "projects" / "orion_soc"

PASS_LOG = """\
UVM_INFO @ 0: reporter [RNTST] Running test mux4to1_exhaustive...
+ntb_random_seed=12345
--- UVM Report Summary ---
UVM_INFO :   42
UVM_WARNING :    0
UVM_ERROR :    0
UVM_FATAL :    0
CPU Time:     12.500 seconds;
"""

FAIL_LOG = """\
+UVM_TESTNAME=ecc_double_bit +ntb_random_seed=99
UVM_ERROR /tb/ecc_sb.sv(88) @ 15400 ns: uvm_test_top.env.sb [ECC_CHK] double-bit error not flagged addr=0x1f40
UVM_ERROR /tb/ecc_sb.sv(88) @ 15800 ns: uvm_test_top.env.sb [ECC_CHK] double-bit error not flagged addr=0x2000
--- UVM Report Summary ---
UVM_ERROR :    2
UVM_FATAL :    0
"""

TIMEOUT_LOG = """\
+UVM_TESTNAME=completion_timeout
UVM_FATAL /uvm/base/uvm_phase.svh(1491) @ 9200000000 ps: reporter [PH_TIMEOUT] Explicit timeout of 9200000000 hit, indicating a probable testbench issue
--- UVM Report Summary ---
UVM_ERROR :    0
UVM_FATAL :    1
"""

CRASH_LOG = "+UVM_TESTNAME=link_up_gen4\nSegmentation fault (core dumped)\n"


class ParseLogTest(unittest.TestCase):
    def test_pass(self):
        r = socdash.parse_log(PASS_LOG)
        self.assertEqual((r["test"], r["seed"], r["status"], r["duration_s"], r["signature"]),
                         ("mux4to1_exhaustive", "12345", "PASS", "12.500", ""))

    def test_fail_uses_first_error_with_numbers_normalized(self):
        r = socdash.parse_log(FAIL_LOG)
        self.assertEqual(r["status"], "FAIL")
        self.assertEqual(r["test"], "ecc_double_bit")
        self.assertEqual(r["signature"], "[ECC_CHK] double-bit error not flagged addr=<HEX>")

    def test_timeout(self):
        r = socdash.parse_log(TIMEOUT_LOG)
        self.assertEqual(r["status"], "TIMEOUT")
        self.assertTrue(r["signature"].startswith("[PH_TIMEOUT] Explicit timeout of <N>"))

    def test_missing_summary_is_error(self):
        r = socdash.parse_log(CRASH_LOG)
        self.assertEqual(r["status"], "ERROR")


class CollectTest(unittest.TestCase):
    def test_collect_appends_rows_with_block_from_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp, "logs")
            (logs / "io_mux").mkdir(parents=True)
            (logs / "ddr_ctrl").mkdir()
            (logs / "io_mux" / "a.log").write_text(PASS_LOG)
            (logs / "ddr_ctrl" / "b.log").write_text(FAIL_LOG)
            out = Path(tmp, "runs.csv")
            self.assertEqual(socdash.collect(logs, "n1", "2026-11-21", out, None, "*.log"), 2)
            socdash.collect(logs, "n2", "2026-11-22", out, None, "*.log")
            with out.open() as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 4)
            self.assertEqual({(r["block"], r["status"]) for r in rows},
                             {("io_mux", "PASS"), ("ddr_ctrl", "FAIL")})


class AnalysisTest(unittest.TestCase):
    def setUp(self):
        self.data = socdash.load(ORION)

    def test_intermittent_needs_both_outcomes(self):
        order = [("r1", None), ("r2", None), ("r3", None)]
        runs = [{"run_id": r, "block": "b", "test": "t", "status": s}
                for r, s in (("r1", "PASS"), ("r2", "FAIL"), ("r3", "PASS"))]
        runs += [{"run_id": r, "block": "b", "test": "solid", "status": "FAIL"} for r in ("r1", "r2", "r3")]
        out = socdash.intermittent_tests(runs, order)
        self.assertEqual([(t["test"], t["fails"]) for t in out], [("t", 1)])

    def test_any_failing_seed_fails_the_run(self):
        order = [("r1", None), ("r2", None)]
        runs = [{"run_id": "r1", "block": "b", "test": "t", "status": s} for s in ("FAIL", "PASS")]
        runs.append({"run_id": "r2", "block": "b", "test": "t", "status": "PASS"})
        self.assertEqual(socdash.intermittent_tests(runs, order)[0]["history"], ["FAIL", "PASS"])

    def test_signoff_counts_fixed_bugs_as_unresolved(self):
        config = {"milestones": [{"name": "M", "criteria": {"max_unresolved_bugs": {"S1": 0}}}]}
        bugs = [{"severity": "S1", "status": "fixed"}]
        self.assertFalse(socdash.signoff(config, 1.0, [], bugs, [])[0]["met"])
        bugs = [{"severity": "S1", "status": "closed"}]
        self.assertTrue(socdash.signoff(config, 1.0, [], bugs, [])[0]["met"])

    def test_signoff_testplan_includes_earlier_milestones(self):
        config = {"milestones": [{"name": "A", "criteria": {}},
                                 {"name": "B", "criteria": {"min_testplan_passing": 1.0}}]}
        plan = [{"milestone": "A", "status": "written"}, {"milestone": "B", "status": "passing"}]
        self.assertFalse(socdash.signoff(config, 1.0, [], [], plan)[1]["met"])

    def test_coverage_scale(self):
        cells = [{"block": "b", "metric": "line", "covered": 90, "total": 100, "target": 98}]
        config = {"milestones": [{"name": "lo", "criteria": {"coverage_target_scale": 0.9}},
                                 {"name": "hi", "criteria": {"coverage_target_scale": 1.0}}]}
        lo, hi = socdash.signoff(config, None, cells, [], [])
        self.assertTrue(lo["checks"][0]["ok"])
        self.assertFalse(hi["checks"][0]["ok"])

    def test_block_scopes_partition_the_whole(self):
        payload = socdash.build_payload(self.data)
        total = payload["scopes"]["all"]["trend"][-1]["total"]
        self.assertEqual(sum(payload["scopes"][b]["trend"][-1]["total"] for b in payload["blockList"]), total)


class BuildTest(unittest.TestCase):
    def test_build_writes_html_and_signoff_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp, "d.html")
            self.assertEqual(socdash.main(["build", "--data", str(ORION), "--out", str(out)]), 0)
            html = out.read_text()
            self.assertTrue(html.startswith("<!doctype html>"))
            self.assertNotIn("__SOCDASH_DATA__", html)
            # The sample project has not met DV 0.8, so CI gating must fail.
            self.assertEqual(socdash.main(["build", "--data", str(ORION), "--out", str(out),
                                           "--fail-on-signoff"]), 2)

    def test_bad_input_reports_file_and_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp, "data")
            shutil.copytree(ORION, data)
            p = data / "bugs.csv"
            lines = p.read_text().splitlines()
            lines[1] = lines[1].replace(",S", ",S9", 1)
            p.write_text("\n".join(lines) + "\n")
            with self.assertRaises(socdash.InputError) as ctx:
                socdash.load(data)
            self.assertIn("bugs.csv:2", str(ctx.exception))

    def test_script_tag_cannot_be_closed_by_data(self):
        payload = socdash.build_payload(socdash.load(ORION))
        payload["project"] = "x</script><b>"
        html = socdash.render(payload)
        self.assertEqual(html.count("</script>"), 2)


class MultiProjectTest(unittest.TestCase):
    def make_projects(self, tmp):
        root = Path(tmp, "projects")
        root.mkdir()
        for name in ("orion_soc", "lyra_soc", "nova_io_hub"):
            shutil.copytree(HERE / "projects" / name, root / name)
        (root / "not_a_project").mkdir()  # no config.json: ignored
        return root

    def test_discover_only_folders_with_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_projects(tmp)
            self.assertEqual([p.name for p in socdash.discover_projects(root)],
                             ["lyra_soc", "nova_io_hub", "orion_soc"])

    def test_build_all_writes_overview_and_one_page_per_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, out = self.make_projects(tmp), Path(tmp, "site")
            self.assertEqual(socdash.build_all(root, out, "Portfolio"), 0)
            self.assertEqual(sorted(p.name for p in out.iterdir()),
                             ["index.html", "lyra-soc.html", "nova-io-hub.html", "orion-soc.html"])
            self.assertIn('"home":"index.html"', (out / "orion-soc.html").read_text())
            index = (out / "index.html").read_text()
            for name in ("Orion SoC", "Lyra SoC", "Nova IO Hub", "orion-soc.html"):
                self.assertIn(name, index)
            # Orion and Lyra have not met their current milestone.
            self.assertEqual(socdash.build_all(root, out, "Portfolio", fail_on_signoff=True), 2)

    def test_broken_project_is_reported_but_others_still_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, out = self.make_projects(tmp), Path(tmp, "site")
            (root / "lyra_soc" / "coverage.csv").unlink()
            self.assertEqual(socdash.build_all(root, out, "Portfolio"), 1)
            self.assertTrue((out / "orion-soc.html").exists())
            self.assertFalse((out / "lyra-soc.html").exists())
            self.assertIn("coverage.csv: file not found", (out / "index.html").read_text())

    def test_config_files_override_renames_inputs(self):
        data = socdash.load(HERE / "projects" / "nova_io_hub")  # uses nightly_results.csv
        self.assertTrue(data["runs"])
        self.assertEqual(data["config"]["files"]["regression"], "nightly_results.csv")

    def test_config_settings_reach_the_page(self):
        payload = socdash.build_payload(socdash.load(HERE / "projects" / "lyra_soc"))
        self.assertEqual(payload["window"], 10)
        self.assertEqual(len(payload["scopes"]["all"]["bugs"]["trend"]), 12)

    def test_config_errors(self):
        cases = [
            ({"files": {"regresion": "x.csv"}}, "unknown key(s) in \"files\": regresion"),
            ({"settings": {"window": 5}}, "unknown key(s) in \"settings\": window"),
            ({"current_milestone": "DV 2", "milestones": [{"name": "DV 1"}]}, "current_milestone 'DV 2'"),
            ({"milestones": [{"name": "A"}, {"name": "A"}]}, "unique"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "config.json")
            for config, message in cases:
                path.write_text(json.dumps(config))
                with self.assertRaises(socdash.InputError) as ctx:
                    socdash.load_config(path)
                self.assertIn(message, str(ctx.exception))
            path.write_text("{")
            with self.assertRaises(socdash.InputError):
                socdash.load_config(path)

    def test_project_name_defaults_to_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "my_chip", "config.json")
            path.parent.mkdir()
            path.write_text("{}")
            self.assertEqual(socdash.load_config(path)["project"], "my_chip")


if __name__ == "__main__":
    unittest.main()
