# -*- coding: utf-8 -*-
"""
exp_dynamic_multisat_ekf_report.py
==================================

This script does not replace the existing real WKB / receiver-chain notebooks.
It adds a dynamic navigation estimation layer on top of the already validated
single-channel physical background.

Main chain
----------
CSV
-> build_fields_from_csv
-> compute_real_wkb_series
-> build_signal_config_from_wkb_time
-> resample_wkb_to_receiver_time
-> KaBpskReceiver.run
-> legacy single-channel time series and error statistics
-> time-varying multisatellite geometry
-> epoch pseudorange / range-rate observations
-> epoch-wise WLS baseline
-> dynamic EKF
-> figures / CSV / JSON / markdown report

Boundary
--------
This remains a hybrid experiment:
- the single-channel plasma/WKB/receiver background is real and reused;
- the multisatellite geometry and dynamic receiver truth are self-consistent
  but synthetic;
- the resulting dynamic navigation metrics must not be claimed as a fully
  end-to-end real multisatellite Ka navigation performance result.
"""

from __future__ import annotations

import csv
import json
import math
import os
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from nav_ka import CANONICAL_RESULTS_ROOT
from nav_ka.legacy import exp_multisat_wls_pvt_report as LEGACY_WLS
from nav_ka.studies.issue_01_truth_dependency import build_truth_free_initial_state_from_observations
from nav_ka.studies.issue_03_textbook_correction import build_textbook_channel_background


# ============================================================
# 0. Legacy loading
# ============================================================

ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = CANONICAL_RESULTS_ROOT / "results_dynamic_multisat_ekf"


def results_dir_for_frequency(fc_hz: float) -> Path:
    if math.isclose(fc_hz, 22.5e9, rel_tol=0.0, abs_tol=1.0):
        return CANONICAL_RESULTS_ROOT / "results_dynamic_multisat_ekf"
    label = f"{fc_hz / 1e9:.1f}".replace(".", "p")
    return CANONICAL_RESULTS_ROOT / f"results_dynamic_multisat_ekf_{label}GHz"
LEGACY_DEBUG = LEGACY_WLS.LEGACY_DEBUG
C_LIGHT = LEGACY_WLS.C_LIGHT

PlotConfig = LEGACY_WLS.PlotConfig
finalize_figure = LEGACY_WLS.finalize_figure
to_serializable = LEGACY_WLS.to_serializable
block_average_sigma = LEGACY_WLS.block_average_sigma
lla_to_ecef = LEGACY_WLS.lla_to_ecef
ecef_to_enu_rotation_matrix = LEGACY_WLS.ecef_to_enu_rotation_matrix
ecef_delta_to_enu = LEGACY_WLS.ecef_delta_to_enu
los_unit_vector_enu = LEGACY_WLS.los_unit_vector_enu
satellite_position_from_local_geometry = LEGACY_WLS.satellite_position_from_local_geometry
compute_tropo_delay_m = LEGACY_WLS.compute_tropo_delay_m
solve_pvt_iterative = LEGACY_WLS.solve_pvt_iterative
plot_legacy_channel_overview = LEGACY_WLS.plot_legacy_channel_overview

plt.rcParams["font.family"] = "serif"
plt.rcParams["xtick.direction"] = "in"
plt.rcParams["ytick.direction"] = "in"


# ============================================================
# 1. Configs and data structures
# ============================================================


@dataclass(frozen=True)
class DynamicExperimentConfig:
    nav_rate_hz: float = 10.0
    carrier_frequency_hz: float = 22.5e9
    receiver_velocity_ecef_mps: tuple[float, float, float] = (-85.0, 120.0, 35.0)
    receiver_clock_bias_m: float = 120.0
    receiver_clock_drift_mps: float = 0.38
    azimuth_deg_list: tuple[float, ...] = (18.0, 62.0, 109.0, 152.0, 208.0, 253.0, 302.0, 342.0)
    elevation_deg_list: tuple[float, ...] = (74.0, 66.0, 56.0, 45.0, 31.0, 22.0, 15.0, 11.0)
    azimuth_rate_degps_list: tuple[float, ...] = (0.042, -0.036, 0.031, -0.026, 0.022, -0.019, 0.017, -0.015)
    elevation_rate_degps_list: tuple[float, ...] = (-0.024, -0.018, -0.011, -0.004, 0.008, 0.013, 0.018, 0.022)
    sat_clock_bias_ns_list: tuple[float, ...] = (28.0, -17.0, 13.0, -31.0, 22.0, -8.0, 36.0, -15.0)
    sat_clock_drift_mps_list: tuple[float, ...] = (0.05, -0.03, 0.02, -0.04, 0.03, -0.02, 0.01, -0.05)
    range_rate_mps_list: tuple[float, ...] = (35.0, 105.0, -280.0, -640.0, -260.0, 390.0, 760.0, -720.0)
    azimuth_oscillation_amp_deg: float = 0.24
    elevation_oscillation_amp_deg: float = 0.18
    range_oscillation_amp_m: float = 12_000.0
    geometry_oscillation_period_s: float = 16.0
    tropo_zenith_delay_m: float = 2.5
    dispersive_scale_factor: float = 1.0
    hardware_scale_factor: float = 1.0
    min_elevation_deg: float = 8.0
    min_post_corr_snr_db: float = -1.0
    min_carrier_lock_metric: float = 0.12
    drop_on_sustained_loss: bool = False
    low_elevation_sigma_boost_factor: float = 1.8
    snr_sigma_boost_factor: float = 0.55
    lock_sigma_boost_factor: float = 2.2
    degradation_start_fraction: float = 0.46
    degradation_end_fraction: float = 0.58
    degradation_sat_ids: tuple[str, ...] = ("G06", "G07", "G08")
    degradation_snr_penalty_db: float = 8.0
    degradation_lock_penalty: float = 0.22
    degradation_sigma_factor: float = 6.5
    independent_pr_noise_fraction: float = 0.35
    independent_rr_noise_fraction: float = 0.35
    process_accel_sigma_mps2: float = 0.45
    process_clock_drift_sigma_mps2: float = 0.20
    init_position_sigma_m: float = 250.0
    init_velocity_sigma_mps: float = 35.0
    init_clock_bias_sigma_m: float = 80.0
    init_clock_drift_sigma_mps: float = 8.0
    divergence_position_sigma_threshold_m: float = 5_000.0
    divergence_innovation_pr_threshold_m: float = 300.0
    divergence_innovation_rr_threshold_mps: float = 120.0
    rng_seed: int = 20260326
    enable_carrier_phase_experiment: bool = False


@dataclass(frozen=True)
class MovingReceiverTruthAdapter:
    receiver_ecef_m: np.ndarray
    receiver_clock_bias_m: float
    latitude_deg: float
    longitude_deg: float


@dataclass(frozen=True)
class DynamicTruthState:
    t_s: float
    position_ecef_m: np.ndarray
    velocity_ecef_mps: np.ndarray
    clock_bias_m: float
    clock_drift_mps: float


@dataclass(frozen=True)
class SatelliteTemplate:
    sat_id: str
    initial_pos_ecef_m: np.ndarray
    initial_geometric_range_m: float
    azimuth_rate_degps: float
    elevation_rate_degps: float
    range_rate_mps: float
    phase_offset_rad: float
    clock_bias_s: float
    clock_drift_mps: float
    hardware_bias_m: float
    azimuth_deg_0: float
    elevation_deg_0: float


@dataclass(frozen=True)
class DynamicObservation:
    epoch_idx: int
    t_s: float
    sat_id: str
    valid: bool
    degradation_applied: bool
    azimuth_deg: float
    elevation_deg: float
    sat_pos_ecef_m: np.ndarray
    sat_vel_ecef_mps: np.ndarray
    geometric_range_m: float
    geometric_range_rate_mps: float
    sat_clock_bias_s: float
    sat_clock_drift_mps: float
    tropo_delay_m: float
    dispersive_delay_m: float
    hardware_bias_m: float
    pseudorange_m: float
    pseudorange_sigma_m: float
    range_rate_mps: float
    range_rate_sigma_mps: float
    legacy_snr_db: float
    legacy_lock_metric: float
    legacy_loss_flag: bool
    legacy_pr_error_m: float
    legacy_rr_error_mps: float
    measurement_note: str


@dataclass(frozen=True)
class EpochObservationBatch:
    epoch_idx: int
    t_s: float
    truth: DynamicTruthState
    observations: tuple[DynamicObservation, ...]

    @property
    def num_valid_sats(self) -> int:
        return int(sum(obs.valid for obs in self.observations))


@dataclass(frozen=True)
class EpochWlsResult:
    epoch_idx: int
    t_s: float
    valid: bool
    num_valid_sats: int
    state_vector_m: np.ndarray
    residual_rms_m: float
    position_error_3d_m: float
    clock_bias_error_m: float
    warning: str


@dataclass(frozen=True)
class EkfEpochResult:
    epoch_idx: int
    t_s: float
    mode: str
    state_vector: np.ndarray
    covariance_diag: np.ndarray
    num_valid_sats: int
    innovation_rms_pr_m: float
    innovation_rms_rr_mps: float
    position_error_3d_m: float
    velocity_error_3d_mps: float
    clock_bias_error_m: float
    clock_drift_error_mps: float
    prediction_only: bool
    diverged: bool
    warning: str


@dataclass(frozen=True)
class RunResult:
    mode: str
    history: tuple[EkfEpochResult, ...]


@dataclass(frozen=True)
class LegacyEpochMetrics:
    t_s: np.ndarray
    pr_shared_error_m: np.ndarray
    rr_shared_error_mps: np.ndarray
    snr_db: np.ndarray
    lock_metric: np.ndarray
    loss_flag: np.ndarray
    tau_g_m: np.ndarray
    pr_sigma_ref_m: float
    rr_sigma_ref_mps: float
    snr_reference_db: float
    lock_reference: float


