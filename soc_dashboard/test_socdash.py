"""Tests for socdash.py. Run with: python3 -m unittest -v test_socdash"""
import csv
import json
import shutil
import tempfile
import sys
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
                             ["index.html", "lyra-soc-regression.html", "lyra-soc.html",
                              "nova-io-hub-regression.html", "nova-io-hub.html",
                              "orion-soc-regression.html", "orion-soc.html"])
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


def run_row(run, status, block="ddr_ctrl", inst="", ss="", test="t1", sig=""):
    return {"run_id": run, "date": socdash.dt.date(2026, 11, int(run[1:])), "block": block, "test": test,
            "seed": "1", "status": status, "duration_s": None, "signature": sig,
            "subsystem": ss, "instance": inst}


def tree_data(runs, subsystems=None):
    config = {"project": "P", "settings": dict(socdash.DEFAULT_SETTINGS),
              "block_subsystem": {b: ss for ss, bs in (subsystems or {}).items() for b in bs}}
    return {"config": config, "runs": runs}


class RegressionTreeTest(unittest.TestCase):
    def nodes(self, tree):
        return {n["id"]: n for n in tree["nodes"]}

    def test_rollup_counts_tests_at_every_level(self):
        runs = [
            run_row("r1", "PASS", inst="u_ddr0", ss="mem"), run_row("r2", "PASS", inst="u_ddr0", ss="mem"),
            run_row("r1", "PASS", inst="u_ddr1", ss="mem"), run_row("r2", "FAIL", inst="u_ddr1", ss="mem", sig="[X] bad"),
            run_row("r1", "FAIL", block="dma", inst="u_dma0", ss="mem"), run_row("r2", "PASS", block="dma", inst="u_dma0", ss="mem"),
        ]
        nodes = self.nodes(socdash.regression_tree(tree_data(runs)))
        mem, ddr, ddr1 = nodes["mem"], nodes["mem--ddr-ctrl"], nodes["mem--ddr-ctrl--u-ddr1"]
        self.assertEqual((mem["tests"], mem["tp"], mem["tf"]), (3, [2, 2], [1, 1]))
        self.assertEqual((ddr["tests"], ddr["tp"][-1], ddr["new_fail"], ddr["fixed"]), (2, 1, 1, 0))
        self.assertEqual((ddr1["new_fail"], ddr1["total"], ddr1["pass"]), (1, [1, 1], [1, 0]))
        self.assertEqual(nodes["mem--dma"]["fixed"], 1)
        self.assertEqual(nodes["all"]["children"], ["mem"])

    def test_one_failing_seed_fails_the_test_and_sims_still_count(self):
        runs = [run_row("r1", "PASS"), run_row("r1", "FAIL", sig="[X] e")]
        tree = socdash.regression_tree(tree_data(runs))
        top = self.nodes(tree)["all"]
        self.assertEqual((top["tp"], top["tf"], top["pass"], top["total"]), ([0], [1], [1], [2]))
        self.assertEqual(tree["tests"][0]["seeds"], "1/2")
        self.assertEqual(tree["tests"][0]["sig"], "[X] e")

    def test_config_subsystems_and_default_instance(self):
        runs = [run_row("r1", "PASS", block="uart"), run_row("r1", "PASS", block="gpio")]
        nodes = self.nodes(socdash.regression_tree(tree_data(runs, {"serial": ["uart"]})))
        self.assertIn("serial--uart--uart", nodes)  # instance defaults to the module name
        self.assertIn(socdash.node_slug((socdash.UNGROUPED, "gpio")), nodes)

    def test_not_run_since_and_never_passed(self):
        runs = [run_row("r1", "PASS", test="a"), run_row("r2", "FAIL", test="a"), run_row("r3", "FAIL", test="a"),
                run_row("r1", "PASS", test="gone"),
                run_row("r1", "FAIL", test="bad"), run_row("r2", "FAIL", test="bad"), run_row("r3", "FAIL", test="bad")]
        tree = socdash.regression_tree(tree_data(runs))
        tests = {t["test"]: t for t in tree["tests"]}
        self.assertEqual((tests["a"]["since"], tests["a"]["hist"]), ("r2", "PFF"))
        self.assertEqual((tests["gone"]["status"], tests["gone"]["hist"]), ("NOT RUN", "P--"))
        top = self.nodes(tree)["all"]
        self.assertEqual((top["not_run"], top["always_fail"]), (1, 1))

    def test_subsystem_listed_twice_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "config.json")
            path.write_text(json.dumps({"subsystems": {"a": ["x"], "b": ["x"]}}))
            with self.assertRaises(socdash.InputError) as ctx:
                socdash.load_config(path)
            self.assertIn("block 'x' is listed under both", str(ctx.exception))

    def test_build_writes_regression_page_beside_project_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp, "orion.html")
            self.assertEqual(socdash.main(["build", "--data", str(ORION), "--out", str(out)]), 0)
            reg = Path(tmp, "orion-regression.html").read_text()
            self.assertIn('"project":"orion.html"', reg)
            self.assertIn('"regression_href":"orion-regression.html"', out.read_text())


