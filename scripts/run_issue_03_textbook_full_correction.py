# -*- coding: utf-8 -*-
"""
run_issue_03_textbook_full_correction.py
=======================================

Issue 03: 在 Issue 01 去真值依赖的基础上，按教材分层重建
signal -> receiver natural measurements -> standard observables -> WLS/EKF
并与 legacy / issue01 结果统一比较。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from nav_ka import CANONICAL_RESULTS_ROOT, CORRECTIONS_ROOT
from nav_ka.legacy import exp_dynamic_multisat_ekf_report as ekf_mod
from nav_ka.legacy import exp_multisat_wls_pvt_report as wls_mod
from nav_ka.legacy import generate_ka_multifreq_report as report_mod
from nav_ka.studies.issue_01_truth_dependency import load_json, write_csv_rows, write_json
from nav_ka.studies.issue_03_textbook_correction import (
    DEFAULT_COMPARISON_KEYS,
    build_three_way_rows,
    run_textbook_single_channel_frequency_grid,
    write_three_way_plot,
)

ROOT = Path(__file__).resolve().parents[1]
from scripts import run_ka_multifreq_full_stack as baseline_runner


FREQUENCIES_HZ = np.arange(19.0e9, 31.0e9 + 0.25e9, 0.5e9)
CORRECTION_ROOT = CORRECTIONS_ROOT / "issue_03_textbook_full_correction"
CORRECTED_ROOT = CORRECTION_ROOT / "corrected_fullstack"
COMPARISON_DIR = CORRECTION_ROOT / "comparison"
NOTES_DIR = CORRECTION_ROOT / "notes"
SINGLE_DIR = CORRECTED_ROOT / "single_channel"
OBSERVABLES_DIR = CORRECTED_ROOT / "observables"
WLS_DIR = CORRECTED_ROOT / "wls"
EKF_DIR = CORRECTED_ROOT / "ekf"
CROSS_DIR = CORRECTED_ROOT / "cross_frequency"
BASELINE_ROOT = CANONICAL_RESULTS_ROOT / "results_ka_multifreq"
ISSUE01_ROOT = CORRECTIONS_ROOT / "issue_01_truth_dependency" / "corrected_fullstack"


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


def _mean_delta(lhs_rows: Sequence[dict[str, Any]], rhs_rows: Sequence[dict[str, Any]], key: str) -> float:
    lhs_map = {float(row["frequency_hz"]): row for row in lhs_rows}
    rhs_map = {float(row["frequency_hz"]): row for row in rhs_rows}
    values = [float(lhs_map[fc_hz][key]) - float(rhs_map[fc_hz][key]) for fc_hz in sorted(set(lhs_map) & set(rhs_map))]
    return float(np.mean(np.asarray(values, dtype=float)))


def _representative_row(rows: Sequence[dict[str, Any]], fc_hz: float) -> dict[str, Any]:
    for row in rows:
        if abs(float(row["frequency_hz"]) - fc_hz) <= 1.0:
            return row
    raise KeyError(fc_hz)


def _build_three_way_summary(
    legacy_rows: Sequence[dict[str, Any]],
    issue01_rows: Sequence[dict[str, Any]],
    issue03_rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "frequencies_hz": [float(row["frequency_hz"]) for row in legacy_rows],
        "metrics": {},
        "roots": {
            "legacy": str(BASELINE_ROOT.resolve()),
            "issue01": str(ISSUE01_ROOT.resolve()),
            "issue03": str(CORRECTED_ROOT.resolve()),
        },
    }
    for key in DEFAULT_COMPARISON_KEYS:
        summary["metrics"][key] = {
            "mean_delta_issue01_vs_legacy": _mean_delta(issue01_rows, legacy_rows, key),
            "mean_delta_issue03_vs_issue01": _mean_delta(issue03_rows, issue01_rows, key),
            "mean_delta_issue03_vs_legacy": _mean_delta(issue03_rows, legacy_rows, key),
        }
    return summary


def _write_textbook_alignment_changes_md(output_path: Path) -> None:
    lines = [
        "# Issue 03: 教材对齐修正清单",
        "",
        "## 本轮新增的正式层次",
        "",
        "1. `signal model`：把导航数据符号真实加入发射/接收信号对象。",
        "2. `receiver natural measurements`：接收机层只输出 `tau_est_s / carrier_phase_rad / carrier_frequency_hz`。",
        "3. `observable formation`：新增标准伪距、载波相位、距离率形成层。",
        "4. `navigation`：WLS/EKF 继续使用 truth-free 初始化，但只消费标准观测。",
        "",
        "## 与 legacy / issue01 的关系",
        "",
        "- legacy：存在运行时真值依赖，并在接收机层把内部状态直接命名为观测。",
        "- issue01：去掉了真值依赖，但仍保留未完全教材化的信号/观测接口。",
        "- issue03：在 issue01 基础上继续修正信号对象、环路结构表达和观测形成边界。",
        "",
        "## 代码层落点",
        "",
        "- `src/nav_ka/studies/issue_03_textbook_correction.py`：Issue 03 corrected 单通道、自然测量量、标准观测和三方对比工具。",
        "- `src/nav_ka/legacy/exp_multisat_wls_pvt_report.py`：新增 `channel_background_mode`，允许 WLS 使用 corrected 背景。",
        "- `src/nav_ka/legacy/exp_dynamic_multisat_ekf_report.py`：新增 `channel_background_mode`，允许 EKF 使用 corrected 背景。",
        "",
        "## 默认口径",
        "",
        "- `truth_free_runtime=True`",
        "- `truth_free_initialization=True`",
        "- `channel_background_mode=issue03_textbook`",
        "- `nav_data_enabled=True`",
        "",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _write_illegal_item_impact_review_md(
    output_path: Path,
    legacy_rows: Sequence[dict[str, Any]],
    issue01_rows: Sequence[dict[str, Any]],
    issue03_rows: Sequence[dict[str, Any]],
) -> None:
    rep_freqs = [19.0e9, 22.5e9, 25.0e9, 31.0e9]
    legacy_map = {float(row["frequency_hz"]): row for row in legacy_rows}
    issue01_map = {float(row["frequency_hz"]): row for row in issue01_rows}
    issue03_map = {float(row["frequency_hz"]): row for row in issue03_rows}

    def fmt_delta(row_map_a: dict[float, dict[str, Any]], row_map_b: dict[float, dict[str, Any]], fc_hz: float, key: str) -> str:
        return f"{float(row_map_a[fc_hz][key]) - float(row_map_b[fc_hz][key]):.3f}"

    lines = [
        "# Issue 03: 不合法 / 不标准项影响复核",
        "",
        "本文件采用三段对比口径：",
        "",
        "- `legacy -> issue01`：隔离真值依赖的影响。",
        "- `issue01 -> issue03`：隔离教材分层修正后的影响。",
        "- `legacy -> issue03`：观察从原始实现到教材修正版的总效果。",
        "",
        "## 1. 运行时真值注入",
        "",
        "教材标准：环路应由相关器输出和内部状态驱动，不应由真值动态直接稳定。",
        "",
        f"- `single_tau_rmse_ns` 平均变化（issue01 - legacy）= {_mean_delta(issue01_rows, legacy_rows, 'single_tau_rmse_ns'):.3f}",
        f"- `wls_case_b_wls_position_error_3d_m` 平均变化（issue01 - legacy）= {_mean_delta(issue01_rows, legacy_rows, 'wls_case_b_wls_position_error_3d_m'):.3f}",
        f"- `ekf_pr_doppler_mean_position_error_3d_m` 平均变化（issue01 - legacy）= {_mean_delta(issue01_rows, legacy_rows, 'ekf_pr_doppler_mean_position_error_3d_m'):.3f}",
        "",
        "说明：这一步已经在 Issue 01 完成，Issue 03 直接继承其 truth-free 运行边界。",
        "",
        "## 2. 信号层未真实包含导航数据",
        "",
        "教材标准：若宣称数据分量存在，则信号对象中必须真实包含数据调制，而不是只停留在配置层。",
        "",
        f"- `single_fd_rmse_hz` 平均变化（issue03 - issue01）= {_mean_delta(issue03_rows, issue01_rows, 'single_fd_rmse_hz'):.3f}",
        f"- `single_tau_rmse_ns` 平均变化（issue03 - issue01）= {_mean_delta(issue03_rows, issue01_rows, 'single_tau_rmse_ns'):.3f}",
        "",
        "说明：Issue 03 把 `nav_data_enabled` 真实注入了 BPSK 数据符号，当前结果反映的是加入数据分量后，捕获/跟踪/WLS/EKF 的整体变化。",
        "",
        "## 3. 接收机层把自然测量量直接命名为标准观测",
        "",
        "教材标准：接收机层先输出 natural measurements，标准伪距和距离率必须在独立的观测形成层内构造。",
        "",
        f"- `wls_case_b_wls_position_error_3d_m` 平均变化（issue03 - issue01）= {_mean_delta(issue03_rows, issue01_rows, 'wls_case_b_wls_position_error_3d_m'):.3f}",
        f"- `ekf_pr_doppler_mean_position_error_3d_m` 平均变化（issue03 - issue01）= {_mean_delta(issue03_rows, issue01_rows, 'ekf_pr_doppler_mean_position_error_3d_m'):.3f}",
        "",
        "说明：数值变化代表 formal observables 接入导航层后的总影响；更重要的是接口资格被恢复，WLS/EKF 不再消费原始环路状态。",
        "",
        "## 4. 环路结构只靠整体工程控制律表达",
        "",
        "教材标准：应把 discriminator、loop filter、NCO/state propagation 拆开，而不是只留下整段更新律。",
        "",
        f"- `single_fd_rmse_hz` 平均变化（issue03 - issue01）= {_mean_delta(issue03_rows, issue01_rows, 'single_fd_rmse_hz'):.3f}",
        f"- `ekf_pr_doppler_mean_velocity_error_3d_mps` 平均变化（issue03 - issue01）= {_mean_delta(issue03_rows, issue01_rows, 'ekf_pr_doppler_mean_velocity_error_3d_mps'):.3f}",
        "",
        "说明：Issue 03 将 carrier/code loop 重写为显式的判别器-滤波器-NCO 更新结构，这一比较反映它对前端和动态层的联动影响。",
        "",
        "## 5. 代表频点",
        "",
        "| 频点 | `tau RMSE` issue03-issue01 (ns) | `fd RMSE` issue03-issue01 (Hz) | WLS Case B issue03-issue01 (m) | EKF PR+D pos issue03-issue01 (m) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for fc_hz in rep_freqs:
        lines.append(
            "| "
            + f"{fc_hz / 1e9:.1f} GHz | "
            + f"{fmt_delta(issue03_map, issue01_map, fc_hz, 'single_tau_rmse_ns')} | "
            + f"{fmt_delta(issue03_map, issue01_map, fc_hz, 'single_fd_rmse_hz')} | "
            + f"{fmt_delta(issue03_map, issue01_map, fc_hz, 'wls_case_b_wls_position_error_3d_m')} | "
            + f"{fmt_delta(issue03_map, issue01_map, fc_hz, 'ekf_pr_doppler_mean_position_error_3d_m')} |"
        )
    lines.extend(
        [
            "",
            "## 6. 结论",
            "",
            "Issue 03 的核心不只是继续优化数值，而是把 signal / receiver / observable / navigation 的对象边界重新立起来。",
            "如果某些频点数值变差，报告口径仍然是：教材约束恢复后暴露了真实性能，而不是系统被“做坏了”。",
        ]
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _write_impact_matrix_md(
    output_path: Path,
    three_way_summary: dict[str, Any],
) -> None:
    metrics = three_way_summary["metrics"]
    lines = [
        "# Issue 03 Impact Matrix",
        "",
        "| 问题项 | 教材金标准 | 对比口径 | 关键指标变化 | 解释 |",
        "| --- | --- | --- | --- | --- |",
        "| 运行时真值注入 | 环路只能由观测与内部状态驱动 | legacy -> issue01 | "
        f"`tau` mean Δ = {metrics['single_tau_rmse_ns']['mean_delta_issue01_vs_legacy']:.3f}, "
        f"WLS mean Δ = {metrics['wls_case_b_wls_position_error_3d_m']['mean_delta_issue01_vs_legacy']:.3f} | "
        "去掉 truth stabilization 后，独立性恢复，低频脆弱区暴露。 |",
        "| 信号层未真实包含导航数据 | data-bearing signal 必须真的进信号对象 | issue01 -> issue03 | "
        f"`tau` mean Δ = {metrics['single_tau_rmse_ns']['mean_delta_issue03_vs_issue01']:.3f}, "
        f"`fd` mean Δ = {metrics['single_fd_rmse_hz']['mean_delta_issue03_vs_issue01']:.3f} | "
        "Issue 03 把 data bit 纳入接收块，前端性能变化开始反映真实 data-bearing channel。 |",
        "| 自然测量量与标准观测混层 | observables 必须独立形成 | issue01 -> issue03 | "
        f"WLS mean Δ = {metrics['wls_case_b_wls_position_error_3d_m']['mean_delta_issue03_vs_issue01']:.3f}, "
        f"EKF pos mean Δ = {metrics['ekf_pr_doppler_mean_position_error_3d_m']['mean_delta_issue03_vs_issue01']:.3f} | "
        "导航层开始只消费 formal observables，解释资格恢复。 |",
        "| 环路结构只剩工程控制律 | discriminator / filter / NCO 应可分离建模 | issue01 -> issue03 | "
        f"`fd` mean Δ = {metrics['single_fd_rmse_hz']['mean_delta_issue03_vs_issue01']:.3f}, "
        f"EKF vel mean Δ = {metrics['ekf_pr_doppler_mean_velocity_error_3d_mps']['mean_delta_issue03_vs_issue01']:.3f} | "
        "结构化 carrier/code loop 后，前端和动态层的耦合变化可被单独解释。 |",
        "",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    CORRECTED_ROOT.mkdir(parents=True, exist_ok=True)
    COMPARISON_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 100)
    print("Issue 03: 教材金标准全链路修正")
    print("=" * 100)
    print(f"频点数 = {len(FREQUENCIES_HZ)}")

    print("\n[1/4] 教材修正版单通道与观测形成")
    run_textbook_single_channel_frequency_grid(
        FREQUENCIES_HZ.tolist(),
        single_output_dir=SINGLE_DIR,
        observables_output_dir=OBSERVABLES_DIR,
        truth_free_runtime=True,
        nav_data_enabled=True,
    )
    single_rows = _read_single_rows(SINGLE_DIR)

    print("\n[2/4] WLS 教材修正版全频点")
    wls_result = wls_mod.run_wls_frequency_grid(
        FREQUENCIES_HZ.tolist(),
        root_output_dir=WLS_DIR,
        truth_free_runtime=True,
        truth_free_initialization=True,
        channel_background_mode="issue03_textbook",
    )
    wls_rows = list(wls_result["rows"])

    print("\n[3/4] EKF 教材修正版全频点")
    ekf_result = ekf_mod.run_dynamic_ekf_frequency_grid(
        FREQUENCIES_HZ.tolist(),
        root_output_dir=EKF_DIR,
        truth_free_runtime=True,
        truth_free_initialization=True,
        channel_background_mode="issue03_textbook",
    )
    ekf_rows = list(ekf_result["rows"])

    print("\n[4/4] 汇总与三方对比")
    combined_rows = baseline_runner._combine_rows(single_rows, wls_rows, ekf_rows)
    baseline_runner.CROSS_DIR = CROSS_DIR
    baseline_runner._write_combined_outputs(combined_rows)
    report_outputs = report_mod.generate_reports(CORRECTED_ROOT)

    write_json(
        CORRECTED_ROOT / "summary.json",
        {
        "issue_id": "issue_03_textbook_full_correction",
        "execution_command": "uv run python scripts/run_issue_03_textbook_full_correction.py",
        "frequencies_hz": [float(v) for v in FREQUENCIES_HZ],
            "textbook_correction": {
                "truth_free_runtime": True,
                "truth_free_initialization": True,
                "channel_background_mode": "issue03_textbook",
                "nav_data_enabled": True,
                "layer_chain": [
                    "signal_model",
                    "receiver_natural_measurements",
                    "observable_formation",
                    "navigation_estimators",
                ],
            },
            "outputs": {
                "corrected_root": str(CORRECTED_ROOT.resolve()),
                "single_channel_dir": str(SINGLE_DIR.resolve()),
                "observables_dir": str(OBSERVABLES_DIR.resolve()),
                "wls_dir": str(WLS_DIR.resolve()),
                "ekf_dir": str(EKF_DIR.resolve()),
                "cross_frequency_dir": str(CROSS_DIR.resolve()),
                "report_summary_md": str(report_outputs["summary_md"].resolve()),
                "report_full_md": str(report_outputs["full_md"].resolve()),
            },
        },
    )

    legacy_rows = load_json(BASELINE_ROOT / "cross_frequency" / "combined_metrics.json")
    issue01_rows = load_json(ISSUE01_ROOT / "cross_frequency" / "combined_metrics.json")
    three_way_rows = build_three_way_rows(legacy_rows, issue01_rows, combined_rows)
    three_way_summary = _build_three_way_summary(legacy_rows, issue01_rows, combined_rows)

    write_json(COMPARISON_DIR / "legacy_vs_issue01_vs_issue03.json", three_way_summary)
    write_csv_rows(COMPARISON_DIR / "tables.csv", three_way_rows)
    write_three_way_plot(three_way_rows, COMPARISON_DIR / "plots.png")

    _write_textbook_alignment_changes_md(NOTES_DIR / "textbook_alignment_changes.md")
    _write_illegal_item_impact_review_md(NOTES_DIR / "illegal_item_impact_review.md", legacy_rows, issue01_rows, combined_rows)
    _write_impact_matrix_md(COMPARISON_DIR / "impact_matrix.md", three_way_summary)


if __name__ == "__main__":
    main()
