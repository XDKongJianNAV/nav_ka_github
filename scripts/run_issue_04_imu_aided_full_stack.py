# -*- coding: utf-8 -*-
"""
run_issue_04_imu_aided_full_stack.py
====================================

Issue 04: 用 IMU 驱动前端 DLL/PLL 标量辅助，并在 18.0/18.5/18.7 GHz +
70/80/90 km + 7.9/8.45/9.0 km/s 网格上批量运行单通道与动态导航实验。
"""

from __future__ import annotations

from pathlib import Path

from nav_ka.studies.issue_04_imu_aided import (
    ISSUE04_ROOT,
    build_scenario_grid,
    run_issue04_case,
    write_issue04_aggregate,
)


ROOT = Path(__file__).resolve().parents[1]
FREQUENCIES_HZ = (18.0e9, 18.5e9, 18.7e9)
CORRECTED_ROOT = ISSUE04_ROOT / "corrected_fullstack"


def _flatten_summary(summary: dict) -> dict:
    return {
        "label": summary["scenario"]["label"],
        "height_km": summary["scenario"]["height_km"],
        "speed_kms": summary["scenario"]["speed_kms"],
        "frequency_hz": summary["scenario"]["carrier_frequency_hz"],
        "single_tau_rmse_ns": summary["single_channel"]["tau_rmse_ns"],
        "single_fd_rmse_hz": summary["single_channel"]["fd_rmse_hz"],
        "single_effective_pseudorange_sigma_1s_m": summary["single_channel"]["effective_pseudorange_sigma_1s_m"],
        "imu_code_aiding_rate_mean": summary["single_channel"]["imu_code_aiding_rate_mean"],
        "imu_carrier_aiding_rate_mean": summary["single_channel"]["imu_carrier_aiding_rate_mean"],
        "aiding_fraction": summary["single_channel"]["aiding_fraction"],
        "ins_mean_position_error_3d_m": summary["ins_diagnostics"]["ins_mean_position_error_3d_m"],
        "ins_mean_velocity_error_3d_mps": summary["ins_diagnostics"]["ins_mean_velocity_error_3d_mps"],
        "ins_mean_attitude_error_deg": summary["ins_diagnostics"]["ins_mean_attitude_error_deg"],
        "ins_final_position_error_3d_m": summary["ins_diagnostics"]["ins_final_position_error_3d_m"],
        "ins_final_velocity_error_3d_mps": summary["ins_diagnostics"]["ins_final_velocity_error_3d_mps"],
        "ins_final_attitude_error_deg": summary["ins_diagnostics"]["ins_final_attitude_error_deg"],
        "wls_mean_position_error_3d_m": summary["dynamic_navigation"]["mean_wls_position_error_3d_m"],
        "ekf_mean_position_error_3d_m": summary["dynamic_navigation"]["mean_ekf_position_error_3d_m"],
        "ekf_mean_velocity_error_3d_mps": summary["dynamic_navigation"]["mean_ekf_velocity_error_3d_mps"],
        "valid_wls_epochs": summary["dynamic_navigation"]["valid_wls_epochs"],
        "prediction_only_epochs": summary["dynamic_navigation"]["prediction_only_epochs"],
    }


def main() -> None:
    CORRECTED_ROOT.mkdir(parents=True, exist_ok=True)
    scenarios = build_scenario_grid(FREQUENCIES_HZ)
    print("=" * 100)
    print("Issue 04: IMU-aided Ka front-end and dynamic navigation sweep")
    print("=" * 100)
    print(f"cases = {len(scenarios)}")

    rows: list[dict] = []
    for idx, scenario in enumerate(scenarios, start=1):
        print(f"[{idx:02d}/{len(scenarios):02d}] {scenario.label}")
        summary = run_issue04_case(scenario, output_root=CORRECTED_ROOT)
        rows.append(_flatten_summary(summary))

    write_issue04_aggregate(CORRECTED_ROOT / "cross_scenario", rows)
    print("\n[Output]")
    print(f"  - root dir = {CORRECTED_ROOT}")
    print("  - cross_scenario/combined_metrics.json")
    print("  - cross_scenario/combined_metrics.csv")


if __name__ == "__main__":
    main()
