#!/usr/bin/env python3
"""Write deterministic example projects to projects/<name>/ for three fictional SoCs.

Each project gets its own folder with config.json and the four CSV files. Replace
them with your own data; the formats are described in README.md. Re-running this
script overwrites the sample folders.
"""
import csv
import datetime as dt
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "projects"
AS_OF = dt.date(2026, 11, 21)
METRIC_TARGETS = {"line": 98, "branch": 95, "toggle": 95, "fsm": 100, "assertion": 100, "functional": 100}
METRIC_SIZES = {"line": 9000, "branch": 4200, "toggle": 26000, "fsm": 160, "assertion": 300, "functional": 1400}
TIMEOUT_SIG = "[PH_TIMEOUT] Explicit timeout of <N> hit, indicating a probable testbench issue"
CRASH_SIG = "no UVM report summary (crash or killed)"


# --------------------------------------------------------------------------- project specs
# blocks: name -> dict(tests, start, floor, timeout_share, lag, features, sigs)
#   start/floor: fail probability in the first and the last run
#   lag: percentage points behind coverage target; also lowers testplan maturity

ORION = {
    "folder": "orion_soc", "seed": 20261121, "runs": 14, "seeds_per_test": 2, "maturity": 0.0,
    "blocks": {
        "cpu_cluster": dict(tests=["smoke_boot", "cache_coherency", "mmu_walk", "irq_latency", "wfi_wakeup",
                                   "atomic_ops", "debug_halt", "l2_ecc_inject", "branch_pred_stress", "multi_core_sync"],
                            start=0.22, floor=0.02, timeout_share=0.10, lag=1.5,
                            features=["Boot and reset", "Cache coherency", "Interrupts", "Debug"],
                            sigs=["[COH_SCB] snoop response mismatch line=<HEX> exp=<HEX> act=<HEX>",
                                  "[IRQ_LAT] interrupt latency <N> cycles exceeds limit <N>"]),
        "noc_fabric": dict(tests=["route_all_to_all", "qos_arbitration", "deadlock_stress", "backpressure",
                                  "addr_decode_err", "outstanding_max"],
                           start=0.25, floor=0.03, timeout_share=0.30, lag=2.5,
                           features=["Routing", "QoS", "Error handling"],
                           sigs=["[NOC_ORDER] response reordered on port <N> id=<N>", TIMEOUT_SIG]),
        "ddr_ctrl": dict(tests=["init_training", "refresh_timing", "bank_interleave", "ecc_single_bit",
                                "ecc_double_bit", "self_refresh_exit", "rw_turnaround", "power_down",
                                "phy_calib", "row_hammer_mitigation"],
                         start=0.45, floor=0.10, timeout_share=0.15, lag=9,
                         features=["Initialization and training", "Refresh and power", "ECC", "Performance"],
                         sigs=["[ECC_CHK] double-bit error not flagged addr=<HEX>",
                               "[DFI_TIMING] tRFC violated by <N> cycles on rank <N>",
                               "[DDR_SCB] read data mismatch addr=<HEX> exp=<HEX> act=<HEX>"]),
        "pcie_ctrl": dict(tests=["link_up_gen4", "ltssm_recovery", "msix_interrupts", "tlp_ordering",
                                 "completion_timeout", "aer_errors", "aspm_l1"],
                          start=0.35, floor=0.06, timeout_share=0.55, lag=6,
                          features=["Link training", "Transaction layer", "Error reporting", "Power management"],
                          sigs=[TIMEOUT_SIG, "[LTSSM] stuck in Recovery.RcvrLock for <N> us",
                                "[TLP_ORDER] posted write passed non-posted read tag=<N>"]),
        "usb3_ctrl": dict(tests=["enum_hs", "enum_ss", "bulk_xfer", "iso_xfer", "u1_u2_lpm", "hot_plug"],
                          start=0.20, floor=0.02, timeout_share=0.20, lag=3,
                          features=["Enumeration", "Transfers", "Link power"],
                          sigs=["[USB_PROTO] unexpected NYET in SS bulk transfer ep=<N>"]),
        "dma_engine": dict(tests=["mem2mem_basic", "scatter_gather", "chained_desc", "abort_midflight",
                                  "parallel_channels", "unaligned_xfer"],
                           start=0.18, floor=0.01, timeout_share=0.10, lag=1,
                           features=["Descriptors", "Channels", "Error handling"],
                           sigs=["[DMA_SCB] descriptor <N> byte count mismatch exp=<N> act=<N>"]),
        "io_mux": dict(tests=["pinmux_sel_all", "mux4to1_exhaustive", "pad_drive_strength", "alt_func_switch"],
                       start=0.10, floor=0.0, timeout_share=0.0, lag=0, small=True,
                       features=["Pin selection", "Electrical"],
                       sigs=["[MUX_CHK] ow mismatch s=<N> i=<HEX> exp=<N> act=<N>"]),
        "sec_crypto": dict(tests=["aes_kat", "sha256_kat", "key_ladder", "tamper_response",
                                  "secure_boot_verify", "side_channel_mask"],
                           start=0.20, floor=0.03, timeout_share=0.05, lag=2,
                           features=["Ciphers", "Key management", "Tamper"],
                           sigs=["[AES_KAT] ciphertext mismatch vector=<N>",
                                 "[TAMPER] alert not raised within <N> cycles"]),
    },
    "sticky": {("ddr_ctrl", "ecc_double_bit"): 0, ("pcie_ctrl", "completion_timeout"): 0},
    "flaky": {("noc_fabric", "deadlock_stress"): 0.45, ("usb3_ctrl", "u1_u2_lpm"): 0.3,
              ("ddr_ctrl", "phy_calib"): 0.35, ("cpu_cluster", "multi_core_sync"): 0.25},
    "bugs": [
        # id, block, severity, status, opened (days before AS_OF), closed (days before) or None, title
        ("DV-101", "ddr_ctrl", "S1", "open", 9, None, "ECC decoder does not flag double-bit errors on burst chop"),
        ("DV-102", "pcie_ctrl", "S1", "open", 6, None, "Completion timeout leaves non-posted queue blocked"),
        ("DV-103", "ddr_ctrl", "S2", "open", 12, None, "tRFC not honoured after self-refresh exit at 3200 MT/s"),
        ("DV-104", "pcie_ctrl", "S2", "fixed", 10, None, "LTSSM hangs in Recovery.RcvrLock after speed change"),
        ("DV-105", "noc_fabric", "S2", "open", 4, None, "Responses reorder across VCs under QoS starvation"),
        ("DV-106", "sec_crypto", "S2", "fixed", 8, None, "Tamper alert delayed by one clock domain crossing"),
        ("DV-107", "usb3_ctrl", "S2", "open", 3, None, "U2 exit latency exceeds spec when LPM and remote wake overlap"),
        ("DV-108", "cpu_cluster", "S2", "closed", 30, 18, "Snoop filter evicts dirty line without writeback"),
        ("DV-109", "dma_engine", "S2", "closed", 26, 15, "Chained descriptor drops last beat on 4KB boundary"),
        ("DV-110", "ddr_ctrl", "S1", "closed", 40, 20, "Read data corruption with bank group interleave"),
        ("DV-111", "pcie_ctrl", "S1", "closed", 33, 22, "MSI-X table writes ignored after function level reset"),
        ("DV-112", "cpu_cluster", "S3", "open", 7, None, "PMU counter overflow interrupt fires one event late"),
        ("DV-113", "noc_fabric", "S3", "open", 11, None, "Decode error response returns wrong ID width"),
        ("DV-114", "ddr_ctrl", "S3", "open", 5, None, "Power-down entry blocked by idle refresh counter"),
        ("DV-115", "usb3_ctrl", "S3", "fixed", 9, None, "Isochronous packet counter wraps early"),
        ("DV-116", "sec_crypto", "S3", "open", 2, None, "Key ladder status register reads stale value"),
        ("DV-117", "dma_engine", "S3", "open", 6, None, "Abort status not cleared on channel re-enable"),
        ("DV-118", "pcie_ctrl", "S3", "open", 1, None, "AER header log captures wrong TLP prefix"),
        ("DV-119", "io_mux", "S3", "closed", 21, 19, "mux4to1 missing default branch infers a latch"),
        ("DV-120", "io_mux", "S4", "closed", 21, 19, "Pinmux register reset value differs from spec table"),
        ("DV-121", "cpu_cluster", "S4", "open", 4, None, "Debug halt reason code undocumented value 0x7"),
        ("DV-122", "noc_fabric", "S4", "closed", 18, 12, "QoS register field naming mismatch"),
    ],
    "history_bugs": 24,
    "config": {
        "project": "Orion SoC",
        "current_milestone": "DV 0.8",
        "milestones": [
            {"name": "DV 0.5", "date": "2026-10-16",
             "criteria": {"min_pass_rate": 0.70, "coverage_target_scale": 0.5,
                          "max_unresolved_bugs": {"S1": 3}, "min_testplan_written": 0.8}},
            {"name": "DV 0.8", "date": "2026-12-11",
             "criteria": {"min_pass_rate": 0.90, "coverage_target_scale": 0.9,
                          "max_unresolved_bugs": {"S1": 0, "S2": 5}, "min_testplan_written": 0.95,
                          "min_testplan_passing": 0.8}},
            {"name": "DV 1.0", "date": "2027-02-05",
             "criteria": {"min_pass_rate": 0.98, "coverage_target_scale": 1.0,
                          "max_unresolved_bugs": {"S1": 0, "S2": 0, "S3": 3}, "min_testplan_written": 1.0,
                          "min_testplan_passing": 1.0}},
        ],
    },
}