class OwnerTest(unittest.TestCase):
    def test_most_specific_scope_wins(self):
        owner = socdash.owner_lookup([{"owner": "A", "scope": "mem"}, {"owner": "B", "scope": "ddr/u1"},
                                      {"owner": "C", "scope": "ddr/u0/t9"}, {"owner": "D", "scope": "dma"}])
        self.assertEqual(owner("mem", "ddr", "u0", "t1"), "A")
        self.assertEqual(owner("mem", "ddr", "u1", "t1"), "B")
        self.assertEqual(owner("mem", "ddr", "u0", "t9"), "C")
        self.assertEqual(owner("mem", "dma", "u0", "t1"), "D")
        self.assertEqual(owner("io", "uart", "u0", "t1"), socdash.UNASSIGNED)

    def week_runs(self):
        # Week 1 ends 11-07 (runs on 11-06, 11-07), week 2 ends 11-14 (runs on 11-10, 11-14).
        rows = []
        for day, a, b in ((6, "PASS", "FAIL"), (7, "PASS", "FAIL"), (10, "FAIL", "PASS"), (14, "FAIL", "PASS")):
            rows.append(run_row(f"r{day}", a, block="ddr", inst="u0", ss="mem", test="ta"))
            rows.append(run_row(f"r{day}", b, block="ddr", inst="u1", ss="mem", test="tb"))
        rows.append(run_row("r14", "PASS", block="ddr", inst="u1", ss="mem", test="tnew"))
        for r in rows:
            r["date"] = socdash.dt.date(2026, 11, int(r["run_id"][1:]))
        return rows

    def test_weekly_progress_per_owner(self):
        data = tree_data(self.week_runs())
        data["config"]["settings"]["weeks"] = 3
        data["owners"] = [{"owner": "Asha", "scope": "mem"}, {"owner": "Elif", "scope": "ddr/u1"}]
        data["bugs"] = [{"block": "ddr", "opened": socdash.dt.date(2026, 11, 9), "closed": None, "owner": "Elif"},
                        {"block": "ddr", "opened": socdash.dt.date(2026, 11, 2), "closed": socdash.dt.date(2026, 11, 12),
                         "owner": ""}]
        tree = socdash.regression_tree(data)
        owners = tree["owners"]
        self.assertEqual([w["end"] for w in tree["weeks"]], ["2026-11-07", "2026-11-14"])  # empty week dropped
        self.assertEqual([w["s"] for w in tree["weeks"]], [None, 1])  # r7 is the last run before week 2
        by = {o["owner"]: o for o in owners["list"]}
        asha, elif_ = by["Asha"]["weeks"][1], by["Elif"]["weeks"][1]
        self.assertEqual((asha["tp_s"], asha["tp_e"], asha["new_fail"], asha["fixed"]), (1, 0, 1, 0))
        self.assertEqual((elif_["tp_s"], elif_["tp_e"], elif_["fixed"], elif_["added"]), (0, 2, 1, 1))
        self.assertEqual((elif_["sims"], elif_["sims_pass"]), (3, 3))
        self.assertEqual((elif_["bug_opened"], elif_["bug_unresolved"]), (1, 1))
        self.assertEqual((asha["bug_closed"], asha["bug_unresolved"]), (1, 0))

    def test_owner_file_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp, "p")
            shutil.copytree(ORION, proj)
            (proj / "owners.csv").write_text("owner,scope\nAsha,ddr_ctl\n")
            with self.assertRaises(socdash.InputError) as ctx:
                socdash.load(proj)
            self.assertIn("owners.csv:2: scope 'ddr_ctl' matches no", str(ctx.exception))
            (proj / "owners.csv").write_text("owner,scope\nAsha,ddr_ctrl\nBen,ddr_ctrl\n")
            with self.assertRaises(socdash.InputError) as ctx:
                socdash.load(proj)
            self.assertIn("already owned by Asha", str(ctx.exception))

    def test_projects_without_owners_have_no_owner_view(self):
        tree = socdash.regression_tree(socdash.load(HERE / "projects" / "nova_io_hub"))
        self.assertIsNone(tree["owners"])
        self.assertEqual({t["o"] for t in tree["tests"]}, {""})


D = socdash.dt.date


