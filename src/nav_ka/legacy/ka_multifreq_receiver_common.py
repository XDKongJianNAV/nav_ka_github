# -*- coding: utf-8 -*-
"""
ka_multifreq_receiver_common.py
===============================

把当前已验证的单通道 Ka/WKB/接收机链路统一暴露为共享模块，
供多频分析 notebook 与下游导航实验共同复用。

这里优先复用现有 `nb_ka225_rx_from_real_wkb_debug.py` 中已经跑通的
实现，而不是再复制一份第三套逻辑。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from nav_ka.legacy import nb_ka225_rx_from_real_wkb_debug as LEGACY_DEBUG

ROOT = Path(__file__).resolve().parents[3]
C_LIGHT = LEGACY_DEBUG.C_LIGHT
SRC = ROOT / "src"

SignalConfig = LEGACY_DEBUG.SignalConfig
MotionConfig = LEGACY_DEBUG.MotionConfig
AcquisitionConfig = LEGACY_DEBUG.AcquisitionConfig
TrackingConfig = LEGACY_DEBUG.TrackingConfig
ReceiverState = LEGACY_DEBUG.ReceiverState
ReceiverRuntimeContext = LEGACY_DEBUG.ReceiverRuntimeContext
ReceiverRunArtifacts = LEGACY_DEBUG.ReceiverRunArtifacts
PlotConfig = LEGACY_DEBUG.PlotConfig
SignalBlockTrace = LEGACY_DEBUG.SignalBlockTrace
AcquisitionEngine = LEGACY_DEBUG.AcquisitionEngine
TrackingEngine = LEGACY_DEBUG.TrackingEngine
KaBpskReceiver = LEGACY_DEBUG.KaBpskReceiver

wrap_to_pi = LEGACY_DEBUG.wrap_to_pi
db20 = LEGACY_DEBUG.db20
db10 = LEGACY_DEBUG.db10
rms = LEGACY_DEBUG.rms
wrap_to_interval = LEGACY_DEBUG.wrap_to_interval
find_first_sustained_true = LEGACY_DEBUG.find_first_sustained_true
build_segment_slices = LEGACY_DEBUG.build_segment_slices
compute_spectrum_db = LEGACY_DEBUG.compute_spectrum_db
finalize_figure = LEGACY_DEBUG.finalize_figure
mseq_7 = LEGACY_DEBUG.mseq_7
sample_code_waveform = LEGACY_DEBUG.sample_code_waveform
build_signal_config_from_wkb_time = LEGACY_DEBUG.build_signal_config_from_wkb_time
compute_real_wkb_series = LEGACY_DEBUG.compute_real_wkb_series
resample_wkb_to_receiver_time = LEGACY_DEBUG.resample_wkb_to_receiver_time
build_transmitter_signal_tools = LEGACY_DEBUG.build_transmitter_signal_tools
evaluate_true_channel_and_motion = LEGACY_DEBUG.evaluate_true_channel_and_motion
make_received_block = LEGACY_DEBUG.make_received_block
build_signal_block_trace = LEGACY_DEBUG.build_signal_block_trace
run_acquisition = LEGACY_DEBUG.run_acquisition
diagnose_acquisition_physics = LEGACY_DEBUG.diagnose_acquisition_physics
correlate_block = LEGACY_DEBUG.correlate_block
dll_discriminator = LEGACY_DEBUG.dll_discriminator
costas_pll_discriminator = LEGACY_DEBUG.costas_pll_discriminator
build_tracking_snapshot = LEGACY_DEBUG.build_tracking_snapshot
run_tracking = LEGACY_DEBUG.run_tracking
diagnose_tracking_physics = LEGACY_DEBUG.diagnose_tracking_physics
plot_receiver_results = LEGACY_DEBUG.plot_receiver_results
build_fields_from_csv = LEGACY_DEBUG.build_fields_from_csv
plot_three_fields_vertical = LEGACY_DEBUG.plot_three_fields_vertical
plot_profile_comparison_from_fields = LEGACY_DEBUG.plot_profile_comparison_from_fields


DEFAULT_NU_EN_HZ = 1.0e9
DEFAULT_DELTA_F_HZ = 5.0e6
DEFAULT_FS_HZ = 500e3
DEFAULT_CHIP_RATE_HZ = 50e3
DEFAULT_COHERENT_INTEGRATION_S = 1e-3
DEFAULT_CODE_LENGTH = 127
DEFAULT_CN0_DBHZ = 45.0
DEFAULT_NAV_DATA_ENABLED = False


def find_legacy_input_files() -> tuple[Path, Path]:
    large_candidates = [
        ROOT / "Large_Scale_Ne_Smooth.csv",
        ROOT / "data" / "raw" / "Large_Scale_Ne_Smooth.csv",
        ROOT / "data" / "Large_Scale_Ne_Smooth.csv",
        ROOT / "notebooks" / "Large_Scale_Ne_Smooth.csv",
    ]
    aoa_candidates = [
        ROOT / "RAMC_AOA_Sim_Input.csv",
        ROOT / "data" / "raw" / "RAMC_AOA_Sim_Input.csv",
        ROOT / "data" / "RAMC_AOA_Sim_Input.csv",
        ROOT / "notebooks" / "RAMC_AOA_Sim_Input.csv",
    ]
    large_csv = next((p for p in large_candidates if p.exists()), None)
    aoa_csv = next((p for p in aoa_candidates if p.exists()), None)
    if large_csv is None:
        raise FileNotFoundError("找不到 Large_Scale_Ne_Smooth.csv")
    if aoa_csv is None:
        raise FileNotFoundError("找不到 RAMC_AOA_Sim_Input.csv")
    return large_csv, aoa_csv


def build_default_field_context() -> dict[str, np.ndarray]:
    large_csv, aoa_csv = find_legacy_input_files()
    return build_fields_from_csv(
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


def build_default_signal_config(
    fc_hz: float,
    wkb_time_s: np.ndarray,
) -> SignalConfig:
    return build_signal_config_from_wkb_time(
        wkb_time_s=wkb_time_s,
        fc_hz=fc_hz,
        fs_hz=DEFAULT_FS_HZ,
        chip_rate_hz=DEFAULT_CHIP_RATE_HZ,
        coherent_integration_s=DEFAULT_COHERENT_INTEGRATION_S,
        code_length=DEFAULT_CODE_LENGTH,
        cn0_dbhz=DEFAULT_CN0_DBHZ,
        nav_data_enabled=DEFAULT_NAV_DATA_ENABLED,
    )


def build_default_motion_config() -> MotionConfig:
    return MotionConfig(
        code_delay_chips_0=17.30,
        code_delay_rate_chips_per_s=0.20,
        doppler_hz_0=48e3,
        doppler_rate_hz_per_s=-1.8e3,
    )


def build_default_acquisition_config() -> AcquisitionConfig:
    return AcquisitionConfig(
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


def build_default_tracking_config() -> TrackingConfig:
    return TrackingConfig(
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


def build_truth_free_tracking_config() -> TrackingConfig:
    cfg_trk = build_default_tracking_config()
    cfg_trk.code_aiding_rate_chips_per_s = 0.0
    cfg_trk.carrier_aiding_rate_hz_per_s = 0.0
    return cfg_trk


def summarize_single_channel_metrics(
    receiver_outputs: ReceiverRunArtifacts,
    wkb_result: dict[str, np.ndarray],
) -> dict[str, float | int | bool]:
    trk = receiver_outputs.trk_result
    acq_diag = receiver_outputs.acq_diag
    trk_diag = receiver_outputs.trk_diag

    return {
        "tau_rmse_ns": float(trk["tau_rmse_ns"][0]),
        "fd_rmse_hz": float(trk["fd_rmse_hz"][0]),
        "peak_to_second_ratio": float(acq_diag["peak_to_second_ratio"]),
        "peak_to_second_db": float(acq_diag["peak_to_second_db"]),
        "loss_found": bool(trk_diag["loss_found"]),
        "loss_fraction": float(np.mean(np.asarray(trk_diag["sustained_loss"], dtype=float))),
        "pll_integrator_clamped": int(np.sum(np.asarray(trk["pll_integrator_clamped"], dtype=int))),
        "pll_freq_clamped": int(np.sum(np.asarray(trk["pll_freq_clamped"], dtype=int))),
        "tau_g_median_m": float(C_LIGHT * np.median(np.asarray(wkb_result["tau_g_t"], dtype=float))),
        "tau_g_span_m": float(C_LIGHT * (np.max(np.asarray(wkb_result["tau_g_t"], dtype=float)) - np.min(np.asarray(wkb_result["tau_g_t"], dtype=float)))),
        "pseudorange_mean_m": float(np.mean(np.asarray(trk["pseudorange_m"], dtype=float))),
        "doppler_mean_hz": float(np.mean(np.asarray(trk["doppler_hz"], dtype=float))),
        "carrier_phase_mean_cycles": float(np.mean(np.asarray(trk["carrier_phase_cycles"], dtype=float))),
        "post_corr_snr_median_db": float(np.median(np.asarray(trk["post_corr_snr_db"], dtype=float))),
        "carrier_lock_metric_median": float(np.median(np.asarray(trk["carrier_lock_metric"], dtype=float))),
    }


def run_single_channel_for_frequency(
    fc_hz: float,
    *,
    field_result: dict[str, np.ndarray] | None = None,
    nu_en_hz: float = DEFAULT_NU_EN_HZ,
    delta_f_hz: float = DEFAULT_DELTA_F_HZ,
    rng_seed: int = 2026,
    truth_free_runtime: bool = False,
) -> dict[str, object]:
    if field_result is None:
        field_result = build_default_field_context()

    t_eval = np.asarray(field_result["t_eval"], dtype=float)
    z_eval = np.asarray(field_result["z_eval"], dtype=float)
    ne_combined = np.asarray(field_result["ne_combined"], dtype=float)
    t_eval_rel = t_eval - t_eval[0]

    wkb_result = compute_real_wkb_series(
        t_eval=t_eval,
        z_eval=z_eval,
        ne_matrix=ne_combined,
        fc_hz=fc_hz,
        nu_en_hz=nu_en_hz,
        delta_f_hz=delta_f_hz,
        verbose=False,
    )

    cfg_sig = build_default_signal_config(fc_hz=fc_hz, wkb_time_s=wkb_result["wkb_time_s"])
    cfg_motion = build_default_motion_config()
    cfg_acq = build_default_acquisition_config()
    cfg_trk = build_truth_free_tracking_config() if truth_free_runtime else build_default_tracking_config()

    rx_time_s = np.arange(cfg_sig.total_samples) / cfg_sig.fs_hz
    plasma_rx = resample_wkb_to_receiver_time(
        rx_time_s=rx_time_s,
        wkb_time_s=wkb_result["wkb_time_s"],
        A_t=wkb_result["A_t"],
        phi_t=wkb_result["phi_t"],
        tau_g_t=wkb_result["tau_g_t"],
    )
    code_chips = build_transmitter_signal_tools(cfg_sig)["code_chips"]
    receiver_context = ReceiverRuntimeContext(
        cfg_sig=cfg_sig,
        cfg_motion=cfg_motion,
        cfg_acq=cfg_acq,
        cfg_trk=cfg_trk,
        code_chips=code_chips,
        plasma_rx=plasma_rx,
        global_rx_time_s=rx_time_s,
    )

    np.random.seed(rng_seed)
    receiver_outputs = KaBpskReceiver(receiver_context).run()
    metrics = summarize_single_channel_metrics(receiver_outputs, wkb_result)

    return {
        "fc_hz": float(fc_hz),
        "field_result": field_result,
        "t_eval_rel": t_eval_rel,
        "wkb_result": wkb_result,
        "cfg_sig": cfg_sig,
        "cfg_motion": cfg_motion,
        "cfg_acq": cfg_acq,
        "cfg_trk": cfg_trk,
        "rx_time_s": rx_time_s,
        "plasma_rx": plasma_rx,
        "receiver_outputs": receiver_outputs,
        "metrics": metrics,
    }

__all__ = [
    "LEGACY_DEBUG",
    "C_LIGHT",
    "ROOT",
    "SRC",
    "SignalConfig",
    "MotionConfig",
    "AcquisitionConfig",
    "TrackingConfig",
    "ReceiverState",
    "ReceiverRuntimeContext",
    "ReceiverRunArtifacts",
    "PlotConfig",
    "SignalBlockTrace",
    "AcquisitionEngine",
    "TrackingEngine",
    "KaBpskReceiver",
    "wrap_to_pi",
    "db20",
    "db10",
    "rms",
    "wrap_to_interval",
    "find_first_sustained_true",
    "build_segment_slices",
    "compute_spectrum_db",
    "finalize_figure",
    "mseq_7",
    "sample_code_waveform",
    "build_signal_config_from_wkb_time",
    "compute_real_wkb_series",
    "resample_wkb_to_receiver_time",
    "build_transmitter_signal_tools",
    "evaluate_true_channel_and_motion",
    "make_received_block",
    "build_signal_block_trace",
    "run_acquisition",
    "diagnose_acquisition_physics",
    "correlate_block",
    "dll_discriminator",
    "costas_pll_discriminator",
    "build_tracking_snapshot",
    "run_tracking",
    "diagnose_tracking_physics",
    "plot_receiver_results",
    "build_fields_from_csv",
    "plot_three_fields_vertical",
    "plot_profile_comparison_from_fields",
    "DEFAULT_NU_EN_HZ",
    "DEFAULT_DELTA_F_HZ",
    "DEFAULT_FS_HZ",
    "DEFAULT_CHIP_RATE_HZ",
    "DEFAULT_COHERENT_INTEGRATION_S",
    "DEFAULT_CODE_LENGTH",
    "DEFAULT_CN0_DBHZ",
    "DEFAULT_NAV_DATA_ENABLED",
    "find_legacy_input_files",
    "build_default_field_context",
    "build_default_signal_config",
    "build_default_motion_config",
    "build_default_acquisition_config",
    "build_default_tracking_config",
    "build_truth_free_tracking_config",
    "summarize_single_channel_metrics",
    "run_single_channel_for_frequency",
]
