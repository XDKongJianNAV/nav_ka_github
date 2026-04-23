# -*- coding: utf-8 -*-
"""
generate_ka_multifreq_report.py
===============================

基于 `results_ka_multifreq/` 目录下已生成的 CSV / JSON / PNG，
输出一份总览型 Markdown 长报告与短摘要报告。
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from nav_ka import CANONICAL_RESULTS_ROOT
import statistics
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
RESULTS_ROOT = CANONICAL_RESULTS_ROOT / "results_ka_multifreq"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        rows = []
        for row in reader:
            parsed: dict[str, Any] = {}
            for key, value in row.items():
                if value is None:
                    parsed[key] = value
                    continue
                try:
                    scalar = float(value)
                except ValueError:
                    parsed[key] = value
                    continue
                parsed[key] = scalar if math.isfinite(scalar) else value
            rows.append(parsed)
        return rows


def _freq_label(fc_hz: float) -> str:
    return f"{fc_hz / 1e9:.1f}".replace(".", "p") + "GHz"


def _freq_ghz(fc_hz: float) -> float:
    return float(fc_hz) / 1e9


def _freq_display(fc_hz: float) -> str:
    return f"{_freq_ghz(fc_hz):.1f} 吉赫"


def _fmt_number(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int,)):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return "nan"
        if abs(value) >= 1e4 or (0.0 < abs(value) < 1e-3):
            return f"{value:.3e}"
        if abs(value - round(value)) < 1e-9:
            return f"{value:.0f}"
        return f"{value:.3f}"
    return str(value)


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_fmt_number(v) for v in row) + " |")
    return "\n".join(lines)


def _relpath(target: Path, base: Path) -> str:
    return str(target.resolve().relative_to(base.resolve()))


def _image_md(report_path: Path, image_path: Path, alt: str) -> str:
    return f"![{alt}]({Path(_relpath(image_path, report_path.parent)).as_posix()})"


def _link_md(report_path: Path, target_path: Path, label: str) -> str:
    return f"[{label}]({Path(_relpath(target_path, report_path.parent)).as_posix()})"


def _metric_extrema(rows: list[dict[str, Any]], key: str, *, pick: str) -> tuple[float, float]:
    if pick not in {"min", "max"}:
        raise ValueError("pick 必须为 min 或 max")
    ordered = sorted(rows, key=lambda row: float(row[key]), reverse=(pick == "max"))
    best = ordered[0]
    return float(best["frequency_hz"]), float(best[key])


def _select_representative_frequencies(frequencies_hz: list[float]) -> list[float]:
    ordered = sorted(float(v) for v in frequencies_hz)
    selected = [ordered[0]]
    target = 22.5e9
    if any(abs(v - target) <= 1.0 for v in ordered):
        selected.append(min(ordered, key=lambda v: abs(v - target)))
    elif len(ordered) >= 3:
        selected.append(ordered[len(ordered) // 2])
    if ordered[-1] not in selected:
        selected.append(ordered[-1])
    return selected


def _build_context(results_root: Path) -> dict[str, Any]:
    single_summary = _load_json(results_root / "single_channel" / "summary.json")
    summary_path = results_root / "summary.json"
    if summary_path.exists():
        root_summary = _load_json(summary_path)
    else:
        root_summary = {
            "frequencies_hz": list(single_summary["frequencies_hz"]),
            "frequency_labels": list(single_summary["frequency_labels"]),
            "outputs": {
                "results_root": str(results_root.resolve()),
                "single_channel_dir": str((results_root / "single_channel").resolve()),
                "wls_dir": str((results_root / "wls").resolve()),
                "ekf_dir": str((results_root / "ekf").resolve()),
                "cross_frequency_dir": str((results_root / "cross_frequency").resolve()),
                "combined_csv": str((results_root / "cross_frequency" / "combined_metrics.csv").resolve()),
                "combined_json": str((results_root / "cross_frequency" / "combined_metrics.json").resolve()),
                "combined_plot": str((results_root / "cross_frequency" / "combined_metrics_vs_frequency.png").resolve()),
            },
        }
    combined_rows = _load_json(results_root / "cross_frequency" / "combined_metrics.json")
    combined_csv_rows = _load_csv_rows(results_root / "cross_frequency" / "combined_metrics.csv")
    wls_rows = _load_json(results_root / "wls" / "cross_frequency" / "wls_metrics.json")
    ekf_rows = _load_json(results_root / "ekf" / "cross_frequency" / "ekf_metrics.json")

    single_detail_dir = results_root / "single_channel" / "frequency_details"
    single_detail_map: dict[float, dict[str, Any]] = {}
    for path in sorted(single_detail_dir.glob("*.json")):
        detail = _load_json(path)
        single_detail_map[float(detail["frequency_hz"])] = detail

    wls_summary_map: dict[float, dict[str, Any]] = {}
    for fc_hz in root_summary["frequencies_hz"]:
        label = _freq_label(float(fc_hz))
        wls_summary_map[float(fc_hz)] = _load_json(results_root / "wls" / label / "summary.json")

    ekf_summary_map: dict[float, dict[str, Any]] = {}
    for fc_hz in root_summary["frequencies_hz"]:
        label = _freq_label(float(fc_hz))
        ekf_summary_map[float(fc_hz)] = _load_json(results_root / "ekf" / label / "summary.json")

    combined_map = {float(row["frequency_hz"]): row for row in combined_rows}
    return {
        "results_root": results_root,
        "root_summary": root_summary,
        "single_summary": single_summary,
        "combined_rows": combined_rows,
        "combined_csv_rows": combined_csv_rows,
        "combined_map": combined_map,
        "wls_rows": wls_rows,
        "ekf_rows": ekf_rows,
        "single_detail_map": single_detail_map,
        "wls_summary_map": wls_summary_map,
        "ekf_summary_map": ekf_summary_map,
        "representative_frequencies_hz": _select_representative_frequencies(list(root_summary["frequencies_hz"])),
    }


def _build_core_frequency_table(rows: list[dict[str, Any]]) -> str:
    table_rows: list[list[Any]] = []
    for row in rows:
        table_rows.append(
            [
                _freq_ghz(float(row["frequency_hz"])),
                row["single_group_delay_ns_median"],
                row["single_receiver_tau_rmse_ns"],
                row["single_post_corr_snr_median_db"],
                row["wls_case_b_wls_position_error_3d_m"],
                row["wls_monte_carlo_wls_mean_m"],
                row["ekf_pr_doppler_mean_position_error_3d_m"],
                row["ekf_pr_doppler_mean_velocity_error_3d_mps"],
            ]
        )
    return _markdown_table(
        [
            "频率（吉赫）",
            "群时延中位数（纳秒）",
            "单通道码时延均方根误差（纳秒）",
            "后相关信噪比中位数（分贝）",
            "困难场景加权定位三维误差（米）",
            "困难场景统计定位均值（米）",
            "动态滤波三维位置误差（米）",
            "动态滤波三维速度误差（米每秒）",
        ],
        table_rows,
    )


def _build_frequency_trend_table(rows: list[dict[str, Any]]) -> str:
    return _markdown_table(
        [
            "频率（吉赫）",
            "单通道码时延均方根误差（纳秒）",
            "困难场景加权定位三维误差（米）",
            "动态滤波三维位置误差（米）",
            "动态滤波三维速度误差（米每秒）",
        ],
        [
            [
                _freq_ghz(float(row["frequency_hz"])),
                row["single_receiver_tau_rmse_ns"],
                row["wls_case_b_wls_position_error_3d_m"],
                row["ekf_pr_doppler_mean_position_error_3d_m"],
                row["ekf_pr_doppler_mean_velocity_error_3d_mps"],
            ]
            for row in rows
        ],
    )


def _band_definitions() -> list[dict[str, Any]]:
    return [
        {"name": "低频段", "range_text": "19.0 至 22.0 吉赫", "lo_hz": 19.0e9, "hi_hz": 22.0e9},
        {"name": "过渡段", "range_text": "22.5 至 25.5 吉赫", "lo_hz": 22.5e9, "hi_hz": 25.5e9},
        {"name": "高频段", "range_text": "26.0 至 31.0 吉赫", "lo_hz": 26.0e9, "hi_hz": 31.0e9},
    ]


def _rows_in_band(rows: list[dict[str, Any]], band: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in rows if band["lo_hz"] <= float(row["frequency_hz"]) <= band["hi_hz"]]


def _mean_metric(rows: list[dict[str, Any]], key: str) -> float:
    return float(statistics.mean(float(row[key]) for row in rows))


def _median_metric(rows: list[dict[str, Any]], key: str) -> float:
    return float(statistics.median(float(row[key]) for row in rows))


def _build_concept_table() -> str:
    return _markdown_table(
        ["概念", "解释"],
        [
            [
                "几何光学近似传播模型（WKB）",
                "把电磁波在缓变介质中的传播近似写成振幅、相位和群时延三个量，用来描述信号穿过等离子体环境后的传播变化。",
            ],
            [
                "加权最小二乘（WLS）",
                "在定位求解中，让质量更高的观测占更大权重、质量更差的观测占更小权重，从而压低低仰角和低信噪比观测的负面影响。",
            ],
            [
                "扩展卡尔曼滤波（EKF）",
                "一种逐历元递推估计方法，把上一时刻状态预测与当前观测结合起来，同时估计位置、速度和时钟状态。",
            ],
            [
                "群时延",
                "信号包络的传播时间延迟。它反映的是码观测层面更直接感受到的时延变化，而不是单纯的相位转动。",
            ],
            [
                "伪距",
                "导航接收机由码相位恢复出的距离型观测量，除了几何距离，还混有时钟差、传播延迟和测量噪声。",
            ],
            [
                "多普勒",
                "载波频率随相对运动和传播环境变化而发生的偏移，在动态滤波中主要对应距离变化率信息。",
            ],
            [
                "后相关信噪比",
                "接收机完成本地码和载波对准以后，在相关器输出端看到的信号强弱与噪声强弱之比。",
            ],
            [
                "载波锁定指标",
                "用来判断载波跟踪环是否稳定跟住真实载波的诊断量，数值越低说明失锁风险越高。",
            ],
            [
                "均方根误差",
                "把误差先平方、再求平均、再开方得到的整体误差量级，适合描述全时段平均恢复精度。",
            ],
        ],
    )


def _build_summary_tables(context: dict[str, Any]) -> tuple[str, str]:
    rows = context["combined_rows"]
    best_tau_freq, best_tau = _metric_extrema(rows, "single_receiver_tau_rmse_ns", pick="min")
    worst_tau_freq, worst_tau = _metric_extrema(rows, "single_receiver_tau_rmse_ns", pick="max")
    best_wls_freq, best_wls = _metric_extrema(rows, "wls_case_b_wls_position_error_3d_m", pick="min")
    worst_wls_freq, worst_wls = _metric_extrema(rows, "wls_case_b_wls_position_error_3d_m", pick="max")
    best_ekf_freq, best_ekf = _metric_extrema(rows, "ekf_pr_doppler_mean_position_error_3d_m", pick="min")
    worst_ekf_freq, worst_ekf = _metric_extrema(rows, "ekf_pr_doppler_mean_position_error_3d_m", pick="max")

    summary_table = _markdown_table(
        ["项目", "数值"],
        [
            ["频点总数", len(rows)],
            ["频率覆盖范围（吉赫）", f"{_freq_ghz(rows[0]['frequency_hz']):.1f} 至 {_freq_ghz(rows[-1]['frequency_hz']):.1f}"],
            ["综合指标总列数", len(context["combined_csv_rows"][0]) if context["combined_csv_rows"] else 0],
            ["单通道误差最佳频点（吉赫）", _freq_ghz(best_tau_freq)],
            ["单通道误差最佳值（纳秒）", best_tau],
            ["单通道误差最差频点（吉赫）", _freq_ghz(worst_tau_freq)],
            ["单通道误差最差值（纳秒）", worst_tau],
            ["困难场景定位最佳频点（吉赫）", _freq_ghz(best_wls_freq)],
            ["困难场景定位最佳值（米）", best_wls],
            ["困难场景定位最差频点（吉赫）", _freq_ghz(worst_wls_freq)],
            ["困难场景定位最差值（米）", worst_wls],
            ["动态滤波最佳频点（吉赫）", _freq_ghz(best_ekf_freq)],
            ["动态滤波最佳位置误差（米）", best_ekf],
            ["动态滤波最差频点（吉赫）", _freq_ghz(worst_ekf_freq)],
            ["动态滤波最差位置误差（米）", worst_ekf],
        ],
    )
    return summary_table, _build_frequency_trend_table(rows)


def _build_band_summary_table(context: dict[str, Any]) -> str:
    rows = context["combined_rows"]
    table_rows: list[list[Any]] = []
    for band in _band_definitions():
        band_rows = _rows_in_band(rows, band)
        table_rows.append(
            [
                band["name"],
                band["range_text"],
                len(band_rows),
                _mean_metric(band_rows, "single_receiver_tau_rmse_ns"),
                _mean_metric(band_rows, "wls_case_b_wls_position_error_3d_m"),
                _mean_metric(band_rows, "ekf_pr_doppler_mean_position_error_3d_m"),
                _median_metric(band_rows, "ekf_pr_doppler_mean_position_error_3d_m"),
            ]
        )
    return _markdown_table(
        [
            "频段",
            "频率范围",
            "频点数",
            "单通道误差均值（纳秒）",
            "困难场景定位均值（米）",
            "动态滤波位置误差均值（米）",
            "动态滤波位置误差中位数（米）",
        ],
        table_rows,
    )


def _build_band_discussion(context: dict[str, Any]) -> str:
    rows = context["combined_rows"]
    texts: list[str] = []
    for band in _band_definitions():
        band_rows = _rows_in_band(rows, band)
        best_freq, best_val = _metric_extrema(band_rows, "ekf_pr_doppler_mean_position_error_3d_m", pick="min")
        worst_freq, worst_val = _metric_extrema(band_rows, "ekf_pr_doppler_mean_position_error_3d_m", pick="max")
        tau_mean = _mean_metric(band_rows, "single_receiver_tau_rmse_ns")
        wls_mean = _mean_metric(band_rows, "wls_case_b_wls_position_error_3d_m")
        ekf_mean = _mean_metric(band_rows, "ekf_pr_doppler_mean_position_error_3d_m")

        if band["name"] == "低频段":
            explanation = (
                "这一段最突出的问题是单通道码时延恢复误差大，而且不同频点之间起伏明显。"
                "传播层的时延和衰减虽然并不呈现灾难性恶化，但接收机恢复过程对这些变化更敏感，"
                "最终把误差放大到定位层与动态滤波层。"
            )
        elif band["name"] == "过渡段":
            explanation = (
                "这一段体现的是从“可用”向“稳定好用”的过渡。单通道误差继续下降，"
                "困难场景定位误差明显收缩，但仍保留若干局部起伏，说明传播层改善尚未完全转化为稳定的导航层收益。"
            )
        else:
            explanation = (
                "这一段已经进入明显稳定区。单通道误差总体维持在较低水平，"
                "单历元定位误差显著收缩，动态滤波的三维位置误差降到数米甚至一米左右，"
                "说明距离变化率观测在这一段能被更充分地利用。"
            )

        texts.append(
            f"""### {band["name"]}