LYRA = {
    "folder": "lyra_soc", "seed": 7311, "runs": 21, "seeds_per_test": 3, "maturity": 0.8,
    "blocks": {
        "cpu_cluster": dict(tests=["smoke_boot", "cache_coherency", "irq_routing", "dvfs_switch", "secure_world_entry"],
                            start=0.08, floor=0.01, timeout_share=0.1, lag=0.4,
                            features=["Boot and reset", "Coherency", "Power states"],
                            sigs=["[COH_SCB] snoop response mismatch line=<HEX> exp=<HEX> act=<HEX>"]),
        "gpu_core": dict(tests=["shader_alu", "texture_fetch", "raster_tiles", "compute_dispatch", "mmu_fault"],
                         start=0.18, floor=0.03, timeout_share=0.35, lag=2.2,
                         features=["Shader", "Texture", "Rasterizer", "Memory"],
                         sigs=["[GPU_SCB] pixel mismatch tile=<N> x=<N> y=<N>", TIMEOUT_SIG]),
        "isp_pipeline": dict(tests=["bayer_demosaic", "auto_white_balance", "hdr_merge", "lens_shading", "scaler_bypass"],
                             start=0.12, floor=0.01, timeout_share=0.1, lag=1.2,
                             features=["Front end", "Color", "HDR", "Output"],
                             sigs=["[ISP_REF] frame CRC mismatch frame=<N> exp=<HEX> act=<HEX>"]),
        "lpddr5_ctrl": dict(tests=["init_training", "wck_sync", "refresh_per_bank", "link_ecc", "dvfsc_switch"],
                            start=0.15, floor=0.02, timeout_share=0.2, lag=1.6,
                            features=["Training", "Refresh", "Link ECC"],
                            sigs=["[LP5_TIMING] tWCKPRE violated by <N> cycles"]),
        "mipi_csi": dict(tests=["lane_deskew", "virtual_channels", "crc_error_inject", "ulps_entry_exit"],
                         start=0.10, floor=0.0, timeout_share=0.1, lag=0.5,
                         features=["PHY", "Protocol"],
                         sigs=["[CSI_PKT] ECC header error not reported vc=<N>"]),
        "pmu": dict(tests=["power_domain_seq", "retention_save_restore", "wakeup_sources", "brownout"],
                    start=0.10, floor=0.0, timeout_share=0.1, lag=0.3, small=True,
                    features=["Sequencing", "Wakeup"],
                    sigs=["[PMU_SEQ] domain <N> isolation released before power good"]),
    },
    "sticky": {},
    "flaky": {("gpu_core", "compute_dispatch"): 0.15},
    "bugs": [
        ("LY-201", "gpu_core", "S2", "open", 5, None, "Compute dispatch hangs when workgroup size is 1024"),
        ("LY-202", "lpddr5_ctrl", "S2", "fixed", 8, None, "Link ECC syndrome dropped during DVFSC switch"),
        ("LY-203", "isp_pipeline", "S3", "open", 4, None, "HDR merge clips highlights one LSB early"),
        ("LY-204", "gpu_core", "S3", "open", 3, None, "MMU fault address register misses upper bits"),
        ("LY-205", "pmu", "S4", "open", 2, None, "Wakeup source status bits not sticky as documented"),
        ("LY-206", "cpu_cluster", "S1", "closed", 26, 9, "Secure world entry leaks non-secure cache lines"),
        ("LY-207", "mipi_csi", "S2", "closed", 19, 11, "Lane deskew fails with 4-lane, 2.5 Gbps"),
    ],
    "history_bugs": 40,
    "config": {
        "project": "Lyra SoC",
        "current_milestone": "DV 1.0",
        "settings": {"intermittent_window": 10, "bug_trend_weeks": 12},
        "milestones": [
            {"name": "DV 0.8", "date": "2026-10-30",
             "criteria": {"min_pass_rate": 0.90, "coverage_target_scale": 0.9,
                          "max_unresolved_bugs": {"S1": 0, "S2": 5}, "min_testplan_passing": 0.8}},
            {"name": "DV 1.0", "date": "2026-12-04",
             "criteria": {"min_pass_rate": 0.97, "coverage_target_scale": 0.98,
                          "max_unresolved_bugs": {"S1": 0, "S2": 1}, "min_testplan_written": 1.0,
                          "min_testplan_passing": 0.95}},
        ],
    },
}

