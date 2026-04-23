from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any, Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


WGS84_A_M = 6_378_137.0
DEFAULT_COMPARISON_KEYS = (
    "single_tau_rmse_ns",
    "single_fd_rmse_hz",
    "wls_case_b_wls_position_error_3d_m",
    "ekf_pr_doppler_mean_position_error_3d_m",
    "ekf_pr_doppler_mean_velocity_error_3d_mps",
)


def build_truth_free_tracking_config(legacy_module: Any) -> Any:
    cfg_trk = legacy_module.build_default_tracking_config()
    cfg_trk.code_aiding_rate_chips_per_s = 0.0
    cfg_trk.carrier_aiding_rate_hz_per_s = 0.0
    return cfg_trk


def build_truth_free_initial_state_from_observations(observations: Sequence[Any]) -> np.ndarray:
    if len(observations) < 4:
        raise ValueError("至少需要 4 条观测来生成无真值初值。")

    sat_positions = np.asarray([obs.sat_pos_ecef_m for obs in observations], dtype=float)
    sat_unit_mean = np.mean(sat_positions / np.linalg.norm(sat_positions, axis=1, keepdims=True), axis=0)
    sat_unit_norm = float(np.linalg.norm(sat_unit_mean))
    if sat_unit_norm < 1e-9:
        unit_direction = np.array([1.0, 0.0, 0.0], dtype=float)
    else:
        unit_direction = sat_unit_mean / sat_unit_norm

    position_guess_m = WGS84_A_M * unit_direction
    corrected_ranges_m = []
    for obs in observations:
        geometric_guess_m = float(np.linalg.norm(obs.sat_pos_ecef_m - position_guess_m))
        corrected_ranges_m.append(
            float(obs.pseudorange_m)
            - geometric_guess_m
            + float(obs.sat_clock_bias_s) * 299_792_458.0
            - float(obs.tropo_delay_m)
            - float(obs.dispersive_delay_m)
            - float(obs.hardware_bias_m)
        )

    clock_bias_guess_m = float(np.median(np.asarray(corrected_ranges_m, dtype=float)))
    return np.array(
        [
            float(position_guess_m[0]),
            float(position_guess_m[1]),
            float(position_guess_m[2]),
            clock_bias_guess_m,
        ],
        dtype=float,
    )


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        return list(reader)


def write_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["frequency_hz"] + sorted({key for row in rows for key in row.keys() if key != "frequency_hz"})
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _to_float_or_none(value: Any) -> float | None:
    try:
        scalar = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(scalar):
        return None
    return scalar


def build_comparison_rows(
    baseline_rows: Sequence[dict[str, Any]],
    corrected_rows: Sequence[dict[str, Any]],
    *,
    keys: Sequence[str] = DEFAULT_COMPARISON_KEYS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    baseline_map = {float(row["frequency_hz"]): row for row in baseline_rows}
    corrected_map = {float(row["frequency_hz"]): row for row in corrected_rows}
    frequencies_hz = sorted(set(baseline_map) & set(corrected_map))
    rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "frequencies_hz": frequencies_hz,
        "metrics": {},
    }

    for fc_hz in frequencies_hz:
        merged: dict[str, Any] = {"frequency_hz": fc_hz}
        baseline = baseline_map[fc_hz]
        corrected = corrected_map[fc_hz]
        for key in keys:
            base_value = _to_float_or_none(baseline.get(key))
            corr_value = _to_float_or_none(corrected.get(key))
            if base_value is None or corr_value is None:
                continue
            merged[f"{key}_baseline"] = base_value
            merged[f"{key}_corrected"] = corr_value
            merged[f"{key}_delta"] = corr_value - base_value
            merged[f"{key}_ratio"] = corr_value / base_value if abs(base_value) > 1e-12 else None
        rows.append(merged)

    for key in keys:
        deltas = [
            float(row[f"{key}_delta"])
            for row in rows
            if f"{key}_delta" in row and math.isfinite(float(row[f"{key}_delta"]))
        ]
        if not deltas:
            continue
        summary["metrics"][key] = {
            "mean_delta": float(np.mean(deltas)),
            "median_delta": float(np.median(deltas)),
            "max_delta": float(np.max(deltas)),
            "min_delta": float(np.min(deltas)),
        }

    return rows, summary


def write_comparison_plot(
    comparison_rows: Sequence[dict[str, Any]],
    output_path: Path,
) -> None:
    if not comparison_rows:
        return

    freq_ghz = np.asarray([float(row["frequency_hz"]) / 1e9 for row in comparison_rows], dtype=float)
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), dpi=160)
    panels = [
        ("single_tau_rmse_ns", "Single-channel tau RMSE", "ns", axes[0, 0]),
        ("single_fd_rmse_hz", "Single-channel Doppler RMSE", "Hz", axes[0, 1]),
        ("wls_case_b_wls_position_error_3d_m", "WLS Case B 3D error", "m", axes[1, 0]),
        ("ekf_pr_doppler_mean_position_error_3d_m", "EKF PR+D position error", "m", axes[1, 1]),
    ]

    for key, title, ylabel, ax in panels:
        base_key = f"{key}_baseline"
        corr_key = f"{key}_corrected"
        if any(base_key not in row or corr_key not in row for row in comparison_rows):
            ax.set_visible(False)
            continue
        ax.plot(freq_ghz, [float(row[base_key]) for row in comparison_rows], marker="o", label="baseline")
        ax.plot(freq_ghz, [float(row[corr_key]) for row in comparison_rows], marker="o", label="corrected")
        ax.set_title(title)
        ax.set_xlabel("Frequency (GHz)")
        ax.set_ylabel(ylabel)
        ax.grid(True, ls=":", alpha=0.5)
        ax.legend()

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def write_issue_findings_md(
    output_path: Path,
    *,
    corrected_root: Path,
    baseline_root: Path,
    comparison_summary: dict[str, Any],
) -> None:
    metrics = comparison_summary.get("metrics", {})
    lines = [
        "# Issue 01: 真值依赖纠正说明",
        "",
        "## 本轮去掉的运行时真值依赖",
        "",
        "1. 单通道跟踪中的 `code_aiding_rate_chips_per_s` 真值注入已关闭。",
        "2. 单通道跟踪中的 `carrier_aiding_rate_hz_per_s` 真值注入已关闭。",
        "3. WLS 单历元求解不再用接收机真值位置/钟差构造默认初值。",
        "4. 动态 epoch-wise WLS 首历元不再用真值位置/钟差构造 warm start。",
        "",
        "## 本轮仍保留 truth 的位置",
        "",
        "1. synthetic observation 的生成仍然使用 truth，这属于仿真造数层。",
        "2. 误差统计、图表 reference curve、baseline/corrected 对比仍然使用 truth，这属于离线评估层。",
        "",
        "## 目录",
        "",
        f"- baseline: `{baseline_root}`",
        f"- corrected: `{corrected_root}`",
        "",
        "## 指标差分摘要",
        "",
    ]
    for key, stats in metrics.items():
        lines.append(
            f"- `{key}`: mean delta = {stats['mean_delta']:.6g}, median delta = {stats['median_delta']:.6g}, "
            f"min delta = {stats['min_delta']:.6g}, max delta = {stats['max_delta']:.6g}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