该频段覆盖 {band["range_text"]}，共 {len(band_rows)} 个频点。

{explanation}

在这一段内：

- 单通道码时延均方根误差均值为 {_fmt_number(tau_mean)} 纳秒。
- 困难场景加权定位三维误差均值为 {_fmt_number(wls_mean)} 米。
- 动态滤波三维位置误差均值为 {_fmt_number(ekf_mean)} 米。
- 动态滤波表现最佳的频点是 {_fmt_number(_freq_ghz(best_freq))} 吉赫，对应位置误差 {_fmt_number(best_val)} 米。
- 动态滤波表现最差的频点是 {_fmt_number(_freq_ghz(worst_freq))} 吉赫，对应位置误差 {_fmt_number(worst_val)} 米。
"""
        )
    return "\n\n".join(texts)


def _build_representative_section(context: dict[str, Any], report_path: Path, fc_hz: float) -> str:
    section_idx = context["representative_frequencies_hz"].index(fc_hz) + 1
    label = _freq_label(fc_hz)
    display_freq = _freq_display(fc_hz)
    single_detail = context["single_detail_map"][fc_hz]
    wls_summary = context["wls_summary_map"][fc_hz]
    ekf_summary = context["ekf_summary_map"][fc_hz]
    combined_row = context["combined_map"][fc_hz]

    wls_a = wls_summary["experiments"]["A"]
    wls_b = wls_summary["experiments"]["B"]
    ekf_runs = ekf_summary["comparison_runs"]

    if math.isclose(fc_hz, 19.0e9, rel_tol=0.0, abs_tol=1.0):
        intro_text = "这一频点代表低频段。它的意义不在于给出最坏值本身，而在于揭示低频端如何把传播层的不利影响放大到接收机恢复与动态估计层。"
    elif math.isclose(fc_hz, 22.5e9, rel_tol=0.0, abs_tol=1.0):
        intro_text = "这一频点代表过渡段，也是此前工作最常用的参考频点。它适合用来比较“旧单频工作流”与“新全频工作流”之间的解释差异。"
    else:
        intro_text = "这一频点代表高频段。它最能体现高频端在单通道恢复、困难场景定位和动态滤波三层上的联合改善。"

    single_table = _markdown_table(
        ["单通道指标", "数值"],
        [
            ["传播振幅中位数", single_detail["wkb"]["amplitude_median"]],
            ["传播衰减中位数（分贝）", single_detail["wkb"]["attenuation_db_median"]],
            ["传播相位中位数（弧度）", single_detail["wkb"]["phase_rad_median"]],
            ["群时延中位数（纳秒）", single_detail["wkb"]["group_delay_ns_median"]],
            ["码时延均方根误差（纳秒）", single_detail["metrics"]["tau_rmse_ns"]],
            ["频率恢复均方根误差（赫兹）", single_detail["metrics"]["fd_rmse_hz"]],
            ["主峰与次峰差值（分贝）", single_detail["metrics"]["peak_to_second_db"]],
            ["后相关信噪比中位数（分贝）", single_detail["metrics"]["post_corr_snr_median_db"]],
            ["载波锁定指标中位数", single_detail["metrics"]["carrier_lock_metric_median"]],
            ["失锁占比", single_detail["metrics"]["loss_fraction"]],
        ],
    )

    wls_table = _markdown_table(
        ["单历元定位指标", "数值"],
        [
            ["群时延中位数（米）", wls_summary["legacy_channel_metrics"]["tau_g_median_m"]],
            ["单通道伪距一秒平滑标准差（米）", wls_summary["legacy_channel_metrics"]["effective_pseudorange_sigma_1s_m"]],
            ["场景甲普通最小二乘三维误差（米）", wls_a["ls"]["position_error_3d_m"]],
            ["场景甲加权最小二乘三维误差（米）", wls_a["wls"]["position_error_3d_m"]],
            ["场景乙普通最小二乘三维误差（米）", wls_b["ls"]["position_error_3d_m"]],
            ["场景乙加权最小二乘三维误差（米）", wls_b["wls"]["position_error_3d_m"]],
            ["场景甲位置精度因子", wls_a["dops"]["PDOP"]],
            ["场景乙位置精度因子", wls_b["dops"]["PDOP"]],
            ["困难场景统计定位均值（米）", wls_summary["monte_carlo"]["stats"]["WLS"]["mean_m"]],
            ["困难场景统计定位九成分位值（米）", wls_summary["monte_carlo"]["stats"]["WLS"]["p90_m"]],
        ],
    )

    ekf_table = _markdown_table(
        ["动态滤波指标", "数值"],
        [
            ["单历元基线平均三维误差（米）", ekf_runs["epoch_wls"]["mean_position_error_3d_m"]],
            ["仅伪距动态滤波平均三维误差（米）", ekf_runs["ekf_pr_only"]["mean_position_error_3d_m"]],
            ["伪距加距离变化率动态滤波平均三维误差（米）", ekf_runs["ekf_pr_doppler"]["mean_position_error_3d_m"]],
            ["伪距加距离变化率动态滤波平均三维速度误差（米每秒）", ekf_runs["ekf_pr_doppler"]["mean_velocity_error_3d_mps"]],
            ["伪距加距离变化率动态滤波平均伪距新息（米）", ekf_runs["ekf_pr_doppler"]["mean_innovation_pr_m"]],
            ["伪距加距离变化率动态滤波平均距离变化率新息（米每秒）", ekf_runs["ekf_pr_doppler"]["mean_innovation_rr_mps"]],
            ["仅预测历元数", ekf_runs["ekf_pr_doppler"]["prediction_only_epochs"]],
            ["动态距离变化率一百毫秒标准差（米每秒）", ekf_summary["legacy_channel_metrics"]["dynamic_range_rate_sigma_100ms_mps"]],
        ],
    )

    single_spectrum = context["results_root"] / "single_channel" / "receiver_spectra" / f"{label}_receiver_spectrum.png"
    wls_legacy = context["results_root"] / "wls" / label / "legacy_channel_overview.png"
    wls_residual = context["results_root"] / "wls" / label / "ls_vs_wls_residuals.png"
    wls_mc = context["results_root"] / "wls" / label / "monte_carlo_position_error.png"
    ekf_traj = context["results_root"] / "ekf" / label / "trajectory_error.png"
    ekf_innov = context["results_root"] / "ekf" / label / "innovation_timeseries.png"
    ekf_vs_wls = context["results_root"] / "ekf" / label / "filter_vs_epoch_wls.png"

    return f"""### 8.{section_idx} 代表频点 {display_freq} 的层间证据