NOVA = {
    "folder": "nova_io_hub", "seed": 99, "runs": 10, "seeds_per_test": 4, "maturity": 0.6,
    "blocks": {
        "i2c_ctrl": dict(tests=["std_mode", "fast_mode_plus", "clock_stretch", "arbitration_loss"],
                         start=0.06, floor=0.0, timeout_share=0.0, lag=0, small=True,
                         features=["Protocol", "Multi-master"], sigs=["[I2C_MON] NACK not detected addr=<HEX>"]),
        "spi_ctrl": dict(tests=["mode0_3", "quad_io", "cs_gap_timing"],
                         start=0.05, floor=0.0, timeout_share=0.0, lag=0, small=True,
                         features=["Modes", "Timing"], sigs=["[SPI_SCB] MISO data mismatch byte=<N>"]),
        "uart": dict(tests=["baud_sweep", "parity_errors", "flow_control"],
                     start=0.04, floor=0.0, timeout_share=0.0, lag=0, small=True,
                     features=["Framing", "Flow control"], sigs=["[UART_CHK] framing error not flagged"]),
        "gpio_mux": dict(tests=["mux4to1_exhaustive", "irq_edge_level", "debounce"],
                         start=0.05, floor=0.0, timeout_share=0.0, lag=0, small=True,
                         features=["Pin mux", "Interrupts"], sigs=["[MUX_CHK] ow mismatch s=<N> i=<HEX> exp=<N> act=<N>"]),
    },
    "sticky": {},
    "flaky": {},
    "bugs": [("NV-11", "spi_ctrl", "S3", "closed", 15, 6, "Quad IO turnaround cycle count off by one"),
             ("NV-12", "uart", "S4", "open", 3, None, "Baud divisor register description has a typo")],
    "history_bugs": 9,
    "config": {
        "project": "Nova IO Hub",
        "current_milestone": "DV 1.0",
        "files": {"regression": "nightly_results.csv"},
        "milestones": [
            {"name": "DV 1.0", "date": "2026-11-27",
             "criteria": {"min_pass_rate": 0.97, "coverage_target_scale": 0.97,
                          "max_unresolved_bugs": {"S1": 0, "S2": 0}, "min_testplan_passing": 0.95}},
        ],
    },
}


