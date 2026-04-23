from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from nav_ka.legacy import ka_multifreq_receiver_common as KA_COMMON
from nav_ka.studies.issue_01_truth_dependency import write_json

ROOT = Path(__file__).resolve().parents[3]


C_LIGHT = KA_COMMON.C_LIGHT
DEFAULT_NAV_BIT_RATE_BPS = 50.0
DEFAULT_TRACKING_RNG_SEED = 2026
DEFAULT_COMPARISON_KEYS = (
    "single_tau_rmse_ns",
    "single_fd_rmse_hz",
    "wls_case_b_wls_position_error_3d_m",
    "ekf_pr_doppler_mean_position_error_3d_m",
    "ekf_pr_doppler_mean_velocity_error_3d_mps",
)


@dataclass(frozen=True)
class NavigationDataModel:
    bit_rate_bps: float
    bit_period_s: float
    symbols: np.ndarray
    source_note: str


@dataclass(frozen=True)
class NaturalMeasurementSeries:
    receive_time_s: np.ndarray
    tau_est_s: np.ndarray
    carrier_phase_rad: np.ndarray
    carrier_frequency_hz: np.ndarray
    tau_true_s: np.ndarray
    fd_true_hz: np.ndarray
    post_corr_snr_db: np.ndarray
    carrier_lock_metric: np.ndarray


@dataclass(frozen=True)
class StandardObservableSeries:
    receive_time_s: np.ndarray
    transmit_time_est_s: np.ndarray
    pseudorange_m: np.ndarray
    pseudorange_true_m: np.ndarray
    carrier_phase_cycles: np.ndarray
    range_rate_mps: np.ndarray
    range_rate_true_mps: np.ndarray
    doppler_hz_compat: np.ndarray
    sign_convention: str


@dataclass(frozen=True)
class MotionProfile:
    t_s: np.ndarray
    code_delay_s: np.ndarray
    code_rate_chips_per_s: np.ndarray
    doppler_hz: np.ndarray
    doppler_rate_hz_per_s: np.ndarray
    range_m: np.ndarray
    range_rate_mps: np.ndarray
    source_note: str


@dataclass(frozen=True)
class TrackingAidingProfile:
    t_s: np.ndarray
    code_aiding_rate_chips_per_s: np.ndarray
    carrier_aiding_rate_hz_per_s: np.ndarray
    aiding_enabled: np.ndarray
    source_note: str


@dataclass
class TextbookChannelBackground:
    large_csv: Path
    aoa_csv: Path
    wkb_result: dict[str, np.ndarray]
    trk_result: dict[str, np.ndarray]
    acq_diag: dict[str, Any]
    trk_diag: dict[str, Any]
    effective_pseudorange_sigma_1s_m: float
    effective_pseudorange_sigma_100ms_m: float
    effective_pseudorange_rmse_m: float
    effective_pseudorange_bias_m: float
    tau_g_median_m: float
    tau_g_span_m: float
    reused_components: list[str]
    natural_measurements: NaturalMeasurementSeries
    standard_observables: StandardObservableSeries
    nav_data_model: NavigationDataModel


@dataclass
class TextbookSingleChannelRun:
    fc_hz: float
    field_result: dict[str, np.ndarray]
    t_eval_rel: np.ndarray
    wkb_result: dict[str, np.ndarray]
    cfg_sig: KA_COMMON.SignalConfig
    cfg_motion: KA_COMMON.MotionConfig
    cfg_acq: KA_COMMON.AcquisitionConfig
    cfg_trk: KA_COMMON.TrackingConfig
    plasma_rx: dict[str, np.ndarray]
    nav_data_model: NavigationDataModel
    acq_result: dict[str, Any]
    acq_diag: dict[str, Any]
    trk_result: dict[str, Any]
    trk_diag: dict[str, Any]
    natural_measurements: NaturalMeasurementSeries
    observables: StandardObservableSeries
    metrics: dict[str, float | int | bool]


@dataclass
class _LoopState:
    tau_est_s: float
    carrier_freq_hz: float
    carrier_phase_start_rad: float
    carrier_phase_total_rad: float
    pll_integrator_hz: float


_RUN_CACHE: dict[tuple[float, bool, bool], TextbookSingleChannelRun] = {}


def _freq_label(fc_hz: float) -> str:
    return f"{fc_hz / 1e9:.1f}".replace(".", "p") + "GHz"