{intro_text}

#### 8.{section_idx}.1 该频点的综合位置

{_markdown_table(
    ["指标", "数值"],
    [
        ["单通道码时延均方根误差（纳秒）", combined_row["single_receiver_tau_rmse_ns"]],
        ["单通道后相关信噪比中位数（分贝）", combined_row["single_post_corr_snr_median_db"]],
        ["困难场景加权定位三维误差（米）", combined_row["wls_case_b_wls_position_error_3d_m"]],
        ["动态滤波三维位置误差（米）", combined_row["ekf_pr_doppler_mean_position_error_3d_m"]],
        ["动态滤波三维速度误差（米每秒）", combined_row["ekf_pr_doppler_mean_velocity_error_3d_mps"]],
    ],
)}

#### 8.{section_idx}.2 单通道传播与恢复

{single_table}

{_image_md(report_path, single_spectrum, f"{display_freq} 单通道频谱图")}

这一层回答的是：传播层变化进入接收机以后，最终会不会转化为码时延恢复误差、频率恢复误差和失锁风险的抬升。

#### 8.{section_idx}.3 单历元定位

{wls_table}

{_image_md(report_path, wls_legacy, f"{display_freq} 单历元定位背景图")}

{_image_md(report_path, wls_residual, f"{display_freq} 单历元定位残差图")}