# --------------------------------------------------------------------------- generation

def regression_rows(spec, rng):
    rows, n = [], spec["runs"]
    for r in range(n):
        date = AS_OF - dt.timedelta(days=n - 1 - r)
        run_id = f"nightly_{date:%m%d}"
        progress = r / max(1, n - 1)
        for block, b in spec["blocks"].items():
            p_block = b["floor"] + (b["start"] - b["floor"]) * (1 - progress) ** 1.6
            for test in b["tests"]:
                for _ in range(spec["seeds_per_test"]):
                    seed = rng.randrange(1, 2**31)
                    sticky = spec["sticky"].get((block, test))
                    failed = sticky is not None or rng.random() < spec["flaky"].get((block, test), p_block)
                    if not failed:
                        rows.append([run_id, date, block, test, seed, "PASS", round(rng.uniform(40, 900), 1), ""])
                        continue
                    if rng.random() < 0.03:
                        status, sig = "ERROR", CRASH_SIG
                    else:
                        sig = b["sigs"][sticky] if sticky is not None else rng.choice(b["sigs"])
                        timeout = "PH_TIMEOUT" in sig or rng.random() < b["timeout_share"] * 0.3
                        status, sig = ("TIMEOUT", TIMEOUT_SIG) if timeout else ("FAIL", sig)
                    rows.append([run_id, date, block, test, seed, status,
                                 3600.0 if status == "TIMEOUT" else round(rng.uniform(30, 600), 1), sig])
    return rows