class ProgressTest(unittest.TestCase):
    def dates(self, n):
        return [D(2026, 11, 1) + socdash.dt.timedelta(days=i) for i in range(n)]

    def test_forecast_statuses(self):
        days = self.dates(10)
        rising = [0.70 + 0.01 * i for i in range(10)]  # +7 points a week, 0.79 now
        f = socdash.forecast(days, rising, 0.90, D(2026, 11, 30), 10)
        self.assertEqual(f["status"], "on_track")
        self.assertEqual(f["eta"], "2026-11-21")  # 11 more points at 1 point a day
        self.assertEqual(socdash.forecast(days, rising, 0.90, D(2026, 11, 15), 10)["status"], "at_risk")
        self.assertEqual(socdash.forecast(days, rising, 0.90, None, 10)["status"], "projected")
        self.assertEqual(socdash.forecast(days, [0.8] * 10, 0.9, None, 10)["status"], "stalled")
        self.assertEqual(socdash.forecast(days, [0.5] * 7 + [0.95, 0.96, 0.97], 0.95, None, 10)["status"], "met")
        # One good run on its own is not "met": the last three must average at the bar.
        self.assertNotEqual(socdash.forecast(days, [0.8] * 9 + [0.99], 0.95, None, 10)["status"], "met")
        self.assertEqual(socdash.forecast(days[:2], rising[:2], 0.9, None, 10)["status"], "unknown")
        self.assertEqual(socdash.forecast(days, [None] * 10, 0.9, None, 10)["status"], "unknown")

    def test_run_weeks_and_fail_age(self):
        days = [D(2026, 11, d) for d in (2, 6, 9, 13, 14)]
        weeks = socdash.run_weeks(days, D(2026, 11, 14), 3)
        self.assertEqual([(w["end"], w["s"], w["e"], w["runs"]) for w in weeks],
                         [("2026-11-07", None, 1, 2), ("2026-11-14", 1, 4, 3)])  # the empty week is dropped
        status = {0: "PASS", 1: "FAIL", 3: "FAIL", 4: "TIMEOUT"}  # run 2 skipped
        self.assertEqual(socdash.fail_age(status, 4, days), 8)  # failing since Nov 6
        self.assertIsNone(socdash.fail_age(status, 0, days))

    def test_coverage_trend_carries_blocks_forward(self):
        hist = [{"date": D(2026, 11, 1), "block": "a", "metric": "line", "covered": 50, "total": 100, "target": 90},
                {"date": D(2026, 11, 1), "block": "b", "metric": "line", "covered": 80, "total": 100, "target": 90},
                {"date": D(2026, 11, 8), "block": "a", "metric": "line", "covered": 70, "total": 100, "target": 90}]
        tr = socdash.coverage_trend(hist)
        self.assertEqual([round(p["metrics"]["line"]["pct"]) for p in tr], [65, 75])  # b's Nov 1 value still counts
        self.assertIsNone(socdash.coverage_trend(hist[:2]))

    def test_testplan_trend(self):
        items = [{"id": "t1", "status": "passing"}, {"id": "t2", "status": "written"}, {"id": "t3", "status": "planned"}]
        hist = [{"date": D(2026, 11, 2), "id": "t1", "status": "written"},
                {"date": D(2026, 11, 9), "id": "t1", "status": "passing"},
                {"date": D(2026, 11, 9), "id": "t2", "status": "written"}]
        tr = socdash.testplan_trend(items, hist, D(2026, 11, 14), 3)
        self.assertEqual([(p["planned"], p["written"], p["passing"]) for p in tr], [(3, 0, 0), (2, 1, 0), (1, 1, 1)])
        self.assertIsNone(socdash.testplan_trend(items, [], D(2026, 11, 14), 3))

    def test_fix_speed(self):
        bugs = [{"severity": "S1", "status": "closed", "opened": D(2026, 11, 1), "closed": D(2026, 11, 5)},
                {"severity": "S1", "status": "closed", "opened": D(2026, 11, 1), "closed": D(2026, 11, 11)},
                {"severity": "S1", "status": "open", "opened": D(2026, 11, 2), "closed": None}]
        s1 = socdash.fix_speed(bugs, D(2026, 11, 14))[0]
        self.assertEqual((s1["closed"], s1["median"], s1["open"], s1["oldest_open"]), (2, 10, 1, 12))

    def test_owner_targets_and_coverage_reach_owner_weeks(self):
        tree = socdash.regression_tree(socdash.load(ORION))
        asha = next(o for o in tree["owners"]["list"] if o["owner"] == "Asha")
        last = asha["weeks"][-1]
        self.assertIsNotNone(last["target"])
        self.assertIsNotNone(last["cov_e"])
        self.assertIn(asha["forecast"]["status"], ("met", "on_track", "at_risk", "stalled", "projected", "unknown"))

    def test_optional_file_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp, "p")
            shutil.copytree(ORION, proj)
            (proj / "owner_targets.csv").write_text("owner,week_end,target_passing\nZed,2026-11-21,4\n")
            with self.assertRaises(socdash.InputError) as ctx:
                socdash.load(proj)
            self.assertIn("owner 'Zed' is not in owners.csv", str(ctx.exception))
            (proj / "owner_targets.csv").unlink()
            (proj / "testplan_history.csv").write_text("date,id,status\n2026-11-01,TP-999,written\n")
            with self.assertRaises(socdash.InputError) as ctx:
                socdash.load(proj)
            self.assertIn("id 'TP-999' is not in the testplan", str(ctx.exception))

    def test_undated_coverage_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp, "p")
            shutil.copytree(ORION, proj)
            (proj / "coverage.csv").write_text("block,metric,covered,total,target_pct\nddr_ctrl,line,90,100,98\n")
            payload = socdash.build_payload(socdash.load(proj))
            self.assertIsNone(payload["scopes"]["all"]["coverage_trend"])
            self.assertEqual(payload["scopes"]["all"]["coverage"]["cells"], 1)

    def test_overview_lists_owners_across_projects(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp, "site")
            socdash.build_all(HERE / "projects", out, "P")
            html = (out / "index.html").read_text()
            self.assertIn('"owners":[{"owner":', html)
            self.assertIn('"forecast":{"status":', html)