{_image_md(report_path, wls_mc, f"{display_freq} 单历元定位统计图")}

这一层回答的是：在同一传播背景之下，低权重观测是否会把困难场景误差显著放大，以及加权求解能否把这种放大压下去。

#### 8.{section_idx}.4 动态滤波

{ekf_table}

{_image_md(report_path, ekf_traj, f"{display_freq} 动态滤波轨迹误差图")}

{_image_md(report_path, ekf_innov, f"{display_freq} 动态滤波新息图")}

{_image_md(report_path, ekf_vs_wls, f"{display_freq} 动态滤波与单历元基线对比图")}

这一层回答的是：在连续历元条件下，伪距和距离变化率是否能形成稳定互补，以及这种互补在该频点上发挥到了什么程度。
"""


def _build_band_appendix_table(
    context: dict[str, Any],
    report_path: Path,
    band: dict[str, Any],
) -> str:
    rows = _rows_in_band(context["combined_rows"], band)
    table_rows: list[list[Any]] = []
    for row in rows:
        fc_hz = float(row["frequency_hz"])
        label = _freq_label(fc_hz)
        table_rows.append(
            [
                _freq_ghz(fc_hz),
                row["single_receiver_tau_rmse_ns"],
                row["wls_case_b_wls_position_error_3d_m"],
                row["ekf_pr_doppler_mean_position_error_3d_m"],
                _link_md(report_path, context["results_root"] / "single_channel" / "frequency_details" / f"{label}.json", "单通道明细"),
                _link_md(report_path, context["results_root"] / "wls" / label / "summary.json", "单历元摘要"),
                _link_md(report_path, context["results_root"] / "ekf" / label / "summary.json", "动态摘要"),
            ]
        )
    return _markdown_table(
        [
            "频率（吉赫）",
            "单通道误差（纳秒）",
            "困难场景定位误差（米）",
            "动态滤波位置误差（米）",
            "单通道文件",
            "单历元文件",
            "动态文件",
        ],
        table_rows,
    )


def write_report_summary_md(context: dict[str, Any], output_path: Path) -> None:
    summary_table, _ = _build_summary_tables(context)
    text = f"""# 泛卡频段全频传播与导航实验摘要

