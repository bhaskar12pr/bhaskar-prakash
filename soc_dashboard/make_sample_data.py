#!/usr/bin/env python3
"""Write deterministic example inputs to sample_data/ for a fictional SoC.

Replace these files with your own project's data; the formats are described in
README.md. Re-running this script overwrites the sample files.
"""
import csv
import datetime as dt
import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent / "sample_data"
rng = random.Random(20261121)

FIRST_RUN = dt.date(2026, 11, 8)
N_RUNS = 14
SEEDS_PER_TEST = 2

# block -> (tests, starting fail probability, floor fail probability, share of failures that time out)
BLOCKS = {
    "cpu_cluster": (["smoke_boot", "cache_coherency", "mmu_walk", "irq_latency", "wfi_wakeup",
                     "atomic_ops", "debug_halt", "l2_ecc_inject", "branch_pred_stress", "multi_core_sync"],
                    0.22, 0.02, 0.10),
    "noc_fabric": (["route_all_to_all", "qos_arbitration", "deadlock_stress", "backpressure",
                    "addr_decode_err", "outstanding_max"], 0.25, 0.03, 0.30),
    "ddr_ctrl": (["init_training", "refresh_timing", "bank_interleave", "ecc_single_bit",
                  "ecc_double_bit", "self_refresh_exit", "rw_turnaround", "power_down",
                  "phy_calib", "row_hammer_mitigation"], 0.45, 0.10, 0.15),
    "pcie_ctrl": (["link_up_gen4", "ltssm_recovery", "msix_interrupts", "tlp_ordering",
                   "completion_timeout", "aer_errors", "aspm_l1"], 0.35, 0.06, 0.55),
    "usb3_ctrl": (["enum_hs", "enum_ss", "bulk_xfer", "iso_xfer", "u1_u2_lpm", "hot_plug"],
                  0.20, 0.02, 0.20),
    "dma_engine": (["mem2mem_basic", "scatter_gather", "chained_desc", "abort_midflight",
                    "parallel_channels", "unaligned_xfer"], 0.18, 0.01, 0.10),
    "io_mux": (["pinmux_sel_all", "mux4to1_exhaustive", "pad_drive_strength", "alt_func_switch"],
               0.10, 0.0, 0.0),
    "sec_crypto": (["aes_kat", "sha256_kat", "key_ladder", "tamper_response", "secure_boot_verify",
                    "side_channel_mask"], 0.20, 0.03, 0.05),
}

SIGNATURES = {
    "cpu_cluster": ["[COH_SCB] snoop response mismatch line=<HEX> exp=<HEX> act=<HEX>",
                    "[IRQ_LAT] interrupt latency <N> cycles exceeds limit <N>"],
    "noc_fabric": ["[NOC_ORDER] response reordered on port <N> id=<N>",
                   "[PH_TIMEOUT] Explicit timeout of <N> hit, indicating a probable testbench issue"],
    "ddr_ctrl": ["[ECC_CHK] double-bit error not flagged addr=<HEX>",
                 "[DFI_TIMING] tRFC violated by <N> cycles on rank <N>",
                 "[DDR_SCB] read data mismatch addr=<HEX> exp=<HEX> act=<HEX>"],
    "pcie_ctrl": ["[PH_TIMEOUT] Explicit timeout of <N> hit, indicating a probable testbench issue",
                  "[LTSSM] stuck in Recovery.RcvrLock for <N> us",
                  "[TLP_ORDER] posted write passed non-posted read tag=<N>"],
    "usb3_ctrl": ["[USB_PROTO] unexpected NYET in SS bulk transfer ep=<N>"],
    "dma_engine": ["[DMA_SCB] descriptor <N> byte count mismatch exp=<N> act=<N>"],
    "io_mux": ["[MUX_CHK] ow mismatch s=<N> i=<HEX> exp=<N> act=<N>"],
    "sec_crypto": ["[AES_KAT] ciphertext mismatch vector=<N>",
                   "[TAMPER] alert not raised within <N> cycles"],
}

# Tests that keep failing because of a known open bug (block, test, signature index).
STICKY = {("ddr_ctrl", "ecc_double_bit"): 0, ("pcie_ctrl", "completion_timeout"): 0}
# Tests that fail now and then, independent of the overall trend.
FLAKY = {("noc_fabric", "deadlock_stress"): 0.45, ("usb3_ctrl", "u1_u2_lpm"): 0.3,
         ("ddr_ctrl", "phy_calib"): 0.35, ("cpu_cluster", "multi_core_sync"): 0.25}


