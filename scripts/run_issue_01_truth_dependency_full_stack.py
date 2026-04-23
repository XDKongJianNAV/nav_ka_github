# -*- coding: utf-8 -*-
"""
run_issue_01_truth_dependency_full_stack.py
===========================================

Issue 01: 去除运行时真值依赖后，重跑单通道 / WLS / EKF 全流程，
并与既有 `results_ka_multifreq/` baseline 做对比。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import numpy as np

from nav_ka import CANONICAL_RESULTS_ROOT, CORRECTIONS_ROOT
from nav_ka.legacy import exp_dynamic_multisat_ekf_report as ekf_mod
from nav_ka.legacy import exp_multisat_wls_pvt_report as wls_mod
from nav_ka.legacy import generate_ka_multifreq_report as report_mod
from nav_ka.legacy import nb_ka_multifreq_wkb_spectrum as single_mod
from nav_ka.studies.issue_01_truth_dependency import (
    build_comparison_rows,
    load_json,
    write_comparison_plot,
    write_csv_rows,
    write_issue_findings_md,
    write_json,
)

ROOT = Path(__file__).resolve().parents[1]
from scripts import run_ka_multifreq_full_stack as baseline_runner


FREQUENCIES_HZ = np.arange(19.0e9, 31.0e9 + 0.25e9, 0.5e9)
CORRECTION_ROOT = CORRECTIONS_ROOT / "issue_01_truth_dependency"
CORRECTED_ROOT = CORRECTION_ROOT / "corrected_fullstack"
COMPARISON_DIR = CORRECTION_ROOT / "comparison"
BASELINE_ROOT = CANONICAL_RESULTS_ROOT / "results_ka_multifreq"
SINGLE_DIR = CORRECTED_ROOT / "single_channel"
WLS_DIR = CORRECTED_ROOT / "wls"
EKF_DIR = CORRECTED_ROOT / "ekf"
CROSS_DIR = CORRECTED_ROOT / "cross_frequency"


def _read_single_rows(single_dir: Path) -> list[dict[str, Any]]:
    summary = load_json(single_dir / "summary.json")
    rows = list(summary["receiver_runs"])
    csv_rows = {
        float(row["frequency_hz"]): row
        for row in csv.DictReader((single_dir / "frequency_summary.csv").open("r", encoding="utf-8"))
    }
    for row in rows:
        row.update({k: float(v) for k, v in csv_rows[float(row["frequency_hz"])].items() if k not in {"frequency_hz"}})
    return rows


def main() -> None:
    CORRECTED_ROOT.mkdir(parents=True, exist_ok=True)
    COMPARISON_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 100)
    print("Issue 01: 去除运行时真值依赖后的 Ka 多频全链路批量实验")
    print("=" * 100)
    print(f"频点数 = {len(FREQUENCIES_HZ)}")

    print("\n[1/4] 单通道修正版频扫")
    single_mod.RESULTS_DIR = SINGLE_DIR
    single_mod.SPECTRUM_DIR = SINGLE_DIR / "receiver_spectra"
    single_mod.FREQUENCIES_HZ = np.asarray(FREQUENCIES_HZ, dtype=float)
    single_mod.TRUTH_FREE_RUNTIME = True
    single_mod.main()
    single_rows = _read_single_rows(SINGLE_DIR)

    print("\n[2/4] WLS 修正版全频点")
    wls_result = wls_mod.run_wls_frequency_grid(
        FREQUENCIES_HZ.tolist(),
        root_output_dir=WLS_DIR,
        truth_free_runtime=True,
        truth_free_initialization=True,
    )
    wls_rows = list(wls_result["rows"])

    print("\n[3/4] EKF 修正版全频点")
    ekf_result = ekf_mod.run_dynamic_ekf_frequency_grid(
        FREQUENCIES_HZ.tolist(),
        root_output_dir=EKF_DIR,
        truth_free_runtime=True,
        truth_free_initialization=True,
    )
    ekf_rows = list(ekf_result["rows"])

    print("\n[4/4] 汇总与对比")
    combined_rows = baseline_runner._combine_rows(single_rows, wls_rows, ekf_rows)
    baseline_runner.CROSS_DIR = CROSS_DIR
    baseline_runner._write_combined_outputs(combined_rows)

    report_outputs = report_mod.generate_reports(CORRECTED_ROOT)
    corrected_summary = {
        "issue_id": "issue_01_truth_dependency",
        "execution_command": "uv run python scripts/run_issue_01_truth_dependency_full_stack.py",
        "frequencies_hz": [float(v) for v in FREQUENCIES_HZ],
        "truth_dependency_correction": {
            "single_channel_truth_free_runtime": True,
            "wls_truth_free_runtime": True,
            "wls_truth_free_initialization": True,
            "ekf_truth_free_runtime": True,
            "ekf_truth_free_initialization": True,
            "allowed_truth_usage": [
                "synthetic data generation",
                "offline evaluation and plotting",
            ],
        },
        "outputs": {
            "corrected_root": str(CORRECTED_ROOT.resolve()),
            "single_channel_dir": str(SINGLE_DIR.resolve()),
            "wls_dir": str(WLS_DIR.resolve()),
            "ekf_dir": str(EKF_DIR.resolve()),
            "cross_frequency_dir": str(CROSS_DIR.resolve()),
            "report_summary_md": str(report_outputs["summary_md"].resolve()),
            "report_full_md": str(report_outputs["full_md"].resolve()),
        },
        "baseline_reference": str(BASELINE_ROOT.resolve()),
    }
    write_json(CORRECTED_ROOT / "summary.json", corrected_summary)

    baseline_rows = load_json(BASELINE_ROOT / "cross_frequency" / "combined_metrics.json")
    comparison_rows, comparison_summary = build_comparison_rows(baseline_rows, combined_rows)
    comparison_summary["baseline_root"] = str(BASELINE_ROOT.resolve())
    comparison_summary["corrected_root"] = str(CORRECTED_ROOT.resolve())

    write_json(COMPARISON_DIR / "issue_01_diff_summary.json", comparison_summary)
    write_csv_rows(COMPARISON_DIR / "issue_01_diff_tables.csv", comparison_rows)
    write_json(COMPARISON_DIR / "issue_01_diff_tables.json", comparison_rows)
    write_comparison_plot(comparison_rows, COMPARISON_DIR / "issue_01_diff_plots.png")
    write_issue_findings_md(
        COMPARISON_DIR / "issue_01_findings.md",
        corrected_root=CORRECTED_ROOT,
        baseline_root=BASELINE_ROOT,
        comparison_summary=comparison_summary,
    )


if __name__ == "__main__":
    main()