## 一、工作概述

本次工作把原先集中在单一频点上的分析扩展为整个频带上的系统性分析，形成了以下三层统一结果：

1. 真实传播层与单通道接收机恢复层
2. 单历元定位层
3. 多历元动态滤波层

## 二、总体结论

{summary_table}

## 三、结论边界

本摘要所代表的是：在真实单通道传播背景之上构建的多层混合式导航实验。

它能够说明频率变化对传播恢复、单历元定位和动态估计的影响规律，但不等同于真实多星端到端系统的最终工程定标。
"""
    output_path.write_text(text, encoding="utf-8")


def write_report_full_md(context: dict[str, Any], output_path: Path) -> None:
    summary_table, trend_table = _build_summary_tables(context)
    results_root = context["results_root"]
    single_summary = context["single_summary"]
    representative_sections = "\n\n".join(
        _build_representative_section(context, output_path, float(fc_hz))
        for fc_hz in context["representative_frequencies_hz"]
    )

    band_appendices: list[str] = []
    for idx, band in enumerate(_band_definitions(), start=2):
        band_rows = _rows_in_band(context["combined_rows"], band)
        band_appendices.append(
            f"""## 11.{idx} {band["name"]}附录

该频段覆盖 {band["range_text"]}，共 {len(band_rows)} 个频点。附录仅保留该频段的核心数值和对应文件索引，正文不再逐频点展开长段解释。

