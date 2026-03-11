#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np


os.environ.setdefault("MPLBACKEND", "Agg")


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "notebooks" / "nb_ka225_rx_from_real_wkb_debug.py"
ASSET_DIR = ROOT / "reports" / "assets" / "ka225_receiver"


def load_module():
    spec = importlib.util.spec_from_file_location("ka225_rx_debug_report", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def to_builtin(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, dict):
        return {str(k): to_builtin(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_builtin(v) for v in value]
    return value


def main() -> None:
    mod = load_module()
    np.random.seed(2026)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    large_csv = ROOT / "notebooks" / "Large_Scale_Ne_Smooth.csv"
    aoa_csv = ROOT / "notebooks" / "RAMC_AOA_Sim_Input.csv"

    field_result = mod.build_fields_from_csv(
        large_csv_path=large_csv,
        aoa_csv_path=aoa_csv,
        start_time=400.0,
        z_min=0.0,
        z_max=0.14,
        nt=800,
        nz=250,
        a_mid=0.1,
        b_mid=-1.0 / 14.0,
        sigma_small=0.08,
        seed=42,
    )

    t_eval = field_result["t_eval"]
    t_eval_rel = t_eval - t_eval[0]
    z_eval = field_result["z_eval"]

    fc_hz = 22.5e9
    wkb_result = mod.compute_real_wkb_series(
        t_eval=t_eval,
        z_eval=z_eval,
        ne_matrix=field_result["ne_combined"],
        fc_hz=fc_hz,
        nu_en_hz=1.0e9,
        delta_f_hz=5.0e6,
        verbose=False,
    )

    cfg_sig = mod.build_signal_config_from_wkb_time(
        wkb_time_s=wkb_result["wkb_time_s"],
        fc_hz=fc_hz,
        fs_hz=500e3,
        chip_rate_hz=50e3,
        coherent_integration_s=1e-3,
        code_length=127,
        cn0_dbhz=45.0,
        nav_data_enabled=False,
    )
    cfg_motion = mod.MotionConfig(
        code_delay_chips_0=17.30,
        code_delay_rate_chips_per_s=0.20,
        doppler_hz_0=48e3,
        doppler_rate_hz_per_s=-1.8e3,
    )
    cfg_acq = mod.AcquisitionConfig(
        search_fd_min_hz=-80e3,
        search_fd_max_hz=80e3,
        search_fd_step_hz=2e3,
        code_search_step_samples=1,
        acq_time_s=0.010,
        refine_fd_step_hz=100.0,
        refine_code_step_samples=0.1,
        refine_half_span_fd_hz=1.0e3,
        refine_half_span_code_samples=2.0,
    )
    cfg_trk = mod.TrackingConfig(
        dll_spacing_chips=0.50,
        dll_gain=0.06,
        dll_error_clip=0.35,
        dll_update_min_prompt_snr_db=1.0,
        code_aiding_rate_chips_per_s=0.20,
        pll_kp=120.0,
        pll_ki=6000.0,
        pll_phase_kp=0.85,
        pll_error_clip_rad=0.75,
        pll_update_min_prompt_snr_db=-3.0,
        pll_integrator_limit_hz=120e3,
        pll_freq_min_hz=-120e3,
        pll_freq_max_hz=120e3,
        carrier_aiding_rate_hz_per_s=-1.8e3,
        fll_gain=0.40,
        fll_assist_time_s=3.0,
        carrier_lock_metric_threshold=0.15,
    )

    rx_time_s = np.arange(cfg_sig.total_samples) / cfg_sig.fs_hz
    plasma_rx = mod.resample_wkb_to_receiver_time(
        rx_time_s=rx_time_s,
        wkb_time_s=wkb_result["wkb_time_s"],
        A_t=wkb_result["A_t"],
        phi_t=wkb_result["phi_t"],
        tau_g_t=wkb_result["tau_g_t"],
    )

    code_chips = mod.build_transmitter_signal_tools(cfg_sig)["code_chips"]
    context = mod.ReceiverRuntimeContext(
        cfg_sig=cfg_sig,
        cfg_motion=cfg_motion,
        cfg_acq=cfg_acq,
        cfg_trk=cfg_trk,
        code_chips=code_chips,
        plasma_rx=plasma_rx,
        global_rx_time_s=rx_time_s,
    )
    outputs = mod.KaBpskReceiver(context).run()

    plot_cfg = mod.PlotConfig(
        enabled=False,
        show_field_context=False,
        show_receiver_overview=True,
        show_acquisition_internal=True,
        show_tracking_internal=True,
        show_tracking_snapshots=True,
        save_dir=ASSET_DIR,
    )
    mod.plot_receiver_results(
        plot_cfg=plot_cfg,
        t_eval_rel=t_eval_rel,
        ne_large=field_result["ne_large"],
        ne_meso=field_result["ne_meso"],
        ne_combined=field_result["ne_combined"],
        z_eval=z_eval,
        wkb_result=wkb_result,
        cfg_sig=cfg_sig,
        cfg_acq=cfg_acq,
        cfg_trk=cfg_trk,
        acq_result=outputs.acq_result,
        acq_diag=outputs.acq_diag,
        trk_result=outputs.trk_result,
        trk_diag=outputs.trk_diag,
    )

    loss_idx = int(outputs.trk_diag["loss_start_idx"])
    loss_time_s = None if loss_idx < 0 else float(outputs.trk_result["t"][loss_idx])
    segment_names = ["前段", "中段", "后段"]

    summary = {
        "title": "Ka 22.5 GHz 接收机调试与架构演进汇报",
        "generation": {
            "seed": 2026,
            "script": str(MODULE_PATH.relative_to(ROOT)),
            "asset_dir": str(ASSET_DIR.relative_to(ROOT)),
        },
        "baseline": {
            "tau_rmse_ns": 8366.573,
            "fd_rmse_hz": 2488.483,
            "final_fd_est_khz": 16.299,
            "final_fd_true_khz": 8.567,
            "final_tau_est_us": 452.805,
            "final_tau_true_us": 433.630,
        },
        "current": {
            "tau_rmse_ns": float(outputs.trk_result["tau_rmse_ns"][0]),
            "fd_rmse_hz": float(outputs.trk_result["fd_rmse_hz"][0]),
            "final_fd_est_khz": float(outputs.trk_result["fd_est_hz"][-1] / 1e3),
            "final_fd_true_khz": float(outputs.trk_result["fd_true_hz"][-1] / 1e3),
            "final_tau_est_us": float(outputs.trk_result["tau_est_s"][-1] * 1e6),
            "final_tau_true_us": float(outputs.trk_result["tau_true_s"][-1] * 1e6),
            "peak_to_second_ratio": float(outputs.acq_diag["peak_to_second_ratio"]),
            "peak_to_second_db": float(outputs.acq_diag["peak_to_second_db"]),
            "coarse_code_error_ns": float(outputs.acq_diag["tau_err_mod_s"] * 1e9),
            "coarse_freq_error_hz": float(outputs.acq_diag["fd_err_hz"]),
            "loss_found": bool(outputs.trk_diag["loss_found"]),
            "loss_start_time_s": loss_time_s,
        },
        "tracking_diagnostics": {
            "predicted_cn0_dbhz_min": float(np.min(outputs.trk_result["predicted_cn0_dbhz"])),
            "predicted_cn0_dbhz_max": float(np.max(outputs.trk_result["predicted_cn0_dbhz"])),
            "post_corr_snr_db_min": float(np.min(outputs.trk_result["post_corr_snr_db"])),
            "post_corr_snr_db_max": float(np.max(outputs.trk_result["post_corr_snr_db"])),
            "pll_out_of_linear_frac": float(np.mean(outputs.trk_diag["pll_out_of_linear"])),
            "dll_out_of_linear_frac": float(np.mean(outputs.trk_diag["dll_out_of_linear"])),
            "weak_prompt_frac": float(np.mean(outputs.trk_diag["weak_prompt"])),
            "carrier_lock_weak_frac": float(np.mean(outputs.trk_diag["carrier_lock_weak"])),
            "fll_active_frac": float(np.mean(outputs.trk_result["fll_active"])),
            "dll_frozen_frac": float(1.0 - np.mean(outputs.trk_result["dll_update_enabled"])),
            "pll_frozen_frac": float(1.0 - np.mean(outputs.trk_result["pll_update_enabled"])),
            "pll_integrator_clamped_count": int(np.sum(outputs.trk_result["pll_integrator_clamped"])),
            "pll_freq_clamped_count": int(np.sum(outputs.trk_result["pll_freq_clamped"])),
            "segment_names": segment_names,
            "segment_tau_rmse_ns": [float(v) for v in outputs.trk_diag["segment_tau_rmse_ns"]],
            "segment_fd_rmse_hz": [float(v) for v in outputs.trk_diag["segment_fd_rmse_hz"]],
            "segment_prompt_snr_db": [float(v) for v in outputs.trk_diag["segment_prompt_snr_db"]],
            "segment_pll_rms": [float(v) for v in outputs.trk_diag["segment_pll_rms"]],
            "segment_dll_rms": [float(v) for v in outputs.trk_diag["segment_dll_rms"]],
            "segment_loss_frac": [float(v) for v in outputs.trk_diag["segment_loss_frac"]],
        },
        "architecture": {
            "receiver_context": "ReceiverRuntimeContext 汇聚配置、码、信道重采样结果和时间轴。",
            "acquisition_engine": "AcquisitionEngine 负责粗捕获、细捕获与捕获物理诊断。",
            "tracking_engine": "TrackingEngine 负责 DLL + FLL-assisted PLL 跟踪和环路物理诊断。",
            "receiver": "KaBpskReceiver 编排 acquisition -> tracking -> diagnostics 的完整链路。",
        },
        "fixes": [
            "引入粗捕获后的局部细化搜索，显著减小初始码相位误差。",
            "在码 NCO 与载波 NCO 中加入线性预测器，匹配脚本中显式给定的动态模型。",
            "加入 FLL 辅助 PLL，改善载波动态收敛与早期稳定性。",
            "为 DLL/PLL 更新增加基于后相关 SNR 与锁定指标的门控。",
            "补充了可选的内部可视化，覆盖捕获块、相关器、环路、快照与频谱。",
        ],
        "figures": [
            "receiver_overview.png",
            "receiver_acquisition_internal.png",
            "receiver_tracking_internal.png",
            "receiver_tracking_snapshots.png",
        ],
    }

    summary_path = ASSET_DIR / "summary.json"
    summary_path.write_text(
        json.dumps(to_builtin(summary), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"saved summary: {summary_path}")
    for name in summary["figures"]:
        print(f"saved figure: {ASSET_DIR / name}")


if __name__ == "__main__":
    main()