def coverage_rows(spec, rng):
    rows = []
    for block, b in spec["blocks"].items():
        scale = 0.2 if b.get("small") else 1.0
        for metric, target in METRIC_TARGETS.items():
            total = max(8, int(METRIC_SIZES[metric] * scale * rng.uniform(0.6, 1.4)))
            extra = 1.6 if metric in ("functional", "toggle") else 1.0
            pct = 100.0 if b["lag"] == 0 else min(
                100.0, target - b["lag"] * extra * rng.uniform(0.3, 1.3) + rng.uniform(-0.5, 1.8))
            rows.append([block, metric, round(total * pct / 100), total, target])
    return rows


def bug_rows(spec, rng):
    bugs = list(spec["bugs"])
    prefix = bugs[0][0].split("-")[0]
    for i in range(spec["history_bugs"]):
        block = rng.choice(list(spec["blocks"]))
        opened = rng.randint(28, 80)
        bugs.append((f"{prefix}-{40 + i}", block, rng.choice(["S2", "S3", "S3", "S4"]), "closed", opened,
                     max(1, opened - rng.randint(4, 25)), f"{block.replace('_', ' ')} issue found in early bring-up"))
    rows = [[bid, title, block, sev, status, AS_OF - dt.timedelta(days=o),
             AS_OF - dt.timedelta(days=c) if c is not None else ""]
            for bid, block, sev, status, o, c, title in bugs]
    return sorted(rows, key=lambda r: (len(r[0]), r[0]))


def testplan_rows(spec, rng):
    milestones = [m["name"] for m in spec["config"]["milestones"]]
    rows, n = [], 1
    for block, b in spec["blocks"].items():
        maturity = 1 - b["lag"] / 12 + spec["maturity"]
        for feature in b["features"]:
            for k in range(rng.randint(3, 6)):
                idx = min(len(milestones) - 1, k * len(milestones) // 6)
                bias = 0.3 - 0.65 * idx / max(1, len(milestones) - 1) if len(milestones) > 1 else 0.0
                score = rng.random() * 0.5 + maturity * 0.5 + bias
                status = "passing" if score > 0.62 else "written" if score > 0.42 else "planned"
                test = rng.choice(b["tests"]) if status != "planned" else ""
                rows.append([f"TP-{n:03d}", block, feature, f"{feature} scenario {k + 1}", milestones[idx], status, test])
                n += 1
    return rows


def write_csv(path, header, rows):
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def write_project(spec):
    rng = random.Random(spec["seed"])
    out = ROOT / spec["folder"]
    out.mkdir(parents=True, exist_ok=True)
    files = {"regression": "regression_runs.csv", "coverage": "coverage.csv", "bugs": "bugs.csv",
             "testplan": "testplan.csv", **spec["config"].get("files", {})}
    write_csv(out / files["regression"], ["run_id", "date", "block", "test", "seed", "status", "duration_s", "signature"],
              regression_rows(spec, rng))
    write_csv(out / files["coverage"], ["block", "metric", "covered", "total", "target_pct"], coverage_rows(spec, rng))
    write_csv(out / files["bugs"], ["id", "title", "block", "severity", "status", "opened", "closed"], bug_rows(spec, rng))
    write_csv(out / files["testplan"], ["id", "block", "feature", "item", "milestone", "status", "test"],
              testplan_rows(spec, rng))
    (out / "config.json").write_text(json.dumps(spec["config"], indent=2) + "\n")
    print(f"Wrote {out}")


if __name__ == "__main__":
    for project in (ORION, LYRA, NOVA):
        write_project(project)