{_build_band_appendix_table(context, output_path, band)}
"""
        )

    text = f"""# 泛卡频段全频真实传播、单历元加权定位与动态滤波研究报告

## 1. 摘要

本报告围绕 `results_ka_multifreq` 中已经生成的正式全频结果展开，研究对象是 `19.0` 至 `31.0` 吉赫之间、步长 `0.5` 吉赫的二十五个频点。

本次工作的核心不再是单一 `22.5` 吉赫频点，而是把“传播层变化如何沿着接收机恢复、单历元定位和动态滤波一路传递”这个问题，放到整个频带中统一观察。

主要数值概览如下：

{summary_table}

从总体结果看，频率升高以后，单通道码时延恢复误差、困难场景定位误差和动态滤波位置误差都呈现出明显改善，但改善并不是严格单调，而是“整体下降趋势之上叠加局部起伏”。

## 2. 引言

在前一阶段的工作中，许多实验和说明都默认围绕 `22.5` 吉赫这一参考频点展开。这样的做法有一个明显局限：它只能说明某个点的行为，却不能回答整个频带的规律。

如果后续算法设计、参数整定和试验判断都建立在单点观察之上，就会出现三个问题：

1. 传播层结论难以推广到整个频带。
2. 接收机恢复层的敏感频段无法被识别。
3. 导航层改进到底是“普遍有效”还是“仅对某个频点有效”无法区分。

因此，本报告把频率本身提升为主分析维度，目的是回答以下三个问题：

1. 真实传播量随频率变化时，哪些量最先发生系统性变化。
2. 这些变化经过接收机恢复以后，是否会放大为单历元定位误差。
3. 在连续历元的动态估计中，频率升高是否会带来更加稳定的速度和位置约束。

## 3. 研究背景与关键概念解释

### 3.1 研究对象

本报告研究的是“真实单通道传播背景之上的多层导航实验”。这里的“多层”指三层：

1. 传播与接收层
2. 单历元定位层
3. 多历元动态估计层

### 3.2 关键概念

{_build_concept_table()}

### 3.3 结果边界

本报告必须严格保持以下边界：

1. 单通道传播与接收机恢复是直接复用的真实链路。
2. 多星几何和动态轨迹仍是自洽构造，不是广播星历与真实飞行轨迹。
3. 各卫星没有独立的真实传播路径，而是共享单通道真实背景后再映射到导航层。
4. 因此，本报告用于揭示频率规律，而不是用于宣布真实系统的最终工程定标。

## 4. 数据来源与实验链路

### 4.1 数据基线