def write_csv(name, header, rows):
    with (OUT / name).open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def regression_rows():
    rows = []
    for r in range(N_RUNS):
        date = FIRST_RUN + dt.timedelta(days=r)
        run_id = f"nightly_{date:%m%d}"
        progress = r / (N_RUNS - 1)
        for block, (tests, start, floor, timeout_share) in BLOCKS.items():
            p_block = floor + (start - floor) * (1 - progress) ** 1.6
            for test in tests:
                for _ in range(SEEDS_PER_TEST):
                    seed = rng.randrange(1, 2**31)
                    p = FLAKY.get((block, test), p_block)
                    failed = (block, test) in STICKY or rng.random() < p
                    if not failed:
                        rows.append([run_id, date, block, test, seed, "PASS",
                                     round(rng.uniform(40, 900), 1), ""])
                        continue
                    if rng.random() < 0.03:
                        status, sig = "ERROR", "no UVM report summary (crash or killed)"
                    else:
                        sigs = SIGNATURES[block]
                        sig = sigs[STICKY[(block, test)]] if (block, test) in STICKY else rng.choice(sigs)
                        status = "TIMEOUT" if "PH_TIMEOUT" in sig or rng.random() < timeout_share * 0.3 else "FAIL"
                        if status == "TIMEOUT" and "PH_TIMEOUT" not in sig:
                            sig = "[PH_TIMEOUT] Explicit timeout of <N> hit, indicating a probable testbench issue"
                    rows.append([run_id, date, block, test, seed, status,
                                 3600.0 if status == "TIMEOUT" else round(rng.uniform(30, 600), 1), sig])
    return rows


TARGETS = {"line": 98, "branch": 95, "toggle": 95, "fsm": 100, "assertion": 100, "functional": 100}
# block -> how far behind target it is, in percentage points (bigger = further)
LAG = {"cpu_cluster": 1.5, "noc_fabric": 2.5, "ddr_ctrl": 9, "pcie_ctrl": 6, "usb3_ctrl": 3,
       "dma_engine": 1, "io_mux": 0, "sec_crypto": 2}
SIZES = {"line": 9000, "branch": 4200, "toggle": 26000, "fsm": 160, "assertion": 300, "functional": 1400}


def coverage_rows():
    rows = []
    for block, lag in LAG.items():
        scale = 0.2 if block == "io_mux" else 1.0
        for metric, target in TARGETS.items():
            total = max(8, int(SIZES[metric] * scale * rng.uniform(0.6, 1.4)))
            extra = 1.6 if metric in ("functional", "toggle") else 1.0
            pct = min(100.0, target - lag * extra * rng.uniform(0.3, 1.3) + rng.uniform(-0.5, 1.8))
            if block == "io_mux":
                pct = 100.0
            rows.append([block, metric, round(total * pct / 100), total, target])
    return rows


BUGS = [
    # id, block, severity, status, opened offset (days before 2026-11-21), closed offset or None, title
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
]
# Older closed bugs to give the trend a history.
for i in range(24):
    block = rng.choice(list(BLOCKS))
    opened = rng.randint(28, 70)
    BUGS.append((f"DV-{60 + i}", block, rng.choice(["S2", "S3", "S3", "S4"]), "closed", opened,
                 max(1, opened - rng.randint(4, 25)), f"{block.replace('_', ' ')} issue found in early bring-up"))


def bug_rows():
    as_of = dt.date(2026, 11, 21)
    rows = []
    for bug_id, block, sev, status, opened, closed, title in BUGS:
        rows.append([bug_id, title, block, sev, status, as_of - dt.timedelta(days=opened),
                     as_of - dt.timedelta(days=closed) if closed is not None else ""])
    return sorted(rows, key=lambda r: r[0])


FEATURES = {
    "cpu_cluster": ["Boot and reset", "Cache coherency", "Interrupts", "Debug"],
    "noc_fabric": ["Routing", "QoS", "Error handling"],
    "ddr_ctrl": ["Initialization and training", "Refresh and power", "ECC", "Performance"],
    "pcie_ctrl": ["Link training", "Transaction layer", "Error reporting", "Power management"],
    "usb3_ctrl": ["Enumeration", "Transfers", "Link power"],
    "dma_engine": ["Descriptors", "Channels", "Error handling"],
    "io_mux": ["Pin selection", "Electrical"],
    "sec_crypto": ["Ciphers", "Key management", "Tamper"],
}
MILESTONES = ["DV 0.5", "DV 0.8", "DV 1.0"]


def testplan_rows():
    rows, n = [], 1
    for block, features in FEATURES.items():
        tests = BLOCKS[block][0]
        maturity = 1 - LAG[block] / 12
        for feature in features:
            for k in range(rng.randint(3, 6)):
                ms = MILESTONES[min(2, k // 2)]
                r = rng.random()
                bias = {"DV 0.5": 0.3, "DV 0.8": 0.0, "DV 1.0": -0.35}[ms]
                score = r * 0.5 + maturity * 0.5 + bias
                status = "passing" if score > 0.62 else "written" if score > 0.42 else "planned"
                test = rng.choice(tests) if status != "planned" else ""
                rows.append([f"TP-{n:03d}", block, feature, f"{feature} scenario {k + 1}", ms, status, test])
                n += 1
    return rows


CONFIG = {
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
}


def main():
    OUT.mkdir(exist_ok=True)
    write_csv("regression_runs.csv",
              ["run_id", "date", "block", "test", "seed", "status", "duration_s", "signature"],
              regression_rows())
    write_csv("coverage.csv", ["block", "metric", "covered", "total", "target_pct"], coverage_rows())
    write_csv("bugs.csv", ["id", "title", "block", "severity", "status", "opened", "closed"], bug_rows())
    write_csv("testplan.csv", ["id", "block", "feature", "item", "milestone", "status", "test"], testplan_rows())
    (OUT / "config.json").write_text(json.dumps(CONFIG, indent=2) + "\n")
    print(f"Wrote sample data to {OUT}")


if __name__ == "__main__":
    main()
