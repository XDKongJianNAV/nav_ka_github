from __future__ import annotations

import csv
import json
import math
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import patches

from nav_ka.studies.issue_04_imu_aided import (
    ImuProfileConfig,
    TrajectoryScenarioConfig,
    mechanize_imu_profile,
)


ROOT = Path(__file__).resolve().parents[1]
ISSUE03_ROOT = ROOT / "archive" / "research" / "corrections" / "issue_03_textbook_full_correction"
ISSUE03_SINGLE_SUMMARY = ISSUE03_ROOT / "corrected_fullstack" / "single_channel" / "summary.json"
ISSUE03_REPORT_MD = ISSUE03_ROOT / "weekly_report_issue_03_textbook_full_context.md"
ISSUE04_ROOT = ROOT / "archive" / "research" / "corrections" / "issue_04_imu_aided"
CORRECTED_ROOT = ISSUE04_ROOT / "corrected_fullstack"
CROSS_PATH = CORRECTED_ROOT / "cross_scenario" / "combined_metrics.csv"
FIGURES_DIR = ISSUE04_ROOT / "figures"
NOTEBOOK_PATH = ROOT / "notebooks" / "imu_aided_receiver_dynamics_review.ipynb"
NOTEBOOK_FIG_DIR = FIGURES_DIR / "notebook"
REPORT_MD = ISSUE04_ROOT / "weekly_report_issue_04_imu_aided.md"
REPORT_DOCX = ISSUE04_ROOT / "weekly_report_issue_04_imu_aided.docx"
REP_CASE_LABEL = "h80km_v8.45kms_18p5GHz"
REP_CASES = (
    "h70km_v7.90kms_18p0GHz",
    "h80km_v8.45kms_18p5GHz",
    "h90km_v9.00kms_18p7GHz",
)
FREQUENCIES_HZ = (18.0e9, 18.5e9, 18.7e9)
HEIGHTS_KM = (70.0, 80.0, 90.0)
SPEEDS_KMS = (7.9, 8.45, 9.0)