def _as_serializable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _as_serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_serializable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, Path):
        return str(value)
    return value


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["frequency_hz"] + sorted({k for row in rows for k in row.keys() if k != "frequency_hz"})
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_series_csv(path: Path, columns: dict[str, np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(columns.keys())
    arrays = [np.asarray(columns[key]) for key in keys]
    if not arrays:
        return
    length = len(arrays[0])
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow(keys)
        for idx in range(length):
            writer.writerow([arrays[col_idx][idx] for col_idx in range(len(keys))])


def block_average_sigma(values: np.ndarray, block_size: int) -> float:
    arr = np.asarray(values, dtype=float)
    n_blocks = len(arr) // block_size
    if n_blocks <= 1:
        return float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
    averaged = arr[: n_blocks * block_size].reshape(n_blocks, block_size).mean(axis=1)
    return float(np.std(averaged, ddof=1))


def _rms(values: np.ndarray | Sequence[float]) -> float:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return float("nan")
    return float(np.sqrt(np.mean(arr ** 2)))


def _interp_motion_profile(motion_profile: MotionProfile, t_s: float) -> dict[str, float]:
    return {
        "code_delay_s": float(np.interp(t_s, motion_profile.t_s, motion_profile.code_delay_s)),
        "code_rate_chips_per_s": float(np.interp(t_s, motion_profile.t_s, motion_profile.code_rate_chips_per_s)),
        "doppler_hz": float(np.interp(t_s, motion_profile.t_s, motion_profile.doppler_hz)),
        "doppler_rate_hz_per_s": float(np.interp(t_s, motion_profile.t_s, motion_profile.doppler_rate_hz_per_s)),
        "range_m": float(np.interp(t_s, motion_profile.t_s, motion_profile.range_m)),
        "range_rate_mps": float(np.interp(t_s, motion_profile.t_s, motion_profile.range_rate_mps)),
    }


def _interp_tracking_aiding_profile(aiding_profile: TrackingAidingProfile | None, t_s: float) -> tuple[float, float, bool]:
    if aiding_profile is None:
        return 0.0, 0.0, False
    code_rate = float(np.interp(t_s, aiding_profile.t_s, aiding_profile.code_aiding_rate_chips_per_s))
    carrier_rate = float(np.interp(t_s, aiding_profile.t_s, aiding_profile.carrier_aiding_rate_hz_per_s))
    enabled = bool(np.interp(t_s, aiding_profile.t_s, aiding_profile.aiding_enabled.astype(float)) >= 0.5)
    return code_rate, carrier_rate, enabled


def build_textbook_signal_config(fc_hz: float, wkb_time_s: np.ndarray, *, nav_data_enabled: bool = True) -> KA_COMMON.SignalConfig:
    cfg_sig = KA_COMMON.build_default_signal_config(fc_hz=fc_hz, wkb_time_s=wkb_time_s)
    cfg_sig.nav_data_enabled = bool(nav_data_enabled)
    return cfg_sig


def build_navigation_data_model(
    cfg_sig: KA_COMMON.SignalConfig,
    *,
    bit_rate_bps: float = DEFAULT_NAV_BIT_RATE_BPS,
    rng_seed: int = DEFAULT_TRACKING_RNG_SEED,
) -> NavigationDataModel:
    bit_period_s = 1.0 / bit_rate_bps
    n_bits = max(int(math.ceil(cfg_sig.total_time_s / bit_period_s)) + 2, 4)
    rng = np.random.default_rng(rng_seed + int(round(cfg_sig.fc_hz / 1e6)))
    symbols = rng.choice(np.array([-1.0, 1.0], dtype=float), size=n_bits)
    return NavigationDataModel(
        bit_rate_bps=float(bit_rate_bps),
        bit_period_s=float(bit_period_s),
        symbols=np.asarray(symbols, dtype=float),
        source_note="deterministic pseudo-random 50 bps BPSK navigation data",
    )


def sample_navigation_waveform(nav_data_model: NavigationDataModel, t_s: np.ndarray) -> np.ndarray:
    total_period_s = nav_data_model.bit_period_s * len(nav_data_model.symbols)
    t_mod = np.mod(np.asarray(t_s, dtype=float), total_period_s)
    bit_idx = np.floor(t_mod / nav_data_model.bit_period_s).astype(int)
    bit_idx = np.clip(bit_idx, 0, len(nav_data_model.symbols) - 1)
    return np.asarray(nav_data_model.symbols[bit_idx], dtype=np.complex128)


def make_textbook_received_block(
    t_block_s: np.ndarray,
    code_chips: np.ndarray,
    cfg_sig: KA_COMMON.SignalConfig,
    cfg_motion: KA_COMMON.MotionConfig,
    plasma_rx: dict[str, np.ndarray],
    global_rx_time_s: np.ndarray,
    nav_data_model: NavigationDataModel,
) -> np.ndarray:
    ch = KA_COMMON.evaluate_true_channel_and_motion(
        t_rel_s=t_block_s,
        cfg_sig=cfg_sig,
        cfg_motion=cfg_motion,
        plasma_rx=plasma_rx,
        global_rx_time_s=global_rx_time_s,
    )

    delayed_code = KA_COMMON.sample_code_waveform(
        code_chips=code_chips,
        chip_rate_hz=cfg_sig.chip_rate_hz,
        t_s=t_block_s - ch["tau_total_s"],
    )
    delayed_data = (
        sample_navigation_waveform(nav_data_model, t_block_s - ch["tau_total_s"])
        if cfg_sig.nav_data_enabled
        else np.ones_like(delayed_code)
    )

    phase_doppler = 2.0 * np.pi * (
        cfg_motion.doppler_hz_0 * t_block_s
        + 0.5 * cfg_motion.doppler_rate_hz_per_s * (t_block_s ** 2)
    )
    phase_total = phase_doppler + ch["phi_p_t"]
    rx_clean = ch["A_t"] * delayed_data * delayed_code * np.exp(1j * phase_total)

    cn0_linear = 10.0 ** (cfg_sig.cn0_dbhz / 10.0)
    n0 = 1.0 / cn0_linear
    noise_var = n0 * cfg_sig.fs_hz / 2.0
    sigma = math.sqrt(noise_var / 2.0)
    noise = sigma * (
        np.random.randn(len(t_block_s)) + 1j * np.random.randn(len(t_block_s))
    )
    return rx_clean + noise


def build_textbook_signal_block_trace(
    t_block_s: np.ndarray,
    code_chips: np.ndarray,
    cfg_sig: KA_COMMON.SignalConfig,
    cfg_motion: KA_COMMON.MotionConfig,
    plasma_rx: dict[str, np.ndarray],
    global_rx_time_s: np.ndarray,
    nav_data_model: NavigationDataModel,
    *,
    rng: np.random.Generator | None = None,
) -> KA_COMMON.SignalBlockTrace:
    """
    返回 Issue 03 信号块的中间量，供 notebook/review 使用。

    与 make_textbook_received_block() 使用完全相同的真实公式，
    只是把 delayed_data 等中间量显式暴露出来。
    """
    ch = KA_COMMON.evaluate_true_channel_and_motion(
        t_rel_s=t_block_s,
        cfg_sig=cfg_sig,
        cfg_motion=cfg_motion,
        plasma_rx=plasma_rx,
        global_rx_time_s=global_rx_time_s,
    )

    delayed_code = KA_COMMON.sample_code_waveform(
        code_chips=code_chips,
        chip_rate_hz=cfg_sig.chip_rate_hz,
        t_s=t_block_s - ch["tau_total_s"],
    )
    delayed_data = (
        sample_navigation_waveform(nav_data_model, t_block_s - ch["tau_total_s"])
        if cfg_sig.nav_data_enabled
        else np.ones_like(delayed_code)
    )

    phase_doppler = 2.0 * np.pi * (
        cfg_motion.doppler_hz_0 * t_block_s
        + 0.5 * cfg_motion.doppler_rate_hz_per_s * (t_block_s ** 2)
    )
    phase_total = phase_doppler + ch["phi_p_t"]
    rx_clean = ch["A_t"] * delayed_data * delayed_code * np.exp(1j * phase_total)

    cn0_linear = 10.0 ** (cfg_sig.cn0_dbhz / 10.0)
    n0 = 1.0 / cn0_linear
    noise_var = n0 * cfg_sig.fs_hz / 2.0
    sigma = math.sqrt(noise_var / 2.0)

    if rng is None:
        noise = sigma * (
            np.random.randn(len(t_block_s)) + 1j * np.random.randn(len(t_block_s))
        )
    else:
        noise = sigma * (
            rng.standard_normal(len(t_block_s)) + 1j * rng.standard_normal(len(t_block_s))
        )
    rx_block = rx_clean + noise

    return KA_COMMON.SignalBlockTrace(
        t_block_s=np.asarray(t_block_s, dtype=float),
        tau_geom_s=np.asarray(ch["tau_geom_s"], dtype=float),
        tau_g_s=np.asarray(ch["tau_g_s"], dtype=float),
        tau_total_s=np.asarray(ch["tau_total_s"], dtype=float),
        fd_total_hz=np.asarray(ch["fd_total_hz"], dtype=float),
        A_t=np.asarray(ch["A_t"], dtype=float),
        phi_p_t=np.asarray(ch["phi_p_t"], dtype=float),
        delayed_code=np.asarray(delayed_code, dtype=np.complex128),
        delayed_data=np.asarray(delayed_data, dtype=np.complex128),
        phase_total=np.asarray(phase_total, dtype=float),
        rx_clean=np.asarray(rx_clean, dtype=np.complex128),
        noise=np.asarray(noise, dtype=np.complex128),
        rx_block=np.asarray(rx_block, dtype=np.complex128),
    )


def run_textbook_acquisition(
    cfg_sig: KA_COMMON.SignalConfig,
    cfg_motion: KA_COMMON.MotionConfig,
    cfg_acq: KA_COMMON.AcquisitionConfig,
    code_chips: np.ndarray,
    plasma_rx: dict[str, np.ndarray],
    global_rx_time_s: np.ndarray,
    nav_data_model: NavigationDataModel,
) -> dict[str, Any]:
    n_samples = int(round(cfg_acq.acq_time_s * cfg_sig.fs_hz))
    t_block = np.arange(n_samples) / cfg_sig.fs_hz
    rx_block = make_textbook_received_block(
        t_block_s=t_block,
        code_chips=code_chips,
        cfg_sig=cfg_sig,
        cfg_motion=cfg_motion,
        plasma_rx=plasma_rx,
        global_rx_time_s=global_rx_time_s,
        nav_data_model=nav_data_model,
    )

    fd_grid = np.arange(
        cfg_acq.search_fd_min_hz,
        cfg_acq.search_fd_max_hz + cfg_acq.search_fd_step_hz,
        cfg_acq.search_fd_step_hz,
    )
    code_period_samples = int(round(cfg_sig.code_period_s * cfg_sig.fs_hz))
    code_offsets = np.arange(0, code_period_samples, cfg_acq.code_search_step_samples)

    metric = np.zeros((len(fd_grid), len(code_offsets)), dtype=float)
    for fd_idx, fd_hz in enumerate(fd_grid):
        carrier_wipeoff = np.exp(-1j * 2.0 * np.pi * fd_hz * t_block)
        mixed = rx_block * carrier_wipeoff
        for code_idx, code_offset in enumerate(code_offsets):
            tau_cand_s = code_offset / cfg_sig.fs_hz
            local_code = KA_COMMON.sample_code_waveform(
                code_chips=code_chips,
                chip_rate_hz=cfg_sig.chip_rate_hz,
                t_s=t_block - tau_cand_s,
            )
            metric[fd_idx, code_idx] = float(np.abs(np.vdot(local_code, mixed)) ** 2)

    idx = np.unravel_index(np.argmax(metric), metric.shape)
    fd_hat_coarse_hz = float(fd_grid[idx[0]])
    tau_hat_coarse_s = float(code_offsets[idx[1]] / cfg_sig.fs_hz)

    fd_refine_grid = np.arange(
        fd_hat_coarse_hz - cfg_acq.refine_half_span_fd_hz,
        fd_hat_coarse_hz + cfg_acq.refine_half_span_fd_hz + 0.5 * cfg_acq.refine_fd_step_hz,
        cfg_acq.refine_fd_step_hz,
    )
    tau_refine_samples = np.arange(
        code_offsets[idx[1]] - cfg_acq.refine_half_span_code_samples,
        code_offsets[idx[1]] + cfg_acq.refine_half_span_code_samples + 0.5 * cfg_acq.refine_code_step_samples,
        cfg_acq.refine_code_step_samples,
    )
    tau_refine_s = tau_refine_samples / cfg_sig.fs_hz
    refine_metric = np.zeros((len(fd_refine_grid), len(tau_refine_s)), dtype=float)
    for fd_idx, fd_hz in enumerate(fd_refine_grid):
        carrier_wipeoff = np.exp(-1j * 2.0 * np.pi * fd_hz * t_block)
        mixed = rx_block * carrier_wipeoff
        for code_idx, tau_cand_s in enumerate(tau_refine_s):
            local_code = KA_COMMON.sample_code_waveform(
                code_chips=code_chips,
                chip_rate_hz=cfg_sig.chip_rate_hz,
                t_s=t_block - tau_cand_s,
            )
            refine_metric[fd_idx, code_idx] = float(np.abs(np.vdot(local_code, mixed)) ** 2)

    refine_idx = np.unravel_index(np.argmax(refine_metric), refine_metric.shape)
    fd_hat_hz = float(fd_refine_grid[refine_idx[0]])
    tau_hat_s = float(tau_refine_s[refine_idx[1]])
    peak = float(metric[idx])
    mean_metric = float(np.mean(metric))
    best_mixed = rx_block * np.exp(-1j * 2.0 * np.pi * fd_hat_hz * t_block)
    best_local_code = KA_COMMON.sample_code_waveform(
        code_chips=code_chips,
        chip_rate_hz=cfg_sig.chip_rate_hz,
        t_s=t_block - tau_hat_s,
    )
    return {
        "fd_grid": fd_grid,
        "code_offsets": code_offsets,
        "metric": metric,
        "refine_fd_grid": fd_refine_grid,
        "refine_tau_s": tau_refine_s,
        "refine_metric": refine_metric,
        "fd_hat_coarse_hz": fd_hat_coarse_hz,
        "tau_hat_coarse_s": tau_hat_coarse_s,
        "fd_hat_hz": fd_hat_hz,
        "tau_hat_s": tau_hat_s,
        "peak_ratio": peak / max(mean_metric, 1e-30),
        "t_block_s": t_block,
        "rx_block": rx_block,
        "best_mixed": best_mixed,
        "best_local_code": best_local_code,
    }


def correlate_textbook_block(
    rx_block: np.ndarray,
    t_block_s: np.ndarray,
    code_chips: np.ndarray,
    cfg_sig: KA_COMMON.SignalConfig,
    state: _LoopState,
    cfg_trk: KA_COMMON.TrackingConfig,
) -> dict[str, complex]:
    local_carrier = np.exp(
        -1j
        * (
            state.carrier_phase_start_rad
            + 2.0 * np.pi * state.carrier_freq_hz * (t_block_s - t_block_s[0])
        )
    )
    baseband = rx_block * local_carrier
    half_spacing_s = 0.5 * cfg_trk.dll_spacing_chips / cfg_sig.chip_rate_hz
    prompt_code = KA_COMMON.sample_code_waveform(
        code_chips=code_chips,
        chip_rate_hz=cfg_sig.chip_rate_hz,
        t_s=t_block_s - state.tau_est_s,
    )
    early_code = KA_COMMON.sample_code_waveform(
        code_chips=code_chips,
        chip_rate_hz=cfg_sig.chip_rate_hz,
        t_s=t_block_s - (state.tau_est_s - half_spacing_s),
    )
    late_code = KA_COMMON.sample_code_waveform(
        code_chips=code_chips,
        chip_rate_hz=cfg_sig.chip_rate_hz,
        t_s=t_block_s - (state.tau_est_s + half_spacing_s),
    )
    return {
        "E": np.vdot(early_code, baseband),
        "P": np.vdot(prompt_code, baseband),
        "L": np.vdot(late_code, baseband),
    }


def update_code_loop(
    state: _LoopState,
    cfg_sig: KA_COMMON.SignalConfig,
    cfg_trk: KA_COMMON.TrackingConfig,
    dll_error: float,
    *,
    update_enabled: bool,
) -> None:
    if update_enabled:
        state.tau_est_s -= cfg_trk.dll_gain * dll_error * cfg_sig.chip_period_s


def update_carrier_loop(
    state: _LoopState,
    cfg_trk: KA_COMMON.TrackingConfig,
    pll_error_rad: float,
    fll_error_hz: float,
    dt_s: float,
    acq_center_hz: float,
    *,
    pll_update_enabled: bool,
    fll_active: bool,
) -> tuple[float, float, bool, bool]:
    pll_integrator_unclipped = state.pll_integrator_hz
    if pll_update_enabled:
        pll_integrator_unclipped = state.pll_integrator_hz + cfg_trk.pll_ki * pll_error_rad * dt_s
    state.pll_integrator_hz = float(
        np.clip(
            pll_integrator_unclipped,
            -cfg_trk.pll_integrator_limit_hz,
            cfg_trk.pll_integrator_limit_hz,
        )
    )
    pll_proportional_hz = cfg_trk.pll_kp * pll_error_rad if pll_update_enabled else 0.0
    fll_assist_hz = cfg_trk.fll_gain * fll_error_hz if fll_active else 0.0
    nco_freq_cmd_hz = acq_center_hz + state.pll_integrator_hz + pll_proportional_hz + fll_assist_hz
    state.carrier_freq_hz = float(
        np.clip(
            nco_freq_cmd_hz,
            cfg_trk.pll_freq_min_hz,
            cfg_trk.pll_freq_max_hz,
        )
    )
    phase_correction_rad = cfg_trk.pll_phase_kp * pll_error_rad if pll_update_enabled else 0.0
    pll_integrator_clamped = abs(pll_integrator_unclipped - state.pll_integrator_hz) > 1e-12
    pll_freq_clamped = abs(nco_freq_cmd_hz - state.carrier_freq_hz) > 1e-12
    state.carrier_phase_total_rad += 2.0 * np.pi * state.carrier_freq_hz * dt_s + phase_correction_rad
    state.carrier_phase_start_rad = float(KA_COMMON.wrap_to_pi(state.carrier_phase_total_rad))
    return nco_freq_cmd_hz, phase_correction_rad, pll_integrator_clamped, pll_freq_clamped


def form_standard_observables(
    cfg_sig: KA_COMMON.SignalConfig,
    natural: NaturalMeasurementSeries,
) -> StandardObservableSeries:
    receive_time_s = np.asarray(natural.receive_time_s, dtype=float)
    transmit_time_est_s = receive_time_s - np.asarray(natural.tau_est_s, dtype=float)
    pseudorange_m = C_LIGHT * (receive_time_s - transmit_time_est_s)
    pseudorange_true_m = C_LIGHT * np.asarray(natural.tau_true_s, dtype=float)
    carrier_phase_cycles = np.asarray(natural.carrier_phase_rad, dtype=float) / (2.0 * np.pi)
    range_rate_mps = -cfg_sig.wavelength_m * np.asarray(natural.carrier_frequency_hz, dtype=float)
    range_rate_true_mps = -cfg_sig.wavelength_m * np.asarray(natural.fd_true_hz, dtype=float)
    return StandardObservableSeries(
        receive_time_s=receive_time_s,
        transmit_time_est_s=transmit_time_est_s,
        pseudorange_m=pseudorange_m,
        pseudorange_true_m=pseudorange_true_m,
        carrier_phase_cycles=carrier_phase_cycles,
        range_rate_mps=range_rate_mps,
        range_rate_true_mps=range_rate_true_mps,
        doppler_hz_compat=np.asarray(natural.carrier_frequency_hz, dtype=float),
        sign_convention="positive range_rate means increasing geometric range; doppler_hz_compat = -range_rate / wavelength",
    )


def run_textbook_tracking(
    cfg_sig: KA_COMMON.SignalConfig,
    cfg_motion: KA_COMMON.MotionConfig,
    cfg_trk: KA_COMMON.TrackingConfig,
    code_chips: np.ndarray,
    plasma_rx: dict[str, np.ndarray],
    global_rx_time_s: np.ndarray,
    nav_data_model: NavigationDataModel,
    acq_result: dict[str, Any],
    *,
    motion_profile: MotionProfile | None = None,
    aiding_profile: TrackingAidingProfile | None = None,
) -> tuple[dict[str, Any], NaturalMeasurementSeries, StandardObservableSeries]:
    dt_s = cfg_sig.coherent_integration_s
    n_block = cfg_sig.total_samples // cfg_sig.update_samples
    phi_rate_hz = np.gradient(plasma_rx["phi_t"], global_rx_time_s, edge_order=1) / (2.0 * np.pi)
    state = _LoopState(
        tau_est_s=float(acq_result["tau_hat_s"]),
        carrier_freq_hz=float(acq_result["fd_hat_hz"]),
        carrier_phase_start_rad=0.0,
        carrier_phase_total_rad=0.0,
        pll_integrator_hz=0.0,
    )
    cn0_linear = 10.0 ** (cfg_sig.cn0_dbhz / 10.0)
    n0 = 1.0 / cn0_linear
    noise_var = n0 * cfg_sig.fs_hz / 2.0
    prompt_noise_power = cfg_sig.update_samples * noise_var

    t_hist: list[float] = []
    tau_est_hist: list[float] = []
    tau_true_hist: list[float] = []
    fd_est_hist: list[float] = []
    fd_true_hist: list[float] = []
    phase_est_hist: list[float] = []
    dll_err_hist: list[float] = []
    pll_err_hist: list[float] = []
    mag_E_hist: list[float] = []
    mag_P_hist: list[float] = []
    mag_L_hist: list[float] = []
    post_corr_snr_db_hist: list[float] = []
    predicted_cn0_dbhz_hist: list[float] = []
    predicted_post_corr_snr_db_hist: list[float] = []
    carrier_lock_metric_hist: list[float] = []
    prompt_quadrature_ratio_hist: list[float] = []
    fll_err_hist: list[float] = []
    fll_active_hist: list[bool] = []
    dll_update_enabled_hist: list[bool] = []
    pll_update_enabled_hist: list[bool] = []
    pll_integrator_hist: list[float] = []
    pll_integrator_clamped_hist: list[bool] = []
    pll_freq_cmd_hist: list[float] = []
    pll_freq_clamped_hist: list[bool] = []
    carrier_freq_center_hist: list[float] = []
    tau_predict_hist: list[float] = []
    imu_code_aiding_rate_hist: list[float] = []
    imu_carrier_aiding_rate_hist: list[float] = []
    aiding_enabled_hist: list[bool] = []
    I_E_hist: list[float] = []
    Q_E_hist: list[float] = []
    I_P_hist: list[float] = []
    Q_P_hist: list[float] = []
    I_L_hist: list[float] = []
    Q_L_hist: list[float] = []

    prev_prompt: complex | None = None
    for block_idx in range(n_block):
        i0 = block_idx * cfg_sig.update_samples
        i1 = i0 + cfg_sig.update_samples
        t_block = np.arange(i0, i1) / cfg_sig.fs_hz
        t_mid = 0.5 * (t_block[0] + t_block[-1])
        rx_block = make_textbook_received_block(
            t_block_s=t_block,
            code_chips=code_chips,
            cfg_sig=cfg_sig,
            cfg_motion=cfg_motion,
            plasma_rx=plasma_rx,
            global_rx_time_s=global_rx_time_s,
            nav_data_model=nav_data_model,
        )
        corr = correlate_textbook_block(
            rx_block=rx_block,
            t_block_s=t_block,
            code_chips=code_chips,
            cfg_sig=cfg_sig,
            state=state,
            cfg_trk=cfg_trk,
        )
        E = corr["E"]
        P = corr["P"]
        L = corr["L"]
        prompt_power = float(np.abs(P) ** 2)
        post_corr_snr_db = float(KA_COMMON.db10(prompt_power / max(prompt_noise_power, 1e-30)))
        rx_input_amp = float(np.interp(t_mid, global_rx_time_s, plasma_rx["A_t"]))
        predicted_cn0_dbhz = float(cfg_sig.cn0_dbhz + KA_COMMON.db20(rx_input_amp))
        predicted_post_corr_snr_db = float(predicted_cn0_dbhz + 10.0 * math.log10(dt_s))
        carrier_lock_metric = float((P.real * P.real - P.imag * P.imag) / (prompt_power + 1e-30))
        prompt_quadrature_ratio = float(abs(P.imag) / (abs(P.real) + 1e-30))
        dll_error = float(np.clip(KA_COMMON.dll_discriminator(E, L), -cfg_trk.dll_error_clip, cfg_trk.dll_error_clip))
        pll_error = float(np.clip(KA_COMMON.costas_pll_discriminator(P), -cfg_trk.pll_error_clip_rad, cfg_trk.pll_error_clip_rad))
        fll_error_hz = 0.0
        if prev_prompt is not None:
            fll_error_hz = float(np.angle(P * np.conj(prev_prompt)) / (2.0 * np.pi * dt_s))

        dll_update_enabled = (
            post_corr_snr_db >= cfg_trk.dll_update_min_prompt_snr_db
            and carrier_lock_metric >= cfg_trk.carrier_lock_metric_threshold
        )
        pll_update_enabled = post_corr_snr_db >= cfg_trk.pll_update_min_prompt_snr_db
        fll_active = block_idx == 0 or (block_idx * dt_s) < cfg_trk.fll_assist_time_s or carrier_lock_metric < cfg_trk.carrier_lock_metric_threshold
        code_aiding_rate_chips_per_s = cfg_trk.code_aiding_rate_chips_per_s
        carrier_aiding_rate_hz_per_s = cfg_trk.carrier_aiding_rate_hz_per_s
        aiding_enabled = abs(code_aiding_rate_chips_per_s) > 0.0 or abs(carrier_aiding_rate_hz_per_s) > 0.0
        if aiding_profile is not None:
            code_aiding_rate_chips_per_s, carrier_aiding_rate_hz_per_s, aiding_enabled = _interp_tracking_aiding_profile(
                aiding_profile,
                float(t_mid),
            )
        if aiding_enabled and block_idx > 0:
            state.tau_est_s += (code_aiding_rate_chips_per_s / cfg_sig.chip_rate_hz) * dt_s
        update_code_loop(state, cfg_sig, cfg_trk, dll_error, update_enabled=dll_update_enabled)
        acq_center_hz = float(acq_result["fd_hat_hz"]) + carrier_aiding_rate_hz_per_s * float(t_mid)
        pll_freq_cmd_hz, _, pll_integrator_clamped, pll_freq_clamped = update_carrier_loop(
            state,
            cfg_trk,
            pll_error,
            fll_error_hz,
            dt_s,
            acq_center_hz,
            pll_update_enabled=pll_update_enabled,
            fll_active=fll_active and prev_prompt is not None,
        )

        if motion_profile is None:
            tau_true_s = (
                cfg_motion.code_delay_chips_0 / cfg_sig.chip_rate_hz
                + (cfg_motion.code_delay_rate_chips_per_s / cfg_sig.chip_rate_hz) * t_mid
                + np.interp(t_mid, global_rx_time_s, plasma_rx["tau_g_t"])
            )
            fd_true_hz = (
                cfg_motion.doppler_hz_0
                + cfg_motion.doppler_rate_hz_per_s * t_mid
                + np.interp(t_mid, global_rx_time_s, phi_rate_hz)
            )
        else:
            motion_at_t = _interp_motion_profile(motion_profile, float(t_mid))
            tau_true_s = motion_at_t["code_delay_s"] + np.interp(t_mid, global_rx_time_s, plasma_rx["tau_g_t"])
            fd_true_hz = motion_at_t["doppler_hz"] + np.interp(t_mid, global_rx_time_s, phi_rate_hz)

        t_hist.append(float(t_mid))
        tau_est_hist.append(float(state.tau_est_s))
        tau_true_hist.append(float(tau_true_s))
        fd_est_hist.append(float(state.carrier_freq_hz))
        fd_true_hist.append(float(fd_true_hz))
        phase_est_hist.append(float(state.carrier_phase_total_rad))
        dll_err_hist.append(dll_error)
        pll_err_hist.append(pll_error)
        mag_E_hist.append(float(abs(E)))
        mag_P_hist.append(float(abs(P)))
        mag_L_hist.append(float(abs(L)))
        post_corr_snr_db_hist.append(post_corr_snr_db)
        predicted_cn0_dbhz_hist.append(predicted_cn0_dbhz)
        predicted_post_corr_snr_db_hist.append(predicted_post_corr_snr_db)
        carrier_lock_metric_hist.append(carrier_lock_metric)
        prompt_quadrature_ratio_hist.append(prompt_quadrature_ratio)
        fll_err_hist.append(float(fll_error_hz))
        fll_active_hist.append(bool(fll_active and prev_prompt is not None))
        dll_update_enabled_hist.append(bool(dll_update_enabled))
        pll_update_enabled_hist.append(bool(pll_update_enabled))
        pll_integrator_hist.append(float(state.pll_integrator_hz))
        pll_integrator_clamped_hist.append(bool(pll_integrator_clamped))
        pll_freq_cmd_hist.append(float(pll_freq_cmd_hz))
        pll_freq_clamped_hist.append(bool(pll_freq_clamped))
        carrier_freq_center_hist.append(float(acq_center_hz))
        tau_predict_hist.append(float(state.tau_est_s))
        imu_code_aiding_rate_hist.append(float(code_aiding_rate_chips_per_s))
        imu_carrier_aiding_rate_hist.append(float(carrier_aiding_rate_hz_per_s))
        aiding_enabled_hist.append(bool(aiding_enabled))
        I_E_hist.append(float(E.real))
        Q_E_hist.append(float(E.imag))
        I_P_hist.append(float(P.real))
        Q_P_hist.append(float(P.imag))
        I_L_hist.append(float(L.real))
        Q_L_hist.append(float(L.imag))
        prev_prompt = P

    natural = NaturalMeasurementSeries(
        receive_time_s=np.asarray(t_hist, dtype=float),
        tau_est_s=np.asarray(tau_est_hist, dtype=float),
        carrier_phase_rad=np.asarray(phase_est_hist, dtype=float),
        carrier_frequency_hz=np.asarray(fd_est_hist, dtype=float),
        tau_true_s=np.asarray(tau_true_hist, dtype=float),
        fd_true_hz=np.asarray(fd_true_hist, dtype=float),
        post_corr_snr_db=np.asarray(post_corr_snr_db_hist, dtype=float),
        carrier_lock_metric=np.asarray(carrier_lock_metric_hist, dtype=float),
    )
    observables = form_standard_observables(cfg_sig, natural)

    tau_err_s = natural.tau_est_s - natural.tau_true_s
    fd_err_hz = natural.carrier_frequency_hz - natural.fd_true_hz
    trk_result = {
        "t": np.asarray(t_hist, dtype=float),
        "tau_est_s": np.asarray(tau_est_hist, dtype=float),
        "tau_true_s": np.asarray(tau_true_hist, dtype=float),
        "tau_err_s": np.asarray(tau_err_s, dtype=float),
        "tau_rmse_ns": np.asarray([_rms(tau_err_s) * 1e9], dtype=float),
        "fd_true_hz": np.asarray(fd_true_hist, dtype=float),
        "doppler_hz": np.asarray(observables.doppler_hz_compat, dtype=float),
        "fd_err_hz": np.asarray(fd_err_hz, dtype=float),
        "fd_rmse_hz": np.asarray([_rms(fd_err_hz)], dtype=float),
        "carrier_phase_cycles": np.asarray(observables.carrier_phase_cycles, dtype=float),
        "pseudorange_m": np.asarray(observables.pseudorange_m, dtype=float),
        "range_rate_mps": np.asarray(observables.range_rate_mps, dtype=float),
        "range_rate_true_mps": np.asarray(observables.range_rate_true_mps, dtype=float),
        "dll_err": np.asarray(dll_err_hist, dtype=float),
        "pll_err": np.asarray(pll_err_hist, dtype=float),
        "mag_E": np.asarray(mag_E_hist, dtype=float),
        "mag_P": np.asarray(mag_P_hist, dtype=float),
        "mag_L": np.asarray(mag_L_hist, dtype=float),
        "post_corr_snr_db": np.asarray(post_corr_snr_db_hist, dtype=float),
        "predicted_cn0_dbhz": np.asarray(predicted_cn0_dbhz_hist, dtype=float),
        "predicted_post_corr_snr_db": np.asarray(predicted_post_corr_snr_db_hist, dtype=float),
        "prompt_quadrature_ratio": np.asarray(prompt_quadrature_ratio_hist, dtype=float),
        "carrier_lock_metric": np.asarray(carrier_lock_metric_hist, dtype=float),
        "fll_err_hz": np.asarray(fll_err_hist, dtype=float),
        "fll_active": np.asarray(fll_active_hist, dtype=bool),
        "dll_update_enabled": np.asarray(dll_update_enabled_hist, dtype=bool),
        "pll_update_enabled": np.asarray(pll_update_enabled_hist, dtype=bool),
        "pll_integrator_hz": np.asarray(pll_integrator_hist, dtype=float),
        "pll_integrator_clamped": np.asarray(pll_integrator_clamped_hist, dtype=bool),
        "pll_freq_cmd_hz": np.asarray(pll_freq_cmd_hist, dtype=float),
        "pll_freq_clamped": np.asarray(pll_freq_clamped_hist, dtype=bool),
        "carrier_freq_center_hz": np.asarray(carrier_freq_center_hist, dtype=float),
        "tau_predict_s": np.asarray(tau_predict_hist, dtype=float),
        "imu_code_aiding_rate_chips_per_s": np.asarray(imu_code_aiding_rate_hist, dtype=float),
        "imu_carrier_aiding_rate_hz_per_s": np.asarray(imu_carrier_aiding_rate_hist, dtype=float),
        "aiding_enabled": np.asarray(aiding_enabled_hist, dtype=bool),
        "I_E": np.asarray(I_E_hist, dtype=float),
        "Q_E": np.asarray(Q_E_hist, dtype=float),
        "I_P": np.asarray(I_P_hist, dtype=float),
        "Q_P": np.asarray(Q_P_hist, dtype=float),
        "I_L": np.asarray(I_L_hist, dtype=float),
        "Q_L": np.asarray(Q_L_hist, dtype=float),
        "natural_measurement_note": "receiver layer outputs replica code delay / carrier phase / carrier frequency before standard observable formation",
        "standard_observable_note": observables.sign_convention,
    }
    return trk_result, natural, observables


def summarize_textbook_single_channel_metrics(
    trk_result: dict[str, np.ndarray],
    trk_diag: dict[str, Any],
    wkb_result: dict[str, np.ndarray],
    observables: StandardObservableSeries,
    nav_data_model: NavigationDataModel,
) -> dict[str, float | int | bool]:
    pseudorange_error = np.asarray(observables.pseudorange_m - observables.pseudorange_true_m, dtype=float)
    range_rate_error = np.asarray(observables.range_rate_mps - observables.range_rate_true_mps, dtype=float)
    return {
        "tau_rmse_ns": float(trk_result["tau_rmse_ns"][0]),
        "fd_rmse_hz": float(trk_result["fd_rmse_hz"][0]),
        "range_rate_rmse_mps": float(_rms(range_rate_error)),
        "peak_to_second_ratio": float(0.0 if not trk_diag else 0.0),
        "peak_to_second_db": float(0.0 if not trk_diag else 0.0),
        "loss_found": bool(trk_diag["loss_found"]),
        "loss_fraction": float(np.mean(np.asarray(trk_diag["sustained_loss"], dtype=float))),
        "pll_integrator_clamped": int(np.sum(np.asarray(trk_result["pll_integrator_clamped"], dtype=int))),
        "pll_freq_clamped": int(np.sum(np.asarray(trk_result["pll_freq_clamped"], dtype=int))),
        "tau_g_median_m": float(C_LIGHT * np.median(np.asarray(wkb_result["tau_g_t"], dtype=float))),
        "tau_g_span_m": float(C_LIGHT * (np.max(np.asarray(wkb_result["tau_g_t"], dtype=float)) - np.min(np.asarray(wkb_result["tau_g_t"], dtype=float)))),
        "pseudorange_mean_m": float(np.mean(np.asarray(observables.pseudorange_m, dtype=float))),
        "range_rate_mean_mps": float(np.mean(np.asarray(observables.range_rate_mps, dtype=float))),
        "carrier_phase_mean_cycles": float(np.mean(np.asarray(observables.carrier_phase_cycles, dtype=float))),
        "post_corr_snr_median_db": float(np.median(np.asarray(trk_result["post_corr_snr_db"], dtype=float))),
        "carrier_lock_metric_median": float(np.median(np.asarray(trk_result["carrier_lock_metric"], dtype=float))),
        "nav_bit_rate_bps": float(nav_data_model.bit_rate_bps),
        "nav_data_enabled": True,
        "effective_pseudorange_sigma_100ms_m": float(block_average_sigma(pseudorange_error, 100)),
        "effective_pseudorange_sigma_1s_m": float(block_average_sigma(pseudorange_error, 1000)),
    }


def _save_receiver_spectrum_plot(
    fc_hz: float,
    acq_result: dict[str, Any],
    trk_diag: dict[str, Any],
    fs_hz: float,
    output_dir: Path,
) -> None:
    freq_raw, spec_raw = KA_COMMON.compute_spectrum_db(np.asarray(acq_result["rx_block"]), fs_hz)
    freq_bb, spec_bb = KA_COMMON.compute_spectrum_db(np.asarray(acq_result["best_mixed"]), fs_hz)
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), dpi=160)
    axes[0].plot(freq_raw / 1e3, spec_raw, lw=1.1)
    axes[0].set_title(f"{_freq_label(fc_hz)} Textbook Acquisition Block Spectrum")
    axes[0].set_xlabel("Frequency (kHz)")
    axes[0].set_ylabel("dB")
    axes[0].grid(True, ls=":", alpha=0.5)
    axes[1].plot(freq_bb / 1e3, spec_bb, lw=1.1, color="tab:orange")
    axes[1].set_title(f"{_freq_label(fc_hz)} Textbook Baseband Spectrum")
    axes[1].set_xlabel("Frequency (kHz)")
    axes[1].set_ylabel("dB")
    axes[1].grid(True, ls=":", alpha=0.5)
    loss_frac = float(np.mean(np.asarray(trk_diag["sustained_loss"], dtype=float)))
    fig.suptitle(f"{_freq_label(fc_hz)} textbook receiver spectra | loss fraction = {loss_frac:.3f}")
    fig.tight_layout()
    output_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_dir / f"{_freq_label(fc_hz)}_receiver_spectrum.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def _save_wkb_overview_plots(
    t_eval_rel: np.ndarray,
    frequency_runs: Sequence[TextbookSingleChannelRun],
    output_dir: Path,
) -> None:
    freqs_ghz = np.asarray([run.fc_hz for run in frequency_runs], dtype=float) / 1e9
    amplitude = np.vstack([np.asarray(run.wkb_result["A_t"], dtype=float) for run in frequency_runs])
    attenuation_db = 20.0 * np.log10(np.maximum(amplitude, 1e-30))
    phase_shift_rad = np.vstack([np.asarray(run.wkb_result["phi_t"], dtype=float) for run in frequency_runs])
    group_delay_ns = 1e9 * np.vstack([np.asarray(run.wkb_result["tau_g_t"], dtype=float) for run in frequency_runs])

    fig, axes = plt.subplots(2, 2, figsize=(14, 9), dpi=160)
    heatmaps = [
        (amplitude, "Amplitude", axes[0, 0]),
        (attenuation_db, "Attenuation (dB)", axes[0, 1]),
        (phase_shift_rad, "Phase Shift (rad)", axes[1, 0]),
        (group_delay_ns, "Group Delay (ns)", axes[1, 1]),
    ]
    for data, title, ax in heatmaps:
        mesh = ax.imshow(
            data,
            aspect="auto",
            origin="lower",
            extent=[float(t_eval_rel[0]), float(t_eval_rel[-1]), float(freqs_ghz[0]), float(freqs_ghz[-1])],
        )
        ax.set_title(title)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Frequency (GHz)")
        fig.colorbar(mesh, ax=ax, shrink=0.88)
    fig.tight_layout()
    fig.savefig(output_dir / "wkb_multifreq_overview.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    fig, axes = plt.subplots(3, 1, figsize=(12, 10), dpi=160)
    axes[0].plot(freqs_ghz, np.median(attenuation_db, axis=1), marker="o")
    axes[0].set_title("Median Attenuation vs Frequency")
    axes[0].set_ylabel("dB")
    axes[0].grid(True, ls=":", alpha=0.5)
    axes[1].plot(freqs_ghz, np.median(phase_shift_rad, axis=1), marker="o")
    axes[1].set_title("Median Phase Shift vs Frequency")
    axes[1].set_ylabel("rad")
    axes[1].grid(True, ls=":", alpha=0.5)
    axes[2].plot(freqs_ghz, np.median(group_delay_ns, axis=1), marker="o")
    axes[2].set_title("Median Group Delay vs Frequency")
    axes[2].set_xlabel("Frequency (GHz)")
    axes[2].set_ylabel("ns")
    axes[2].grid(True, ls=":", alpha=0.5)
    fig.tight_layout()
    fig.savefig(output_dir / "wkb_multifreq_frequency_summary.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def run_textbook_single_channel_for_frequency(
    fc_hz: float,
    *,
    field_result: dict[str, np.ndarray] | None = None,
    nu_en_hz: float = KA_COMMON.DEFAULT_NU_EN_HZ,
    delta_f_hz: float = KA_COMMON.DEFAULT_DELTA_F_HZ,
    rng_seed: int = DEFAULT_TRACKING_RNG_SEED,
    truth_free_runtime: bool = True,
    nav_data_enabled: bool = True,
    motion_profile: MotionProfile | None = None,
    aiding_profile: TrackingAidingProfile | None = None,
) -> TextbookSingleChannelRun:
    cache_key = (float(fc_hz), bool(truth_free_runtime), bool(nav_data_enabled))
    if field_result is None and motion_profile is None and aiding_profile is None and cache_key in _RUN_CACHE:
        return _RUN_CACHE[cache_key]

    if field_result is None:
        field_result = KA_COMMON.build_default_field_context()

    t_eval = np.asarray(field_result["t_eval"], dtype=float)
    z_eval = np.asarray(field_result["z_eval"], dtype=float)
    ne_combined = np.asarray(field_result["ne_combined"], dtype=float)
    t_eval_rel = t_eval - t_eval[0]
    wkb_result = KA_COMMON.compute_real_wkb_series(
        t_eval=t_eval,
        z_eval=z_eval,
        ne_matrix=ne_combined,
        fc_hz=fc_hz,
        nu_en_hz=nu_en_hz,
        delta_f_hz=delta_f_hz,
        verbose=False,
    )
    cfg_sig = build_textbook_signal_config(fc_hz=fc_hz, wkb_time_s=wkb_result["wkb_time_s"], nav_data_enabled=nav_data_enabled)
    cfg_motion = KA_COMMON.build_default_motion_config()
    cfg_acq = KA_COMMON.build_default_acquisition_config()
    cfg_trk = KA_COMMON.build_truth_free_tracking_config() if truth_free_runtime else KA_COMMON.build_default_tracking_config()
    rx_time_s = np.arange(cfg_sig.total_samples) / cfg_sig.fs_hz
    plasma_rx = KA_COMMON.resample_wkb_to_receiver_time(
        rx_time_s=rx_time_s,
        wkb_time_s=wkb_result["wkb_time_s"],
        A_t=wkb_result["A_t"],
        phi_t=wkb_result["phi_t"],
        tau_g_t=wkb_result["tau_g_t"],
    )
    code_chips = KA_COMMON.build_transmitter_signal_tools(cfg_sig)["code_chips"]
    nav_data_model = build_navigation_data_model(cfg_sig, rng_seed=rng_seed)
    np.random.seed(rng_seed)
    acq_result = run_textbook_acquisition(
        cfg_sig=cfg_sig,
        cfg_motion=cfg_motion,
        cfg_acq=cfg_acq,
        code_chips=code_chips,
        plasma_rx=plasma_rx,
        global_rx_time_s=rx_time_s,
        nav_data_model=nav_data_model,
    )
    acq_diag = KA_COMMON.LEGACY_DEBUG.diagnose_acquisition_physics(
        cfg_sig=cfg_sig,
        cfg_motion=cfg_motion,
        cfg_acq=cfg_acq,
        acq_result=acq_result,
        plasma_rx=plasma_rx,
        global_rx_time_s=rx_time_s,
    )
    trk_result, natural, observables = run_textbook_tracking(
        cfg_sig=cfg_sig,
        cfg_motion=cfg_motion,
        cfg_trk=cfg_trk,
        code_chips=code_chips,
        plasma_rx=plasma_rx,
        global_rx_time_s=rx_time_s,
        nav_data_model=nav_data_model,
        acq_result=acq_result,
        motion_profile=motion_profile,
        aiding_profile=aiding_profile,
    )
    trk_diag = KA_COMMON.LEGACY_DEBUG.diagnose_tracking_physics(cfg_sig=cfg_sig, cfg_trk=cfg_trk, trk_result=trk_result)
    metrics = summarize_textbook_single_channel_metrics(trk_result, trk_diag, wkb_result, observables, nav_data_model)
    metrics["peak_to_second_ratio"] = float(acq_diag["peak_to_second_ratio"])
    metrics["peak_to_second_db"] = float(acq_diag["peak_to_second_db"])

    run = TextbookSingleChannelRun(
        fc_hz=float(fc_hz),
        field_result=field_result,
        t_eval_rel=t_eval_rel,
        wkb_result=wkb_result,
        cfg_sig=cfg_sig,
        cfg_motion=cfg_motion,
        cfg_acq=cfg_acq,
        cfg_trk=cfg_trk,
        plasma_rx=plasma_rx,
        nav_data_model=nav_data_model,
        acq_result=acq_result,
        acq_diag=acq_diag,
        trk_result=trk_result,
        trk_diag=trk_diag,
        natural_measurements=natural,
        observables=observables,
        metrics=metrics,
    )
    if motion_profile is None and aiding_profile is None:
        _RUN_CACHE[cache_key] = run
    return run


def build_textbook_channel_background(
    receiver_cfg: Any,
    *,
    truth_free_runtime: bool = True,
    nav_data_enabled: bool = True,
    motion_profile: MotionProfile | None = None,
    aiding_profile: TrackingAidingProfile | None = None,
) -> TextbookChannelBackground:
    large_csv, aoa_csv = KA_COMMON.find_legacy_input_files()
    run = run_textbook_single_channel_for_frequency(
        float(receiver_cfg.carrier_frequency_hz),
        truth_free_runtime=truth_free_runtime,
        nav_data_enabled=nav_data_enabled,
        motion_profile=motion_profile,
        aiding_profile=aiding_profile,
    )
    pseudorange_error_m = np.asarray(run.observables.pseudorange_m - run.observables.pseudorange_true_m, dtype=float)
    effective_sigma_100ms_m = block_average_sigma(pseudorange_error_m, 100)
    effective_sigma_1s_m = block_average_sigma(pseudorange_error_m, 1000)
    n_blocks_1s = len(pseudorange_error_m) // 1000
    if n_blocks_1s > 0:
        effective_rmse_m = float(
            np.sqrt(np.mean((pseudorange_error_m[: n_blocks_1s * 1000].reshape(-1, 1000).mean(axis=1)) ** 2))
        )
    else:
        effective_rmse_m = float(_rms(pseudorange_error_m))
    effective_bias_m = float(np.mean(pseudorange_error_m))
    tau_g_m = C_LIGHT * np.asarray(run.wkb_result["tau_g_t"], dtype=float)
    return TextbookChannelBackground(
        large_csv=large_csv,
        aoa_csv=aoa_csv,
        wkb_result=run.wkb_result,
        trk_result=run.trk_result,
        acq_diag=run.acq_diag,
        trk_diag=run.trk_diag,
        effective_pseudorange_sigma_1s_m=effective_sigma_1s_m,
        effective_pseudorange_sigma_100ms_m=effective_sigma_100ms_m,
        effective_pseudorange_rmse_m=effective_rmse_m,
        effective_pseudorange_bias_m=effective_bias_m,
        tau_g_median_m=float(np.median(tau_g_m)),
        tau_g_span_m=float(np.max(tau_g_m) - np.min(tau_g_m)),
        reused_components=[
            "build_fields_from_csv",
            "compute_real_wkb_series",
            "build_textbook_signal_config",
            "build_navigation_data_model",
            "run_textbook_acquisition",
            "run_textbook_tracking",
            "form_standard_observables",
        ],
        natural_measurements=run.natural_measurements,
        standard_observables=run.observables,
        nav_data_model=run.nav_data_model,
    )


def run_textbook_single_channel_frequency_grid(
    frequencies_hz: Sequence[float],
    *,
    single_output_dir: Path,
    observables_output_dir: Path,
    truth_free_runtime: bool = True,
    nav_data_enabled: bool = True,
) -> list[TextbookSingleChannelRun]:
    single_output_dir.mkdir(parents=True, exist_ok=True)
    observables_output_dir.mkdir(parents=True, exist_ok=True)
    spectra_dir = single_output_dir / "receiver_spectra"
    details_dir = single_output_dir / "frequency_details"
    details_dir.mkdir(parents=True, exist_ok=True)

    field_result = KA_COMMON.build_default_field_context()
    runs: list[TextbookSingleChannelRun] = []
    summary_rows: list[dict[str, Any]] = []
    receiver_runs: list[dict[str, Any]] = []
    for idx, fc_hz in enumerate(frequencies_hz):
        run = run_textbook_single_channel_for_frequency(
            float(fc_hz),
            field_result=field_result,
            rng_seed=DEFAULT_TRACKING_RNG_SEED + idx,
            truth_free_runtime=truth_free_runtime,
            nav_data_enabled=nav_data_enabled,
        )
        runs.append(run)
        _save_receiver_spectrum_plot(float(fc_hz), run.acq_result, run.trk_diag, run.cfg_sig.fs_hz, spectra_dir)
        label = _freq_label(float(fc_hz))
        natural = run.natural_measurements
        observables = run.observables
        obs_dir = observables_output_dir / label
        _write_series_csv(
            obs_dir / "natural_measurements.csv",
            {
                "receive_time_s": natural.receive_time_s,
                "tau_est_s": natural.tau_est_s,
                "tau_true_s": natural.tau_true_s,
                "carrier_phase_rad": natural.carrier_phase_rad,
                "carrier_frequency_hz": natural.carrier_frequency_hz,
                "fd_true_hz": natural.fd_true_hz,
                "post_corr_snr_db": natural.post_corr_snr_db,
                "carrier_lock_metric": natural.carrier_lock_metric,
            },
        )
        _write_series_csv(
            obs_dir / "standard_observables.csv",
            {
                "receive_time_s": observables.receive_time_s,
                "transmit_time_est_s": observables.transmit_time_est_s,
                "pseudorange_m": observables.pseudorange_m,
                "pseudorange_true_m": observables.pseudorange_true_m,
                "carrier_phase_cycles": observables.carrier_phase_cycles,
                "range_rate_mps": observables.range_rate_mps,
                "range_rate_true_mps": observables.range_rate_true_mps,
                "doppler_hz_compat": observables.doppler_hz_compat,
            },
        )
        write_json(
            obs_dir / "summary.json",
            {
                "frequency_hz": float(fc_hz),
                "signal_model": {
                    "nav_data_enabled": bool(run.cfg_sig.nav_data_enabled),
                    "nav_bit_rate_bps": float(run.nav_data_model.bit_rate_bps),
                    "sign_convention": observables.sign_convention,
                },
                "natural_measurements": {
                    "count": int(len(natural.receive_time_s)),
                    "tau_rmse_ns": float(run.trk_result["tau_rmse_ns"][0]),
                    "fd_rmse_hz": float(run.trk_result["fd_rmse_hz"][0]),
                },
                "standard_observables": {
                    "pseudorange_sigma_100ms_m": float(run.metrics["effective_pseudorange_sigma_100ms_m"]),
                    "pseudorange_sigma_1s_m": float(run.metrics["effective_pseudorange_sigma_1s_m"]),
                    "range_rate_rmse_mps": float(run.metrics["range_rate_rmse_mps"]),
                },
            },
        )
        summary_rows.append(
            {
                "frequency_hz": float(fc_hz),
                "amplitude_median": float(np.median(np.asarray(run.wkb_result["A_t"], dtype=float))),
                "attenuation_db_median": float(np.median(20.0 * np.log10(np.asarray(run.wkb_result["A_t"], dtype=float) + 1e-30))),
                "phase_rad_median": float(np.median(np.asarray(run.wkb_result["phi_t"], dtype=float))),
                "group_delay_ns_median": float(np.median(np.asarray(run.wkb_result["tau_g_t"], dtype=float)) * 1e9),
                "receiver_tau_rmse_ns": float(run.metrics["tau_rmse_ns"]),
                "receiver_fd_rmse_hz": float(run.metrics["fd_rmse_hz"]),
                "peak_to_second_db": float(run.metrics["peak_to_second_db"]),
                "post_corr_snr_median_db": float(run.metrics["post_corr_snr_median_db"]),
                "carrier_lock_metric_median": float(run.metrics["carrier_lock_metric_median"]),
                "loss_fraction": float(run.metrics["loss_fraction"]),
            }
        )
        receiver_runs.append(
            {
                "label": label,
                "frequency_hz": float(fc_hz),
                "tau_rmse_ns": float(run.metrics["tau_rmse_ns"]),
                "fd_rmse_hz": float(run.metrics["fd_rmse_hz"]),
                "peak_to_second_db": float(run.metrics["peak_to_second_db"]),
                "loss_fraction": float(run.metrics["loss_fraction"]),
                "spectrum_png": str((spectra_dir / f"{label}_receiver_spectrum.png").resolve()),
            }
        )
        write_json(
            details_dir / f"{label}.json",
            {
                "label": label,
                "frequency_hz": float(fc_hz),
                "metrics": _as_serializable(run.metrics),
                "wkb": {
                    "amplitude_median": float(np.median(np.asarray(run.wkb_result["A_t"], dtype=float))),
                    "attenuation_db_median": float(np.median(20.0 * np.log10(np.asarray(run.wkb_result["A_t"], dtype=float) + 1e-30))),
                    "phase_rad_median": float(np.median(np.asarray(run.wkb_result["phi_t"], dtype=float))),
                    "group_delay_ns_median": float(np.median(np.asarray(run.wkb_result["tau_g_t"], dtype=float)) * 1e9),
                },
                "signal_model": {
                    "nav_data_enabled": bool(run.cfg_sig.nav_data_enabled),
                    "nav_bit_rate_bps": float(run.nav_data_model.bit_rate_bps),
                },
                "outputs": {
                    "spectrum_png": str((spectra_dir / f"{label}_receiver_spectrum.png").resolve()),
                    "natural_measurements_csv": str((obs_dir / "natural_measurements.csv").resolve()),
                    "standard_observables_csv": str((obs_dir / "standard_observables.csv").resolve()),
                },
            },
        )

    _write_csv(single_output_dir / "frequency_summary.csv", summary_rows)
    _save_wkb_overview_plots(runs[0].t_eval_rel, runs, single_output_dir)
    write_json(
        single_output_dir / "summary.json",
        {
            "title": "Issue 03 textbook-corrected single-channel Ka receiver sweep",
            "frequencies_hz": [float(v) for v in frequencies_hz],
            "frequency_labels": [_freq_label(float(v)) for v in frequencies_hz],
            "collision_frequency_hz": float(KA_COMMON.DEFAULT_NU_EN_HZ),
            "receiver_config": {
                "fs_hz": float(KA_COMMON.DEFAULT_FS_HZ),
                "chip_rate_hz": float(KA_COMMON.DEFAULT_CHIP_RATE_HZ),
                "coherent_integration_s": float(KA_COMMON.DEFAULT_COHERENT_INTEGRATION_S),
                "code_length": int(KA_COMMON.DEFAULT_CODE_LENGTH),
                "cn0_dbhz": float(KA_COMMON.DEFAULT_CN0_DBHZ),
                "truth_free_runtime": bool(truth_free_runtime),
                "nav_data_enabled": bool(nav_data_enabled),
                "nav_bit_rate_bps": float(DEFAULT_NAV_BIT_RATE_BPS),
            },
            "receiver_runs": receiver_runs,
            "outputs": {
                "results_dir": str(single_output_dir.resolve()),
                "summary_csv": str((single_output_dir / "frequency_summary.csv").resolve()),
                "overview_png": str((single_output_dir / "wkb_multifreq_overview.png").resolve()),
                "frequency_summary_png": str((single_output_dir / "wkb_multifreq_frequency_summary.png").resolve()),
                "spectrum_dir": str(spectra_dir.resolve()),
                "frequency_detail_dir": str(details_dir.resolve()),
                "observables_dir": str(observables_output_dir.resolve()),
            },
        },
    )
    return runs


def build_three_way_rows(
    legacy_rows: Sequence[dict[str, Any]],
    issue01_rows: Sequence[dict[str, Any]],
    issue03_rows: Sequence[dict[str, Any]],
    *,
    keys: Sequence[str] = DEFAULT_COMPARISON_KEYS,
) -> list[dict[str, Any]]:
    legacy_map = {float(row["frequency_hz"]): row for row in legacy_rows}
    issue01_map = {float(row["frequency_hz"]): row for row in issue01_rows}
    issue03_map = {float(row["frequency_hz"]): row for row in issue03_rows}
    freqs = sorted(set(legacy_map) & set(issue01_map) & set(issue03_map))
    rows: list[dict[str, Any]] = []
    for fc_hz in freqs:
        row: dict[str, Any] = {"frequency_hz": float(fc_hz)}
        for key in keys:
            legacy_val = float(legacy_map[fc_hz][key])
            issue01_val = float(issue01_map[fc_hz][key])
            issue03_val = float(issue03_map[fc_hz][key])
            row[f"{key}_legacy"] = legacy_val
            row[f"{key}_issue01"] = issue01_val
            row[f"{key}_issue03"] = issue03_val
            row[f"{key}_delta_issue01_vs_legacy"] = issue01_val - legacy_val
            row[f"{key}_delta_issue03_vs_issue01"] = issue03_val - issue01_val
            row[f"{key}_delta_issue03_vs_legacy"] = issue03_val - legacy_val
        rows.append(row)
    return rows


def write_three_way_plot(
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
        ax.plot(freq_ghz, [float(row[f"{key}_legacy"]) for row in comparison_rows], marker="o", label="legacy")
        ax.plot(freq_ghz, [float(row[f"{key}_issue01"]) for row in comparison_rows], marker="o", label="issue01")
        ax.plot(freq_ghz, [float(row[f"{key}_issue03"]) for row in comparison_rows], marker="o", label="issue03")
        ax.set_title(title)
        ax.set_xlabel("Frequency (GHz)")
        ax.set_ylabel(ylabel)
        ax.grid(True, ls=":", alpha=0.5)
        ax.legend()
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180, bbox_inches="tight")
    plt.close(fig)


__all__ = [
    "DEFAULT_COMPARISON_KEYS",
    "NavigationDataModel",
    "NaturalMeasurementSeries",
    "StandardObservableSeries",
    "MotionProfile",
    "TrackingAidingProfile",
    "TextbookChannelBackground",
    "TextbookSingleChannelRun",
    "build_textbook_channel_background",
    "run_textbook_single_channel_for_frequency",
    "run_textbook_single_channel_frequency_grid",
    "build_three_way_rows",
    "write_three_way_plot",
]
