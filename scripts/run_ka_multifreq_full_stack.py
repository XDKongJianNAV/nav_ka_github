# -*- coding: utf-8 -*-
"""
run_ka_multifreq_full_stack.py
==============================

一键执行泛 Ka 全频点（19.0~31.0 GHz, step=0.5 GHz）三层实验：
1) 单通道 WKB + 接收机频谱
2) 多星单历元 WLS
3) 多历元动态 EKF

并输出跨频综合汇总。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from nav_ka import CANONICAL_RESULTS_ROOT
from nav_ka.legacy import exp_dynamic_multisat_ekf_report as ekf_mod
from nav_ka.legacy import exp_multisat_wls_pvt_report as wls_mod
from nav_ka.legacy import generate_ka_multifreq_report as report_mod
from nav_ka.legacy import nb_ka_multifreq_wkb_spectrum as single_mod


ROOT = Path(__file__).resolve().parents[1]

FREQUENCIES_HZ = np.arange(19.0e9, 31.0e9 + 0.25e9, 0.5e9)
RESULTS_ROOT = CANONICAL_RESULTS_ROOT / "results_ka_multifreq"
SINGLE_DIR = RESULTS_ROOT / "single_channel"
WLS_DIR = RESULTS_ROOT / "wls"
EKF_DIR = RESULTS_ROOT / "ekf"
CROSS_DIR = RESULTS_ROOT / "cross_frequency"


def _write_combined_outputs(rows: list[dict[str, float]]) -> None:
    CROSS_DIR.mkdir(parents=True, exist_ok=True)
    key_union = {key for row in rows for key in row.keys()}
    fieldnames = ["frequency_hz"] + sorted(key for key in key_union if key != "frequency_hz")
    with (CROSS_DIR / "combined_metrics.csv").open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    (CROSS_DIR / "combined_metrics.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    freq_ghz = np.asarray([row["frequency_hz"] for row in rows], dtype=float) / 1e9
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), dpi=160)

    axes[0, 0].plot(freq_ghz, [row["single_tau_rmse_ns"] for row in rows], marker="o")
    axes[0, 0].set_title("Single-channel tau RMSE")
    axes[0, 0].set_xlabel("Frequency (GHz)")
    axes[0, 0].set_ylabel("ns")
    axes[0, 0].grid(True, ls=":", alpha=0.5)

    axes[0, 1].plot(freq_ghz, [row["wls_case_b_wls_position_error_3d_m"] for row in rows], marker="o")
    axes[0, 1].set_title("WLS Case B 3D error")
    axes[0, 1].set_xlabel("Frequency (GHz)")
    axes[0, 1].set_ylabel("m")
    axes[0, 1].grid(True, ls=":", alpha=0.5)

    axes[1, 0].plot(freq_ghz, [row["ekf_pr_doppler_mean_position_error_3d_m"] for row in rows], marker="o")
    axes[1, 0].set_title("EKF PR+Doppler mean 3D position error")
    axes[1, 0].set_xlabel("Frequency (GHz)")
    axes[1, 0].set_ylabel("m")
    axes[1, 0].grid(True, ls=":", alpha=0.5)

    axes[1, 1].plot(freq_ghz, [row["ekf_pr_doppler_mean_velocity_error_3d_mps"] for row in rows], marker="o")
    axes[1, 1].set_title("EKF PR+Doppler mean 3D velocity error")
    axes[1, 1].set_xlabel("Frequency (GHz)")
    axes[1, 1].set_ylabel("m/s")
    axes[1, 1].grid(True, ls=":", alpha=0.5)

    fig.tight_layout()
    fig.savefig(CROSS_DIR / "combined_metrics_vs_frequency.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def _to_float_or_none(value: Any) -> float | None:
    try:
        scalar = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(scalar):
        return None
    return scalar


def _merge_prefixed_numeric_fields(dst: dict[str, float], src: dict[str, Any], *, prefix: str) -> None:
    for key, value in src.items():
        if key == "frequency_hz":
            continue
        scalar = _to_float_or_none(value)
        if scalar is None:
            continue
        dst[f"{prefix}_{key}"] = scalar


def _combine_rows(
    single_rows: list[dict[str, Any]],
    wls_rows: list[dict[str, Any]],
    ekf_rows: list[dict[str, Any]],
) -> list[dict[str, float]]:
    single_map = {float(r["frequency_hz"]): r for r in single_rows}
    wls_map = {float(r["frequency_hz"]): r for r in wls_rows}
    ekf_map = {float(r["frequency_hz"]): r for r in ekf_rows}

    merged: list[dict[str, float]] = []
    for fc_hz in sorted(single_map.keys()):
        if fc_hz not in wls_map or fc_hz not in ekf_map:
            raise RuntimeError(f"跨频汇总缺失频点: {fc_hz}")
        s = single_map[fc_hz]
        w = wls_map[fc_hz]
        e = ekf_map[fc_hz]
        row = {
            "frequency_hz": float(fc_hz),
            "single_tau_rmse_ns": float(s["receiver_tau_rmse_ns"]),
            "single_fd_rmse_hz": float(s["receiver_fd_rmse_hz"]),
            "single_peak_to_second_db": float(s["peak_to_second_db"]),
            "single_post_corr_snr_median_db": float(s["post_corr_snr_median_db"]),
            "single_carrier_lock_metric_median": float(s["carrier_lock_metric_median"]),
            "single_loss_fraction": float(s["loss_fraction"]),
            "wls_tau_g_median_m": float(w["tau_g_median_m"]),
            "wls_case_a_wls_position_error_3d_m": float(w["case_a_wls_position_error_3d_m"]),
            "wls_case_b_wls_position_error_3d_m": float(w["case_b_wls_position_error_3d_m"]),
            "wls_case_a_pdop": float(w["case_a_pdop"]),
            "wls_case_b_pdop": float(w["case_b_pdop"]),
            "wls_monte_carlo_wls_mean_m": float(w["monte_carlo_wls_mean_m"]),
            "ekf_pr_only_mean_position_error_3d_m": float(e["ekf_pr_only_mean_position_error_3d_m"]),
            "ekf_pr_doppler_mean_position_error_3d_m": float(e["ekf_pr_doppler_mean_position_error_3d_m"]),
            "ekf_pr_only_mean_velocity_error_3d_mps": float(e["ekf_pr_only_mean_velocity_error_3d_mps"]),
            "ekf_pr_doppler_mean_velocity_error_3d_mps": float(e["ekf_pr_doppler_mean_velocity_error_3d_mps"]),
            "ekf_pr_doppler_mean_innovation_pr_m": float(e["ekf_pr_doppler_mean_innovation_pr_m"]),
            "ekf_pr_doppler_mean_innovation_rr_mps": float(e["ekf_pr_doppler_mean_innovation_rr_mps"]),
            "ekf_pr_doppler_prediction_only_epochs": float(e["ekf_pr_doppler_prediction_only_epochs"]),
        }
        # 同时输出三层的全部数值指标，满足“全指标全频点”分析。
        _merge_prefixed_numeric_fields(row, s, prefix="single")
        _merge_prefixed_numeric_fields(row, w, prefix="wls")
        _merge_prefixed_numeric_fields(row, e, prefix="ekf")
        merged.append(row)
    return merged


def main() -> None:
    RESULTS_ROOT.mkdir(parents=True, exist_ok=True)

    print("=" * 100)
    print("Ka 多频全链路批量实验")
    print("=" * 100)
    print(f"频点数 = {len(FREQUENCIES_HZ)}")

    print("\n[1/3] 单通道 WKB + 频谱全频点")
    single_mod.RESULTS_DIR = SINGLE_DIR
    single_mod.SPECTRUM_DIR = SINGLE_DIR / "receiver_spectra"
    single_mod.FREQUENCIES_HZ = np.asarray(FREQUENCIES_HZ, dtype=float)
    single_mod.main()
    single_summary = json.loads((SINGLE_DIR / "summary.json").read_text(encoding="utf-8"))
    single_rows = list(single_summary["receiver_runs"])
    single_csv = {float(r["frequency_hz"]): r for r in csv.DictReader((SINGLE_DIR / "frequency_summary.csv").open("r", encoding="utf-8"))}
    for row in single_rows:
        row.update({k: float(v) for k, v in single_csv[float(row["frequency_hz"])].items() if k not in {"frequency_hz"}})

    print("\n[2/3] WLS 全频点")
    wls_result = wls_mod.run_wls_frequency_grid(FREQUENCIES_HZ.tolist(), root_output_dir=WLS_DIR)
    wls_rows = list(wls_result["rows"])

    print("\n[3/3] EKF 全频点")
    ekf_result = ekf_mod.run_dynamic_ekf_frequency_grid(FREQUENCIES_HZ.tolist(), root_output_dir=EKF_DIR)
    ekf_rows = list(ekf_result["rows"])

    combined_rows = _combine_rows(single_rows, wls_rows, ekf_rows)
    _write_combined_outputs(combined_rows)

    summary = {
        "frequencies_hz": [float(v) for v in FREQUENCIES_HZ],
        "frequency_labels": [f"{v / 1e9:.1f}".replace(".", "p") + "GHz" for v in FREQUENCIES_HZ],
        "outputs": {
            "results_root": str(RESULTS_ROOT.resolve()),
            "single_channel_dir": str(SINGLE_DIR.resolve()),
            "wls_dir": str(WLS_DIR.resolve()),
            "ekf_dir": str(EKF_DIR.resolve()),
            "cross_frequency_dir": str(CROSS_DIR.resolve()),
            "combined_csv": str((CROSS_DIR / "combined_metrics.csv").resolve()),
            "combined_json": str((CROSS_DIR / "combined_metrics.json").resolve()),
            "combined_plot": str((CROSS_DIR / "combined_metrics_vs_frequency.png").resolve()),
        },
    }
    (RESULTS_ROOT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report_outputs = report_mod.generate_reports(RESULTS_ROOT)
    summary["outputs"]["report_summary_md"] = str(report_outputs["summary_md"].resolve())
    summary["outputs"]["report_full_md"] = str(report_outputs["full_md"].resolve())
    (RESULTS_ROOT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n[完成]")
    print(f"  - results root = {RESULTS_ROOT}")
    print(f"  - combined metrics = {CROSS_DIR / 'combined_metrics.csv'}")
    print(f"  - report = {report_outputs['full_md']}")


if __name__ == "__main__":
    main()