class SafetyTest(unittest.TestCase):
    """Static guarantees about the generated pages. checks/browser_safety_check.js proves the
    same things in a real browser, including that hostile names never run."""

    TEMPLATES = sorted((HERE / "templates").glob("*.html")) + [HERE / "templates" / "viz.js"]

    def test_no_external_scripts_or_network_calls(self):
        import re
        for path in self.TEMPLATES:
            text = path.read_text()
            self.assertIsNone(re.search(r"<script[^>]+src=", text), f"{path.name} loads an external script")
            for banned in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "EventSource", "eval(", "new Function", "document.write"):
                self.assertNotIn(banned, text, f"{path.name} uses {banned}")
            links = re.findall(r"https?://[^\s\"')]+", text)
            self.assertTrue(all("fonts.googleapis.com" in u or "w3.org/2000/svg" in u for u in links),
                            f"{path.name} links outside Google Fonts: {links}")

    def test_palette_builds_results_as_text(self):
        text = (HERE / "templates" / "regression.html").read_text()
        palette = text[text.index("var Palette = (function"):text.index("window.addEventListener(\"hashchange\"")]
        self.assertNotIn("innerHTML", palette)
        self.assertIn("textContent", palette)

    def test_hostile_names_are_escaped_in_built_pages(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            out = subprocess.run([sys.executable, str(HERE / "checks" / "make_hostile_project.py"), tmp],
                                 capture_output=True, text=True)
            self.assertEqual(out.returncode, 0, out.stderr)
            site = Path(tmp, "site")
            for page in site.glob("*.html"):
                html = page.read_text()
                # Only the page's own two script blocks close; payloads inside data are escaped.
                self.assertEqual(html.count("</script>"), 2, page.name)
                self.assertNotIn('<img src=x onerror="window.__pwned=1">', html.split('<script type="application/json"')[0])


class CollectLayoutTest(unittest.TestCase):
    def test_layout_fills_subsystem_and_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp, "logs")
            (logs / "memory_ss" / "ddr_ctrl" / "u_ddr1").mkdir(parents=True)
            (logs / "memory_ss" / "ddr_ctrl" / "u_ddr1" / "a.log").write_text(FAIL_LOG)
            out = Path(tmp, "runs.csv")
            socdash.collect(logs, "n1", "2026-11-21", out, None, "*.log", "subsystem/block/instance")
            with out.open() as f:
                row = next(csv.DictReader(f))
            self.assertEqual((row["subsystem"], row["block"], row["instance"], row["status"]),
                             ("memory_ss", "ddr_ctrl", "u_ddr1", "FAIL"))

    def test_layout_needs_matching_header_and_valid_levels(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = Path(tmp, "logs")
            (logs / "ss" / "blk").mkdir(parents=True)
            (logs / "ss" / "blk" / "a.log").write_text(PASS_LOG)
            out = Path(tmp, "runs.csv")
            out.write_text(",".join(socdash.REGRESSION_COLS) + "\n")
            with self.assertRaises(socdash.InputError) as ctx:
                socdash.collect(logs, "n1", "2026-11-21", out, None, "*.log", "subsystem/block")
            self.assertIn("lacks column(s) subsystem", str(ctx.exception))
            with self.assertRaises(socdash.InputError):
                socdash.collect(logs, "n1", "2026-11-21", out, None, "*.log", "subsystem/module")


if __name__ == "__main__":
    unittest.main()