def rms(values: Sequence[float] | np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0:
        return float("nan")
    return float(np.sqrt(np.mean(arr ** 2)))


def safe_std(values: Sequence[float] | np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    if arr.size <= 1:
        return 0.0
    return float(np.std(arr, ddof=1))


def nanmean_or_nan(values: Sequence[float] | np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0 or np.all(np.isnan(arr)):
        return float("nan")
    return float(np.nanmean(arr))


def finite_or_none(value: float) -> float | None:
    return float(value) if math.isfinite(value) else None


def wrap_to_range(value: float, lower: float, upper: float) -> float:
    width = upper - lower
    wrapped = (value - lower) % width + lower
    if wrapped == upper:
        wrapped = lower
    return float(wrapped)


# ============================================================
# 2. Truth trajectory and legacy background
# ============================================================


def build_receiver_truth_config(exp_cfg: DynamicExperimentConfig) -> LEGACY_WLS.ReceiverTruthConfig:
    return LEGACY_WLS.ReceiverTruthConfig(
        latitude_deg=34.0,
        longitude_deg=108.0,
        height_m=500.0,
        receiver_clock_bias_m=exp_cfg.receiver_clock_bias_m,
        carrier_frequency_hz=exp_cfg.carrier_frequency_hz,
        sat_orbit_radius_m=26_560_000.0,
    )


def build_truth_history(
    receiver_cfg: LEGACY_WLS.ReceiverTruthConfig,
    exp_cfg: DynamicExperimentConfig,
    epoch_times_s: np.ndarray,
) -> list[DynamicTruthState]:
    initial_pos = receiver_cfg.receiver_ecef_m.astype(float)
    velocity = np.asarray(exp_cfg.receiver_velocity_ecef_mps, dtype=float)

    truth_history: list[DynamicTruthState] = []
    for t_s in epoch_times_s:
        position = initial_pos + velocity * float(t_s)
        clock_bias_m = exp_cfg.receiver_clock_bias_m + exp_cfg.receiver_clock_drift_mps * float(t_s)
        truth_history.append(
            DynamicTruthState(
                t_s=float(t_s),
                position_ecef_m=position,
                velocity_ecef_mps=velocity.copy(),
                clock_bias_m=float(clock_bias_m),
                clock_drift_mps=float(exp_cfg.receiver_clock_drift_mps),
            )
        )
    return truth_history


def build_nav_epoch_metrics(
    legacy_bg: LEGACY_WLS.LegacyChannelBackground,
    receiver_cfg: LEGACY_WLS.ReceiverTruthConfig,
    exp_cfg: DynamicExperimentConfig,
) -> tuple[np.ndarray, LegacyEpochMetrics]:
    trk_result = legacy_bg.trk_result
    trk_diag = legacy_bg.trk_diag
    tracking_t = np.asarray(trk_result["t"], dtype=float)
    tracking_dt = float(np.median(np.diff(tracking_t)))
    nav_dt = 1.0 / exp_cfg.nav_rate_hz
    nav_block_size = max(int(round(nav_dt / tracking_dt)), 1)
    num_epochs = len(tracking_t) // nav_block_size
    if num_epochs < 5:
        raise RuntimeError("Too few navigation epochs after aggregation.")

    truncated = slice(0, num_epochs * nav_block_size)
    tracking_t = tracking_t[truncated]
    pr_error_m = np.asarray(trk_result["pseudorange_m"], dtype=float)[truncated] - C_LIGHT * np.asarray(
        trk_result["tau_true_s"], dtype=float
    )[truncated]
    rr_error_mps = -(C_LIGHT / receiver_cfg.carrier_frequency_hz) * (
        np.asarray(trk_result["doppler_hz"], dtype=float)[truncated] - np.asarray(trk_result["fd_true_hz"], dtype=float)[truncated]
    )
    snr_db = np.asarray(trk_result["post_corr_snr_db"], dtype=float)[truncated]
    lock_metric = np.asarray(trk_result["carrier_lock_metric"], dtype=float)[truncated]
    loss_flag = np.asarray(trk_diag["sustained_loss"], dtype=bool)[truncated]
    tau_g_tracking_m = C_LIGHT * np.interp(
        tracking_t,
        np.asarray(legacy_bg.wkb_result["wkb_time_s"], dtype=float),
        np.asarray(legacy_bg.wkb_result["tau_g_t"], dtype=float),
    )

    def reshape(arr: np.ndarray) -> np.ndarray:
        return np.asarray(arr, dtype=float).reshape(num_epochs, nav_block_size)

    epoch_times_s = reshape(tracking_t).mean(axis=1)
    metrics = LegacyEpochMetrics(
        t_s=epoch_times_s,
        pr_shared_error_m=reshape(pr_error_m).mean(axis=1),
        rr_shared_error_mps=reshape(rr_error_mps).mean(axis=1),
        snr_db=np.median(reshape(snr_db), axis=1),
        lock_metric=np.median(reshape(lock_metric), axis=1),
        loss_flag=np.any(loss_flag.reshape(num_epochs, nav_block_size), axis=1),
        tau_g_m=np.median(reshape(tau_g_tracking_m), axis=1),
        pr_sigma_ref_m=float(block_average_sigma(pr_error_m, nav_block_size)),
        rr_sigma_ref_mps=float(block_average_sigma(rr_error_mps, nav_block_size)),
        snr_reference_db=float(np.median(snr_db)),
        lock_reference=float(np.median(lock_metric)),
    )
    return epoch_times_s, metrics


# ============================================================
# 3. Satellite time-varying geometry
# ============================================================


def _unit(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm <= 0.0:
        raise ValueError("Zero-norm vector encountered.")
    return np.asarray(vector, dtype=float) / norm


def _build_tangent_velocity_direction(position_ecef_m: np.ndarray, phase_deg: float) -> np.ndarray:
    sat_hat = _unit(position_ecef_m)
    reference = np.array([0.0, 0.0, 1.0], dtype=float)
    if abs(float(np.dot(sat_hat, reference))) > 0.92:
        reference = np.array([1.0, 0.0, 0.0], dtype=float)
    tangent_a = _unit(np.cross(reference, sat_hat))
    tangent_b = _unit(np.cross(sat_hat, tangent_a))
    phase_rad = math.radians(phase_deg)
    return _unit(math.cos(phase_rad) * tangent_a + math.sin(phase_rad) * tangent_b)


def build_satellite_templates(
    receiver_cfg: LEGACY_WLS.ReceiverTruthConfig,
    exp_cfg: DynamicExperimentConfig,
) -> list[SatelliteTemplate]:
    base_hardware_biases = np.array([0.8, -0.6, 1.1, -0.9, 0.4, -0.7, 1.6, -1.3], dtype=float)
    templates: list[SatelliteTemplate] = []
    for idx, (azimuth_deg, elevation_deg, az_rate_degps, el_rate_degps, range_rate_mps) in enumerate(
        zip(
            exp_cfg.azimuth_deg_list,
            exp_cfg.elevation_deg_list,
            exp_cfg.azimuth_rate_degps_list,
            exp_cfg.elevation_rate_degps_list,
            exp_cfg.range_rate_mps_list,
            strict=True,
        )
    ):
        sat_pos_ecef_m, geometric_range_m = satellite_position_from_local_geometry(
            receiver_ecef_m=receiver_cfg.receiver_ecef_m,
            latitude_deg=receiver_cfg.latitude_deg,
            longitude_deg=receiver_cfg.longitude_deg,
            azimuth_deg=azimuth_deg,
            elevation_deg=elevation_deg,
            sat_orbit_radius_m=receiver_cfg.sat_orbit_radius_m,
        )
        templates.append(
            SatelliteTemplate(
                sat_id=f"G{idx + 1:02d}",
                initial_pos_ecef_m=sat_pos_ecef_m,
                initial_geometric_range_m=float(geometric_range_m),
                azimuth_rate_degps=float(az_rate_degps),
                elevation_rate_degps=float(el_rate_degps),
                range_rate_mps=float(range_rate_mps),
                phase_offset_rad=float(math.radians(32.0 * idx)),
                clock_bias_s=exp_cfg.sat_clock_bias_ns_list[idx] * 1e-9,
                clock_drift_mps=float(exp_cfg.sat_clock_drift_mps_list[idx]),
                hardware_bias_m=float(exp_cfg.hardware_scale_factor * base_hardware_biases[idx]),
                azimuth_deg_0=float(azimuth_deg),
                elevation_deg_0=float(elevation_deg),
            )
        )
    return templates


def _dynamic_local_geometry(
    template: SatelliteTemplate,
    exp_cfg: DynamicExperimentConfig,
    t_s: float,
) -> tuple[float, float, float]:
    omega_radps = 2.0 * math.pi / exp_cfg.geometry_oscillation_period_s
    phase = omega_radps * float(t_s) + template.phase_offset_rad
    azimuth_deg = wrap_to_range(
        template.azimuth_deg_0
        + template.azimuth_rate_degps * float(t_s)
        + exp_cfg.azimuth_oscillation_amp_deg * math.sin(phase),
        0.0,
        360.0,
    )
    elevation_deg = float(
        np.clip(
            template.elevation_deg_0
            + template.elevation_rate_degps * float(t_s)
            + exp_cfg.elevation_oscillation_amp_deg * math.sin(phase + 0.9),
            5.0,
            85.0,
        )
    )
    geometric_range_m = float(
        template.initial_geometric_range_m
        + template.range_rate_mps * float(t_s)
        + exp_cfg.range_oscillation_amp_m * math.sin(phase + 1.4)
    )
    return float(azimuth_deg), elevation_deg, geometric_range_m


def _satellite_position_from_dynamic_local_geometry(
    receiver_cfg: LEGACY_WLS.ReceiverTruthConfig,
    azimuth_deg: float,
    elevation_deg: float,
    geometric_range_m: float,
) -> np.ndarray:
    rot_enu_to_ecef = ecef_to_enu_rotation_matrix(receiver_cfg.latitude_deg, receiver_cfg.longitude_deg).T
    los_ecef = rot_enu_to_ecef @ los_unit_vector_enu(azimuth_deg, elevation_deg)
    los_ecef = los_ecef / np.linalg.norm(los_ecef)
    return receiver_cfg.receiver_ecef_m + geometric_range_m * los_ecef


def compute_satellite_state_at_time(
    template: SatelliteTemplate,
    receiver_cfg: LEGACY_WLS.ReceiverTruthConfig,
    exp_cfg: DynamicExperimentConfig,
    t_s: float,
) -> tuple[np.ndarray, np.ndarray]:
    azimuth_deg, elevation_deg, geometric_range_m = _dynamic_local_geometry(template, exp_cfg, t_s)
    sat_pos = _satellite_position_from_dynamic_local_geometry(
        receiver_cfg,
        azimuth_deg,
        elevation_deg,
        geometric_range_m,
    )

    finite_diff_dt_s = 0.5
    _, _, geometric_range_prev_m = _dynamic_local_geometry(template, exp_cfg, t_s - finite_diff_dt_s)
    azimuth_prev_deg, elevation_prev_deg, _ = _dynamic_local_geometry(template, exp_cfg, t_s - finite_diff_dt_s)
    sat_pos_prev = _satellite_position_from_dynamic_local_geometry(
        receiver_cfg,
        azimuth_prev_deg,
        elevation_prev_deg,
        geometric_range_prev_m,
    )
    azimuth_next_deg, elevation_next_deg, geometric_range_next_m = _dynamic_local_geometry(template, exp_cfg, t_s + finite_diff_dt_s)
    sat_pos_next = _satellite_position_from_dynamic_local_geometry(
        receiver_cfg,
        azimuth_next_deg,
        elevation_next_deg,
        geometric_range_next_m,
    )
    sat_vel = (sat_pos_next - sat_pos_prev) / (2.0 * finite_diff_dt_s)
    return sat_pos, sat_vel


def compute_az_el(
    delta_ecef_m: np.ndarray,
    reference_latitude_deg: float,
    reference_longitude_deg: float,
) -> tuple[float, float]:
    enu = ecef_delta_to_enu(delta_ecef_m, reference_latitude_deg, reference_longitude_deg)
    range_m = float(np.linalg.norm(enu))
    if range_m <= 0.0:
        return 0.0, -90.0
    azimuth_deg = math.degrees(math.atan2(enu[0], enu[1]))
    azimuth_deg = wrap_to_range(azimuth_deg, 0.0, 360.0)
    elevation_deg = math.degrees(math.asin(np.clip(enu[2] / range_m, -1.0, 1.0)))
    return azimuth_deg, elevation_deg


# ============================================================
# 4. Observation formation
# ============================================================


def degradation_window(exp_cfg: DynamicExperimentConfig, epoch_times_s: np.ndarray) -> tuple[float, float]:
    total_duration_s = float(epoch_times_s[-1] - epoch_times_s[0])
    start_s = float(epoch_times_s[0] + exp_cfg.degradation_start_fraction * total_duration_s)
    end_s = float(epoch_times_s[0] + exp_cfg.degradation_end_fraction * total_duration_s)
    return start_s, end_s


def is_in_degradation_window(t_s: float, start_s: float, end_s: float) -> bool:
    return bool(start_s <= t_s <= end_s)


def measurement_sigma_from_legacy(
    elevation_deg: float,
    snr_db: float,
    lock_metric: float,
    sigma_ref: float,
    exp_cfg: DynamicExperimentConfig,
    *,
    snr_reference_db: float,
    lock_reference: float,
    rate_mode: str,
    extra_sigma_factor: float,
) -> float:
    sin_el = max(math.sin(math.radians(max(elevation_deg, 1e-3))), 0.08)
    elevation_power = 0.70 if rate_mode == "pr" else 0.40
    sigma = sigma_ref / (sin_el ** elevation_power)

    if elevation_deg < 15.0:
        scale = 1.0 - elevation_deg / 15.0
        sigma += sigma_ref * exp_cfg.low_elevation_sigma_boost_factor * scale

    snr_gap_db = max(0.0, snr_reference_db - snr_db)
    sigma *= 1.0 + exp_cfg.snr_sigma_boost_factor * snr_gap_db / 6.0

    lock_gap = max(0.0, lock_reference - lock_metric)
    sigma *= 1.0 + exp_cfg.lock_sigma_boost_factor * lock_gap

    sigma *= extra_sigma_factor
    return float(max(sigma, 1e-3))


def build_dynamic_observation_batches(
    receiver_cfg: LEGACY_WLS.ReceiverTruthConfig,
    exp_cfg: DynamicExperimentConfig,
    legacy_bg: LEGACY_WLS.LegacyChannelBackground,
    legacy_metrics: LegacyEpochMetrics,
    truth_history: Sequence[DynamicTruthState],
    satellite_templates: Sequence[SatelliteTemplate],
) -> list[EpochObservationBatch]:
    epoch_batches: list[EpochObservationBatch] = []
    rng = np.random.default_rng(exp_cfg.rng_seed)
    degrade_start_s, degrade_end_s = degradation_window(exp_cfg, legacy_metrics.t_s)
    phase_scale_draws = rng.uniform(0.85, 1.15, size=(len(truth_history), len(satellite_templates)))
    rate_scale_draws = rng.uniform(0.85, 1.15, size=(len(truth_history), len(satellite_templates)))

    for epoch_idx, truth in enumerate(truth_history):
        observations: list[DynamicObservation] = []
        for sat_idx, sat_template in enumerate(satellite_templates):
            sat_pos_ecef_m, sat_vel_ecef_mps = compute_satellite_state_at_time(
                sat_template,
                receiver_cfg,
                exp_cfg,
                truth.t_s,
            )
            delta_ecef = sat_pos_ecef_m - truth.position_ecef_m
            geometric_range_m = float(np.linalg.norm(delta_ecef))
            los_unit = delta_ecef / geometric_range_m
            geometric_range_rate_mps = float(np.dot(los_unit, sat_vel_ecef_mps - truth.velocity_ecef_mps))
            azimuth_deg, elevation_deg = compute_az_el(
                delta_ecef,
                receiver_cfg.latitude_deg,
                receiver_cfg.longitude_deg,
            )

            tropo_delay_m = compute_tropo_delay_m(exp_cfg.tropo_zenith_delay_m, elevation_deg)
            sin_el = max(math.sin(math.radians(max(elevation_deg, 1e-3))), 0.10)
            dispersive_delay_m = float(
                legacy_metrics.tau_g_m[epoch_idx] * exp_cfg.dispersive_scale_factor / (sin_el ** 1.25)
            )

            sat_clock_bias_s = sat_template.clock_bias_s + sat_template.clock_drift_mps * truth.t_s / C_LIGHT
            sat_clock_drift_mps = sat_template.clock_drift_mps
            degradation_active = is_in_degradation_window(truth.t_s, degrade_start_s, degrade_end_s) and (
                sat_template.sat_id in exp_cfg.degradation_sat_ids
            )

            local_snr_db = float(legacy_metrics.snr_db[epoch_idx])
            local_lock_metric = float(legacy_metrics.lock_metric[epoch_idx])
            extra_sigma_factor = 1.0
            measurement_note = "legacy single-channel background mapped to dynamic multisat observation"
            if degradation_active:
                local_snr_db -= exp_cfg.degradation_snr_penalty_db
                local_lock_metric -= exp_cfg.degradation_lock_penalty
                extra_sigma_factor *= exp_cfg.degradation_sigma_factor
                measurement_note = "artificial low-SNR / low-lock degradation injected"
            if bool(legacy_metrics.loss_flag[epoch_idx]):
                extra_sigma_factor *= 2.5
                measurement_note += "; legacy sustained-loss interval downweighted"

            pr_sigma_m = measurement_sigma_from_legacy(
                elevation_deg,
                local_snr_db,
                local_lock_metric,
                legacy_metrics.pr_sigma_ref_m,
                exp_cfg,
                snr_reference_db=legacy_metrics.snr_reference_db,
                lock_reference=legacy_metrics.lock_reference,
                rate_mode="pr",
                extra_sigma_factor=float(extra_sigma_factor * phase_scale_draws[epoch_idx, sat_idx]),
            )
            rr_sigma_mps = measurement_sigma_from_legacy(
                elevation_deg,
                local_snr_db,
                local_lock_metric,
                legacy_metrics.rr_sigma_ref_mps,
                exp_cfg,
                snr_reference_db=legacy_metrics.snr_reference_db,
                lock_reference=legacy_metrics.lock_reference,
                rate_mode="rr",
                extra_sigma_factor=float(extra_sigma_factor * rate_scale_draws[epoch_idx, sat_idx]),
            )

            independent_pr_noise_m = float(
                rng.normal(0.0, exp_cfg.independent_pr_noise_fraction * pr_sigma_m)
            )
            independent_rr_noise_mps = float(
                rng.normal(0.0, exp_cfg.independent_rr_noise_fraction * rr_sigma_mps)
            )

            pseudorange_m = (
                geometric_range_m
                + truth.clock_bias_m
                - C_LIGHT * sat_clock_bias_s
                + tropo_delay_m
                + dispersive_delay_m
                + sat_template.hardware_bias_m
                + legacy_metrics.pr_shared_error_m[epoch_idx]
                + independent_pr_noise_m
            )
            range_rate_mps = (
                geometric_range_rate_mps
                + truth.clock_drift_mps
                - sat_clock_drift_mps
                + legacy_metrics.rr_shared_error_mps[epoch_idx]
                + independent_rr_noise_mps
            )

            valid = True
            if elevation_deg < exp_cfg.min_elevation_deg:
                valid = False
            if local_snr_db < exp_cfg.min_post_corr_snr_db:
                valid = False
            if local_lock_metric < exp_cfg.min_carrier_lock_metric:
                valid = False
            if exp_cfg.drop_on_sustained_loss and bool(legacy_metrics.loss_flag[epoch_idx]):
                valid = False

            observations.append(
                DynamicObservation(
                    epoch_idx=epoch_idx,
                    t_s=float(truth.t_s),
                    sat_id=sat_template.sat_id,
                    valid=bool(valid),
                    degradation_applied=bool(degradation_active),
                    azimuth_deg=float(azimuth_deg),
                    elevation_deg=float(elevation_deg),
                    sat_pos_ecef_m=sat_pos_ecef_m,
                    sat_vel_ecef_mps=sat_vel_ecef_mps,
                    geometric_range_m=float(geometric_range_m),
                    geometric_range_rate_mps=float(geometric_range_rate_mps),
                    sat_clock_bias_s=float(sat_clock_bias_s),
                    sat_clock_drift_mps=float(sat_clock_drift_mps),
                    tropo_delay_m=float(tropo_delay_m),
                    dispersive_delay_m=float(dispersive_delay_m),
                    hardware_bias_m=float(sat_template.hardware_bias_m),
                    pseudorange_m=float(pseudorange_m),
                    pseudorange_sigma_m=float(pr_sigma_m),
                    range_rate_mps=float(range_rate_mps),
                    range_rate_sigma_mps=float(rr_sigma_mps),
                    legacy_snr_db=float(local_snr_db),
                    legacy_lock_metric=float(local_lock_metric),
                    legacy_loss_flag=bool(legacy_metrics.loss_flag[epoch_idx]),
                    legacy_pr_error_m=float(legacy_metrics.pr_shared_error_m[epoch_idx]),
                    legacy_rr_error_mps=float(legacy_metrics.rr_shared_error_mps[epoch_idx]),
                    measurement_note=measurement_note,
                )
            )
        epoch_batches.append(
            EpochObservationBatch(
                epoch_idx=epoch_idx,
                t_s=float(truth.t_s),
                truth=truth,
                observations=tuple(observations),
            )
        )
    return epoch_batches


# ============================================================
# 5. Epoch WLS baseline
# ============================================================


def _truth_adapter_from_state(
    truth: DynamicTruthState,
    receiver_cfg: LEGACY_WLS.ReceiverTruthConfig,
) -> MovingReceiverTruthAdapter:
    return MovingReceiverTruthAdapter(
        receiver_ecef_m=truth.position_ecef_m.copy(),
        receiver_clock_bias_m=float(truth.clock_bias_m),
        latitude_deg=receiver_cfg.latitude_deg,
        longitude_deg=receiver_cfg.longitude_deg,
    )


def _to_legacy_pseudorange_observations(
    batch: EpochObservationBatch,
    legacy_metrics: LegacyEpochMetrics,
) -> list[LEGACY_WLS.PseudorangeObservation]:
    observations: list[LEGACY_WLS.PseudorangeObservation] = []
    for obs in batch.observations:
        if not obs.valid:
            continue
        model_without_noise = (
            obs.geometric_range_m
            + batch.truth.clock_bias_m
            - C_LIGHT * obs.sat_clock_bias_s
            + obs.tropo_delay_m
            + obs.dispersive_delay_m
            + obs.hardware_bias_m
        )
        noise_m = obs.pseudorange_m - model_without_noise
        observations.append(
            LEGACY_WLS.PseudorangeObservation(
                sat_id=obs.sat_id,
                azimuth_deg=obs.azimuth_deg,
                elevation_deg=obs.elevation_deg,
                sat_pos_ecef_m=obs.sat_pos_ecef_m.copy(),
                geometric_range_m=float(obs.geometric_range_m),
                receiver_clock_bias_m=float(batch.truth.clock_bias_m),
                sat_clock_bias_s=float(obs.sat_clock_bias_s),
                tropo_delay_m=float(obs.tropo_delay_m),
                dispersive_delay_m=float(obs.dispersive_delay_m),
                hardware_bias_m=float(obs.hardware_bias_m),
                noise_m=float(noise_m),
                pseudorange_m=float(obs.pseudorange_m),
                sigma_m=float(obs.pseudorange_sigma_m),
                legacy_tau_g_m=float(obs.dispersive_delay_m),
                legacy_tracking_sigma_reference_m=float(legacy_metrics.pr_sigma_ref_m),
                legacy_source_used="dynamic epoch mapping from reused single-channel legacy outputs",
                formation_note=obs.measurement_note,
            )
        )
    return observations


def run_epoch_wls_series(
    epoch_batches: Sequence[EpochObservationBatch],
    legacy_metrics: LegacyEpochMetrics,
    receiver_cfg: LEGACY_WLS.ReceiverTruthConfig,
    *,
    truth_free_initialization: bool = False,
) -> list[EpochWlsResult]:
    results: list[EpochWlsResult] = []
    previous_state_m: np.ndarray | None = None

    for batch in epoch_batches:
        valid_observations = _to_legacy_pseudorange_observations(batch, legacy_metrics)
        truth_adapter = _truth_adapter_from_state(batch.truth, receiver_cfg)

        if len(valid_observations) < 4:
            results.append(
                EpochWlsResult(
                    epoch_idx=batch.epoch_idx,
                    t_s=batch.t_s,
                    valid=False,
                    num_valid_sats=len(valid_observations),
                    state_vector_m=np.full(4, np.nan, dtype=float),
                    residual_rms_m=float("nan"),
                    position_error_3d_m=float("nan"),
                    clock_bias_error_m=float("nan"),
                    warning="insufficient valid pseudorange satellites for epoch WLS",
                )
            )
            continue

        if previous_state_m is None or not np.all(np.isfinite(previous_state_m)):
            if truth_free_initialization:
                initial_state_m = build_truth_free_initial_state_from_observations(valid_observations)
            else:
                initial_state_m = np.array(
                    [
                        batch.truth.position_ecef_m[0] + 1_200.0,
                        batch.truth.position_ecef_m[1] - 900.0,
                        batch.truth.position_ecef_m[2] + 650.0,
                        batch.truth.clock_bias_m + 180.0,
                    ],
                    dtype=float,
                )
        else:
            initial_state_m = previous_state_m.copy()

        solution = solve_pvt_iterative(
            valid_observations,
            truth_adapter,
            weighted=True,
            initial_state_m=initial_state_m,
        )
        previous_state_m = solution.state_vector_m.copy()
        results.append(
            EpochWlsResult(
                epoch_idx=batch.epoch_idx,
                t_s=batch.t_s,
                valid=True,
                num_valid_sats=len(valid_observations),
                state_vector_m=solution.state_vector_m.copy(),
                residual_rms_m=float(solution.residual_rms_m),
                position_error_3d_m=float(solution.position_error_3d_m),
                clock_bias_error_m=float(solution.state_vector_m[3] - batch.truth.clock_bias_m),
                warning="" if solution.converged else "epoch WLS reached max iterations",
            )
        )
    return results


# ============================================================
# 6. EKF
# ============================================================


def state_transition_matrix(dt_s: float) -> np.ndarray:
    """8-state CV model: [r, v, cb, cd]."""
    f_matrix = np.eye(8, dtype=float)
    f_matrix[0:3, 3:6] = dt_s * np.eye(3, dtype=float)
    f_matrix[6, 7] = dt_s
    return f_matrix


def process_noise_matrix(
    dt_s: float,
    accel_sigma_mps2: float,
    clock_drift_sigma_mps2: float,
) -> np.ndarray:
    """
    Q for:
    - position/velocity driven by white acceleration
    - clock bias/drift driven by white drift-rate noise
    """
    q_matrix = np.zeros((8, 8), dtype=float)

    # Constant-velocity translational process noise.
    q_block_rv = np.array(
        [
            [dt_s ** 4 / 4.0, dt_s ** 3 / 2.0],
            [dt_s ** 3 / 2.0, dt_s ** 2],
        ],
        dtype=float,
    ) * (accel_sigma_mps2 ** 2)
    for axis in range(3):
        indices = [axis, axis + 3]
        q_matrix[np.ix_(indices, indices)] = q_block_rv

    # Clock bias / clock drift process noise in meter units.
    q_clock = np.array(
        [
            [dt_s ** 4 / 4.0, dt_s ** 3 / 2.0],
            [dt_s ** 3 / 2.0, dt_s ** 2],
        ],
        dtype=float,
    ) * (clock_drift_sigma_mps2 ** 2)
    q_matrix[6:8, 6:8] = q_clock
    return q_matrix


def build_measurement_stack(
    batch: EpochObservationBatch,
    state_vector: np.ndarray,
    mode: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str], int]:
    h_rows: list[np.ndarray] = []
    z_values: list[float] = []
    h_values: list[float] = []
    variances: list[float] = []
    residual_types: list[str] = []
    valid_satellite_ids = set()

    receiver_pos = state_vector[0:3]
    receiver_vel = state_vector[3:6]
    receiver_clock_bias_m = float(state_vector[6])
    receiver_clock_drift_mps = float(state_vector[7])

    for obs in batch.observations:
        if not obs.valid:
            continue

        line_of_sight = obs.sat_pos_ecef_m - receiver_pos
        geometric_range_m = float(np.linalg.norm(line_of_sight))
        los_unit = line_of_sight / geometric_range_m
        relative_velocity = obs.sat_vel_ecef_mps - receiver_vel
        geometric_range_rate_mps = float(np.dot(los_unit, relative_velocity))

        predicted_pr_m = (
            geometric_range_m
            + receiver_clock_bias_m
            - C_LIGHT * obs.sat_clock_bias_s
            + obs.tropo_delay_m
            + obs.dispersive_delay_m
            + obs.hardware_bias_m
        )
        h_pr = np.zeros(8, dtype=float)
        h_pr[0:3] = -los_unit
        h_pr[6] = 1.0

        h_rows.append(h_pr)
        z_values.append(float(obs.pseudorange_m))
        h_values.append(float(predicted_pr_m))
        variances.append(float(obs.pseudorange_sigma_m ** 2))
        residual_types.append("pr")
        valid_satellite_ids.add(obs.sat_id)

        if mode == "ekf_pr_doppler":
            i_minus_uu = np.eye(3, dtype=float) - np.outer(los_unit, los_unit)
            h_rr = np.zeros(8, dtype=float)
            h_rr[0:3] = -(i_minus_uu @ relative_velocity) / geometric_range_m
            h_rr[3:6] = -los_unit
            h_rr[7] = 1.0
            predicted_rr_mps = geometric_range_rate_mps + receiver_clock_drift_mps - obs.sat_clock_drift_mps

            h_rows.append(h_rr)
            z_values.append(float(obs.range_rate_mps))
            h_values.append(float(predicted_rr_mps))
            variances.append(float(obs.range_rate_sigma_mps ** 2))
            residual_types.append("rr")

    if not h_rows:
        return (
            np.empty((0, 8), dtype=float),
            np.empty(0, dtype=float),
            np.empty(0, dtype=float),
            np.empty((0, 0), dtype=float),
            [],
            0,
        )

    h_matrix = np.asarray(h_rows, dtype=float)
    z_vector = np.asarray(z_values, dtype=float)
    h_vector = np.asarray(h_values, dtype=float)
    r_matrix = np.diag(np.asarray(variances, dtype=float))
    return h_matrix, z_vector, h_vector, r_matrix, residual_types, len(valid_satellite_ids)


def initialize_ekf_state(
    wls_results: Sequence[EpochWlsResult],
    epoch_batches: Sequence[EpochObservationBatch],
    exp_cfg: DynamicExperimentConfig,
) -> tuple[np.ndarray, np.ndarray, int]:
    valid_indices = [idx for idx, result in enumerate(wls_results) if result.valid]
    if not valid_indices:
        raise RuntimeError("No valid WLS epochs available for EKF initialization.")

    first_idx = valid_indices[0]
    first_state4 = wls_results[first_idx].state_vector_m
    x0 = np.zeros(8, dtype=float)
    x0[0:3] = first_state4[0:3]
    x0[6] = first_state4[3]

    fit_indices = valid_indices[: min(len(valid_indices), 8)]
    fit_times_s = np.array([epoch_batches[idx].t_s for idx in fit_indices], dtype=float)
    fit_times_s = fit_times_s - fit_times_s[0]
    if len(fit_indices) >= 3 and np.max(fit_times_s) > 0.0:
        fit_positions = np.vstack([wls_results[idx].state_vector_m[0:3] for idx in fit_indices]).astype(float)
        fit_clock_bias = np.array([wls_results[idx].state_vector_m[3] for idx in fit_indices], dtype=float)
        for axis in range(3):
            slope, _ = np.polyfit(fit_times_s, fit_positions[:, axis], 1)
            x0[3 + axis] = float(slope)
        slope_clock, _ = np.polyfit(fit_times_s, fit_clock_bias, 1)
        x0[7] = float(slope_clock)
    elif len(valid_indices) >= 2:
        second_idx = valid_indices[1]
        dt_s = float(epoch_batches[second_idx].t_s - epoch_batches[first_idx].t_s)
        if dt_s > 0.0:
            second_state4 = wls_results[second_idx].state_vector_m
            x0[3:6] = (second_state4[0:3] - first_state4[0:3]) / dt_s
            x0[7] = (second_state4[3] - first_state4[3]) / dt_s

    p0 = np.diag(
        [
            exp_cfg.init_position_sigma_m ** 2,
            exp_cfg.init_position_sigma_m ** 2,
            exp_cfg.init_position_sigma_m ** 2,
            exp_cfg.init_velocity_sigma_mps ** 2,
            exp_cfg.init_velocity_sigma_mps ** 2,
            exp_cfg.init_velocity_sigma_mps ** 2,
            exp_cfg.init_clock_bias_sigma_m ** 2,
            exp_cfg.init_clock_drift_sigma_mps ** 2,
        ]
    ).astype(float)
    return x0, p0, first_idx


def run_ekf(
    mode: str,
    epoch_batches: Sequence[EpochObservationBatch],
    wls_results: Sequence[EpochWlsResult],
    exp_cfg: DynamicExperimentConfig,
) -> RunResult:
    if mode not in {"ekf_pr_only", "ekf_pr_doppler"}:
        raise ValueError(f"Unsupported EKF mode: {mode}")

    x_post, p_post, init_epoch_idx = initialize_ekf_state(wls_results, epoch_batches, exp_cfg)
    history: list[EkfEpochResult] = []
    previous_t_s: float | None = None

    for batch in epoch_batches:
        if batch.epoch_idx < init_epoch_idx:
            history.append(
                EkfEpochResult(
                    epoch_idx=batch.epoch_idx,
                    t_s=batch.t_s,
                    mode=mode,
                    state_vector=np.full(8, np.nan, dtype=float),
                    covariance_diag=np.full(8, np.nan, dtype=float),
                    num_valid_sats=batch.num_valid_sats,
                    innovation_rms_pr_m=float("nan"),
                    innovation_rms_rr_mps=float("nan"),
                    position_error_3d_m=float("nan"),
                    velocity_error_3d_mps=float("nan"),
                    clock_bias_error_m=float("nan"),
                    clock_drift_error_mps=float("nan"),
                    prediction_only=True,
                    diverged=False,
                    warning="pre-init epoch before first valid WLS initialization",
                )
            )
            continue

        if previous_t_s is None:
            x_pred = x_post.copy()
            p_pred = p_post.copy()
        else:
            dt_s = float(batch.t_s - previous_t_s)
            f_matrix = state_transition_matrix(dt_s)
            q_matrix = process_noise_matrix(
                dt_s,
                accel_sigma_mps2=exp_cfg.process_accel_sigma_mps2,
                clock_drift_sigma_mps2=exp_cfg.process_clock_drift_sigma_mps2,
            )
            x_pred = f_matrix @ x_post
            p_pred = f_matrix @ p_post @ f_matrix.T + q_matrix

        h_matrix, z_vector, h_vector, r_matrix, residual_types, num_valid_sats = build_measurement_stack(
            batch,
            x_pred,
            mode=mode,
        )
        warning_parts: list[str] = []
        prediction_only = False

        if num_valid_sats < 4 or h_matrix.size == 0:
            x_post = x_pred
            p_post = p_pred
            prediction_only = True
            warning_parts.append("prediction only: fewer than 4 valid satellites")
            innovation_vector = np.empty(0, dtype=float)
        else:
            innovation_vector = z_vector - h_vector
            s_matrix = h_matrix @ p_pred @ h_matrix.T + r_matrix
            try:
                k_matrix = p_pred @ h_matrix.T @ np.linalg.inv(s_matrix)
            except np.linalg.LinAlgError:
                x_post = x_pred
                p_post = p_pred
                prediction_only = True
                warning_parts.append("prediction only: singular innovation covariance")
            else:
                x_post = x_pred + k_matrix @ innovation_vector
                joseph_left = np.eye(8, dtype=float) - k_matrix @ h_matrix
                p_post = joseph_left @ p_pred @ joseph_left.T + k_matrix @ r_matrix @ k_matrix.T

        pr_innovations = [innovation_vector[idx] for idx, tag in enumerate(residual_types) if tag == "pr"]
        rr_innovations = [innovation_vector[idx] for idx, tag in enumerate(residual_types) if tag == "rr"]

        truth = batch.truth
        pos_error_m = float(np.linalg.norm(x_post[0:3] - truth.position_ecef_m))
        vel_error_mps = float(np.linalg.norm(x_post[3:6] - truth.velocity_ecef_mps))
        clock_bias_error_m = float(x_post[6] - truth.clock_bias_m)
        clock_drift_error_mps = float(x_post[7] - truth.clock_drift_mps)

        diverged = False
        if np.any(~np.isfinite(np.diag(p_post))):
            diverged = True
            warning_parts.append("non-finite covariance diagonal")
        if math.sqrt(float(max(p_post[0, 0], 0.0))) > exp_cfg.divergence_position_sigma_threshold_m:
            diverged = True
            warning_parts.append("position sigma exceeded threshold")
        if rms(pr_innovations) > exp_cfg.divergence_innovation_pr_threshold_m:
            warning_parts.append("large pseudorange innovation")
        if rr_innovations and rms(rr_innovations) > exp_cfg.divergence_innovation_rr_threshold_mps:
            warning_parts.append("large range-rate innovation")

        history.append(
            EkfEpochResult(
                epoch_idx=batch.epoch_idx,
                t_s=batch.t_s,
                mode=mode,
                state_vector=x_post.copy(),
                covariance_diag=np.diag(p_post).copy(),
                num_valid_sats=num_valid_sats,
                innovation_rms_pr_m=rms(pr_innovations),
                innovation_rms_rr_mps=rms(rr_innovations),
                position_error_3d_m=pos_error_m,
                velocity_error_3d_mps=vel_error_mps,
                clock_bias_error_m=clock_bias_error_m,
                clock_drift_error_mps=clock_drift_error_mps,
                prediction_only=prediction_only,
                diverged=diverged,
                warning="; ".join(part for part in warning_parts if part),
            )
        )
        previous_t_s = batch.t_s
    return RunResult(mode=mode, history=tuple(history))


# ============================================================
# 7. Plotting
# ============================================================


def _find_run(run_results: Sequence[RunResult], mode: str) -> RunResult:
    return next(result for result in run_results if result.mode == mode)


def _stack_states(history: Sequence[EkfEpochResult]) -> np.ndarray:
    return np.vstack([item.state_vector for item in history]).astype(float)


def _stack_cov(history: Sequence[EkfEpochResult]) -> np.ndarray:
    return np.vstack([item.covariance_diag for item in history]).astype(float)


def _stack_truth(epoch_batches: Sequence[EpochObservationBatch]) -> np.ndarray:
    rows = []
    for batch in epoch_batches:
        rows.append(
            np.hstack(
                [
                    batch.truth.position_ecef_m,
                    batch.truth.velocity_ecef_mps,
                    batch.truth.clock_bias_m,
                    batch.truth.clock_drift_mps,
                ]
            )
        )
    return np.vstack(rows).astype(float)


def _time_vector(epoch_batches: Sequence[EpochObservationBatch]) -> np.ndarray:
    return np.array([batch.t_s for batch in epoch_batches], dtype=float)


def _satellite_id_order(epoch_batches: Sequence[EpochObservationBatch]) -> list[str]:
    if not epoch_batches:
        return []
    return [obs.sat_id for obs in epoch_batches[0].observations]


def _satellite_color_map(sat_ids: Sequence[str]) -> dict[str, tuple[float, float, float, float]]:
    cmap = plt.get_cmap("tab10")
    return {sat_id: cmap(idx % 10) for idx, sat_id in enumerate(sat_ids)}


def _build_observation_matrices(epoch_batches: Sequence[EpochObservationBatch]) -> tuple[list[str], dict[str, np.ndarray]]:
    sat_ids = _satellite_id_order(epoch_batches)
    num_epochs = len(epoch_batches)
    num_sats = len(sat_ids)
    matrices: dict[str, np.ndarray] = {
        "azimuth_deg": np.full((num_epochs, num_sats), np.nan, dtype=float),
        "elevation_deg": np.full((num_epochs, num_sats), np.nan, dtype=float),
        "geometric_range_m": np.full((num_epochs, num_sats), np.nan, dtype=float),
        "geometric_range_rate_mps": np.full((num_epochs, num_sats), np.nan, dtype=float),
        "pseudorange_sigma_m": np.full((num_epochs, num_sats), np.nan, dtype=float),
        "range_rate_sigma_mps": np.full((num_epochs, num_sats), np.nan, dtype=float),
        "legacy_snr_db": np.full((num_epochs, num_sats), np.nan, dtype=float),
        "legacy_lock_metric": np.full((num_epochs, num_sats), np.nan, dtype=float),
        "valid": np.zeros((num_epochs, num_sats), dtype=bool),
        "degradation_applied": np.zeros((num_epochs, num_sats), dtype=bool),
        "legacy_loss_flag": np.zeros((num_epochs, num_sats), dtype=bool),
    }

    sat_index = {sat_id: idx for idx, sat_id in enumerate(sat_ids)}
    for epoch_idx, batch in enumerate(epoch_batches):
        for obs in batch.observations:
            idx = sat_index[obs.sat_id]
            matrices["azimuth_deg"][epoch_idx, idx] = obs.azimuth_deg
            matrices["elevation_deg"][epoch_idx, idx] = obs.elevation_deg
            matrices["geometric_range_m"][epoch_idx, idx] = obs.geometric_range_m
            matrices["geometric_range_rate_mps"][epoch_idx, idx] = obs.geometric_range_rate_mps
            matrices["pseudorange_sigma_m"][epoch_idx, idx] = obs.pseudorange_sigma_m
            matrices["range_rate_sigma_mps"][epoch_idx, idx] = obs.range_rate_sigma_mps
            matrices["legacy_snr_db"][epoch_idx, idx] = obs.legacy_snr_db
            matrices["legacy_lock_metric"][epoch_idx, idx] = obs.legacy_lock_metric
            matrices["valid"][epoch_idx, idx] = obs.valid
            matrices["degradation_applied"][epoch_idx, idx] = obs.degradation_applied
            matrices["legacy_loss_flag"][epoch_idx, idx] = obs.legacy_loss_flag
    return sat_ids, matrices


def _select_representative_epochs(
    epoch_batches: Sequence[EpochObservationBatch],
    exp_cfg: DynamicExperimentConfig,
) -> list[tuple[int, str]]:
    time_s = _time_vector(epoch_batches)
    degradation_start_s, degradation_end_s = degradation_window(exp_cfg, time_s)
    pre_degradation_indices = np.where(time_s < degradation_start_s)[0]
    degradation_indices = np.where((time_s >= degradation_start_s) & (time_s <= degradation_end_s))[0]
    pre_mid_idx = int(pre_degradation_indices[len(pre_degradation_indices) // 2]) if pre_degradation_indices.size else len(time_s) // 2
    degradation_mid_idx = int(degradation_indices[len(degradation_indices) // 2]) if degradation_indices.size else len(time_s) // 2

    candidates = [
        (0, "Start"),
        (pre_mid_idx, "Mid"),
        (degradation_mid_idx, "Degradation"),
        (len(time_s) - 1, "End"),
    ]
    selected: list[tuple[int, str]] = []
    seen: set[int] = set()
    for idx, label in candidates:
        if idx in seen:
            continue
        selected.append((idx, label))
        seen.add(idx)
    return selected


def plot_sky_geometry_dynamic(
    epoch_batches: Sequence[EpochObservationBatch],
    exp_cfg: DynamicExperimentConfig,
    plot_cfg: PlotConfig,
) -> None:
    selected_epochs = _select_representative_epochs(epoch_batches, exp_cfg)
    fig = plt.figure(figsize=(5.0 * len(selected_epochs) + 0.9, 5.9), dpi=140)
    gridspec = fig.add_gridspec(
        1,
        len(selected_epochs) + 1,
        width_ratios=[1.0] * len(selected_epochs) + [0.06],
        wspace=0.38,
    )
    axes = np.array([fig.add_subplot(gridspec[0, idx], projection="polar") for idx in range(len(selected_epochs))], dtype=object)
    cbar_ax = fig.add_subplot(gridspec[0, -1])

    sigma_values = np.array(
        [
            obs.pseudorange_sigma_m
            for epoch_idx, _ in selected_epochs
            for obs in epoch_batches[epoch_idx].observations
        ],
        dtype=float,
    )
    norm = matplotlib.colors.Normalize(vmin=float(np.nanmin(sigma_values)), vmax=float(np.nanmax(sigma_values)))

    for ax, (epoch_idx, label) in zip(axes, selected_epochs, strict=True):
        batch = epoch_batches[epoch_idx]
        valid_obs = [obs for obs in batch.observations if obs.valid]
        invalid_obs = [obs for obs in batch.observations if not obs.valid]

        if valid_obs:
            theta = np.deg2rad([obs.azimuth_deg for obs in valid_obs])
            radius = 90.0 - np.array([obs.elevation_deg for obs in valid_obs], dtype=float)
            sigma = np.array([obs.pseudorange_sigma_m for obs in valid_obs], dtype=float)
            scatter = ax.scatter(theta, radius, c=sigma, s=105, cmap="viridis", norm=norm, edgecolors="black", linewidths=0.6)
        else:
            scatter = ax.scatter([], [], c=[], cmap="viridis", norm=norm)

        if invalid_obs:
            theta_bad = np.deg2rad([obs.azimuth_deg for obs in invalid_obs])
            radius_bad = 90.0 - np.array([obs.elevation_deg for obs in invalid_obs], dtype=float)
            ax.scatter(theta_bad, radius_bad, marker="x", s=70, color="0.45", linewidths=1.3)

        ordered_observations = sorted(batch.observations, key=lambda obs: obs.azimuth_deg)
        for local_idx, obs in enumerate(ordered_observations):
            theta = math.radians(obs.azimuth_deg)
            radius = 90.0 - obs.elevation_deg
            angle_offset_deg = ((local_idx % 4) - 1.5) * 4.0
            if local_idx % 2:
                angle_offset_deg *= -1.0
            if obs.elevation_deg >= 60.0:
                radial_offset = 5.5 + 1.2 * (local_idx % 2)
            elif obs.elevation_deg <= 20.0:
                radial_offset = 2.5 + 0.8 * (local_idx % 3)
            else:
                radial_offset = 4.0 + 1.0 * (local_idx % 3)
            text_radius = float(np.clip(radius + radial_offset, 5.0, 87.0))
            text_theta = theta + math.radians(angle_offset_deg)
            ha = "left" if math.cos(text_theta) > 0.25 else "right" if math.cos(text_theta) < -0.25 else "center"
            ax.annotate(
                obs.sat_id,
                xy=(theta, radius),
                xytext=(text_theta, text_radius),
                fontsize=7.6,
                ha=ha,
                va="center",
                bbox=dict(boxstyle="round,pad=0.10", fc="white", ec="none", alpha=0.72),
                arrowprops=dict(arrowstyle="-", lw=0.45, color="0.4"),
            )

        visible_count = int(sum(obs.elevation_deg > 0.0 for obs in batch.observations))
        degradation_flag = any(obs.degradation_applied for obs in batch.observations)
        title_suffix = "\nInjected degradation" if degradation_flag else ""
        ax.set_title(
            f"{label} | t={batch.t_s:.1f}s\nvisible={visible_count}, valid={batch.num_valid_sats}{title_suffix}",
            pad=18,
        )
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        ax.set_rlim(90.0, 0.0)
        ax.set_rticks([10, 25, 40, 55, 70, 85])
        ax.set_yticklabels(["80°", "65°", "50°", "35°", "20°", "5°"])
        ax.grid(True, ls=":", alpha=0.5)

    fig.subplots_adjust(left=0.04, right=0.97, top=0.86, bottom=0.08)
    cbar = fig.colorbar(scatter, cax=cbar_ax)
    cbar.set_label("Pseudorange sigma (m)")
    fig.suptitle("Dynamic sky geometry snapshots", y=0.99, fontsize=13)
    finalize_figure(fig, plot_cfg, "sky_geometry_dynamic")


def plot_geometry_3d_timeslices(
    receiver_cfg: LEGACY_WLS.ReceiverTruthConfig,
    epoch_batches: Sequence[EpochObservationBatch],
    exp_cfg: DynamicExperimentConfig,
    plot_cfg: PlotConfig,
) -> None:
    selected_epochs = _select_representative_epochs(epoch_batches, exp_cfg)
    sat_colors = _satellite_color_map(_satellite_id_order(epoch_batches))

    fig = plt.figure(figsize=(4.8 * len(selected_epochs), 5.6), dpi=140)
    for panel_idx, (epoch_idx, label) in enumerate(selected_epochs, start=1):
        batch = epoch_batches[epoch_idx]
        ax = fig.add_subplot(1, len(selected_epochs), panel_idx, projection="3d")
        receiver_xyz = np.zeros(3, dtype=float)
        ax.scatter([0.0], [0.0], [0.0], s=95, c="black", label="Receiver")

        for obs in batch.observations:
            sat_xyz = (
                ecef_delta_to_enu(
                    obs.sat_pos_ecef_m - batch.truth.position_ecef_m,
                    receiver_cfg.latitude_deg,
                    receiver_cfg.longitude_deg,
                )
                / 1e6
            )
            marker = "o" if obs.valid else "x"
            line_style = "-" if obs.valid else "--"
            ax.scatter([sat_xyz[0]], [sat_xyz[1]], [sat_xyz[2]], s=58, marker=marker, color=sat_colors[obs.sat_id])
            ax.plot(
                [receiver_xyz[0], sat_xyz[0]],
                [receiver_xyz[1], sat_xyz[1]],
                [receiver_xyz[2], sat_xyz[2]],
                lw=0.9,
                ls=line_style,
                alpha=0.72,
                color=sat_colors[obs.sat_id],
            )
            ax.text(sat_xyz[0], sat_xyz[1], sat_xyz[2], obs.sat_id, fontsize=8)

        degradation_flag = any(obs.degradation_applied for obs in batch.observations)
        title_suffix = " | degraded" if degradation_flag else ""
        ax.set_title(f"{label} | t={batch.t_s:.1f}s{title_suffix}")
        ax.set_xlabel("East (Mm)")
        ax.set_ylabel("North (Mm)")
        ax.set_zlabel("Up (Mm)")
        ax.grid(True)

    finalize_figure(fig, plot_cfg, "geometry_3d_timeslices")


def plot_geometry_timeseries(
    epoch_batches: Sequence[EpochObservationBatch],
    exp_cfg: DynamicExperimentConfig,
    plot_cfg: PlotConfig,
) -> None:
    time_s = _time_vector(epoch_batches)
    sat_ids, matrices = _build_observation_matrices(epoch_batches)
    sat_colors = _satellite_color_map(sat_ids)
    degradation_start_s, degradation_end_s = degradation_window(exp_cfg, time_s)

    visible_count = np.sum(matrices["elevation_deg"] > 0.0, axis=1)
    valid_count = np.sum(matrices["valid"], axis=1)

    fig, axes = plt.subplots(4, 1, figsize=(15, 13), dpi=140, sharex=True)
    axes[0].plot(time_s, visible_count, lw=1.3, color="0.35", label="Visible")
    axes[0].plot(time_s, valid_count, lw=1.4, color="#4C78A8", label="Valid")
    axes[0].axhline(4.0, color="black", lw=1.0, ls="--")
    axes[0].set_title("Satellite visibility and validity")
    axes[0].set_ylabel("Count")
    axes[0].legend()

    for sat_idx, sat_id in enumerate(sat_ids):
        color = sat_colors[sat_id]
        elevation_delta_deg = matrices["elevation_deg"][:, sat_idx] - matrices["elevation_deg"][0, sat_idx]
        range_delta_km = (matrices["geometric_range_m"][:, sat_idx] - matrices["geometric_range_m"][0, sat_idx]) / 1e3
        range_rate_delta_mps = matrices["geometric_range_rate_mps"][:, sat_idx] - matrices["geometric_range_rate_mps"][0, sat_idx]
        axes[1].plot(time_s, elevation_delta_deg, lw=1.15, color=color, label=sat_id)
        axes[2].plot(time_s, range_delta_km, lw=1.15, color=color, label=sat_id)
        axes[3].plot(time_s, range_rate_delta_mps, lw=1.15, color=color, label=sat_id)

    axes[1].set_title("Elevation change from start")
    axes[1].set_ylabel("deg")
    axes[2].set_title("Geometric range change from start")
    axes[2].set_ylabel("km")
    axes[3].set_title("Geometric range-rate change from start")
    axes[3].set_ylabel("m/s")
    axes[3].set_xlabel("Time (s)")

    for ax in axes:
        ax.axvspan(degradation_start_s, degradation_end_s, color="#F2CF5B", alpha=0.22)
        ax.grid(True, ls=":", alpha=0.5)
    axes[1].legend(ncol=4, fontsize=8, loc="upper right")
    finalize_figure(fig, plot_cfg, "geometry_timeseries")


def plot_observation_formation_overview(
    epoch_batches: Sequence[EpochObservationBatch],
    exp_cfg: DynamicExperimentConfig,
    plot_cfg: PlotConfig,
) -> None:
    time_s = _time_vector(epoch_batches)
    sat_ids, matrices = _build_observation_matrices(epoch_batches)
    selected_epochs = _select_representative_epochs(epoch_batches, exp_cfg)
    representative_idx = next((idx for idx, label in selected_epochs if label == "Degradation"), selected_epochs[min(1, len(selected_epochs) - 1)][0])
    representative_batch = epoch_batches[representative_idx]
    representative_obs = sorted(representative_batch.observations, key=lambda obs: obs.elevation_deg, reverse=True)
    degradation_start_s, degradation_end_s = degradation_window(exp_cfg, time_s)

    fig, axes = plt.subplots(2, 2, figsize=(16, 11), dpi=140)
    ax = axes.ravel()
    x_index = np.arange(len(representative_obs))
    bar_width = 0.18

    tropo = np.array([obs.tropo_delay_m for obs in representative_obs], dtype=float)
    dispersive = np.array([obs.dispersive_delay_m for obs in representative_obs], dtype=float)
    hardware = np.array([obs.hardware_bias_m for obs in representative_obs], dtype=float)
    legacy_shared = np.array([obs.legacy_pr_error_m for obs in representative_obs], dtype=float)
    sigma = np.array([obs.pseudorange_sigma_m for obs in representative_obs], dtype=float)

    ax[0].bar(x_index - 1.5 * bar_width, tropo, width=bar_width, color="#4C78A8", label="Troposphere")
    ax[0].bar(x_index - 0.5 * bar_width, dispersive, width=bar_width, color="#F58518", label="Dispersive")
    ax[0].bar(x_index + 0.5 * bar_width, hardware, width=bar_width, color="#54A24B", label="Hardware")
    ax[0].bar(x_index + 1.5 * bar_width, legacy_shared, width=bar_width, color="#E45756", label="Legacy shared error")
    ax[0].plot(x_index, sigma, color="black", marker="o", lw=1.2, label="Sigma")
    ax[0].set_xticks(x_index)
    ax[0].set_xticklabels([f"{obs.sat_id}\n{obs.elevation_deg:.0f}°" for obs in representative_obs])
    ax[0].set_title(f"Pseudorange formation terms @ t={representative_batch.t_s:.1f}s")
    ax[0].set_ylabel("m")
    ax[0].grid(True, axis="y", ls=":", alpha=0.5)
    ax[0].legend(ncol=3, fontsize=8)

    snr = np.array([obs.legacy_snr_db for obs in representative_obs], dtype=float)
    lock = np.array([obs.legacy_lock_metric for obs in representative_obs], dtype=float)
    valid_flag = np.array([float(obs.valid) for obs in representative_obs], dtype=float)
    ax[1].bar(x_index, snr, color="#4C78A8", alpha=0.75, label="Legacy SNR")
    ax1_right = ax[1].twinx()
    ax1_right.plot(x_index, lock, color="#E45756", marker="o", lw=1.2, label="Lock metric")
    ax1_right.step(x_index, valid_flag, where="mid", color="black", lw=1.0, label="Valid")
    ax[1].axhline(exp_cfg.min_post_corr_snr_db, color="#4C78A8", lw=1.0, ls="--")
    ax1_right.axhline(exp_cfg.min_carrier_lock_metric, color="#E45756", lw=1.0, ls="--")
    ax[1].set_xticks(x_index)
    ax[1].set_xticklabels([f"{obs.sat_id}\n{obs.elevation_deg:.0f}°" for obs in representative_obs])
    ax[1].set_title(f"Quality gating terms @ t={representative_batch.t_s:.1f}s")
    ax[1].set_ylabel("SNR (dB)")
    ax1_right.set_ylabel("Lock / Valid")
    ax[1].grid(True, axis="y", ls=":", alpha=0.5)
    handles_left, labels_left = ax[1].get_legend_handles_labels()
    handles_right, labels_right = ax1_right.get_legend_handles_labels()
    ax[1].legend(handles_left + handles_right, labels_left + labels_right, loc="upper right", fontsize=8)

    mean_pr_sigma = np.nanmean(matrices["pseudorange_sigma_m"], axis=1)
    mean_rr_sigma = np.nanmean(matrices["range_rate_sigma_mps"], axis=1)
    ax[2].plot(time_s, mean_pr_sigma, lw=1.3, color="#4C78A8", label="Mean PR sigma")
    ax[2].plot(time_s, mean_rr_sigma * 100.0, lw=1.3, color="#F58518", label="100 x mean RR sigma")
    ax[2].axvspan(degradation_start_s, degradation_end_s, color="#F2CF5B", alpha=0.22)
    ax[2].set_title("Epoch-mean observation sigma")
    ax[2].set_ylabel("m / scaled m/s")
    ax[2].grid(True, ls=":", alpha=0.5)
    ax[2].legend()

    validity_matrix = matrices["valid"].astype(float).T
    im = ax[3].imshow(
        validity_matrix,
        aspect="auto",
        interpolation="nearest",
        origin="lower",
        extent=[time_s[0], time_s[-1], -0.5, len(sat_ids) - 0.5],
        cmap="Blues",
        vmin=0.0,
        vmax=1.0,
    )
    ax[3].axvline(degradation_start_s, color="black", lw=1.0, ls="--")
    ax[3].axvline(degradation_end_s, color="black", lw=1.0, ls="--")
    ax[3].set_yticks(np.arange(len(sat_ids), dtype=float))
    ax[3].set_yticklabels(sat_ids)
    ax[3].set_title("Per-satellite validity mask")
    ax[3].set_xlabel("Time (s)")
    ax[3].set_ylabel("Satellite")
    cbar = fig.colorbar(im, ax=ax[3], fraction=0.05, pad=0.02)
    cbar.set_label("1 = valid")

    finalize_figure(fig, plot_cfg, "observation_formation_overview")


def plot_trajectory_error(
    receiver_cfg: LEGACY_WLS.ReceiverTruthConfig,
    epoch_batches: Sequence[EpochObservationBatch],
    run_results: Sequence[RunResult],
    plot_cfg: PlotConfig,
) -> None:
    truth = _stack_truth(epoch_batches)
    time_s = _time_vector(epoch_batches)
    fig, axes = plt.subplots(4, 1, figsize=(14, 11), dpi=140, sharex=True)

    labels = {
        "ekf_pr_only": "EKF PR only",
        "ekf_pr_doppler": "EKF PR + Doppler",
    }
    colors = {
        "ekf_pr_only": "#E45756",
        "ekf_pr_doppler": "#4C78A8",
    }

    for mode in labels:
        run = _find_run(run_results, mode)
        states = _stack_states(run.history)
        enu_errors = np.vstack(
            [
                ecef_delta_to_enu(
                    state[0:3] - truth_row[0:3],
                    receiver_cfg.latitude_deg,
                    receiver_cfg.longitude_deg,
                )
                for state, truth_row in zip(states, truth, strict=True)
            ]
        )
        axes[0].plot(time_s, enu_errors[:, 0], lw=1.3, color=colors[mode], label=labels[mode])
        axes[1].plot(time_s, enu_errors[:, 1], lw=1.3, color=colors[mode], label=labels[mode])
        axes[2].plot(time_s, enu_errors[:, 2], lw=1.3, color=colors[mode], label=labels[mode])
        axes[3].plot(
            time_s,
            np.linalg.norm(states[:, 0:3] - truth[:, 0:3], axis=1),
            lw=1.4,
            color=colors[mode],
            label=labels[mode],
        )

    titles = ["East error", "North error", "Up error", "3D position error"]
    ylabels = ["m", "m", "m", "m"]
    for ax, title, ylabel in zip(axes, titles, ylabels, strict=True):
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.grid(True, ls=":", alpha=0.5)
        ax.legend()
    axes[-1].set_xlabel("Time (s)")
    finalize_figure(fig, plot_cfg, "trajectory_error")


def plot_velocity_error(
    epoch_batches: Sequence[EpochObservationBatch],
    run_results: Sequence[RunResult],
    plot_cfg: PlotConfig,
) -> None:
    truth = _stack_truth(epoch_batches)
    time_s = _time_vector(epoch_batches)
    fig, axes = plt.subplots(4, 1, figsize=(14, 11), dpi=140, sharex=True)
    for mode, color in (("ekf_pr_only", "#E45756"), ("ekf_pr_doppler", "#4C78A8")):
        states = _stack_states(_find_run(run_results, mode).history)
        vel_error = states[:, 3:6] - truth[:, 3:6]
        axes[0].plot(time_s, vel_error[:, 0], lw=1.2, color=color, label=mode)
        axes[1].plot(time_s, vel_error[:, 1], lw=1.2, color=color, label=mode)
        axes[2].plot(time_s, vel_error[:, 2], lw=1.2, color=color, label=mode)
        axes[3].plot(time_s, np.linalg.norm(vel_error, axis=1), lw=1.4, color=color, label=mode)

    for ax, title in zip(axes, ["Vx error", "Vy error", "Vz error", "3D velocity error"], strict=True):
        ax.set_title(title)
        ax.set_ylabel("m/s")
        ax.grid(True, ls=":", alpha=0.5)
        ax.legend()
    axes[-1].set_xlabel("Time (s)")
    finalize_figure(fig, plot_cfg, "velocity_error")


def plot_clock_bias_and_drift(
    epoch_batches: Sequence[EpochObservationBatch],
    run_results: Sequence[RunResult],
    plot_cfg: PlotConfig,
) -> None:
    truth = _stack_truth(epoch_batches)
    time_s = _time_vector(epoch_batches)
    fig, axes = plt.subplots(2, 1, figsize=(14, 7), dpi=140, sharex=True)
    axes[0].plot(time_s, truth[:, 6], color="black", lw=1.1, ls="--", label="Truth")
    axes[1].plot(time_s, truth[:, 7], color="black", lw=1.1, ls="--", label="Truth")

    for mode, color in (("ekf_pr_only", "#E45756"), ("ekf_pr_doppler", "#4C78A8")):
        states = _stack_states(_find_run(run_results, mode).history)
        axes[0].plot(time_s, states[:, 6], lw=1.3, color=color, label=mode)
        axes[1].plot(time_s, states[:, 7], lw=1.3, color=color, label=mode)

    axes[0].set_title("Clock bias")
    axes[0].set_ylabel("m")
    axes[1].set_title("Clock drift")
    axes[1].set_ylabel("m/s")
    axes[1].set_xlabel("Time (s)")
    for ax in axes:
        ax.grid(True, ls=":", alpha=0.5)
        ax.legend()
    finalize_figure(fig, plot_cfg, "clock_bias_drift")


def plot_innovation_timeseries(run_results: Sequence[RunResult], plot_cfg: PlotConfig) -> None:
    pr_only = _find_run(run_results, "ekf_pr_only")
    pr_doppler = _find_run(run_results, "ekf_pr_doppler")
    time_s = np.array([item.t_s for item in pr_only.history], dtype=float)

    fig, axes = plt.subplots(2, 1, figsize=(14, 7), dpi=140, sharex=True)
    axes[0].plot(time_s, [item.innovation_rms_pr_m for item in pr_only.history], lw=1.2, color="#E45756", label="PR only")
    axes[0].plot(time_s, [item.innovation_rms_pr_m for item in pr_doppler.history], lw=1.2, color="#4C78A8", label="PR + Doppler")
    axes[0].set_title("Pseudorange innovation RMS")
    axes[0].set_ylabel("m")

    axes[1].plot(time_s, [item.innovation_rms_rr_mps for item in pr_doppler.history], lw=1.2, color="#4C78A8", label="PR + Doppler")
    axes[1].set_title("Range-rate innovation RMS")
    axes[1].set_ylabel("m/s")
    axes[1].set_xlabel("Time (s)")

    for ax in axes:
        ax.grid(True, ls=":", alpha=0.5)
        ax.legend()
    finalize_figure(fig, plot_cfg, "innovation_timeseries")


def plot_visible_satellites_and_weights(
    epoch_batches: Sequence[EpochObservationBatch],
    exp_cfg: DynamicExperimentConfig,
    plot_cfg: PlotConfig,
) -> None:
    time_s = _time_vector(epoch_batches)
    valid_counts = np.array([batch.num_valid_sats for batch in epoch_batches], dtype=float)
    mean_weight_pr = np.array(
        [
            np.mean([1.0 / (obs.pseudorange_sigma_m ** 2) for obs in batch.observations if obs.valid]) if batch.num_valid_sats > 0 else np.nan
            for batch in epoch_batches
        ],
        dtype=float,
    )
    degrade_start_s, degrade_end_s = degradation_window(exp_cfg, time_s)

    fig, axes = plt.subplots(2, 1, figsize=(14, 7), dpi=140, sharex=True)
    axes[0].plot(time_s, valid_counts, lw=1.4, color="#4C78A8")
    axes[0].axhline(4.0, lw=1.0, ls="--", color="black")
    axes[0].axvspan(degrade_start_s, degrade_end_s, color="#F2CF5B", alpha=0.25, label="Injected degradation")
    axes[0].set_title("Visible valid satellites")
    axes[0].set_ylabel("Count")
    axes[0].grid(True, ls=":", alpha=0.5)
    axes[0].legend()

    axes[1].plot(time_s, mean_weight_pr, lw=1.4, color="#54A24B")
    axes[1].axvspan(degrade_start_s, degrade_end_s, color="#F2CF5B", alpha=0.25, label="Injected degradation")
    axes[1].set_title("Mean pseudorange weight")
    axes[1].set_ylabel("1/m$^2$")
    axes[1].set_xlabel("Time (s)")
    axes[1].grid(True, ls=":", alpha=0.5)
    axes[1].legend()
    finalize_figure(fig, plot_cfg, "visible_satellites_and_weights")


def plot_filter_vs_epoch_wls(
    wls_results: Sequence[EpochWlsResult],
    run_results: Sequence[RunResult],
    plot_cfg: PlotConfig,
) -> None:
    time_s = np.array([result.t_s for result in wls_results], dtype=float)
    wls_position_error = np.array([result.position_error_3d_m for result in wls_results], dtype=float)
    wls_clock_error = np.array([result.clock_bias_error_m for result in wls_results], dtype=float)
    pr_only = _find_run(run_results, "ekf_pr_only")
    pr_doppler = _find_run(run_results, "ekf_pr_doppler")

    fig, axes = plt.subplots(2, 1, figsize=(14, 7), dpi=140, sharex=True)
    axes[0].plot(time_s, wls_position_error, lw=1.2, color="0.3", label="Epoch WLS")
    axes[0].plot(time_s, [item.position_error_3d_m for item in pr_only.history], lw=1.2, color="#E45756", label="EKF PR only")
    axes[0].plot(time_s, [item.position_error_3d_m for item in pr_doppler.history], lw=1.2, color="#4C78A8", label="EKF PR + Doppler")
    axes[0].set_title("3D position error: WLS vs EKF")
    axes[0].set_ylabel("m")

    axes[1].plot(time_s, wls_clock_error, lw=1.2, color="0.3", label="Epoch WLS")
    axes[1].plot(time_s, [item.clock_bias_error_m for item in pr_only.history], lw=1.2, color="#E45756", label="EKF PR only")
    axes[1].plot(time_s, [item.clock_bias_error_m for item in pr_doppler.history], lw=1.2, color="#4C78A8", label="EKF PR + Doppler")
    axes[1].set_title("Clock bias error: WLS vs EKF")
    axes[1].set_ylabel("m")
    axes[1].set_xlabel("Time (s)")

    for ax in axes:
        ax.grid(True, ls=":", alpha=0.5)
        ax.legend()
    finalize_figure(fig, plot_cfg, "filter_vs_epoch_wls")


# ============================================================
# 8. Result export
# ============================================================


def write_dynamic_observations_csv(epoch_batches: Sequence[EpochObservationBatch], output_path: Path) -> None:
    fieldnames = [
        "epoch_idx",
        "t_s",
        "sat_id",
        "valid",
        "degradation_applied",
        "azimuth_deg",
        "elevation_deg",
        "geometric_range_m",
        "geometric_range_rate_mps",
        "sat_clock_bias_s",
        "sat_clock_drift_mps",
        "tropo_delay_m",
        "dispersive_delay_m",
        "hardware_bias_m",
        "pseudorange_m",
        "pseudorange_sigma_m",
        "range_rate_mps",
        "range_rate_sigma_mps",
        "legacy_snr_db",
        "legacy_lock_metric",
        "legacy_loss_flag",
        "legacy_pr_error_m",
        "legacy_rr_error_mps",
        "measurement_note",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        for batch in epoch_batches:
            for obs in batch.observations:
                writer.writerow(
                    {
                        "epoch_idx": batch.epoch_idx,
                        "t_s": f"{obs.t_s:.6f}",
                        "sat_id": obs.sat_id,
                        "valid": int(obs.valid),
                        "degradation_applied": int(obs.degradation_applied),
                        "azimuth_deg": f"{obs.azimuth_deg:.6f}",
                        "elevation_deg": f"{obs.elevation_deg:.6f}",
                        "geometric_range_m": f"{obs.geometric_range_m:.6f}",
                        "geometric_range_rate_mps": f"{obs.geometric_range_rate_mps:.6f}",
                        "sat_clock_bias_s": f"{obs.sat_clock_bias_s:.12e}",
                        "sat_clock_drift_mps": f"{obs.sat_clock_drift_mps:.6f}",
                        "tropo_delay_m": f"{obs.tropo_delay_m:.6f}",
                        "dispersive_delay_m": f"{obs.dispersive_delay_m:.6f}",
                        "hardware_bias_m": f"{obs.hardware_bias_m:.6f}",
                        "pseudorange_m": f"{obs.pseudorange_m:.6f}",
                        "pseudorange_sigma_m": f"{obs.pseudorange_sigma_m:.6f}",
                        "range_rate_mps": f"{obs.range_rate_mps:.6f}",
                        "range_rate_sigma_mps": f"{obs.range_rate_sigma_mps:.6f}",
                        "legacy_snr_db": f"{obs.legacy_snr_db:.6f}",
                        "legacy_lock_metric": f"{obs.legacy_lock_metric:.6f}",
                        "legacy_loss_flag": int(obs.legacy_loss_flag),
                        "legacy_pr_error_m": f"{obs.legacy_pr_error_m:.6f}",
                        "legacy_rr_error_mps": f"{obs.legacy_rr_error_mps:.6f}",
                        "measurement_note": obs.measurement_note,
                    }
                )


def write_dynamic_state_history_csv(
    epoch_batches: Sequence[EpochObservationBatch],
    wls_results: Sequence[EpochWlsResult],
    run_results: Sequence[RunResult],
    output_path: Path,
) -> None:
    fieldnames = [
        "mode",
        "epoch_idx",
        "t_s",
        "rx_m",
        "ry_m",
        "rz_m",
        "vx_mps",
        "vy_mps",
        "vz_mps",
        "cb_m",
        "cd_mps",
        "truth_rx_m",
        "truth_ry_m",
        "truth_rz_m",
        "truth_vx_mps",
        "truth_vy_mps",
        "truth_vz_mps",
        "truth_cb_m",
        "truth_cd_mps",
        "cov_rx",
        "cov_ry",
        "cov_rz",
        "cov_vx",
        "cov_vy",
        "cov_vz",
        "cov_cb",
        "cov_cd",
        "pos_err_3d_m",
        "vel_err_3d_mps",
        "cb_err_m",
        "cd_err_mps",
        "innovation_rms_pr_m",
        "innovation_rms_rr_mps",
        "num_valid_sats",
        "prediction_only",
        "diverged",
        "warning",
    ]

    with output_path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()

        for batch, wls_result in zip(epoch_batches, wls_results, strict=True):
            state = np.full(8, np.nan, dtype=float)
            cov_diag = np.full(8, np.nan, dtype=float)
            if wls_result.valid:
                state[0:3] = wls_result.state_vector_m[0:3]
                state[6] = wls_result.state_vector_m[3]
                pos_err = wls_result.position_error_3d_m
                cb_err = wls_result.clock_bias_error_m
            else:
                pos_err = float("nan")
                cb_err = float("nan")

            writer.writerow(
                {
                    "mode": "epoch_wls",
                    "epoch_idx": batch.epoch_idx,
                    "t_s": f"{batch.t_s:.6f}",
                    "rx_m": f"{state[0]:.6f}",
                    "ry_m": f"{state[1]:.6f}",
                    "rz_m": f"{state[2]:.6f}",
                    "vx_mps": "",
                    "vy_mps": "",
                    "vz_mps": "",
                    "cb_m": f"{state[6]:.6f}",
                    "cd_mps": "",
                    "truth_rx_m": f"{batch.truth.position_ecef_m[0]:.6f}",
                    "truth_ry_m": f"{batch.truth.position_ecef_m[1]:.6f}",
                    "truth_rz_m": f"{batch.truth.position_ecef_m[2]:.6f}",
                    "truth_vx_mps": f"{batch.truth.velocity_ecef_mps[0]:.6f}",
                    "truth_vy_mps": f"{batch.truth.velocity_ecef_mps[1]:.6f}",
                    "truth_vz_mps": f"{batch.truth.velocity_ecef_mps[2]:.6f}",
                    "truth_cb_m": f"{batch.truth.clock_bias_m:.6f}",
                    "truth_cd_mps": f"{batch.truth.clock_drift_mps:.6f}",
                    "cov_rx": "",
                    "cov_ry": "",
                    "cov_rz": "",
                    "cov_vx": "",
                    "cov_vy": "",
                    "cov_vz": "",
                    "cov_cb": "",
                    "cov_cd": "",
                    "pos_err_3d_m": f"{pos_err:.6f}",
                    "vel_err_3d_mps": "",
                    "cb_err_m": f"{cb_err:.6f}",
                    "cd_err_mps": "",
                    "innovation_rms_pr_m": f"{wls_result.residual_rms_m:.6f}",
                    "innovation_rms_rr_mps": "",
                    "num_valid_sats": wls_result.num_valid_sats,
                    "prediction_only": "",
                    "diverged": "",
                    "warning": wls_result.warning,
                }
            )

        for run in run_results:
            for batch, hist in zip(epoch_batches, run.history, strict=True):
                writer.writerow(
                    {
                        "mode": run.mode,
                        "epoch_idx": hist.epoch_idx,
                        "t_s": f"{hist.t_s:.6f}",
                        "rx_m": f"{hist.state_vector[0]:.6f}",
                        "ry_m": f"{hist.state_vector[1]:.6f}",
                        "rz_m": f"{hist.state_vector[2]:.6f}",
                        "vx_mps": f"{hist.state_vector[3]:.6f}",
                        "vy_mps": f"{hist.state_vector[4]:.6f}",
                        "vz_mps": f"{hist.state_vector[5]:.6f}",
                        "cb_m": f"{hist.state_vector[6]:.6f}",
                        "cd_mps": f"{hist.state_vector[7]:.6f}",
                        "truth_rx_m": f"{batch.truth.position_ecef_m[0]:.6f}",
                        "truth_ry_m": f"{batch.truth.position_ecef_m[1]:.6f}",
                        "truth_rz_m": f"{batch.truth.position_ecef_m[2]:.6f}",
                        "truth_vx_mps": f"{batch.truth.velocity_ecef_mps[0]:.6f}",
                        "truth_vy_mps": f"{batch.truth.velocity_ecef_mps[1]:.6f}",
                        "truth_vz_mps": f"{batch.truth.velocity_ecef_mps[2]:.6f}",
                        "truth_cb_m": f"{batch.truth.clock_bias_m:.6f}",
                        "truth_cd_mps": f"{batch.truth.clock_drift_mps:.6f}",
                        "cov_rx": f"{hist.covariance_diag[0]:.6f}",
                        "cov_ry": f"{hist.covariance_diag[1]:.6f}",
                        "cov_rz": f"{hist.covariance_diag[2]:.6f}",
                        "cov_vx": f"{hist.covariance_diag[3]:.6f}",
                        "cov_vy": f"{hist.covariance_diag[4]:.6f}",
                        "cov_vz": f"{hist.covariance_diag[5]:.6f}",
                        "cov_cb": f"{hist.covariance_diag[6]:.6f}",
                        "cov_cd": f"{hist.covariance_diag[7]:.6f}",
                        "pos_err_3d_m": f"{hist.position_error_3d_m:.6f}",
                        "vel_err_3d_mps": f"{hist.velocity_error_3d_mps:.6f}",
                        "cb_err_m": f"{hist.clock_bias_error_m:.6f}",
                        "cd_err_mps": f"{hist.clock_drift_error_mps:.6f}",
                        "innovation_rms_pr_m": f"{hist.innovation_rms_pr_m:.6f}",
                        "innovation_rms_rr_mps": f"{hist.innovation_rms_rr_mps:.6f}",
                        "num_valid_sats": hist.num_valid_sats,
                        "prediction_only": int(hist.prediction_only),
                        "diverged": int(hist.diverged),
                        "warning": hist.warning,
                    }
                )


def summarize_run(run: RunResult) -> dict[str, Any]:
    history = run.history
    return {
        "mode": run.mode,
        "mean_position_error_3d_m": finite_or_none(nanmean_or_nan([item.position_error_3d_m for item in history])),
        "mean_velocity_error_3d_mps": finite_or_none(nanmean_or_nan([item.velocity_error_3d_mps for item in history])),
        "mean_clock_bias_abs_error_m": finite_or_none(nanmean_or_nan(np.abs([item.clock_bias_error_m for item in history]))),
        "mean_clock_drift_abs_error_mps": finite_or_none(nanmean_or_nan(np.abs([item.clock_drift_error_mps for item in history]))),
        "mean_innovation_pr_m": finite_or_none(nanmean_or_nan([item.innovation_rms_pr_m for item in history])),
        "mean_innovation_rr_mps": finite_or_none(nanmean_or_nan([item.innovation_rms_rr_mps for item in history])),
        "prediction_only_epochs": int(sum(item.prediction_only for item in history)),
        "diverged_epochs": int(sum(item.diverged for item in history)),
    }


def summarize_wls(wls_results: Sequence[EpochWlsResult]) -> dict[str, Any]:
    valid_results = [item for item in wls_results if item.valid]
    return {
        "valid_epochs": len(valid_results),
        "mean_position_error_3d_m": float(np.mean([item.position_error_3d_m for item in valid_results])),
        "mean_clock_bias_abs_error_m": float(np.mean(np.abs([item.clock_bias_error_m for item in valid_results]))),
        "mean_residual_rms_m": float(np.mean([item.residual_rms_m for item in valid_results])),
    }


def build_summary_json(
    receiver_cfg: LEGACY_WLS.ReceiverTruthConfig,
    exp_cfg: DynamicExperimentConfig,
    legacy_bg: LEGACY_WLS.LegacyChannelBackground,
    legacy_metrics: LegacyEpochMetrics,
    epoch_batches: Sequence[EpochObservationBatch],
    wls_results: Sequence[EpochWlsResult],
    run_results: Sequence[RunResult],
) -> dict[str, Any]:
    epoch_times_s = _time_vector(epoch_batches)
    degrade_start_s, degrade_end_s = degradation_window(exp_cfg, epoch_times_s)
    return {
        "receiver_truth_reference": {
            "latitude_deg": receiver_cfg.latitude_deg,
            "longitude_deg": receiver_cfg.longitude_deg,
            "height_m": receiver_cfg.height_m,
            "initial_clock_bias_m": exp_cfg.receiver_clock_bias_m,
            "initial_clock_drift_mps": exp_cfg.receiver_clock_drift_mps,
            "receiver_velocity_ecef_mps": exp_cfg.receiver_velocity_ecef_mps,
        },
        "legacy_reused_components": legacy_bg.reused_components + [
            "solve_pvt_iterative",
            "compute_tropo_delay_m",
            "lla_to_ecef",
            "ecef_delta_to_enu",
        ],
        "dynamic_state_definition": "[rx, ry, rz, vx, vy, vz, cb, cd] in [m, m/s, m, m/s]",
        "state_equations": {
            "position": "r(k+1) = r(k) + v(k) * dt",
            "velocity": "v(k+1) = v(k) + w_v",
            "clock_bias": "cb(k+1) = cb(k) + cd(k) * dt",
            "clock_drift": "cd(k+1) = cd(k) + w_c",
        },
        "measurement_equations": {
            "pseudorange": "rho = ||rs-r|| + cb - c*dts + tropo + dispersive + hardware + noise",
            "range_rate": "rhodot = u_LOS^T (vs-vr) + cd - c*ddts + noise",
            "doppler_conversion": "range_rate_mps = -(c / fc) * doppler_hz",
        },
        "time_axes": {
            "receiver_sample_rate_hz": 500_000.0,
            "tracking_output_rate_hz": float(1.0 / np.median(np.diff(np.asarray(legacy_bg.trk_result["t"], dtype=float)))),
            "navigation_rate_hz": exp_cfg.nav_rate_hz,
            "num_navigation_epochs": len(epoch_batches),
        },
        "legacy_channel_metrics": {
            "effective_pseudorange_sigma_100ms_m": legacy_bg.effective_pseudorange_sigma_100ms_m,
            "effective_pseudorange_sigma_1s_m": legacy_bg.effective_pseudorange_sigma_1s_m,
            "effective_pseudorange_rmse_m": legacy_bg.effective_pseudorange_rmse_m,
            "effective_pseudorange_bias_m": legacy_bg.effective_pseudorange_bias_m,
            "tau_g_median_m": legacy_bg.tau_g_median_m,
            "tau_g_span_m": legacy_bg.tau_g_span_m,
            "dynamic_range_rate_sigma_100ms_mps": legacy_metrics.rr_sigma_ref_mps,
        },
        "comparison_runs": {
            "epoch_wls": summarize_wls(wls_results),
            **{run.mode: summarize_run(run) for run in run_results},
        },
        "degradation_window_s": {
            "start_s": degrade_start_s,
            "end_s": degrade_end_s,
            "degraded_satellites": list(exp_cfg.degradation_sat_ids),
        },
        "simplifications": [
            "Satellite geometry is synthesized in receiver-local az/el/range coordinates, mapped to ECEF at each epoch, and differentiated to obtain velocity; no broadcast ephemeris is used.",
            "Receiver truth is a self-consistent constant-velocity ECEF trajectory, not a RAM-C 6DoF truth.",
            "All satellites share one reused real single-channel Ka/WKB background, then receive per-satellite geometry and weighting maps.",
            "Carrier phase is not used in the main EKF because ambiguity states are not part of the 8-state baseline filter.",
            "Troposphere, satellite clocks, and hardware terms are parameterized navigation-layer terms.",
        ],
        "claim_boundary": "This is a hybrid dynamic multisatellite Ka navigation experiment coupled to a reused real single-channel WKB/receiver background, not a fully end-to-end real multisatellite Ka navigation performance result.",
        "outputs": {
            "results_dir": RESULTS_DIR,
            "legacy_channel_overview_png": RESULTS_DIR / "legacy_channel_overview.png",
            "sky_geometry_dynamic_png": RESULTS_DIR / "sky_geometry_dynamic.png",
            "geometry_3d_timeslices_png": RESULTS_DIR / "geometry_3d_timeslices.png",
            "geometry_timeseries_png": RESULTS_DIR / "geometry_timeseries.png",
            "observation_formation_overview_png": RESULTS_DIR / "observation_formation_overview.png",
            "trajectory_error_png": RESULTS_DIR / "trajectory_error.png",
            "velocity_error_png": RESULTS_DIR / "velocity_error.png",
            "clock_bias_drift_png": RESULTS_DIR / "clock_bias_drift.png",
            "innovation_timeseries_png": RESULTS_DIR / "innovation_timeseries.png",
            "visible_satellites_and_weights_png": RESULTS_DIR / "visible_satellites_and_weights.png",
            "filter_vs_epoch_wls_png": RESULTS_DIR / "filter_vs_epoch_wls.png",
            "summary_json": RESULTS_DIR / "summary.json",
            "dynamic_observations_csv": RESULTS_DIR / "dynamic_observations.csv",
            "dynamic_state_history_csv": RESULTS_DIR / "dynamic_state_history.csv",
            "report_summary_md": RESULTS_DIR / "report_summary.md",
            "report_full_md": RESULTS_DIR / "report_full.md",
        },
        "figure_groups": {
            "input_background_figures": [
                RESULTS_DIR / "legacy_channel_overview.png",
            ],
            "geometry_figures": [
                RESULTS_DIR / "sky_geometry_dynamic.png",
                RESULTS_DIR / "geometry_3d_timeslices.png",
                RESULTS_DIR / "geometry_timeseries.png",
            ],
            "observation_intermediate_figures": [
                RESULTS_DIR / "observation_formation_overview.png",
                RESULTS_DIR / "visible_satellites_and_weights.png",
            ],
            "estimation_result_figures": [
                RESULTS_DIR / "trajectory_error.png",
                RESULTS_DIR / "velocity_error.png",
                RESULTS_DIR / "clock_bias_drift.png",
                RESULTS_DIR / "innovation_timeseries.png",
                RESULTS_DIR / "filter_vs_epoch_wls.png",
            ],
        },
    }


def write_summary_json(summary: dict[str, Any], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as file_obj:
        json.dump(to_serializable(summary), file_obj, ensure_ascii=False, indent=2)


def _markdown_value(value: Any, *, digits: int = 3) -> str:
    if value is None:
        return "-"
    if isinstance(value, (bool, np.bool_)):
        return "Yes" if bool(value) else "No"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        if not math.isfinite(float(value)):
            return "-"
        return f"{float(value):.{digits}f}"
    return str(value)


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_markdown_value(item) for item in row) + " |")
    return "\n".join(lines)


def _masked_mean(values: Sequence[float] | np.ndarray, mask: np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0 or mask.size == 0 or not np.any(mask):
        return float("nan")
    selected = arr[mask]
    if selected.size == 0:
        return float("nan")
    return float(np.nanmean(selected))


def _masked_rate(values: Sequence[bool] | np.ndarray, mask: np.ndarray) -> float:
    arr = np.asarray(values, dtype=bool)
    if arr.size == 0 or mask.size == 0 or not np.any(mask):
        return float("nan")
    return 100.0 * float(np.mean(arr[mask]))


def _representative_observation_batch(
    epoch_batches: Sequence[EpochObservationBatch],
    exp_cfg: DynamicExperimentConfig,
) -> EpochObservationBatch:
    selected_epochs = _select_representative_epochs(epoch_batches, exp_cfg)
    representative_idx = next((idx for idx, label in selected_epochs if label == "Degradation"), selected_epochs[min(1, len(selected_epochs) - 1)][0])
    return epoch_batches[representative_idx]


def _build_mode_comparison_rows(
    summary: dict[str, Any],
) -> list[list[Any]]:
    wls_summary = summary["comparison_runs"]["epoch_wls"]
    pr_only = summary["comparison_runs"]["ekf_pr_only"]
    pr_doppler = summary["comparison_runs"]["ekf_pr_doppler"]
    return [
        [
            "Epoch WLS",
            wls_summary["mean_position_error_3d_m"],
            None,
            wls_summary["mean_clock_bias_abs_error_m"],
            None,
            wls_summary["mean_residual_rms_m"],
            None,
            None,
            None,
        ],
        [
            "EKF PR only",
            pr_only["mean_position_error_3d_m"],
            pr_only["mean_velocity_error_3d_mps"],
            pr_only["mean_clock_bias_abs_error_m"],
            pr_only["mean_clock_drift_abs_error_mps"],
            pr_only["mean_innovation_pr_m"],
            pr_only["mean_innovation_rr_mps"],
            pr_only["prediction_only_epochs"],
            pr_only["diverged_epochs"],
        ],
        [
            "EKF PR + Doppler",
            pr_doppler["mean_position_error_3d_m"],
            pr_doppler["mean_velocity_error_3d_mps"],
            pr_doppler["mean_clock_bias_abs_error_m"],
            pr_doppler["mean_clock_drift_abs_error_mps"],
            pr_doppler["mean_innovation_pr_m"],
            pr_doppler["mean_innovation_rr_mps"],
            pr_doppler["prediction_only_epochs"],
            pr_doppler["diverged_epochs"],
        ],
    ]


def _build_segment_comparison_rows(
    epoch_batches: Sequence[EpochObservationBatch],
    run_results: Sequence[RunResult],
    exp_cfg: DynamicExperimentConfig,
) -> list[list[Any]]:
    time_s = _time_vector(epoch_batches)
    degradation_start_s, degradation_end_s = degradation_window(exp_cfg, time_s)
    degraded_mask = (time_s >= degradation_start_s) & (time_s <= degradation_end_s)
    normal_mask = ~degraded_mask
    _, matrices = _build_observation_matrices(epoch_batches)
    valid_counts = np.array([batch.num_valid_sats for batch in epoch_batches], dtype=float)
    mean_pr_sigma = np.nanmean(matrices["pseudorange_sigma_m"], axis=1)
    mean_rr_sigma = np.nanmean(matrices["range_rate_sigma_mps"], axis=1)
    main_run = _find_run(run_results, "ekf_pr_doppler")
    position_error = np.array([item.position_error_3d_m for item in main_run.history], dtype=float)
    velocity_error = np.array([item.velocity_error_3d_mps for item in main_run.history], dtype=float)
    innovation_pr = np.array([item.innovation_rms_pr_m for item in main_run.history], dtype=float)
    innovation_rr = np.array([item.innovation_rms_rr_mps for item in main_run.history], dtype=float)

    return [
        [
            "Normal",
            _masked_mean(valid_counts, normal_mask),
            _masked_mean(mean_pr_sigma, normal_mask),
            _masked_mean(mean_rr_sigma, normal_mask),
            _masked_mean(innovation_pr, normal_mask),
            _masked_mean(innovation_rr, normal_mask),
            _masked_mean(position_error, normal_mask),
            _masked_mean(velocity_error, normal_mask),
        ],
        [
            "Degraded",
            _masked_mean(valid_counts, degraded_mask),
            _masked_mean(mean_pr_sigma, degraded_mask),
            _masked_mean(mean_rr_sigma, degraded_mask),
            _masked_mean(innovation_pr, degraded_mask),
            _masked_mean(innovation_rr, degraded_mask),
            _masked_mean(position_error, degraded_mask),
            _masked_mean(velocity_error, degraded_mask),
        ],
    ]


def _build_per_satellite_rows(
    epoch_batches: Sequence[EpochObservationBatch],
    exp_cfg: DynamicExperimentConfig,
) -> list[list[Any]]:
    time_s = _time_vector(epoch_batches)
    degradation_start_s, degradation_end_s = degradation_window(exp_cfg, time_s)
    degraded_mask = (time_s >= degradation_start_s) & (time_s <= degradation_end_s)
    sat_ids, matrices = _build_observation_matrices(epoch_batches)
    rows: list[list[Any]] = []

    for sat_idx, sat_id in enumerate(sat_ids):
        rows.append(
            [
                sat_id,
                np.nanmean(matrices["elevation_deg"][:, sat_idx]),
                np.nanmean(matrices["geometric_range_m"][:, sat_idx]) / 1e6,
                np.nanmean(matrices["geometric_range_rate_mps"][:, sat_idx]),
                np.nanmean(matrices["pseudorange_sigma_m"][:, sat_idx]),
                _masked_rate(matrices["valid"][:, sat_idx], np.ones(len(time_s), dtype=bool)),
                _masked_rate(matrices["valid"][:, sat_idx], degraded_mask),
                sat_id in exp_cfg.degradation_sat_ids,
            ]
        )
    return rows


def _build_representative_observation_rows(
    epoch_batches: Sequence[EpochObservationBatch],
    exp_cfg: DynamicExperimentConfig,
) -> tuple[EpochObservationBatch, list[list[Any]]]:
    batch = _representative_observation_batch(epoch_batches, exp_cfg)
    observations = sorted(batch.observations, key=lambda obs: obs.elevation_deg, reverse=True)
    rows = [
        [
            obs.sat_id,
            obs.azimuth_deg,
            obs.elevation_deg,
            obs.geometric_range_m / 1e6,
            obs.geometric_range_rate_mps,
            obs.tropo_delay_m,
            obs.dispersive_delay_m,
            obs.hardware_bias_m,
            obs.legacy_pr_error_m,
            obs.legacy_snr_db,
            obs.legacy_lock_metric,
            obs.pseudorange_sigma_m,
            obs.valid,
        ]
        for obs in observations
    ]
    return batch, rows


def write_report_full_md(
    receiver_cfg: LEGACY_WLS.ReceiverTruthConfig,
    exp_cfg: DynamicExperimentConfig,
    legacy_bg: LEGACY_WLS.LegacyChannelBackground,
    legacy_metrics: LegacyEpochMetrics,
    epoch_batches: Sequence[EpochObservationBatch],
    wls_results: Sequence[EpochWlsResult],
    run_results: Sequence[RunResult],
    summary: dict[str, Any],
    output_path: Path,
) -> None:
    carrier_freq_ghz = receiver_cfg.carrier_frequency_hz / 1e9
    time_s = _time_vector(epoch_batches)
    degradation_start_s, degradation_end_s = degradation_window(exp_cfg, time_s)
    valid_satellite_count = np.array([batch.num_valid_sats for batch in epoch_batches], dtype=float)
    main_run = _find_run(run_results, "ekf_pr_doppler")
    representative_batch, representative_rows = _build_representative_observation_rows(epoch_batches, exp_cfg)
    sat_ids, matrices = _build_observation_matrices(epoch_batches)
    azimuth_spans_deg = np.nanmax(matrices["azimuth_deg"], axis=0) - np.nanmin(matrices["azimuth_deg"], axis=0)
    elevation_spans_deg = np.nanmax(matrices["elevation_deg"], axis=0) - np.nanmin(matrices["elevation_deg"], axis=0)
    range_spans_km = (np.nanmax(matrices["geometric_range_m"], axis=0) - np.nanmin(matrices["geometric_range_m"], axis=0)) / 1e3
    range_rate_spans_mps = np.nanmax(matrices["geometric_range_rate_mps"], axis=0) - np.nanmin(matrices["geometric_range_rate_mps"], axis=0)

    summary_table = _markdown_table(
        ["项目", "数值"],
        [
            ["tau_g 中位数 (m)", legacy_bg.tau_g_median_m],
            ["tau_g 跨度 (m)", legacy_bg.tau_g_span_m],
            ["legacy PR 100 ms sigma (m)", legacy_bg.effective_pseudorange_sigma_100ms_m],
            ["legacy PR 1 s sigma (m)", legacy_bg.effective_pseudorange_sigma_1s_m],
            ["导航历元数", len(epoch_batches)],
            ["平均有效卫星数", np.mean(valid_satellite_count)],
            ["Epoch WLS 平均 3D 误差 (m)", summary["comparison_runs"]["epoch_wls"]["mean_position_error_3d_m"]],
            ["EKF PR only 平均 3D 误差 (m)", summary["comparison_runs"]["ekf_pr_only"]["mean_position_error_3d_m"]],
            ["EKF PR + Doppler 平均 3D 误差 (m)", summary["comparison_runs"]["ekf_pr_doppler"]["mean_position_error_3d_m"]],
            ["EKF PR + Doppler 平均 3D 速度误差 (m/s)", summary["comparison_runs"]["ekf_pr_doppler"]["mean_velocity_error_3d_mps"]],
            ["PR + Doppler prediction-only epochs", summary["comparison_runs"]["ekf_pr_doppler"]["prediction_only_epochs"]],
            ["退化窗口起点 (s)", degradation_start_s],
            ["退化窗口终点 (s)", degradation_end_s],
        ],
    )

    mode_comparison_table = _markdown_table(
        [
            "Mode",
            "Mean 3D pos (m)",
            "Mean 3D vel (m/s)",
            "Mean |cb| (m)",
            "Mean |cd| (m/s)",
            "Mean PR innov (m)",
            "Mean RR innov (m/s)",
            "Prediction-only epochs",
            "Diverged epochs",
        ],
        _build_mode_comparison_rows(summary),
    )

    segment_comparison_table = _markdown_table(
        [
            "Segment",
            "Mean valid sats",
            "Mean PR sigma (m)",
            "Mean RR sigma (m/s)",
            "Mean PR innov (m)",
            "Mean RR innov (m/s)",
            "Mean pos err (m)",
            "Mean vel err (m/s)",
        ],
        _build_segment_comparison_rows(epoch_batches, run_results, exp_cfg),
    )

    per_satellite_table = _markdown_table(
        [
            "Sat",
            "Mean El (deg)",
            "Mean range (Mm)",
            "Mean range-rate (m/s)",
            "Mean PR sigma (m)",
            "Valid rate (%)",
            "Degraded-window valid rate (%)",
            "Injected degradation",
        ],
        _build_per_satellite_rows(epoch_batches, exp_cfg),
    )

    representative_table = _markdown_table(
        [
            "Sat",
            "Az (deg)",
            "El (deg)",
            "Geom range (Mm)",
            "Geom rr (m/s)",
            "Tropo (m)",
            "Dispersive (m)",
            "Hardware (m)",
            "Legacy PR err (m)",
            "Legacy SNR (dB)",
            "Legacy lock",
            "PR sigma (m)",
            "Valid",
        ],
        representative_rows,
    )

    time_axis_table = _markdown_table(
        ["项目", "数值"],
        [
            ["接收机内部采样率 (Hz)", summary["time_axes"]["receiver_sample_rate_hz"]],
            ["跟踪输出率 (Hz)", summary["time_axes"]["tracking_output_rate_hz"]],
            ["导航解算率 (Hz)", summary["time_axes"]["navigation_rate_hz"]],
            ["导航时间步长 (s)", 1.0 / summary["time_axes"]["navigation_rate_hz"]],
            ["导航历元数", summary["time_axes"]["num_navigation_epochs"]],
            ["总时长 (s)", time_s[-1] - time_s[0] if len(time_s) >= 2 else 0.0],
            ["退化窗口长度 (s)", degradation_end_s - degradation_start_s],
            ["卫星数", len(epoch_batches[0].observations) if epoch_batches else 0],
            ["退化注入卫星", ", ".join(exp_cfg.degradation_sat_ids)],
        ],
    )

    geometry_span_table = _markdown_table(
        ["量", "最小值", "中位数", "最大值"],
        [
            ["Azimuth span (deg)", np.min(azimuth_spans_deg), np.median(azimuth_spans_deg), np.max(azimuth_spans_deg)],
            ["Elevation span (deg)", np.min(elevation_spans_deg), np.median(elevation_spans_deg), np.max(elevation_spans_deg)],
            ["Range span (km)", np.min(range_spans_km), np.median(range_spans_km), np.max(range_spans_km)],
            ["Range-rate span (m/s)", np.min(range_rate_spans_mps), np.median(range_rate_spans_mps), np.max(range_rate_spans_mps)],
        ],
    )

    quality_gate_table = _markdown_table(
        ["参数", "数值", "含义"],
        [
            ["min_elevation_deg", exp_cfg.min_elevation_deg, "低于此仰角直接判 invalid"],
            ["min_post_corr_snr_db", exp_cfg.min_post_corr_snr_db, "低于此后相关 SNR 判 invalid"],
            ["min_carrier_lock_metric", exp_cfg.min_carrier_lock_metric, "低于此锁定指标判 invalid"],
            ["low_elevation_sigma_boost_factor", exp_cfg.low_elevation_sigma_boost_factor, "低仰角 sigma 放大"],
            ["snr_sigma_boost_factor", exp_cfg.snr_sigma_boost_factor, "低 SNR sigma 放大斜率"],
            ["lock_sigma_boost_factor", exp_cfg.lock_sigma_boost_factor, "低锁定指标 sigma 放大斜率"],
            ["degradation_sigma_factor", exp_cfg.degradation_sigma_factor, "退化窗口内额外 sigma 放大"],
            ["drop_on_sustained_loss", exp_cfg.drop_on_sustained_loss, "是否在 sustained-loss 时直接丢弃"],
        ],
    )

    filter_config_table = _markdown_table(
        ["参数", "数值", "含义"],
        [
            ["process_accel_sigma_mps2", exp_cfg.process_accel_sigma_mps2, "平移白加速度过程噪声"],
            ["process_clock_drift_sigma_mps2", exp_cfg.process_clock_drift_sigma_mps2, "钟漂随机游走过程噪声"],
            ["init_position_sigma_m", exp_cfg.init_position_sigma_m, "初始位置标准差"],
            ["init_velocity_sigma_mps", exp_cfg.init_velocity_sigma_mps, "初始速度标准差"],
            ["init_clock_bias_sigma_m", exp_cfg.init_clock_bias_sigma_m, "初始钟差标准差"],
            ["init_clock_drift_sigma_mps", exp_cfg.init_clock_drift_sigma_mps, "初始钟漂标准差"],
            ["divergence_position_sigma_threshold_m", exp_cfg.divergence_position_sigma_threshold_m, "位置 sigma 发散门限"],
            ["divergence_innovation_pr_threshold_m", exp_cfg.divergence_innovation_pr_threshold_m, "PR innovation 告警门限"],
            ["divergence_innovation_rr_threshold_mps", exp_cfg.divergence_innovation_rr_threshold_mps, "RR innovation 告警门限"],
        ],
    )

    filter_health_table = _markdown_table(
        ["Mode", "Prediction-only epochs", "Diverged epochs", "Warning epochs", "Mean valid sats"],
        [
            [
                run.mode,
                sum(item.prediction_only for item in run.history),
                sum(item.diverged for item in run.history),
                sum(bool(item.warning) for item in run.history),
                np.mean([item.num_valid_sats for item in run.history]),
            ]
            for run in run_results
        ],
    )

    output_inventory_table = _markdown_table(
        ["文件", "用途"],
        [
            ["legacy_channel_overview.png", "legacy 单通道真实背景"],
            ["sky_geometry_dynamic.png", "动态天空图"],
            ["geometry_3d_timeslices.png", "接收机中心 ENU 下的动态 3D 几何快照"],
            ["geometry_timeseries.png", "相对起点的几何变化时序"],
            ["observation_formation_overview.png", "观测形成中间量"],
            ["visible_satellites_and_weights.png", "有效卫星数与权重"],
            ["trajectory_error.png", "位置误差结果"],
            ["velocity_error.png", "速度误差结果"],
            ["clock_bias_drift.png", "钟差与钟漂结果"],
            ["innovation_timeseries.png", "innovation 时序"],
            ["filter_vs_epoch_wls.png", "滤波器与 epoch-wise WLS 对比"],
            ["dynamic_observations.csv", "逐星逐历元观测表"],
            ["dynamic_state_history.csv", "逐模式逐历元状态历史"],
            ["summary.json", "机器可读全局摘要"],
            ["report_summary.md", "短摘要报告"],
            ["report_full.md", "完整长报告"],
        ],
    )

    appendix_field_table = _markdown_table(
        ["文件", "关键字段", "用途"],
        [
            [
                "dynamic_observations.csv",
                "epoch_idx, sat_id, valid, az_deg, el_deg, pseudorange_m, range_rate_mps, sigma, SNR, lock",
                "复查观测形成、权重、有效性与退化注入",
            ],
            [
                "dynamic_state_history.csv",
                "mode, t_s, state, truth, covariance_diag, innovation_rms, num_valid_sats, warning",
                "复查状态估计、协方差、innovation 和告警",
            ],
            [
                "summary.json",
                "comparison_runs, time_axes, outputs, figure_groups, simplifications",
                "读取总体指标、输出路径与简化项",
            ],
        ],
    )

    code_legacy = """```python
field_result = LEGACY_DEBUG.build_fields_from_csv(...)
wkb_result = LEGACY_DEBUG.compute_real_wkb_series(...)
cfg_sig = LEGACY_DEBUG.build_signal_config_from_wkb_time(...)
plasma_rx = LEGACY_DEBUG.resample_wkb_to_receiver_time(...)
receiver_outputs = LEGACY_DEBUG.KaBpskReceiver(receiver_context).run()
trk_result = receiver_outputs.trk_result
```"""

    code_dynamic_observation = """```python
pseudorange_m = (
    geometric_range_m
    + truth.clock_bias_m
    - C_LIGHT * sat_clock_bias_s
    + tropo_delay_m
    + dispersive_delay_m
    + sat_template.hardware_bias_m
    + legacy_metrics.pr_shared_error_m[epoch_idx]
    + independent_pr_noise_m
)

range_rate_mps = (
    geometric_range_rate_mps
    + truth.clock_drift_mps
    - sat_clock_drift_mps
    + legacy_metrics.rr_shared_error_mps[epoch_idx]
    + independent_rr_noise_mps
)
```"""

    code_state_model = """```python
def state_transition_matrix(dt_s: float) -> np.ndarray:
    f_matrix = np.eye(8, dtype=float)
    f_matrix[0:3, 3:6] = dt_s * np.eye(3, dtype=float)
    f_matrix[6, 7] = dt_s
    return f_matrix

def process_noise_matrix(dt_s: float, accel_sigma_mps2: float, clock_drift_sigma_mps2: float) -> np.ndarray:
    ...
```"""

    code_ekf_update = """```python
h_matrix, z_vector, h_vector, r_matrix, residual_types, num_valid_sats = build_measurement_stack(...)
innovation_vector = z_vector - h_vector
s_matrix = h_matrix @ p_pred @ h_matrix.T + r_matrix
k_matrix = p_pred @ h_matrix.T @ np.linalg.inv(s_matrix)
x_post = x_pred + k_matrix @ innovation_vector
```"""

    code_main = """```python
plot_legacy_channel_overview(...)
plot_sky_geometry_dynamic(...)
plot_geometry_3d_timeslices(...)
plot_geometry_timeseries(...)
plot_observation_formation_overview(...)
plot_trajectory_error(...)
plot_velocity_error(...)
plot_clock_bias_and_drift(...)
plot_innovation_timeseries(...)
plot_visible_satellites_and_weights(...)
plot_filter_vs_epoch_wls(...)
```"""

    text = f"""# Ka {carrier_freq_ghz:.1f} GHz 真实 WKB 单通道背景下的多历元动态多星导航 EKF 实验报告

## 1. 摘要

[../notebooks/ka_multifreq_receiver_common.py](../notebooks/ka_multifreq_receiver_common.py) 提供真实单通道共享链路：
真实电子密度场、真实 WKB、Ka {carrier_freq_ghz:.1f} GHz PN/BPSK 信号、捕获、DLL / PLL 跟踪，以及单通道
`pseudorange / carrier phase / Doppler` 输出。  
[../notebooks/exp_multisat_wls_pvt_report.py](../notebooks/exp_multisat_wls_pvt_report.py) 在此基础上增加了多星几何、
标准伪距方程和单历元 LS/WLS PVT。  
[../notebooks/exp_dynamic_multisat_ekf_report.py](../notebooks/exp_dynamic_multisat_ekf_report.py) 则进一步把系统推进到
“多历元位置-速度-钟差-钟漂动态估计”。

本报告中的动态多星结果不代表真实多星端到端 Ka 动态导航系统的性能定标。真实单通道传播与接收机链路已经接入；
动态接收机真值、多星时变几何、多历元观测形成和 EKF 仍是新增的导航层构造。

主要数字如下：

{summary_table}

## 2. 旧脚本已有内容

共享单通道模块 [../notebooks/ka_multifreq_receiver_common.py](../notebooks/ka_multifreq_receiver_common.py) 的主链路如下：

1. 从 CSV 构造电子密度场。
2. 计算真实 WKB，得到 `A(t)`、`phi(t)`、`tau_g(t)`。
3. 用真实传播量生成 Ka {carrier_freq_ghz:.1f} GHz PN/BPSK 信号。
4. 完成捕获。
5. 完成 DLL / PLL 跟踪。
6. 输出单通道 `pseudorange / carrier phase / Doppler`。

单历元多星脚本 [../notebooks/exp_multisat_wls_pvt_report.py](../notebooks/exp_multisat_wls_pvt_report.py) 在此基础上补上了：

1. 多星几何
2. 标准伪距形成
3. 单历元 LS/WLS
4. DOP
5. Monte Carlo

动态脚本没有重写这些内容，而是在它们的基础上增加：

1. 多历元接收机真值轨迹
2. 多历元多星时间变化几何
3. 多历元标准 `pseudorange / range-rate`
4. epoch-wise WLS 串联基线
5. 动态 EKF

## 3. 新脚本增加的动态步骤

动态脚本主链路如下：

```text
电子密度场 CSV
  -> 旧脚本 build_fields_from_csv
  -> 旧脚本 compute_real_wkb_series
  -> 旧脚本 build_signal_config_from_wkb_time
  -> 旧脚本 resample_wkb_to_receiver_time
  -> 旧脚本 KaBpskReceiver.run
  -> legacy 单通道背景: A(t), phi(t), tau_g(t), pseudorange, Doppler, SNR, lock
  -> 动态接收机真值轨迹
  -> 动态多星几何
  -> 多历元标准观测形成
  -> epoch-wise WLS baseline
  -> EKF
  -> 图片、CSV、JSON、Markdown
```

流程中的量可分成四层：

1. 真实单通道链路量：`A(t)`、`phi(t)`、`tau_g(t)`、legacy `pseudorange`、legacy Doppler、SNR、lock。
2. 动态几何量：receiver truth、satellite position/velocity、LOS、几何距离、几何距离率。
3. 标准观测量：进入统一观测方程的多历元 `pseudorange_m / range_rate_mps`。
4. 动态导航结果：WLS 基线、EKF 状态、协方差、innovation、位置/速度/时钟误差。

## 4. 复用的旧脚本函数

动态脚本直接复用了以下旧函数：

1. `build_fields_from_csv`
2. `compute_real_wkb_series`
3. `build_signal_config_from_wkb_time`
4. `resample_wkb_to_receiver_time`
5. `KaBpskReceiver.run`
6. `solve_pvt_iterative`

代码摘录如下：

{code_legacy}

旧脚本负责真实传播和单通道接收机；动态脚本只补充旧脚本尚未覆盖的多历元导航层。

## 5. 动态状态空间模型

动态滤波状态定义为：

```text
x = [rx, ry, rz, vx, vy, vz, cb, cd]^T
```

其中：

- `r` 为接收机 ECEF 位置，单位 m
- `v` 为接收机 ECEF 速度，单位 m/s
- `cb` 为接收机钟差，单位 m
- `cd` 为接收机钟漂，单位 m/s

状态方程采用首版常速度模型：

```text
r(k+1)  = r(k) + v(k) * dt
v(k+1)  = v(k) + w_v
cb(k+1) = cb(k) + cd(k) * dt
cd(k+1) = cd(k) + w_c
```

这里的设计取舍是：

1. 接收机真值轨迹是连续常速度 ECEF 轨迹，因此常速度滤波模型与真值模型在一阶上自洽。
2. 首版重点是把系统从单历元推进到动态估计，而不是一开始就把复杂动力学引入主线。
3. `cb/cd` 分离能让 pseudorange 和 Doppler 分别约束钟差与钟漂。

代码摘录如下：

{code_state_model}

`F` 的块结构负责位置由速度推进、钟差由钟漂推进。  
`Q` 的平移部分按白加速度离散化，时钟部分按钟漂随机游走离散化。  
这意味着滤波器不是把速度和钟漂当成严格常数，而是允许它们在统计意义上缓慢变化。

若把 `F` 写成块矩阵，则可以写成：

```text
F =
[ I3  dt*I3   0   0 ]
[  0    I3    0   0 ]
[  0     0    1  dt ]
[  0     0    0   1 ]
```

对应的 `Q` 在平移子空间和时钟子空间都采用同一类二阶积分白噪声离散化：

```text
Q_block =
sigma^2 * [
  dt^4/4   dt^3/2
  dt^3/2   dt^2
]
```

三维位置/速度部分把该 `Q_block` 分别放到 `x/y/z` 三个轴上；钟差/钟漂部分再放一份到 `cb/cd` 上。  
这样做的物理含义是：速度并非刚性常数，而是由白加速度驱动的随机过程；钟漂也不是严格常数，而是允许在较慢时间尺度上随机变化。

### 5.1 滤波器关键配置

{filter_config_table}

## 6. 观测模型

动态脚本使用两类主观测：

1. `pseudorange`
2. `range-rate`（由 legacy Doppler 转换而来）

伪距方程：

```text
rho = ||rs-r|| + cb - c*dts + tropo + dispersive + hardware + noise
```

距离率方程：

```text
rhodot = u_LOS^T (vs-vr) + cd - c*ddts + noise
```

其中：

- `||rs-r||` 是几何距离
- `u_LOS^T (vs-vr)` 是 LOS 方向相对速度
- `cb/cd` 是接收机钟差和钟漂
- `dts/ddts` 是卫星钟差和钟漂
- `tropo / dispersive / hardware` 是非几何项
- `noise` 来自 legacy 单通道跟踪误差统计和质量指标映射

脚本内部统一用距离率单位 `m/s`，并使用：

```text
range_rate_mps = -(c / fc) * doppler_hz
```

因此，legacy Doppler 不再只是链路内部频偏量，而是进入标准导航观测方程的距离率观测。

代码摘录如下：

{code_dynamic_observation}

这里需要强调：动态脚本并没有把 DLL 内部 `c * tau_est` 直接当成导航伪距本体，而是把几何、
时钟和非几何项统一写入标准伪距方程，再把 legacy 误差统计映射为噪声和权重。

## 7. 动态几何与时间轴

时间轴分三层：

1. 接收机内部采样率：`500 kHz`
2. 跟踪输出率：`1 ms`，约 `1000 Hz`
3. 导航解算率：`{exp_cfg.nav_rate_hz:.1f} Hz`

接收机真值轨迹采用自洽常速度 ECEF 轨迹，不是真实 RAM-C 六自由度轨迹。  
卫星几何不是广播星历外推，而是先在接收机本地坐标系中参数化 `azimuth / elevation / range` 的时变轨迹，
再逐 epoch 映射到 ECEF，并用有限差分构造卫星速度。这种写法的目的不是模拟真实 GNSS 轨道动力学，
而是确保在当前 21.8 s 的短时间窗内，几何变化能够被清楚地表达和诊断。

时间轴和场景配置摘要如下：

{time_axis_table}

几何变化跨度摘要如下：

{geometry_span_table}

### 7.1 动态天空图

![](./sky_geometry_dynamic.png)

图 1 展示起始、中段、退化段和结束时刻的天空图。可以直接看到：

1. 多星几何不是静态不变的，而且在短时间窗内已经达到可见的子度级到度级变化。
2. 各星的 sigma 和 validity 会随几何和质量门限共同变化。
3. 退化窗口中的观测质量变化可以在图上直接看到。

### 7.2 3D 几何快照

![](./geometry_3d_timeslices.png)

图 2 给出对应时刻的接收机中心 ENU 3D 几何。黑点为接收机原点，彩色点为卫星，连线为 LOS。  
这里故意不用绝对 ECEF 坐标，而改用接收机中心局部坐标，是因为在 20~25 Mm 量级的绝对坐标上，
短时间窗内的几何变化很容易在视觉上被淹没；改成 ENU 后，同一段时变几何就能直观看出方向和高度的变化。

### 7.3 几何时间演化

![](./geometry_timeseries.png)

图 3 不再画几条几乎重合的绝对量直线，而是给出相对起点的几何变化：
可见/有效卫星数、逐星 elevation change、range change、range-rate change。  
图中阴影区域为人为退化窗口，便于把几何变化和质量变化分开看。

## 8. 旧脚本生成的单通道背景

![](./legacy_channel_overview.png)

图 4 给出 legacy 单通道背景，包括：

1. 真实 WKB 幅度 `A(t)`
2. 真实 WKB 相位 `phi(t)`
3. 真实群时延 `tau_g(t)`
4. legacy 单通道伪距误差
5. legacy 后相关 SNR
6. legacy 单通道伪距 truth vs estimate

legacy 背景的关键量级如下：

{_markdown_table(
    ["指标", "数值"],
    [
        ["tau_g 中位数 (m)", legacy_bg.tau_g_median_m],
        ["tau_g 跨度 (m)", legacy_bg.tau_g_span_m],
        ["legacy PR 100 ms sigma (m)", legacy_bg.effective_pseudorange_sigma_100ms_m],
        ["legacy PR 1 s sigma (m)", legacy_bg.effective_pseudorange_sigma_1s_m],
        ["legacy PR 1 s RMSE (m)", legacy_bg.effective_pseudorange_rmse_m],
        ["legacy PR 平均偏置 (m)", legacy_bg.effective_pseudorange_bias_m],
        ["dynamic RR 100 ms sigma (m/s)", legacy_metrics.rr_sigma_ref_mps],
    ],
)}

这部分说明两件事：

1. 动态多星导航层不是凭空造数据，而是确实耦合了真实单通道 WKB / 接收机背景。
2. legacy 单通道误差本身并不小，因此动态 EKF 的结果必须谨慎解释。
3. 从 `100 ms` 到 `1 s` 平滑后 sigma 明显下降，说明共享背景里既有快变误差也有低频慢变分量。
4. 动态观测层继承了这类时间相关误差，因此 EKF 的收益一部分来自时序约束，而不仅仅是“多加几颗卫星”。

## 9. 从 legacy 背景到多历元多星观测

动态脚本没有直接把单通道 `c * tau_est` 复制给所有卫星，而是做了下面几步：

1. 为每个 epoch、每颗卫星生成几何距离和几何距离率。
2. 把 legacy `tau_g` 按仰角映射到色散项。
3. 把 legacy 单通道 PR / RR 误差统计映射到多星多历元 sigma。
4. 把 legacy SNR、lock、sustained-loss 映射到 downweight / invalid 逻辑。
5. 在退化窗口内对指定卫星额外施加低 SNR / 低 lock / 大 sigma。

图 5 和图 6 展示这一层：

![](./observation_formation_overview.png)

![](./visible_satellites_and_weights.png)

图 5 侧重代表性 epoch 下的观测组成与质量门限。图 6 侧重全时段的有效卫星数和权重变化。  
二者一起说明“观测为什么在某些时段更弱”。

### 9.1 质量门限与权重映射

本实验的 gating / weighting 配置如下：

{quality_gate_table}

观测形成的工程逻辑可以概括为：

1. 几何先给出 `range / range-rate / elevation`。
2. legacy 单通道背景给出共享的 `PR / RR error`、`SNR`、`lock`、`loss flag`。
3. 仰角越低，`tropo` 和 `dispersive` 越大，同时 sigma 也会放大。
4. `SNR` 和 `lock` 既能直接触发 invalid，也能通过 sigma 放大形成软降权。
5. 退化窗口并不是修改 EKF，而是在观测形成层注入更差的 `SNR / lock / sigma`，因此报告可以明确区分“输入变差”与“滤波器失效”。

### 9.2 代表性 epoch 逐星观测组成摘要

代表性 epoch 取退化段中的代表时刻 `t = {representative_batch.t_s:.3f} s`。逐星组成如下：

{representative_table}

表中可以直接看到：

1. 仰角下降时，`tropo / dispersive / sigma` 会一起变化。
2. legacy SNR 与 lock 会影响 `valid` 和 sigma。
3. 退化段被注入的卫星会出现更高 sigma 或直接失效。

## 10. epoch-wise WLS 串联基线

动态脚本保留了 epoch-wise WLS 串联结果，作用有两个：

1. 作为动态 EKF 的初始化来源
2. 作为“每个 epoch 独立解算”的对比基线

WLS 仍然只解位置和钟差，不解速度和钟漂。  
因此，它能提供静态位置/钟差基线，但不能替代真正的动态滤波。

WLS 摘要如下：

{_markdown_table(
    ["项目", "数值"],
    [
        ["有效 WLS epoch 数", summary["comparison_runs"]["epoch_wls"]["valid_epochs"]],
        ["无效 WLS epoch 数", len(epoch_batches) - summary["comparison_runs"]["epoch_wls"]["valid_epochs"]],
        ["平均 3D 位置误差 (m)", summary["comparison_runs"]["epoch_wls"]["mean_position_error_3d_m"]],
        ["平均 |钟差误差| (m)", summary["comparison_runs"]["epoch_wls"]["mean_clock_bias_abs_error_m"]],
        ["平均残差 RMS (m)", summary["comparison_runs"]["epoch_wls"]["mean_residual_rms_m"]],
    ],
)}

## 11. EKF 初始化与工程策略

EKF 初始状态来自 WLS：

1. 首个有效 WLS epoch 提供位置和钟差初值
2. 前若干个有效 WLS epoch 线性拟合提供速度和钟漂初值

这一步的意义在于避免把速度和钟漂完全靠任意常数拍脑袋初始化。  
即使 PR-only 模式观测不足以强约束速度，它也至少从 WLS 序列获得了一个自洽初始斜率。

工程上还加入了以下处理：

1. 有效卫星数不足 4 时进入 prediction-only
2. 创新协方差奇异时进入 prediction-only
3. 协方差非有限或位置 sigma 过大时标记 divergence warning
4. innovation 过大时记录 warning，但不直接中止实验

代码摘录如下：

{code_ekf_update}

初始化与保护逻辑的核心工程含义是：

1. 首版先把“能稳定跑起来、能给出可解释误差曲线”的动态滤波链路打通。
2. 观测不足时宁可 prediction-only，也不强行做数值不稳定的更新。
3. divergence 检查优先作为诊断量输出，而不是把所有异常直接吞掉。
4. 这样生成的 `dynamic_state_history.csv` 能直接支持后续继续加更复杂动力学或 phase 状态。

## 12. 实验设计

本动态脚本固定包含三组对比：

### 12.1 实验 A：epoch-wise WLS vs EKF

目标：比较“每个 epoch 独立解算”与“动态滤波”的差别。

### 12.2 实验 B：PR-only EKF vs PR + Doppler EKF

目标：比较只靠伪距与加入距离率之后的状态可观测性差异，特别是速度和钟漂。

### 12.3 实验 C：正常观测段 vs 注入退化段

目标：检查低 SNR / 低 lock / 高 sigma / 失效逻辑在动态滤波中的表现。

## 13. 实验结果

### 13.1 模式对比总表

{mode_comparison_table}

这张表直接给出三个结论：

1. `EKF PR + Doppler` 的平均 3D 位置误差显著低于 `epoch-wise WLS`。
2. `PR-only` 模式在速度与钟漂上明显更弱。
3. 当前实验中 `PR + Doppler` 是主线可解释结果，`PR-only` 更像一个退化对照组。

### 13.2 正常段 vs 退化段

以下结果基于主线 `EKF PR + Doppler`：

{segment_comparison_table}

退化段中，有效卫星数下降、sigma 增大、innovation 恶化，这说明退化注入和质量门限确实在动态观测层生效了。

### 13.3 位置误差结果

![](./trajectory_error.png)

图 7 给出 ENU 和 3D 位置误差。  
从图中可以看出，`EKF PR + Doppler` 明显比 `PR-only` 更稳定，也比单纯拼接的 WLS 曲线更平滑。

### 13.4 速度误差结果

![](./velocity_error.png)

图 8 给出速度误差。  
这一项最能体现 Doppler 的价值：`PR + Doppler` 把速度误差压到了远低于 `PR-only` 的量级。

### 13.5 时钟结果

![](./clock_bias_drift.png)

图 9 给出钟差和钟漂。  
加入距离率之后，钟漂状态被明显约束；只用伪距时，钟漂的可观测性更弱。

### 13.6 innovation 结果

![](./innovation_timeseries.png)

图 10 给出 PR 和 RR innovation。  
这张图的作用是检查滤波是否持续稳定，而不是只看最终误差。

### 13.7 WLS 与 EKF 直接对比

![](./filter_vs_epoch_wls.png)

图 11 直接对比 epoch-wise WLS 与 EKF。  
动态滤波的优势不只是更小的平均误差，还包括时间连续性更好。

### 13.8 滤波健康度统计

{filter_health_table}

这张表说明两点：

1. `prediction-only epochs` 不是 bug，而是观测不足或数值保护逻辑触发后的预期行为。
2. 若某模式 warning epoch 明显偏多，通常意味着该模式的可观测性或观测质量更弱，而不是单纯“图上误差大一点”。

## 14. 逐星统计

全程逐星统计如下：

{per_satellite_table}

这张表用来回答：

1. 哪些星长期处在低仰角
2. 哪些星长期 sigma 更大
3. 哪些星在退化窗口内更容易掉出有效观测集合

## 15. 代码片段

### 15.1 legacy 背景构造

{code_legacy}

### 15.2 动态观测形成

{code_dynamic_observation}

### 15.3 状态模型

{code_state_model}

### 15.4 EKF 更新

{code_ekf_update}

### 15.5 主流程与出图

{code_main}

## 16. 简化项与适用范围

### 16.1 简化项

1. 多星几何是接收机本地 `az/el/range` 参数化后再映射到 ECEF 的时变构造，不是广播星历。
2. 接收机真值轨迹是连续常速度 ECEF 轨迹，不是 RAM-C 六自由度真值。
3. 各颗卫星没有独立真实传播路径，而是共享同一条 legacy 单通道真实背景再做映射。
4. 对流层、硬件偏差、卫星钟差和卫星钟漂是参数化项。
5. carrier phase 尚未进入主滤波器，不应作整周或 phase-based 动态结论。

### 16.2 结果适用范围

本结果适用于：

**真实单通道 Ka/WKB 背景 + 动态多星几何映射 + 标准 pseudorange/range-rate + 8 状态 EKF**

本结果不适用于：

**真实多星端到端 Ka 动态导航系统性能定标**

### 16.3 下一步建议

1. 引入更接近真实任务的接收机机动轨迹，而不只是假设常速度。
2. 把卫星几何替换为广播星历或更真实的时变轨道。
3. 把 carrier phase 作为扩状态 float ambiguity 实验分支接入。
4. 把各星独立传播路径和独立电离层/等离子体背景接进来，而不是共享单条 legacy 背景。
5. 在 EKF 之上增加 RTS smoothing 或更严格的一致性检验。

## 17. 运行方式与输出物

运行命令：

```bash
.venv/bin/python notebooks/exp_dynamic_multisat_ekf_report.py
```

输出目录：

```text
results_dynamic_multisat_ekf/
```

主报告使用的文件如下：

{output_inventory_table}

## 18. 附录

### 18.1 `summary.json`

适合做：

1. 全局数值摘要读取
2. 输出文件路径索引
3. 模式级统计读取

### 18.2 `dynamic_observations.csv`

适合做：

1. 每星每历元观测值检查
2. 几何项 / 非几何项 / sigma / quality flag 复查
3. 代表性 epoch 逐星观测重建

### 18.3 `dynamic_state_history.csv`

适合做：

1. 各模式状态时序复查
2. 协方差对角和 warning 复查
3. 误差和 innovation 二次分析

### 18.4 主要文件字段速查

{appendix_field_table}

---

旧脚本完成了真实单通道传播和单通道接收机。  
单历元多星脚本完成了标准伪距和单历元 WLS。  
动态脚本则把系统推进到多历元动态 EKF，并把输入、几何、观测形成和结果层全部串成了一份完整报告。
"""
    with output_path.open("w", encoding="utf-8") as file_obj:
        file_obj.write(text)


def write_report_summary_md(
    receiver_cfg: LEGACY_WLS.ReceiverTruthConfig,
    exp_cfg: DynamicExperimentConfig,
    summary: dict[str, Any],
    output_path: Path,
) -> None:
    run_pr_only = summary["comparison_runs"]["ekf_pr_only"]
    run_pr_doppler = summary["comparison_runs"]["ekf_pr_doppler"]
    run_wls = summary["comparison_runs"]["epoch_wls"]
    text = f"""# 多历元动态多星导航 EKF 汇报摘要

## 复用的旧脚本能力

本次没有重写旧的真实链路，而是直接复用了以下已有函数和结论：

1. `build_fields_from_csv`
2. `compute_real_wkb_series`
3. `build_signal_config_from_wkb_time`
4. `resample_wkb_to_receiver_time`
5. `KaBpskReceiver.run`
6. `solve_pvt_iterative`

因此，真实电子密度场、真实 WKB、重采样到接收机时间轴、Ka PN/BPSK 接收机链路、
单通道 `pseudorange / Doppler / SNR / lock metric` 背景都来自旧脚本，而不是这里重新手写的替代品。

## 本次新增的动态层内容

新脚本新增了以下导航层能力：

1. 多历元接收机真值轨迹
2. 多历元多星时间变化几何与卫星速度
3. 每个 epoch 的标准 `pseudorange` 与 `range-rate` 观测形成
4. 单历元 WLS 串联基线
5. 8 维动态 EKF：位置、速度、钟差、钟漂
6. 退化观测段注入与有效观测门限/降权

## 输入与中间量图片

本次动态报告现在不只输出结果图，也补上了输入和中间量图片：

1. `legacy_channel_overview.png`
   - 展示复用旧链路得到的 `A(t)`、`phi(t)`、`tau_g(t)`、legacy 伪距误差、legacy SNR
2. `sky_geometry_dynamic.png`
   - 展示起始、中段、退化段、结束的动态天空几何
3. `geometry_3d_timeslices.png`
   - 展示接收机中心 ENU 下的 3D 几何和 LOS 连线
4. `geometry_timeseries.png`
   - 展示 visibility，以及相对起点的 elevation、geometric range、range-rate 变化
5. `observation_formation_overview.png`
   - 展示观测形成里的非几何项、sigma、legacy SNR、lock、valid mask

因此，这份报告现在可以同时回答：

1. 输入背景是什么
2. 动态几何是什么
3. 标准观测是如何形成的
4. 滤波结果最终如何表现

## 状态定义

主状态向量采用：

`x = [rx, ry, rz, vx, vy, vz, cb, cd]^T`

其中：

- `r` 为接收机 ECEF 位置，单位 m
- `v` 为接收机 ECEF 速度，单位 m/s
- `cb` 为接收机钟差，单位 m
- `cd` 为接收机钟漂，单位 m/s

## 状态方程

首版采用常速度模型：

- `r(k+1) = r(k) + v(k) * dt`
- `v(k+1) = v(k) + w_v`
- `cb(k+1) = cb(k) + cd(k) * dt`
- `cd(k+1) = cd(k) + w_c`

其中过程噪声 `Q` 在代码中显式按白加速度和钟漂随机游走离散化。

## 观测方程

伪距模型：

`rho = ||rs-r|| + cb - c*dts + tropo + dispersive + hardware + noise`

距离率 / Doppler 模型：

`rhodot = u_LOS^T (vs-vr) + cd - c*ddts + noise`

脚本内部统一使用距离率单位 `m/s`，并按：

`range_rate_mps = -(c / fc) * doppler_hz`

把旧单通道 Doppler 误差统计映射到 EKF 权重。

## 时间轴

- 接收机内部采样率：继承旧脚本真实接收机配置
- 跟踪输出率：`1 ms` 积分块，即约 `1000 Hz`
- 导航解算率：`{exp_cfg.nav_rate_hz:.1f} Hz`

卫星几何采用接收机本地 `az/el/range` 的时变参数化，再逐 epoch 映射到 ECEF，并用有限差分构造卫星速度。

## 主要数值结果

- Epoch-wise WLS 平均 3D 位置误差：{run_wls['mean_position_error_3d_m']:.3f} m
- EKF PR only 平均 3D 位置误差：{run_pr_only['mean_position_error_3d_m']:.3f} m
- EKF PR + Doppler 平均 3D 位置误差：{run_pr_doppler['mean_position_error_3d_m']:.3f} m
- EKF PR only 平均 3D 速度误差：{run_pr_only['mean_velocity_error_3d_mps']:.3f} m/s
- EKF PR + Doppler 平均 3D 速度误差：{run_pr_doppler['mean_velocity_error_3d_mps']:.3f} m/s
- EKF PR + Doppler 平均伪距创新 RMS：{run_pr_doppler['mean_innovation_pr_m']:.3f} m
- EKF PR + Doppler 平均距离率创新 RMS：{run_pr_doppler['mean_innovation_rr_mps']:.3f} m/s

## 主要简化项

1. 多星几何是本地 `az/el/range` 参数化后映射到 ECEF 的时变构造，不是广播星历
2. 接收机真值是连续常速度 ECEF 轨迹，不是 RAM-C 六自由度真轨迹
3. 所有卫星共享同一条旧脚本单通道真实 WKB/接收机背景，再映射到多星多历元观测
4. 对流层、卫星钟差、硬件偏差仍为导航层参数化项
5. 首版主实验只做 `pseudorange + Doppler`，没有把 carrier phase ambiguity 扩展进主滤波器

## 首版限制

1. 这不是完整真实多星端到端 Ka 动态导航系统定标
2. 多星各链路没有独立真实射线/等离子体路径
3. 观测相关性来自共享 legacy 背景映射，不是独立多通道同步接收机跟踪
4. carrier phase 暂未进入主 EKF，因此不能给出整周相关结论

## 下一步建议

1. 将卫星几何从当前自洽模型升级到真实星历驱动
2. 为 carrier phase 引入每星 float ambiguity 状态，形成 `PR + Doppler + Phase` 扩展滤波
3. 把多星各 LOS 的色散项从共享背景映射升级为独立传播路径
4. 若后续有真实飞行轨迹，再用真实动力学替换当前常速度接收机真值

## 边界声明

本结果代表：

**真实单通道 Ka/WKB 背景耦合下的 hybrid 多历元动态多星 EKF 实验**

不代表：

**真实端到端多星 Ka 动态导航系统性能定标**

完整长报告见：

`report_full.md`
"""
    with output_path.open("w", encoding="utf-8") as file_obj:
        file_obj.write(text)


# ============================================================
# 9. Main
# ============================================================


def print_overview(
    exp_cfg: DynamicExperimentConfig,
    epoch_batches: Sequence[EpochObservationBatch],
    wls_results: Sequence[EpochWlsResult],
    run_results: Sequence[RunResult],
) -> None:
    print("\n[Dynamic experiment summary]")
    print(f"  - navigation rate = {exp_cfg.nav_rate_hz:.1f} Hz")
    print(f"  - navigation epochs = {len(epoch_batches)}")
    print(f"  - mean valid satellites = {np.mean([batch.num_valid_sats for batch in epoch_batches]):.2f}")
    print(
        "  - epoch WLS mean 3D position error = "
        f"{np.nanmean([item.position_error_3d_m for item in wls_results if item.valid]):.3f} m"
    )
    for run in run_results:
        print(
            f"  - {run.mode}: "
            f"mean pos err {np.nanmean([item.position_error_3d_m for item in run.history]):.3f} m, "
            f"mean vel err {np.nanmean([item.velocity_error_3d_mps for item in run.history]):.3f} m/s, "
            f"prediction-only epochs {sum(item.prediction_only for item in run.history)}"
        )


def _frequency_label(fc_hz: float) -> str:
    return f"{fc_hz / 1e9:.1f}".replace(".", "p") + "GHz"


def _flatten_numeric_scalars(value: Any, *, prefix: str = "") -> dict[str, float]:
    out: dict[str, float] = {}
    if isinstance(value, dict):
        for key, sub_value in value.items():
            next_prefix = f"{prefix}_{key}" if prefix else str(key)
            out.update(_flatten_numeric_scalars(sub_value, prefix=next_prefix))
        return out
    if isinstance(value, (list, tuple)):
        return out
    if isinstance(value, (bool, np.bool_)):
        if prefix:
            out[prefix] = float(int(value))
        return out
    if isinstance(value, (int, float, np.integer, np.floating)):
        scalar = float(value)
        if np.isfinite(scalar) and prefix:
            out[prefix] = scalar
    return out


def _extract_cross_frequency_row(fc_hz: float, summary: dict[str, Any]) -> dict[str, float]:
    def _get_metric(metrics: dict[str, Any], *candidates: str) -> float:
        for key in candidates:
            if key in metrics:
                return float(metrics[key])
        raise KeyError(f"缺少指标字段，候选={candidates}")

    runs = summary["comparison_runs"]
    pr_only = runs["ekf_pr_only"]
    pr_doppler = runs["ekf_pr_doppler"]
    row = {
        "frequency_hz": float(fc_hz),
        "epoch_wls_mean_position_error_3d_m": float(runs["epoch_wls"]["mean_position_error_3d_m"]),
        "epoch_wls_mean_residual_rms_m": float(runs["epoch_wls"]["mean_residual_rms_m"]),
        "ekf_pr_only_mean_position_error_3d_m": float(pr_only["mean_position_error_3d_m"]),
        "ekf_pr_only_mean_velocity_error_3d_mps": float(pr_only["mean_velocity_error_3d_mps"]),
        "ekf_pr_only_mean_clock_bias_error_m": _get_metric(
            pr_only,
            "mean_clock_bias_error_m",
            "mean_clock_bias_abs_error_m",
        ),
        "ekf_pr_only_mean_clock_drift_error_mps": _get_metric(
            pr_only,
            "mean_clock_drift_error_mps",
            "mean_clock_drift_abs_error_mps",
        ),
        "ekf_pr_only_mean_innovation_pr_m": float(pr_only["mean_innovation_pr_m"]),
        "ekf_pr_only_prediction_only_epochs": float(pr_only["prediction_only_epochs"]),
        "ekf_pr_doppler_mean_position_error_3d_m": float(pr_doppler["mean_position_error_3d_m"]),
        "ekf_pr_doppler_mean_velocity_error_3d_mps": float(pr_doppler["mean_velocity_error_3d_mps"]),
        "ekf_pr_doppler_mean_clock_bias_error_m": _get_metric(
            pr_doppler,
            "mean_clock_bias_error_m",
            "mean_clock_bias_abs_error_m",
        ),
        "ekf_pr_doppler_mean_clock_drift_error_mps": _get_metric(
            pr_doppler,
            "mean_clock_drift_error_mps",
            "mean_clock_drift_abs_error_mps",
        ),
        "ekf_pr_doppler_mean_innovation_pr_m": float(pr_doppler["mean_innovation_pr_m"]),
        "ekf_pr_doppler_mean_innovation_rr_mps": float(pr_doppler["mean_innovation_rr_mps"]),
        "ekf_pr_doppler_prediction_only_epochs": float(pr_doppler["prediction_only_epochs"]),
    }
    # 除核心列外，把 summary 中可量化的指标都纳入跨频分析。
    row.update(_flatten_numeric_scalars(summary.get("legacy_channel_metrics", {}), prefix="legacy"))
    row.update(_flatten_numeric_scalars(summary.get("comparison_runs", {}), prefix="comparison_runs"))
    row.update(_flatten_numeric_scalars(summary.get("time_axes", {}), prefix="time_axes"))
    row.update(_flatten_numeric_scalars(summary.get("degradation_window_s", {}), prefix="degradation_window_s"))
    return row


def _write_cross_frequency_outputs(
    rows: list[dict[str, float]],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    key_union = {key for row in rows for key in row.keys()}
    fieldnames = ["frequency_hz"] + sorted(key for key in key_union if key != "frequency_hz")
    csv_path = output_dir / "ekf_metrics.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    json_path = output_dir / "ekf_metrics.json"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    freq_ghz = np.asarray([row["frequency_hz"] for row in rows], dtype=float) / 1e9
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), dpi=160)

    axes[0, 0].plot(freq_ghz, [row["epoch_wls_mean_position_error_3d_m"] for row in rows], marker="o", label="epoch WLS")
    axes[0, 0].plot(freq_ghz, [row["ekf_pr_only_mean_position_error_3d_m"] for row in rows], marker="o", label="EKF PR")
    axes[0, 0].plot(freq_ghz, [row["ekf_pr_doppler_mean_position_error_3d_m"] for row in rows], marker="o", label="EKF PR+Doppler")
    axes[0, 0].set_title("Mean 3D position error")
    axes[0, 0].set_xlabel("Frequency (GHz)")
    axes[0, 0].set_ylabel("m")
    axes[0, 0].grid(True, ls=":", alpha=0.5)
    axes[0, 0].legend()

    axes[0, 1].plot(freq_ghz, [row["ekf_pr_only_mean_velocity_error_3d_mps"] for row in rows], marker="o", label="EKF PR")
    axes[0, 1].plot(freq_ghz, [row["ekf_pr_doppler_mean_velocity_error_3d_mps"] for row in rows], marker="o", label="EKF PR+Doppler")
    axes[0, 1].set_title("Mean 3D velocity error")
    axes[0, 1].set_xlabel("Frequency (GHz)")
    axes[0, 1].set_ylabel("m/s")
    axes[0, 1].grid(True, ls=":", alpha=0.5)
    axes[0, 1].legend()

    axes[1, 0].plot(freq_ghz, [row["ekf_pr_only_mean_innovation_pr_m"] for row in rows], marker="o", label="EKF PR innovation PR")
    axes[1, 0].plot(freq_ghz, [row["ekf_pr_doppler_mean_innovation_pr_m"] for row in rows], marker="o", label="EKF PR+D innovation PR")
    axes[1, 0].plot(freq_ghz, [row["ekf_pr_doppler_mean_innovation_rr_mps"] for row in rows], marker="o", label="EKF PR+D innovation RR")
    axes[1, 0].set_title("Innovation means")
    axes[1, 0].set_xlabel("Frequency (GHz)")
    axes[1, 0].grid(True, ls=":", alpha=0.5)
    axes[1, 0].legend()

    axes[1, 1].plot(freq_ghz, [row["ekf_pr_only_prediction_only_epochs"] for row in rows], marker="o", label="EKF PR")
    axes[1, 1].plot(freq_ghz, [row["ekf_pr_doppler_prediction_only_epochs"] for row in rows], marker="o", label="EKF PR+Doppler")
    axes[1, 1].set_title("Prediction-only epochs")
    axes[1, 1].set_xlabel("Frequency (GHz)")
    axes[1, 1].set_ylabel("epochs")
    axes[1, 1].grid(True, ls=":", alpha=0.5)
    axes[1, 1].legend()

    fig.tight_layout()
    fig.savefig(output_dir / "ekf_metrics_vs_frequency.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def run_dynamic_ekf_for_frequency(
    fc_hz: float,
    *,
    results_dir: Path | None = None,
    exp_cfg_override: DynamicExperimentConfig | None = None,
    truth_free_runtime: bool = False,
    truth_free_initialization: bool = False,
    channel_background_mode: str = "legacy",
) -> dict[str, Any]:
    global RESULTS_DIR
    prev_results_dir = RESULTS_DIR
    exp_cfg = exp_cfg_override or DynamicExperimentConfig(carrier_frequency_hz=float(fc_hz))
    receiver_cfg = build_receiver_truth_config(exp_cfg)
    RESULTS_DIR = results_dir if results_dir is not None else results_dir_for_frequency(receiver_cfg.carrier_frequency_hz)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        plot_cfg = PlotConfig(enabled=False, save_dir=RESULTS_DIR)
        if channel_background_mode == "legacy":
            legacy_bg = LEGACY_WLS.build_legacy_channel_background(receiver_cfg, truth_free_runtime=truth_free_runtime)
        elif channel_background_mode == "issue03_textbook":
            legacy_bg = build_textbook_channel_background(
                receiver_cfg,
                truth_free_runtime=truth_free_runtime,
                nav_data_enabled=True,
            )
        else:
            raise ValueError(f"Unsupported channel background mode: {channel_background_mode}")
        epoch_times_s, legacy_metrics = build_nav_epoch_metrics(legacy_bg, receiver_cfg, exp_cfg)
        truth_history = build_truth_history(receiver_cfg, exp_cfg, epoch_times_s)
        satellite_templates = build_satellite_templates(receiver_cfg, exp_cfg)
        epoch_batches = build_dynamic_observation_batches(
            receiver_cfg,
            exp_cfg,
            legacy_bg,
            legacy_metrics,
            truth_history,
            satellite_templates,
        )
        wls_results = run_epoch_wls_series(
            epoch_batches,
            legacy_metrics,
            receiver_cfg,
            truth_free_initialization=truth_free_initialization,
        )
        run_results = [
            run_ekf("ekf_pr_only", epoch_batches, wls_results, exp_cfg),
            run_ekf("ekf_pr_doppler", epoch_batches, wls_results, exp_cfg),
        ]

        plot_legacy_channel_overview(legacy_bg, plot_cfg)
        plot_sky_geometry_dynamic(epoch_batches, exp_cfg, plot_cfg)
        plot_geometry_3d_timeslices(receiver_cfg, epoch_batches, exp_cfg, plot_cfg)
        plot_geometry_timeseries(epoch_batches, exp_cfg, plot_cfg)
        plot_observation_formation_overview(epoch_batches, exp_cfg, plot_cfg)
        plot_trajectory_error(receiver_cfg, epoch_batches, run_results, plot_cfg)
        plot_velocity_error(epoch_batches, run_results, plot_cfg)
        plot_clock_bias_and_drift(epoch_batches, run_results, plot_cfg)
        plot_innovation_timeseries(run_results, plot_cfg)
        plot_visible_satellites_and_weights(epoch_batches, exp_cfg, plot_cfg)
        plot_filter_vs_epoch_wls(wls_results, run_results, plot_cfg)

        write_dynamic_observations_csv(epoch_batches, RESULTS_DIR / "dynamic_observations.csv")
        write_dynamic_state_history_csv(epoch_batches, wls_results, run_results, RESULTS_DIR / "dynamic_state_history.csv")
        summary = build_summary_json(receiver_cfg, exp_cfg, legacy_bg, legacy_metrics, epoch_batches, wls_results, run_results)
        write_summary_json(summary, RESULTS_DIR / "summary.json")
        write_report_summary_md(receiver_cfg, exp_cfg, summary, RESULTS_DIR / "report_summary.md")
        write_report_full_md(
            receiver_cfg,
            exp_cfg,
            legacy_bg,
            legacy_metrics,
            epoch_batches,
            wls_results,
            run_results,
            summary,
            RESULTS_DIR / "report_full.md",
        )

        return {
            "frequency_hz": float(fc_hz),
            "results_dir": RESULTS_DIR,
            "summary": json.loads((RESULTS_DIR / "summary.json").read_text(encoding="utf-8")),
        }
    finally:
        RESULTS_DIR = prev_results_dir


def run_dynamic_ekf_frequency_grid(
    frequencies_hz: Sequence[float],
    *,
    root_output_dir: Path | None = None,
    truth_free_runtime: bool = False,
    truth_free_initialization: bool = False,
    channel_background_mode: str = "legacy",
) -> dict[str, Any]:
    if len(frequencies_hz) == 0:
        raise ValueError("frequencies_hz 不能为空。")
    root_dir = root_output_dir if root_output_dir is not None else (CANONICAL_RESULTS_ROOT / "results_ka_multifreq" / "ekf")
    root_dir.mkdir(parents=True, exist_ok=True)

    per_frequency: list[dict[str, Any]] = []
    rows: list[dict[str, float]] = []
    for idx, fc_hz in enumerate(frequencies_hz):
        label = _frequency_label(float(fc_hz))
        result = run_dynamic_ekf_for_frequency(
            float(fc_hz),
            results_dir=root_dir / label,
            exp_cfg_override=DynamicExperimentConfig(carrier_frequency_hz=float(fc_hz), rng_seed=20260326 + idx * 1000),
            truth_free_runtime=truth_free_runtime,
            truth_free_initialization=truth_free_initialization,
            channel_background_mode=channel_background_mode,
        )
        per_frequency.append(result)
        rows.append(_extract_cross_frequency_row(float(fc_hz), result["summary"]))

    cross_dir = root_dir / "cross_frequency"
    _write_cross_frequency_outputs(rows, cross_dir)
    return {
        "root_dir": root_dir,
        "cross_dir": cross_dir,
        "rows": rows,
        "per_frequency": per_frequency,
    }


def main() -> None:
    global RESULTS_DIR
    print("=" * 100)
    print("Dynamic multisatellite EKF experiment on top of reused legacy Ka/WKB chain")
    print("=" * 100)
    result = run_dynamic_ekf_for_frequency(22.5e9, results_dir=results_dir_for_frequency(22.5e9))
    RESULTS_DIR = result["results_dir"]

    print("\n[Output files]")
    print(f"  - results dir = {RESULTS_DIR}")
    print("  - legacy_channel_overview.png")
    print("  - sky_geometry_dynamic.png")
    print("  - geometry_3d_timeslices.png")
    print("  - geometry_timeseries.png")
    print("  - observation_formation_overview.png")
    print("  - trajectory_error.png")
    print("  - velocity_error.png")
    print("  - clock_bias_drift.png")
    print("  - innovation_timeseries.png")
    print("  - visible_satellites_and_weights.png")
    print("  - filter_vs_epoch_wls.png")
    print("  - summary.json")
    print("  - dynamic_observations.csv")
    print("  - dynamic_state_history.csv")
    print("  - report_summary.md")
    print("  - report_full.md")


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*tight_layout.*", category=UserWarning)
        np.random.seed(20260326)
        main()