{_markdown_table(
    ["项目", "数值"],
    [
        ["频率覆盖范围（吉赫）", f"{_freq_ghz(float(context['root_summary']['frequencies_hz'][0])):.1f} 至 {_freq_ghz(float(context['root_summary']['frequencies_hz'][-1])):.1f}"],
        ["频点总数", len(context["root_summary"]["frequencies_hz"])],
        ["接收机采样率（赫兹）", single_summary["receiver_config"]["fs_hz"]],
        ["码率（赫兹）", single_summary["receiver_config"]["chip_rate_hz"]],
        ["相干积分时间（秒）", single_summary["receiver_config"]["coherent_integration_s"]],
        ["扩频码长度", single_summary["receiver_config"]["code_length"]],
        ["名义载噪比（分贝赫兹）", single_summary["receiver_config"]["cn0_dbhz"]],
        ["综合指标列数", len(context["combined_csv_rows"][0]) if context["combined_csv_rows"] else 0],
    ],
)}

### 4.2 三层链路

本次实验链路可概括为：

```
电子密度场
  -> 真实传播振幅、相位、群时延
  -> 单通道接收机捕获与跟踪
  -> 单通道伪距、载波与多普勒观测
  -> 多星标准伪距形成
  -> 单历元加权定位
  -> 多历元动态滤波
  -> 全频综合指标与研究报告
```

这种组织方式的意义在于：每一层都可以单独观察，但又能够沿着同一条链路向下传递影响。

## 5. 全频总体结果

### 5.1 传播层与接收层的总体形态

{_image_md(output_path, results_root / "single_channel" / "wkb_multifreq_overview.png", "全频传播热图")}

传播热图同时展示了振幅、衰减、相位和群时延随时间与频率的二维变化。它揭示了一个重要事实：频率变化并不是只影响某一个量，而是同时改变信号的传播强度、相位积累和码观测相关的时间延迟。

{_image_md(output_path, results_root / "single_channel" / "wkb_multifreq_frequency_summary.png", "全频传播频率趋势图")}

频率趋势图进一步把二维变化压缩到单一频率轴上，使得“随着频率升高，哪些量整体下降、哪些量只是局部波动”变得一目了然。

### 5.2 三层核心指标长表

{_build_core_frequency_table(context["combined_rows"])}

上表是全报告最重要的总表之一，因为它把传播层、单历元定位层和动态滤波层放在同一条频率轴上。读这张表时要注意：

1. 单通道码时延均方根误差是接收机恢复层最核心的桥接指标。
2. 困难场景加权定位三维误差是单历元导航层最敏感的放大镜。
3. 动态滤波三维位置误差体现的是多历元条件下最终可达到的估计水平。

### 5.3 总体趋势解释

{trend_table}

从全频长表可以总结出三条总体规律：

1. 单通道码时延恢复误差在低频段明显偏大，在高频段显著收缩。
2. 困难场景单历元定位误差随频率升高总体下降，但中间存在若干局部反弹点。
3. 动态滤波位置误差在高频段压缩得最明显，说明距离变化率观测与较稳定的传播恢复在该段形成了更强的互补。

但是，上述趋势都不应写成“频率越高越好”的简单口号。现有数据里存在明显局部起伏，例如 `19.5`、`20.0`、`21.5`、`22.0`、`25.0`、`29.5` 和 `30.0` 吉赫附近都表现出不同程度的波动，这说明传播层变化进入导航层以后还会受到几何、权重和动态滤波门控的共同影响。

## 6. 分层结果分析

### 6.1 单通道传播与恢复层

在这一层，最值得关注的不是单独某一个传播量，而是“传播量的变化最终是否变成了接收机可见的恢复误差”。现有结果表明：

1. 群时延中位数从低频端到高频端整体变化不算剧烈。
2. 但是码时延恢复误差却在低频端明显偏大。
3. 这说明接收机恢复层对传播变化的响应并不是线性的直接映射。

换言之，传播层的变化先进入捕获与跟踪环，再由环路把它转化为码时延恢复误差、频率恢复误差和锁定稳定性差异。因此，只看传播层本身的量级，无法完整解释导航层的误差差异。

### 6.2 单历元加权定位层

{_image_md(output_path, results_root / "wls" / "cross_frequency" / "wls_metrics_vs_frequency.png", "单历元定位全频趋势图")}

单历元定位层的核心观察对象是困难场景。困难场景中包含更多低仰角观测，因此对观测质量差异更敏感，更适合用来观察频率变化如何放大到定位误差。

这一层的结果说明：

1. 当单通道伪距统计较差时，即便加权求解存在，也很难把误差完全压住。
2. 当单通道统计改善后，加权求解可以更有效地抑制低质量观测带来的误差放大。
3. 因此，单历元加权定位的改善既依赖传播恢复层，也依赖权重映射本身。

### 6.3 多历元动态滤波层

{_image_md(output_path, results_root / "ekf" / "cross_frequency" / "ekf_metrics_vs_frequency.png", "动态滤波全频趋势图")}

多历元动态滤波层最关键的结论是：加入距离变化率观测以后，高频段的改进非常显著。