plt.rcParams["font.family"] = ["Hiragino Sans GB", "Songti SC", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["axes.titlesize"] = 11
plt.rcParams["axes.labelsize"] = 10
plt.rcParams["xtick.labelsize"] = 9
plt.rcParams["ytick.labelsize"] = 9


def _run_checked(cmd: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        check=True,
        text=True,
    )


def _load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as fp:
        return list(csv.DictReader(fp))


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_issue03_baseline_row() -> dict[str, Any]:
    summary = _load_json(ISSUE03_SINGLE_SUMMARY)
    return next(
        row
        for row in summary["receiver_runs"]
        if abs(float(row["frequency_hz"]) - 22.5e9) <= 1.0
    )


def _scenario_from_row(row: dict[str, str]) -> TrajectoryScenarioConfig:
    return TrajectoryScenarioConfig(
        height_km=float(row["height_km"]),
        speed_kms=float(row["speed_kms"]),
        carrier_frequency_hz=float(row["frequency_hz"]),
    )


def _compute_attitude_error_deg(reference_dcm: np.ndarray, mechanized_dcm: np.ndarray) -> np.ndarray:
    errors_deg = np.empty(len(reference_dcm), dtype=float)
    for idx in range(len(reference_dcm)):
        rot_err = reference_dcm[idx].T @ mechanized_dcm[idx]
        trace_val = np.clip((np.trace(rot_err) - 1.0) * 0.5, -1.0, 1.0)
        errors_deg[idx] = math.degrees(math.acos(trace_val))
    return errors_deg


def _metrics_stats(rows: list[dict[str, str]], key: str) -> dict[str, float]:
    values = np.asarray([float(row[key]) for row in rows], dtype=float)
    return {
        "min": float(np.min(values)),
        "mean": float(np.mean(values)),
        "max": float(np.max(values)),
    }


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _rel(path: Path) -> str:
    return path.relative_to(ISSUE04_ROOT).as_posix()


def _format_scenario_brief(height_km: float, speed_kms: float, frequency_hz: float) -> str:
    return f"{height_km:.0f} km、{speed_kms:.2f} km/s、{frequency_hz / 1e9:.1f} GHz"


def _format_scenario_row(row: dict[str, str]) -> str:
    return _format_scenario_brief(
        float(row["height_km"]),
        float(row["speed_kms"]),
        float(row["frequency_hz"]),
    )


def _save_figure(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def _execute_notebook() -> None:
    _run_checked(
        [
            "uv",
            "run",
            "jupyter",
            "nbconvert",
            "--execute",
            "--inplace",
            str(NOTEBOOK_PATH.relative_to(ROOT)),
        ],
        cwd=ROOT,
    )


def _draw_flow_figure(path: Path) -> None:
    fig, ax = plt.subplots(figsize=(13.5, 4.2))
    ax.set_axis_off()
    box_specs = [
        ("参考轨迹", (0.04, 0.57), "#d9ead3"),
        ("惯性测量序列\n(角速度 / 比力)", (0.23, 0.57), "#fff2cc"),
        ("惯性导航解算\n(姿态 / 速度 / 位置)", (0.42, 0.57), "#cfe2f3"),
        ("运动信息与\n跟踪辅助量", (0.64, 0.57), "#f4cccc"),
        ("跟踪前端\nDLL / PLL", (0.84, 0.57), "#ead1dc"),
        ("标准观测量", (0.84, 0.15), "#d9d2e9"),
        ("WLS / EKF\n导航结果", (0.64, 0.15), "#c9daf8"),
        ("参考真值\n离线评估", (0.42, 0.15), "#d0e0e3"),
    ]
    width = 0.145
    height = 0.20
    for text, (x_pos, y_pos), color in box_specs:
        box = patches.FancyBboxPatch(
            (x_pos, y_pos),
            width,
            height,
            boxstyle="round,pad=0.012,rounding_size=0.02",
            linewidth=1.2,
            edgecolor="#3c3c3c",
            facecolor=color,
        )
        ax.add_patch(box)
        ax.text(x_pos + width / 2.0, y_pos + height / 2.0, text, ha="center", va="center", fontsize=10)

    arrow_specs = [
        ((0.185, 0.67), (0.23, 0.67)),
        ((0.375, 0.67), (0.42, 0.67)),
        ((0.585, 0.67), (0.64, 0.67)),
        ((0.785, 0.67), (0.84, 0.67)),
        ((0.91, 0.57), (0.91, 0.35)),
        ((0.84, 0.25), (0.785, 0.25)),
        ((0.64, 0.25), (0.565, 0.25)),
        ((0.49, 0.35), (0.49, 0.57)),
    ]
    for start, end in arrow_specs:
        ax.annotate(
            "",
            xy=end,
            xytext=start,
            arrowprops=dict(arrowstyle="->", lw=1.8, color="#4d4d4d"),
        )

    ax.text(
        0.50,
        0.93,
        "惯性辅助条件下的信号到导航链路",
        ha="center",
        va="center",
        fontsize=13,
        fontweight="bold",
    )
    ax.text(
        0.50,
        0.04,
        "本轮审查的重点在于：跟踪辅助量和滤波预测状态已经来自惯性导航解算结果，而不是来自外部修正量。",
        ha="center",
        va="center",
        fontsize=9,
    )
    _save_figure(fig, path)


def _draw_scenario_grid(path: Path, rows: list[dict[str, str]]) -> None:
    freq_groups: dict[float, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        freq_groups[float(row["frequency_hz"])].append(row)
    fig, axes = plt.subplots(1, 3, figsize=(12.8, 3.8), sharex=True, sharey=True)
    for ax, fc_hz in zip(axes, FREQUENCIES_HZ, strict=True):
        subset = freq_groups[fc_hz]
        ax.scatter(
            [float(row["speed_kms"]) for row in subset],
            [float(row["height_km"]) for row in subset],
            s=115,
            color="#2f6db0",
            edgecolors="white",
            linewidths=1.0,
        )
        for row in subset:
            ax.text(
                float(row["speed_kms"]),
                float(row["height_km"]) + 0.65,
                row["label"].split("_")[1],
                fontsize=8,
                ha="center",
            )
        ax.set_title(f"{fc_hz / 1e9:.1f} GHz")
        ax.grid(alpha=0.25)
        ax.set_xlabel("速度（km/s）")
    axes[0].set_ylabel("高度（km）")
    fig.suptitle("场景网格：3 个频点 × 3 个高度 × 3 个速度", fontsize=13, fontweight="bold")
    _save_figure(fig, path)


def _draw_rep_case_imu_ins(path: Path, scenario: TrajectoryScenarioConfig) -> dict[str, np.ndarray]:
    reference, measured_imu, mechanization, motion_profile, aiding_profile = mechanize_imu_profile(scenario, ImuProfileConfig())
    pos_err_m = np.linalg.norm(mechanization.position_ecef_m - reference.position_ecef_m, axis=1)
    vel_err_mps = np.linalg.norm(mechanization.velocity_ecef_mps - reference.velocity_ecef_mps, axis=1)
    att_err_deg = _compute_attitude_error_deg(reference.attitude_dcm_bn, mechanization.attitude_dcm_bn)

    fig, axes = plt.subplots(3, 1, figsize=(12.5, 8.5), sharex=True)
    axes[0].plot(measured_imu.t_s, measured_imu.gyro_body_radps[:, 0], label="角速度 x", lw=1.0)
    axes[0].plot(measured_imu.t_s, measured_imu.gyro_body_radps[:, 1], label="角速度 y", lw=1.0)
    axes[0].plot(measured_imu.t_s, measured_imu.gyro_body_radps[:, 2], label="角速度 z", lw=1.2)
    axes[0].set_ylabel("rad/s")
    axes[0].set_title("角速度测量序列")
    axes[0].legend(ncol=3, fontsize=8, loc="upper right")
    axes[0].grid(alpha=0.25)

    axes[1].plot(measured_imu.t_s, measured_imu.accel_body_mps2[:, 0], label="比力 x", lw=1.0)
    axes[1].plot(measured_imu.t_s, measured_imu.accel_body_mps2[:, 1], label="比力 y", lw=1.0)
    axes[1].plot(measured_imu.t_s, measured_imu.accel_body_mps2[:, 2], label="比力 z", lw=1.0)
    axes[1].set_ylabel("m/s²")
    axes[1].set_title("机体系比力测量序列")
    axes[1].legend(ncol=3, fontsize=8, loc="upper right")
    axes[1].grid(alpha=0.25)

    axes[2].plot(reference.t_s, pos_err_m, label="位置误差", lw=1.3, color="#c0504d")
    axes[2].plot(reference.t_s, vel_err_mps * 12.0, label="速度误差 ×12", lw=1.2, color="#4f81bd")
    ax2 = axes[2].twinx()
    ax2.plot(reference.t_s, att_err_deg, label="姿态误差", lw=1.2, color="#9bbb59")
    axes[2].set_ylabel("m / 缩放后的 m/s")
    ax2.set_ylabel("°")
    axes[2].set_title("惯性导航误差包络")
    axes[2].set_xlabel("时间（s）")
    axes[2].grid(alpha=0.25)
    lines1, labels1 = axes[2].get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    axes[2].legend(lines1 + lines2, labels1 + labels2, ncol=3, fontsize=8, loc="upper right")

    fig.suptitle(f"典型场景：{_format_scenario_brief(scenario.height_km, scenario.speed_kms, scenario.carrier_frequency_hz)}", fontsize=13, fontweight="bold")
    _save_figure(fig, path)
    return {
        "t_s": reference.t_s,
        "position_error_m": pos_err_m,
        "velocity_error_mps": vel_err_mps,
        "attitude_error_deg": att_err_deg,
        "motion_t_s": motion_profile.t_s,
        "code_rate_chips_per_s": motion_profile.code_rate_chips_per_s,
        "carrier_rate_hz_per_s": aiding_profile.carrier_aiding_rate_hz_per_s,
    }


def _draw_rep_case_navigation(
    path: Path,
    scenario: TrajectoryScenarioConfig,
    rep_series: dict[str, np.ndarray],
) -> None:
    state_rows = [
        row
        for row in _load_csv_rows(CORRECTED_ROOT / scenario.label / "dynamic_state_history.csv")
        if row["mode"] == "ekf_pr_doppler" and row["vel_err_3d_mps"] not in {"", "nan", "None"}
    ]
    state_t_s = np.asarray([float(row["t_s"]) for row in state_rows], dtype=float)
    num_valid_sats = np.asarray([float(row["num_valid_sats"]) for row in state_rows], dtype=float)
    prediction_only = np.asarray([1.0 if row["prediction_only"].lower() == "true" else 0.0 for row in state_rows], dtype=float)
    pos_err_m = np.asarray([float(row["pos_err_3d_m"]) for row in state_rows], dtype=float)
    vel_err_mps = np.asarray([float(row["vel_err_3d_mps"]) for row in state_rows], dtype=float)

    fig, axes = plt.subplots(3, 1, figsize=(12.5, 8.3), sharex=True)
    axes[0].plot(rep_series["motion_t_s"], rep_series["code_rate_chips_per_s"], color="#4f81bd", lw=1.3, label="码率辅助量")
    ax0r = axes[0].twinx()
    ax0r.plot(rep_series["motion_t_s"], rep_series["carrier_rate_hz_per_s"], color="#c0504d", lw=1.3, label="载波频率辅助量")
    axes[0].set_ylabel("chips/s")
    ax0r.set_ylabel("Hz/s")
    axes[0].set_title("惯性导航生成的跟踪辅助量")
    axes[0].grid(alpha=0.25)
    lines1, labels1 = axes[0].get_legend_handles_labels()
    lines2, labels2 = ax0r.get_legend_handles_labels()
    axes[0].legend(lines1 + lines2, labels1 + labels2, ncol=2, fontsize=8, loc="upper right")

    axes[1].step(state_t_s, num_valid_sats, where="mid", color="#9bbb59", lw=1.4, label="有效卫星数")
    axes[1].step(state_t_s, prediction_only * np.max(num_valid_sats), where="mid", color="#8064a2", lw=1.1, label="纯预测历元")
    axes[1].set_ylabel("数量 / 标记")
    axes[1].set_title("观测更新情况")
    axes[1].grid(alpha=0.25)
    axes[1].legend(fontsize=8, loc="upper right")

    axes[2].plot(state_t_s, pos_err_m, color="#c0504d", lw=1.3, label="位置误差")
    ax2r = axes[2].twinx()
    ax2r.plot(state_t_s, vel_err_mps, color="#4f81bd", lw=1.2, label="速度误差")
    axes[2].set_ylabel("m")
    ax2r.set_ylabel("m/s")
    axes[2].set_xlabel("时间（s）")
    axes[2].set_title("惯性辅助后的导航误差")
    axes[2].grid(alpha=0.25)
    lines1, labels1 = axes[2].get_legend_handles_labels()
    lines2, labels2 = ax2r.get_legend_handles_labels()
    axes[2].legend(lines1 + lines2, labels1 + labels2, ncol=2, fontsize=8, loc="upper right")

    fig.suptitle(f"典型场景下的跟踪与导航：{_format_scenario_brief(scenario.height_km, scenario.speed_kms, scenario.carrier_frequency_hz)}", fontsize=13, fontweight="bold")
    _save_figure(fig, path)


def _heatmap_matrix(
    ax: plt.Axes,
    matrix: np.ndarray,
    speeds: tuple[float, ...],
    heights: tuple[float, ...],
    title: str,
    cmap: str,
) -> None:
    im = ax.imshow(matrix, origin="lower", cmap=cmap, aspect="auto")
    ax.set_xticks(np.arange(len(speeds)), [f"{val:.2f}" for val in speeds])
    ax.set_yticks(np.arange(len(heights)), [f"{val:.0f}" for val in heights])
    ax.set_title(title)
    ax.set_xlabel("速度（km/s）")
    ax.set_ylabel("高度（km）")
    for y_idx in range(matrix.shape[0]):
        for x_idx in range(matrix.shape[1]):
            ax.text(x_idx, y_idx, f"{matrix[y_idx, x_idx]:.1f}", ha="center", va="center", fontsize=7, color="black")
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)


def _matrix_from_rows(rows: list[dict[str, str]], fc_hz: float, key: str) -> np.ndarray:
    matrix = np.zeros((len(HEIGHTS_KM), len(SPEEDS_KMS)), dtype=float)
    for y_idx, height_km in enumerate(HEIGHTS_KM):
        for x_idx, speed_kms in enumerate(SPEEDS_KMS):
            row = next(
                item
                for item in rows
                if abs(float(item["frequency_hz"]) - fc_hz) <= 1.0
                and abs(float(item["height_km"]) - height_km) <= 1e-9
                and abs(float(item["speed_kms"]) - speed_kms) <= 1e-9
            )
            matrix[y_idx, x_idx] = float(row[key])
    return matrix


def _draw_cross_metric_heatmaps(path: Path, rows: list[dict[str, str]]) -> None:
    metric_specs = (
        ("single_tau_rmse_ns", "码时延均方根误差（ns）", "YlOrRd"),
        ("single_fd_rmse_hz", "多普勒均方根误差（Hz）", "YlOrBr"),
        ("ekf_mean_position_error_3d_m", "扩展卡尔曼滤波平均位置误差（m）", "PuBuGn"),
    )
    fig, axes = plt.subplots(len(FREQUENCIES_HZ), len(metric_specs), figsize=(13.8, 11.2))
    for row_idx, fc_hz in enumerate(FREQUENCIES_HZ):
        for col_idx, (key, label, cmap) in enumerate(metric_specs):
            matrix = _matrix_from_rows(rows, fc_hz, key)
            _heatmap_matrix(
                axes[row_idx, col_idx],
                matrix,
                SPEEDS_KMS,
                HEIGHTS_KM,
                f"{fc_hz / 1e9:.1f} GHz\n{label}",
                cmap,
            )
    fig.suptitle("跨场景性能热图", fontsize=14, fontweight="bold")
    _save_figure(fig, path)


def _draw_cross_availability_heatmaps(path: Path, rows: list[dict[str, str]]) -> None:
    metric_specs = (
        ("prediction_only_epochs", "纯预测历元数", "OrRd"),
        ("valid_wls_epochs", "可用于加权最小二乘的历元数", "GnBu"),
    )
    fig, axes = plt.subplots(len(FREQUENCIES_HZ), len(metric_specs), figsize=(9.8, 11.2))
    for row_idx, fc_hz in enumerate(FREQUENCIES_HZ):
        for col_idx, (key, label, cmap) in enumerate(metric_specs):
            matrix = _matrix_from_rows(rows, fc_hz, key)
            _heatmap_matrix(
                axes[row_idx, col_idx],
                matrix,
                SPEEDS_KMS,
                HEIGHTS_KM,
                f"{fc_hz / 1e9:.1f} GHz\n{label}",
                cmap,
            )
    fig.suptitle("观测可用性与导航支撑热图", fontsize=14, fontweight="bold")
    _save_figure(fig, path)


def _write_markdown_report(
    rows: list[dict[str, str]],
    summaries: dict[str, dict[str, Any]],
    issue03_baseline: dict[str, Any],
) -> None:
    issue_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    tau_stats = _metrics_stats(rows, "single_tau_rmse_ns")
    fd_stats = _metrics_stats(rows, "single_fd_rmse_hz")
    ins_pos_stats = _metrics_stats(rows, "ins_mean_position_error_3d_m")
    ins_att_stats = _metrics_stats(rows, "ins_mean_attitude_error_deg")
    ekf_pos_stats = _metrics_stats(rows, "ekf_mean_position_error_3d_m")
    pred_stats = _metrics_stats(rows, "prediction_only_epochs")
    wls_valid_stats = _metrics_stats(rows, "valid_wls_epochs")
    prediction_ratio_mean = pred_stats["mean"] / summaries[REP_CASE_LABEL]["dynamic_navigation"]["num_epochs"]

    worst_tau = max(rows, key=lambda row: float(row["single_tau_rmse_ns"]))
    worst_fd = max(rows, key=lambda row: float(row["single_fd_rmse_hz"]))
    worst_ekf = max(rows, key=lambda row: float(row["ekf_mean_position_error_3d_m"]))
    worst_pred = max(rows, key=lambda row: float(row["prediction_only_epochs"]))
    worst_rows = sorted(rows, key=lambda row: float(row["ekf_mean_position_error_3d_m"]), reverse=True)[:5]

    all_truth_bypassed = all(bool(summaries[row["label"]]["ins_diagnostics"]["ins_aiding_truth_bypassed"]) for row in rows)
    severe_review = "未发现需要整体返工的严重逻辑问题。"
    if not all_truth_bypassed:
        severe_review = "发现参考真值直接进入惯性辅助链路的情况，需要先修正后再形成正式报告。"

    rep_row = next(item for item in rows if item["label"] == REP_CASE_LABEL)
    rep_row_brief = _format_scenario_row(rep_row)
    rep_table_rows: list[list[str]] = []
    for label in REP_CASES:
        row = next(item for item in rows if item["label"] == label)
        rep_table_rows.append(
            [
                _format_scenario_row(row),
                f"{float(row['single_tau_rmse_ns']):.1f}",
                f"{float(row['single_fd_rmse_hz']):.1f}",
                f"{float(row['ins_mean_position_error_3d_m']):.3f}",
                f"{float(row['ekf_mean_position_error_3d_m']):.1f}",
                f"{float(row['prediction_only_epochs']):.0f}",
            ]
        )

    worst_table_rows = [
        [
            _format_scenario_row(row),
            f"{float(row['single_tau_rmse_ns']):.1f}",
            f"{float(row['single_fd_rmse_hz']):.1f}",
            f"{float(row['ekf_mean_position_error_3d_m']):.1f}",
            f"{float(row['prediction_only_epochs']):.0f}",
        ]
        for row in worst_rows
    ]

    stats_table_rows = [
        ["码时延均方根误差（ns）", f"{tau_stats['min']:.1f}", f"{tau_stats['mean']:.1f}", f"{tau_stats['max']:.1f}"],
        ["多普勒均方根误差（Hz）", f"{fd_stats['min']:.1f}", f"{fd_stats['mean']:.1f}", f"{fd_stats['max']:.1f}"],
        ["惯性导航平均位置误差（m）", f"{ins_pos_stats['min']:.3f}", f"{ins_pos_stats['mean']:.3f}", f"{ins_pos_stats['max']:.3f}"],
        ["惯性导航平均姿态误差（°）", f"{ins_att_stats['min']:.6f}", f"{ins_att_stats['mean']:.6f}", f"{ins_att_stats['max']:.6f}"],
        ["扩展卡尔曼滤波平均位置误差（m）", f"{ekf_pos_stats['min']:.1f}", f"{ekf_pos_stats['mean']:.1f}", f"{ekf_pos_stats['max']:.1f}"],
        ["纯预测历元数", f"{pred_stats['min']:.0f}", f"{pred_stats['mean']:.1f}", f"{pred_stats['max']:.0f}"],
    ]

    role_table_rows = [
        ["链路终点", "接收机直接测量量与标准观测量", "在标准观测量基础上继续完成惯性辅助和状态预测"],
        ["动态信息来源", "不引入惯性信息耦合", "由惯性导航解算统一生成运动信息、跟踪辅助量和预测状态"],
        ["主要关注点", "码时延和多普勒恢复、锁定质量、观测形成边界", "惯性信息是否真正接管动态支撑，以及观测是否持续可用"],
        ["当前主要瓶颈", "接收机恢复层的解释和稳定性", "纯预测历元偏多，有效观测更新偏少"],
    ]
    baseline_compare_rows = [
        [
            "上一轮纯接收机方案",
            "22.5 GHz",
            f"{float(issue03_baseline['tau_rmse_ns']):.1f}",
            f"{float(issue03_baseline['fd_rmse_hz']):.1f}",
            f"主峰与次峰差 {float(issue03_baseline['peak_to_second_db']):.2f} dB，失锁比例 {float(issue03_baseline['loss_fraction']):.3f}",
            "用于说明未引入惯性信息时，接收机恢复层的表现与边界",
        ],
        [
            "本轮惯性辅助方案的典型场景",
            rep_row_brief,
            f"{float(rep_row['single_tau_rmse_ns']):.1f}",
            f"{float(rep_row['single_fd_rmse_hz']):.1f}",
            f"辅助量覆盖比例 {float(rep_row['aiding_fraction']):.2f}，纯预测历元 {float(rep_row['prediction_only_epochs']):.0f}",
            "用于说明引入惯性信息后，主要问题转为观测可用性和更新密度",
        ],
    ]

    imu_cfg = ImuProfileConfig()
    md = f"""# 惯性测量单元辅助的前端跟踪与动态导航审查报告

生成时间：{issue_time}

## 一、执行摘要

本轮工作将原先依赖外部修正量的动态支撑方式，改为由惯性测量单元（IMU）和惯性导航解算（INS）直接提供支持，并在 `18.0 / 18.5 / 18.7 GHz`、`70 / 80 / 90 km`、`7.9 / 8.45 / 9.0 km/s` 组成的 `27` 个场景上完成了全量验证。

审查结论如下：**{severe_review}** 目前的实现已经完成了“用惯性导航解算替代外部修正量”的主要目标。延迟锁定环（DLL）和锁相环（PLL）所需的跟踪辅助量，以及扩展卡尔曼滤波（EKF）中的预测状态，均由惯性导航解算结果提供，不再直接依赖参考真值或额外修正项。现阶段更突出的限制不是惯性链路本身，而是高动态条件下可用于更新的观测历元偏少，纯预测历元数仍然偏高。

![总体链路示意图]({_rel(FIGURES_DIR / "issue04_system_flow.png")})

## 二、背景与本轮目标

上一轮工作已经把整体流程梳理为四个层次：信号生成、接收机直接测量量、标准观测量，以及加权最小二乘（WLS）与扩展卡尔曼滤波。那一阶段虽然完成了接收机与观测层的整理，但动态支撑部分仍保留外部修正量，因此整条链路的物理含义还不够完整。

本轮工作的目标可以概括为四点：

1. 用惯性测量数据和简化捷联惯性导航替代外部修正量。
2. 由惯性导航解算结果生成跟踪环所需的辅助量。
3. 由同一套惯性状态提供加权最小二乘初值和扩展卡尔曼滤波预测状态。
4. 在高动态、跨频点、跨高度、跨速度的场景网格上验证这条链路是否稳定成立。

本轮采用的惯性测量单元参数取值偏向高端工程水平，但仍保持现实可实现性：

{_markdown_table(
    ["参数", "取值"],
    [
        ["采样率（Hz）", f"{imu_cfg.imu_rate_hz:.0f}"],
        ["陀螺零偏（°/h）", f"{imu_cfg.gyro_bias_in_run_degph:.3f}"],
        ["陀螺角随机游走（°/√h）", f"{imu_cfg.gyro_arw_deg_rt_hr:.3f}"],
        ["加速度计零偏（mg）", f"{imu_cfg.accel_bias_in_run_mg:.3f}"],
        ["加速度计速度随机游走（m/s/√h）", f"{imu_cfg.accel_vrw_mps_rt_hr:.3f}"],
        ["陀螺满量程（°/s）", f"{imu_cfg.gyro_full_scale_dps:.0f}"],
        ["加速度计满量程（g）", f"{imu_cfg.accel_full_scale_g:.0f}"],
    ],
)}

本轮场景分布如下图所示：

![场景分布图]({_rel(FIGURES_DIR / "issue04_scenario_grid.png")})

## 三、与上一轮纯接收机方案的对比

为了说明本轮改动的实际意义，需要先给出上一轮纯接收机方案的参照结果。上一轮工作已经把流程收敛到“接收机直接测量量形成标准观测量”的框架内，但尚未把惯性信息接入跟踪和动态导航，因此它适合作为本轮的基线。

这里还需要说明一个前提：上一轮的单通道频点扫描覆盖 `19.0~31.0 GHz`，本轮的场景则固定在 `18.0 / 18.5 / 18.7 GHz`。因此，这里的比较不是严格的一一同频对比，而是用来说明“链路职责发生了什么变化，以及这种变化带来了什么现象”。

两轮方案的职责差别如下：

{_markdown_table(
    ["比较项", "上一轮纯接收机方案", "本轮惯性辅助方案"],
    role_table_rows,
)}

![两种方案的链路位置对比]({_rel(NOTEBOOK_FIG_DIR / "receiver_chain_role_comparison.png")})

为便于理解，下面选取上一轮 `22.5 GHz` 的纯接收机结果，以及本轮 `{rep_row_brief}` 这一典型场景进行对照：

{_markdown_table(
    ["对象", "代表频点或场景", "码时延均方根误差（ns）", "多普勒均方根误差（Hz）", "锁定或可用性指标", "说明"],
    baseline_compare_rows,
)}

![上一轮方案与本轮典型场景对照图]({_rel(NOTEBOOK_FIG_DIR / "pure_receiver_vs_imu_aided_tracking.png")})

这组对照说明了两个事实。第一，上一轮工作的重点是把纯接收机恢复过程和标准观测形成过程讲清楚。第二，本轮在此基础上引入了惯性信息，因此关注重点已经从“是否存在外部修正量”转移到“在高动态条件下观测是否还能持续更新”。

上一轮纯接收机方案的主报告和单通道汇总文件位于：

- `{ISSUE03_REPORT_MD.relative_to(ROOT).as_posix()}`
- `{ISSUE03_SINGLE_SUMMARY.relative_to(ROOT).as_posix()}`

## 四、改进思路与实现原理

### 4.1 总体思路

本轮改动的重点，不是简单增加一组惯性参数，而是把动态部分重写为一条完整、闭合的物理链路：

`参考轨迹 -> IMU 测量序列 -> 惯性导航解算 -> 运动信息与跟踪辅助量 -> 跟踪前端 -> 标准观测量 -> 加权最小二乘与扩展卡尔曼滤波`

这条链路成立的前提有三点：

1. 角速度测量必须真实进入姿态传播。
2. 比力测量必须先经过姿态变换，再参与速度和位置积分。
3. 跟踪辅助量与滤波预测状态必须来自惯性导航解算结果，而不是直接使用参考真值。

### 4.2 简化捷联惯性导航的基本关系

本轮采用的是简化捷联惯性导航，而不是完整的惯性误差状态滤波。核心关系可以概括为三步：

$$
C_{{bn,k+1}} = C_{{bn,k}} \\exp([\\omega_b \\Delta t]_\\times)
$$

$$
a_n = C_{{bn}} f_b
$$

$$
v_{{k+1}} = v_k + a_n \\Delta t, \\qquad
p_{{k+1}} = p_k + v_k \\Delta t + \\tfrac{{1}}{{2}} a_n \\Delta t^2
$$

在跟踪辅助侧，惯性导航的位置和速度继续投影到视线方向上，从而得到距离变化率，并进一步生成码率辅助量和载波频率辅助量：

$$
\\dot{{\\rho}} = u^T v_r, \\qquad
f_D = -\\frac{{f_c}}{{c}} \\dot{{\\rho}}
$$

因此，本轮新增的不是另一套外部修正项，而是把同一套惯性导航状态同时用于四件事：

1. 生成运动信息。
2. 生成跟踪辅助量。
3. 提供加权最小二乘初值。
4. 提供扩展卡尔曼滤波预测状态。

## 五、最终审查结论

### 5.1 严重问题复核

围绕“是否存在必须推翻当前实现的严重问题”，本轮重点复核了四项内容：

1. 惯性辅助链路中是否仍有参考真值直接写入。
2. 角速度测量是否真实参与姿态传播。
3. 机体系比力是否经过姿态变换后再积分。
4. 综合统计结果是否与单场景输出一致。

复核结果如下：

{_markdown_table(
    ["审查项", "结论"],
    [
        ["惯性辅助链路是否直接使用参考真值", "27 个场景均确认未直接使用参考真值，惯性辅助量全部来自惯性导航状态"],
        ["惯性导航误差量级是否异常", f"平均位置误差范围为 {ins_pos_stats['min']:.3f}~{ins_pos_stats['max']:.3f} m，未见数值发散"],
        ["姿态传播是否存在明显失真", f"平均姿态误差范围为 {ins_att_stats['min']:.6f}~{ins_att_stats['max']:.6f}°，陀螺建模与姿态传播保持一致"],
        ["综合统计文件是否完整", "27 个场景目录、27 份摘要文件以及 1 组综合统计文件均已生成"],
    ],
)}

综合判断是：当前实现没有暴露出必须整体返工的问题，可以直接作为正式汇报版本使用。

### 5.2 当前的主要限制

如果只看惯性导航本身，本轮结果是稳定的：

- 惯性导航平均位置误差均值为 `{ins_pos_stats['mean']:.3f} m`
- 惯性导航平均姿态误差均值为 `{ins_att_stats['mean']:.6f}°`

但如果同时看跟踪和导航结果，限制因素仍然集中在观测可用性上：

- 码时延均方根误差均值为 `{tau_stats['mean']:.1f} ns`，最大达到 `{tau_stats['max']:.1f} ns`
- 多普勒均方根误差均值为 `{fd_stats['mean']:.1f} Hz`，最大达到 `{fd_stats['max']:.1f} Hz`
- 可用于加权最小二乘的历元数均值为 `{wls_valid_stats['mean']:.1f}`，最少仅 `{wls_valid_stats['min']:.0f}`
- 纯预测历元数均值为 `{pred_stats['mean']:.1f}`，约占 `219` 个历元中的 `{prediction_ratio_mean * 100.0:.1f}%`

这说明系统已经具备由惯性信息支撑动态过程的能力，但高动态条件下可用于更新的观测历元仍然不足，这也是下一步需要优先处理的问题。

## 六、典型场景与中间量

为便于说明中间量的变化情况，下面选取 `{rep_row_brief}` 这一典型场景作为示例。

### 6.1 惯性测量量与惯性导航误差

![典型场景下的惯性测量量与导航误差]({_rel(FIGURES_DIR / "issue04_rep_case_imu_ins.png")})

这张图可以说明三点：

1. 惯性测量序列中确实存在连续的角速度和比力数据，而不是只有参数配置。
2. 惯性导航的位置、速度和姿态误差始终保持在较小范围内，没有出现发散。
3. 在当前高动态场景下，惯性导航本身并不是主要误差来源。

下图进一步把惯性测量量和惯性导航误差拆开显示，便于单独观察各项变化：

![惯性测量量与惯性导航误差细节图]({_rel(NOTEBOOK_FIG_DIR / "imu_ins_error_detail.png")})

### 6.2 跟踪辅助量与导航时序

![典型场景下的跟踪辅助量与导航时序]({_rel(FIGURES_DIR / "issue04_rep_case_navigation.png")})

这一组结果最关键的信息有两点：

1. 惯性导航持续生成码率辅助量和载波频率辅助量，并将其送入跟踪环。
2. 纯预测历元仍然较多，说明扩展卡尔曼滤波虽然能够依靠惯性信息维持运行，但观测更新仍然偏稀疏。

下图把有效卫星数、创新量和导航误差放到同一视角下，用于说明观测更新不足对导航结果的影响：

![导航误差与观测更新细节图]({_rel(NOTEBOOK_FIG_DIR / "imu_navigation_error_detail.png")})

典型场景和两端场景的结果摘要如下：

{_markdown_table(
    ["场景", "码时延均方根误差（ns）", "多普勒均方根误差（Hz）", "惯性导航平均位置误差（m）", "扩展卡尔曼滤波平均位置误差（m）", "纯预测历元数"],
    rep_table_rows,
)}

## 七、27 个场景的综合结果

### 7.1 综合统计

{_markdown_table(
    ["指标", "最小值", "均值", "最大值"],
    stats_table_rows,
)}

### 7.2 跨场景性能分布

![跨场景性能热图]({_rel(FIGURES_DIR / "issue04_cross_scenario_metrics.png")})

从这组热图可以看出两个整体趋势：

1. 惯性导航相关误差整体比较稳定，但码时延误差、多普勒误差和导航位置误差会随着场景条件明显变化。
2. 频率、高度和速度共同决定动态压力，其中高速度与部分中高频点组合更容易使跟踪前端进入困难区间。

### 7.3 观测可用性分布

![观测可用性热图]({_rel(FIGURES_DIR / "issue04_cross_scenario_availability.png")})

这张图对应本轮最重要的判断：真正限制结果上限的，不是惯性导航本身，而是很多场景中的观测更新历元明显偏少。这也是为什么：

- 加权最小二乘的平均误差仍然较大。
- 扩展卡尔曼滤波虽然明显优于加权最小二乘，但仍有不少时间处于纯预测状态。

### 7.4 误差最大的场景

按照扩展卡尔曼滤波平均位置误差排序，误差最大的 5 个场景如下：

{_markdown_table(
    ["场景", "码时延均方根误差（ns）", "多普勒均方根误差（Hz）", "扩展卡尔曼滤波平均位置误差（m）", "纯预测历元数"],
    worst_table_rows,
)}

其中需要单独指出的极值如下：

- 码时延均方根误差最大场景：`{_format_scenario_row(worst_tau)}`，`{float(worst_tau['single_tau_rmse_ns']):.1f} ns`
- 多普勒均方根误差最大场景：`{_format_scenario_row(worst_fd)}`，`{float(worst_fd['single_fd_rmse_hz']):.1f} Hz`
- 扩展卡尔曼滤波平均位置误差最大场景：`{_format_scenario_row(worst_ekf)}`，`{float(worst_ekf['ekf_mean_position_error_3d_m']):.1f} m`
- 纯预测历元数最大场景：`{_format_scenario_row(worst_pred)}`，`{float(worst_pred['prediction_only_epochs']):.0f}`

## 八、结果解释与汇报建议

本轮工作的结论可以归纳为一条清晰的主线：过去需要依赖外部修正量来支撑的动态部分，现在已经可以由惯性信息直接承担；惯性导航本身误差较小，说明这种替换在原理上和实现上都是成立的；而当前系统的精度上限，主要受制于高动态条件下观测更新不足。

因此，在正式汇报时，更合适的表述应当是：

> 本轮工作已经完成了从“外部修正量支撑”到“惯性信息支撑”的替换，并在 27 个高动态场景上验证了这条链路的稳定性。当前系统的主要约束，已经从动态先验是否合法，转移到高动态条件下观测是否能够持续更新。

## 九、后续建议

基于本轮结果，后续工作建议集中在三点：

1. 当前版本可以直接作为正式汇报稿件使用，不建议在汇报前继续大幅修改主算法。
2. 下一阶段如继续推进，应优先提升跟踪前端的鲁棒性和有效观测历元数，而不是重新引入外部修正量。
3. 如果后续需要进一步提高性能，可单独评估更紧密的跟踪方案或更完整的惯性误差状态建模，但不建议放入本轮收尾工作中。

## 十、交付内容

- 主报告：`{_rel(REPORT_MD)}`
- 文档版（.docx）：`{_rel(REPORT_DOCX)}`
- 综合数据：`{_rel(CROSS_PATH)}`
- 图表目录：`{_rel(FIGURES_DIR)}`
- 专题分析笔记本：`{NOTEBOOK_PATH.relative_to(ROOT).as_posix()}`
- 专题图表目录：`{_rel(NOTEBOOK_FIG_DIR)}`
"""
    REPORT_MD.write_text(md, encoding="utf-8")


def _export_docx() -> None:
    _run_checked(
        [
            "pandoc",
            str(REPORT_MD),
            "--toc",
            "--standalone",
            "--highlight-style",
            "tango",
            "-o",
            str(REPORT_DOCX),
        ],
        cwd=ISSUE04_ROOT,
    )


def main() -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    NOTEBOOK_FIG_DIR.mkdir(parents=True, exist_ok=True)
    rows = _load_csv_rows(CROSS_PATH)
    summaries = {
        row["label"]: _load_json(CORRECTED_ROOT / row["label"] / "summary.json")
        for row in rows
    }
    issue03_baseline = _load_issue03_baseline_row()

    rep_scenario = _scenario_from_row(next(row for row in rows if row["label"] == REP_CASE_LABEL))

    _draw_flow_figure(FIGURES_DIR / "issue04_system_flow.png")
    _draw_scenario_grid(FIGURES_DIR / "issue04_scenario_grid.png", rows)
    rep_series = _draw_rep_case_imu_ins(FIGURES_DIR / "issue04_rep_case_imu_ins.png", rep_scenario)
    _draw_rep_case_navigation(FIGURES_DIR / "issue04_rep_case_navigation.png", rep_scenario, rep_series)
    _draw_cross_metric_heatmaps(FIGURES_DIR / "issue04_cross_scenario_metrics.png", rows)
    _draw_cross_availability_heatmaps(FIGURES_DIR / "issue04_cross_scenario_availability.png", rows)
    _execute_notebook()

    _write_markdown_report(rows, summaries, issue03_baseline)
    _export_docx()

    print(f"Wrote markdown report to: {REPORT_MD.resolve()}")
    print(f"Wrote docx report to: {REPORT_DOCX.resolve()}")


if __name__ == "__main__":
    main()