这背后的逻辑是：

1. 单通道恢复更稳定时，距离变化率观测更容易形成有效约束。
2. 动态滤波可以把相邻历元信息串起来，因此比单历元求解更能消化局部噪声扰动。
3. 当传播恢复层和距离变化率观测都比较稳定时，位置误差会快速压缩到很低水平。

## 7. 频段分区结论

### 7.1 分区依据

本报告不做任意切段，而是固定按以下三段组织讨论：

1. 低频段：`19.0` 至 `22.0` 吉赫
2. 过渡段：`22.5` 至 `25.5` 吉赫
3. 高频段：`26.0` 至 `31.0` 吉赫

这样分区的原因是：现有全频结果已经显示，低频段、过渡段和高频段在单通道恢复、单历元定位和动态滤波三层上都呈现出可区分的统计行为。

### 7.2 分区统计总表

{_build_band_summary_table(context)}

### 7.3 分区讨论

{_build_band_discussion(context)}

## 8. 代表频点对比

代表频点固定为 `19.0`、`22.5` 和 `31.0` 吉赫，分别对应低频段、过渡段和高频段的典型行为。

{representative_sections}

## 9. 讨论与局限

### 9.1 为什么高频段总体更优

从现有结果看，高频段总体更优并不只是因为某一个传播量单独变好了，而是因为以下三层因素同时朝有利方向变化：

1. 接收机恢复层的码时延误差整体收缩。
2. 单历元定位层在困难场景中的误差放大幅度下降。
3. 动态滤波层可以更稳定地利用距离变化率信息。

### 9.2 为什么仍会出现局部波动

局部波动并不意味着总体趋势失效，而说明系统是多因素耦合的：

1. 传播层变化本身不是严格线性单调。
2. 单历元求解还会受到几何和权重映射影响。
3. 动态滤波则进一步受到观测门控和仅预测历元的影响。

因此，本报告采用的是“总体趋势加局部波动”的解释框架，而不是简单的单调结论。

### 9.3 本报告不能替代什么

本报告不能替代真实多星端到端系统定标，原因在于：

1. 多星几何不是广播星历。
2. 各卫星没有独立真实传播路径。
3. 动态轨迹不是实飞轨迹。

但本报告已经足够支撑后续的两类工作：

1. 把后续笔记本和实验从单频点扩展为全频分析。
2. 为更进一步的真实星历、真实轨迹和独立传播路径扩展提供频率侧依据。

## 10. 结论

本次全频研究最重要的结论可以压缩为四点：

1. 频率不能再被视为一个固定常数，而必须被视为主实验维度。
2. 单通道传播恢复误差是传播层影响导航层的关键中间环节。
3. 困难场景单历元定位对频率变化高度敏感，因此非常适合作为跨频比较基准。
4. 动态滤波在高频段展现出最稳定的优势，说明高频段更容易把传播层改善转化成连续历元定位收益。

## 11. 附录

### 11.1 全频核心指标总表

{_build_core_frequency_table(context["combined_rows"])}

{chr(10).join(band_appendices)}

## 12. 数据文件与图像索引

完整跨层综合指标位于：

- `{_relpath(results_root / 'cross_frequency' / 'combined_metrics.csv', output_path.parent)}`
- `{_relpath(results_root / 'cross_frequency' / 'combined_metrics.json', output_path.parent)}`

分层统计文件位于：

- `{_relpath(results_root / 'wls' / 'cross_frequency' / 'wls_metrics.csv', output_path.parent)}`
- `{_relpath(results_root / 'ekf' / 'cross_frequency' / 'ekf_metrics.csv', output_path.parent)}`

关键图像位于：

- `{_relpath(results_root / 'single_channel' / 'wkb_multifreq_overview.png', output_path.parent)}`
- `{_relpath(results_root / 'single_channel' / 'wkb_multifreq_frequency_summary.png', output_path.parent)}`
- `{_relpath(results_root / 'wls' / 'cross_frequency' / 'wls_metrics_vs_frequency.png', output_path.parent)}`
- `{_relpath(results_root / 'ekf' / 'cross_frequency' / 'ekf_metrics_vs_frequency.png', output_path.parent)}`
- `{_relpath(results_root / 'cross_frequency' / 'combined_metrics_vs_frequency.png', output_path.parent)}`
"""
    output_path.write_text(text, encoding="utf-8")


def generate_reports(results_root: Path | None = None) -> dict[str, Path]:
    root = results_root if results_root is not None else RESULTS_ROOT
    context = _build_context(root)
    summary_path = root / "report_summary.md"
    full_path = root / "report_full.md"
    write_report_summary_md(context, summary_path)
    write_report_full_md(context, full_path)
    return {
        "summary_md": summary_path,
        "full_md": full_path,
    }


def main() -> None:
    outputs = generate_reports(RESULTS_ROOT)
    print(f"summary_md = {outputs['summary_md']}")
    print(f"full_md = {outputs['full_md']}")


if __name__ == "__main__":
    main()
