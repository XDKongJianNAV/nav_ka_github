from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from nav_ka import CORRECTIONS_ROOT
from nav_ka.legacy import exp_dynamic_multisat_ekf_report as LEGACY_EKF
from nav_ka.legacy import exp_multisat_wls_pvt_report as LEGACY_WLS
from nav_ka.studies.issue_01_truth_dependency import build_truth_free_initial_state_from_observations
from nav_ka.studies.issue_03_textbook_correction import (
    MotionProfile,
    TrackingAidingProfile,
    build_textbook_channel_background,
    run_textbook_single_channel_for_frequency,
)


C_LIGHT = LEGACY_WLS.C_LIGHT
ISSUE04_ROOT = CORRECTIONS_ROOT / "issue_04_imu_aided"
GRAVITY_REF_MPS2 = 9.80665


@dataclass(frozen=True)
class ImuProfileConfig:
    imu_rate_hz: float = 200.0
    gyro_bias_in_run_degph: float = 0.005
    gyro_arw_deg_rt_hr: float = 0.003
    accel_bias_in_run_mg: float = 0.03
    accel_vrw_mps_rt_hr: float = 0.02
    gyro_full_scale_dps: float = 500.0
    accel_full_scale_g: float = 20.0


@dataclass(frozen=True)
class TrajectoryScenarioConfig:
    height_km: float
    speed_kms: float
    carrier_frequency_hz: float
    duration_s: float = 22.0
    latitude_deg: float = 34.0
    longitude_deg: float = 108.0
    receiver_clock_bias_m: float = 120.0
    receiver_clock_drift_mps: float = 0.38

    @property
    def label(self) -> str:
        freq_label = f"{self.carrier_frequency_hz / 1e9:.1f}".replace(".", "p")
        return f"h{self.height_km:.0f}km_v{self.speed_kms:.2f}kms_{freq_label}GHz"


@dataclass(frozen=True)
class ReferenceTrajectory:
    t_s: np.ndarray
    position_enu_m: np.ndarray
    velocity_enu_mps: np.ndarray
    accel_enu_mps2: np.ndarray
    attitude_quat_bn: np.ndarray
    attitude_dcm_bn: np.ndarray
    gyro_body_radps: np.ndarray
    accel_body_mps2: np.ndarray
    position_ecef_m: np.ndarray
    velocity_ecef_mps: np.ndarray
    accel_ecef_mps2: np.ndarray


@dataclass(frozen=True)
class ImuSampleSeries:
    t_s: np.ndarray
    gyro_body_radps: np.ndarray
    accel_body_mps2: np.ndarray


@dataclass(frozen=True)
class ImuMechanizationResult:
    t_s: np.ndarray
    position_enu_m: np.ndarray
    velocity_enu_mps: np.ndarray
    accel_enu_mps2: np.ndarray
    position_ecef_m: np.ndarray
    velocity_ecef_mps: np.ndarray
    accel_ecef_mps2: np.ndarray
    attitude_quat_bn: np.ndarray
    attitude_dcm_bn: np.ndarray
    gyro_body_radps: np.ndarray
    accel_body_mps2: np.ndarray


def build_scenario_grid(
    frequencies_hz: Sequence[float],
    *,
    heights_km: Sequence[float] = (70.0, 80.0, 90.0),
    speeds_kms: Sequence[float] = (7.9, 8.45, 9.0),
) -> list[TrajectoryScenarioConfig]:
    return [
        TrajectoryScenarioConfig(height_km=float(height_km), speed_kms=float(speed_kms), carrier_frequency_hz=float(fc_hz))
        for fc_hz in frequencies_hz
        for height_km in heights_km
        for speed_kms in speeds_kms
    ]


def _enu_to_ecef_matrix(latitude_deg: float, longitude_deg: float) -> np.ndarray:
    return LEGACY_WLS.ecef_to_enu_rotation_matrix(latitude_deg, longitude_deg).T


def _skew(vector: np.ndarray) -> np.ndarray:
    x_val, y_val, z_val = np.asarray(vector, dtype=float)
    return np.array([[0.0, -z_val, y_val], [z_val, 0.0, -x_val], [-y_val, x_val, 0.0]], dtype=float)


def _rotation_matrix_from_euler(roll_rad: float, pitch_rad: float, yaw_rad: float) -> np.ndarray:
    cr = math.cos(roll_rad)
    sr = math.sin(roll_rad)
    cp = math.cos(pitch_rad)
    sp = math.sin(pitch_rad)
    cy = math.cos(yaw_rad)
    sy = math.sin(yaw_rad)
    return np.array(
        [
            [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp, cp * sr, cp * cr],
        ],
        dtype=float,
    )


def _rotation_matrix_to_quaternion(rotation: np.ndarray) -> np.ndarray:
    mat = np.asarray(rotation, dtype=float)
    trace = float(np.trace(mat))
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        quat = np.array(
            [
                0.25 * scale,
                (mat[2, 1] - mat[1, 2]) / scale,
                (mat[0, 2] - mat[2, 0]) / scale,
                (mat[1, 0] - mat[0, 1]) / scale,
            ],
            dtype=float,
        )
    elif mat[0, 0] > mat[1, 1] and mat[0, 0] > mat[2, 2]:
        scale = math.sqrt(1.0 + mat[0, 0] - mat[1, 1] - mat[2, 2]) * 2.0
        quat = np.array(
            [
                (mat[2, 1] - mat[1, 2]) / scale,
                0.25 * scale,
                (mat[0, 1] + mat[1, 0]) / scale,
                (mat[0, 2] + mat[2, 0]) / scale,
            ],
            dtype=float,
        )
    elif mat[1, 1] > mat[2, 2]:
        scale = math.sqrt(1.0 + mat[1, 1] - mat[0, 0] - mat[2, 2]) * 2.0
        quat = np.array(
            [
                (mat[0, 2] - mat[2, 0]) / scale,
                (mat[0, 1] + mat[1, 0]) / scale,
                0.25 * scale,
                (mat[1, 2] + mat[2, 1]) / scale,
            ],
            dtype=float,
        )
    else:
        scale = math.sqrt(1.0 + mat[2, 2] - mat[0, 0] - mat[1, 1]) * 2.0
        quat = np.array(
            [
                (mat[1, 0] - mat[0, 1]) / scale,
                (mat[0, 2] + mat[2, 0]) / scale,
                (mat[1, 2] + mat[2, 1]) / scale,
                0.25 * scale,
            ],
            dtype=float,
        )
    return quat / np.linalg.norm(quat)


def _integrate_body_rotation(rotation_prev: np.ndarray, gyro_body_radps: np.ndarray, dt_s: float) -> np.ndarray:
    omega_dt = np.asarray(gyro_body_radps, dtype=float) * float(dt_s)
    angle_rad = float(np.linalg.norm(omega_dt))
    if angle_rad <= 1e-12:
        delta_rot = np.eye(3, dtype=float) + _skew(omega_dt)
    else:
        axis = omega_dt / angle_rad
        axis_skew = _skew(axis)
        delta_rot = (
            np.eye(3, dtype=float)
            + math.sin(angle_rad) * axis_skew
            + (1.0 - math.cos(angle_rad)) * (axis_skew @ axis_skew)
        )
    rotation_next = np.asarray(rotation_prev, dtype=float) @ delta_rot
    u_mat, _, vh_mat = np.linalg.svd(rotation_next)
    return u_mat @ vh_mat


def _interp_vector_series(t_grid_s: np.ndarray, values: np.ndarray, t_s: float) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    return np.array([np.interp(t_s, t_grid_s, arr[:, axis]) for axis in range(arr.shape[1])], dtype=float)


def _build_reference_trajectory(
    scenario: TrajectoryScenarioConfig,
    imu_cfg: ImuProfileConfig,
) -> ReferenceTrajectory:
    dt_s = 1.0 / imu_cfg.imu_rate_hz
    t_s = np.arange(0.0, scenario.duration_s + 0.5 * dt_s, dt_s)
    speed_mps = scenario.speed_kms * 1e3
    turn_rate_radps = 0.0016 + 0.00015 * (scenario.speed_kms - 7.9)
    theta = math.radians(78.0) + turn_rate_radps * t_s + 0.02 * np.sin(2.0 * np.pi * t_s / max(scenario.duration_s, 1.0))
    speed_scale = 1.0 + 0.012 * np.sin(2.0 * np.pi * t_s / max(scenario.duration_s, 1.0))
    vertical_rate_mps = 18.0 * np.sin(2.0 * np.pi * t_s / max(scenario.duration_s, 1.0))
    velocity_enu_mps = np.column_stack(
        [
            speed_mps * speed_scale * np.cos(theta),
            speed_mps * speed_scale * np.sin(theta),
            vertical_rate_mps,
        ]
    )
    position_enu_m = np.zeros_like(velocity_enu_mps)
    for idx in range(1, len(t_s)):
        position_enu_m[idx] = position_enu_m[idx - 1] + 0.5 * (velocity_enu_mps[idx - 1] + velocity_enu_mps[idx]) * dt_s
    accel_enu_mps2 = np.gradient(velocity_enu_mps, dt_s, axis=0, edge_order=1)

    horiz_speed = np.linalg.norm(velocity_enu_mps[:, :2], axis=1)
    yaw_rad = np.unwrap(np.arctan2(velocity_enu_mps[:, 0], velocity_enu_mps[:, 1]))
    pitch_rad = np.arctan2(velocity_enu_mps[:, 2], np.maximum(horiz_speed, 1.0))
    roll_rad = np.zeros_like(yaw_rad)
    yaw_rate_radps = np.gradient(yaw_rad, t_s, edge_order=1)
    pitch_rate_radps = np.gradient(pitch_rad, t_s, edge_order=1)
    gyro_body_radps = np.column_stack(
        [
            np.zeros_like(t_s),
            pitch_rate_radps,
            yaw_rate_radps * np.cos(pitch_rad),
        ]
    )

    attitude_dcm_bn = np.empty((len(t_s), 3, 3), dtype=float)
    attitude_quat_bn = np.empty((len(t_s), 4), dtype=float)
    accel_body_mps2 = np.empty((len(t_s), 3), dtype=float)
    for idx, (roll_val, pitch_val, yaw_val) in enumerate(zip(roll_rad, pitch_rad, yaw_rad, strict=True)):
        dcm_bn = _rotation_matrix_from_euler(float(roll_val), float(pitch_val), float(yaw_val))
        attitude_dcm_bn[idx] = dcm_bn
        attitude_quat_bn[idx] = _rotation_matrix_to_quaternion(dcm_bn)
        accel_body_mps2[idx] = dcm_bn.T @ accel_enu_mps2[idx]

    rot_enu_to_ecef = _enu_to_ecef_matrix(scenario.latitude_deg, scenario.longitude_deg)
    origin_ecef_m = LEGACY_WLS.lla_to_ecef(scenario.latitude_deg, scenario.longitude_deg, scenario.height_km * 1e3)
    position_ecef_m = origin_ecef_m[None, :] + position_enu_m @ rot_enu_to_ecef.T
    velocity_ecef_mps = velocity_enu_mps @ rot_enu_to_ecef.T
    accel_ecef_mps2 = accel_enu_mps2 @ rot_enu_to_ecef.T
    return ReferenceTrajectory(
        t_s=np.asarray(t_s, dtype=float),
        position_enu_m=np.asarray(position_enu_m, dtype=float),
        velocity_enu_mps=np.asarray(velocity_enu_mps, dtype=float),
        accel_enu_mps2=np.asarray(accel_enu_mps2, dtype=float),
        attitude_quat_bn=np.asarray(attitude_quat_bn, dtype=float),
        attitude_dcm_bn=np.asarray(attitude_dcm_bn, dtype=float),
        gyro_body_radps=np.asarray(gyro_body_radps, dtype=float),
        accel_body_mps2=np.asarray(accel_body_mps2, dtype=float),
        position_ecef_m=np.asarray(position_ecef_m, dtype=float),
        velocity_ecef_mps=np.asarray(velocity_ecef_mps, dtype=float),
        accel_ecef_mps2=np.asarray(accel_ecef_mps2, dtype=float),
    )


def _build_measured_imu(
    scenario: TrajectoryScenarioConfig,
    imu_cfg: ImuProfileConfig,
    reference: ReferenceTrajectory,
) -> ImuSampleSeries:
    seed = int(round(scenario.carrier_frequency_hz / 1e6)) + int(round(scenario.height_km * 10.0)) + int(round(scenario.speed_kms * 100.0))
    rng = np.random.default_rng(seed)
    dt_s = 1.0 / imu_cfg.imu_rate_hz
    accel_bias_mps2 = np.full(3, imu_cfg.accel_bias_in_run_mg * 9.80665e-3, dtype=float)
    gyro_bias_radps = np.full(3, math.radians(imu_cfg.gyro_bias_in_run_degph) / 3600.0, dtype=float)
    accel_noise_sigma_mps2 = imu_cfg.accel_vrw_mps_rt_hr / math.sqrt(3600.0 * dt_s)
    gyro_noise_sigma_radps = math.radians(imu_cfg.gyro_arw_deg_rt_hr) / math.sqrt(3600.0 * dt_s)

    accel_meas = reference.accel_body_mps2 + accel_bias_mps2 + rng.normal(0.0, accel_noise_sigma_mps2, size=reference.accel_body_mps2.shape)
    gyro_meas = reference.gyro_body_radps + gyro_bias_radps + rng.normal(0.0, gyro_noise_sigma_radps, size=reference.gyro_body_radps.shape)
    accel_limit = imu_cfg.accel_full_scale_g * GRAVITY_REF_MPS2
    gyro_limit = math.radians(imu_cfg.gyro_full_scale_dps)
    accel_meas = np.clip(accel_meas, -accel_limit, accel_limit)
    gyro_meas = np.clip(gyro_meas, -gyro_limit, gyro_limit)
    return ImuSampleSeries(
        t_s=np.asarray(reference.t_s, dtype=float),
        gyro_body_radps=np.asarray(gyro_meas, dtype=float),
        accel_body_mps2=np.asarray(accel_meas, dtype=float),
    )


def _build_motion_profile_from_ins(
    scenario: TrajectoryScenarioConfig,
    t_s: np.ndarray,
    position_enu_m: np.ndarray,
    velocity_enu_mps: np.ndarray,
) -> MotionProfile:
    los_east = 0.075 + 0.01 * ((scenario.height_km - 70.0) / 20.0)
    los_north = -0.03
    los_up = 0.015
    los_vector = np.array([los_east, los_north, los_up], dtype=float)
    los_vector /= np.linalg.norm(los_vector)
    base_range_m = 115_000.0
    range_m = base_range_m + position_enu_m @ los_vector
    range_rate_mps = velocity_enu_mps @ los_vector
    code_delay_s = range_m / C_LIGHT
    code_rate_chips_per_s = (range_rate_mps / C_LIGHT) * 50_000.0
    doppler_hz = -(scenario.carrier_frequency_hz / C_LIGHT) * range_rate_mps
    doppler_rate_hz_per_s = np.gradient(doppler_hz, t_s, edge_order=1)
    return MotionProfile(
        t_s=np.asarray(t_s, dtype=float),
        code_delay_s=np.asarray(code_delay_s, dtype=float),
        code_rate_chips_per_s=np.asarray(code_rate_chips_per_s, dtype=float),
        doppler_hz=np.asarray(doppler_hz, dtype=float),
        doppler_rate_hz_per_s=np.asarray(doppler_rate_hz_per_s, dtype=float),
        range_m=np.asarray(range_m, dtype=float),
        range_rate_mps=np.asarray(range_rate_mps, dtype=float),
        source_note="issue04 mechanized INS front-end motion profile",
    )


def _build_tracking_aiding_profile(motion_profile: MotionProfile) -> TrackingAidingProfile:
    return TrackingAidingProfile(
        t_s=np.asarray(motion_profile.t_s, dtype=float),
        code_aiding_rate_chips_per_s=np.asarray(motion_profile.code_rate_chips_per_s, dtype=float),
        carrier_aiding_rate_hz_per_s=np.asarray(motion_profile.doppler_rate_hz_per_s, dtype=float),
        aiding_enabled=np.ones_like(motion_profile.t_s, dtype=bool),
        source_note="issue04 INS-derived scalar DLL/PLL feedback profile",
    )


def mechanize_imu_profile(
    scenario: TrajectoryScenarioConfig,
    imu_cfg: ImuProfileConfig,
) -> tuple[ReferenceTrajectory, ImuSampleSeries, ImuMechanizationResult, MotionProfile, TrackingAidingProfile]:
    reference = _build_reference_trajectory(scenario, imu_cfg)
    measured_imu = _build_measured_imu(scenario, imu_cfg, reference)
    rot_enu_to_ecef = _enu_to_ecef_matrix(scenario.latitude_deg, scenario.longitude_deg)
    origin_ecef_m = LEGACY_WLS.lla_to_ecef(scenario.latitude_deg, scenario.longitude_deg, scenario.height_km * 1e3)
    dt_s = 1.0 / imu_cfg.imu_rate_hz

    position_enu_m = np.zeros_like(reference.position_enu_m)
    velocity_enu_mps = np.zeros_like(reference.velocity_enu_mps)
    accel_enu_mps2 = np.zeros_like(reference.accel_enu_mps2)
    attitude_dcm_bn = np.zeros_like(reference.attitude_dcm_bn)
    attitude_quat_bn = np.zeros_like(reference.attitude_quat_bn)

    position_enu_m[0] = reference.position_enu_m[0]
    velocity_enu_mps[0] = reference.velocity_enu_mps[0]
    accel_enu_mps2[0] = reference.attitude_dcm_bn[0] @ measured_imu.accel_body_mps2[0]
    attitude_dcm_bn[0] = reference.attitude_dcm_bn[0]
    attitude_quat_bn[0] = _rotation_matrix_to_quaternion(attitude_dcm_bn[0])

    for idx in range(1, len(reference.t_s)):
        attitude_dcm_bn[idx] = _integrate_body_rotation(attitude_dcm_bn[idx - 1], measured_imu.gyro_body_radps[idx - 1], dt_s)
        attitude_quat_bn[idx] = _rotation_matrix_to_quaternion(attitude_dcm_bn[idx])
        accel_enu_mps2[idx - 1] = attitude_dcm_bn[idx - 1] @ measured_imu.accel_body_mps2[idx - 1]
        velocity_enu_mps[idx] = velocity_enu_mps[idx - 1] + accel_enu_mps2[idx - 1] * dt_s
        position_enu_m[idx] = position_enu_m[idx - 1] + velocity_enu_mps[idx - 1] * dt_s + 0.5 * accel_enu_mps2[idx - 1] * dt_s ** 2
    accel_enu_mps2[-1] = attitude_dcm_bn[-1] @ measured_imu.accel_body_mps2[-1]

    position_ecef_m = origin_ecef_m[None, :] + position_enu_m @ rot_enu_to_ecef.T
    velocity_ecef_mps = velocity_enu_mps @ rot_enu_to_ecef.T
    accel_ecef_mps2 = accel_enu_mps2 @ rot_enu_to_ecef.T
    mechanization = ImuMechanizationResult(
        t_s=np.asarray(reference.t_s, dtype=float),
        position_enu_m=np.asarray(position_enu_m, dtype=float),
        velocity_enu_mps=np.asarray(velocity_enu_mps, dtype=float),
        accel_enu_mps2=np.asarray(accel_enu_mps2, dtype=float),
        position_ecef_m=np.asarray(position_ecef_m, dtype=float),
        velocity_ecef_mps=np.asarray(velocity_ecef_mps, dtype=float),
        accel_ecef_mps2=np.asarray(accel_ecef_mps2, dtype=float),
        attitude_quat_bn=np.asarray(attitude_quat_bn, dtype=float),
        attitude_dcm_bn=np.asarray(attitude_dcm_bn, dtype=float),
        gyro_body_radps=np.asarray(measured_imu.gyro_body_radps, dtype=float),
        accel_body_mps2=np.asarray(measured_imu.accel_body_mps2, dtype=float),
    )
    motion_profile = _build_motion_profile_from_ins(
        scenario,
        mechanization.t_s,
        mechanization.position_enu_m,
        mechanization.velocity_enu_mps,
    )
    aiding_profile = _build_tracking_aiding_profile(motion_profile)
    return reference, measured_imu, mechanization, motion_profile, aiding_profile


def _scenario_receiver_cfg(scenario: TrajectoryScenarioConfig) -> LEGACY_WLS.ReceiverTruthConfig:
    return LEGACY_WLS.ReceiverTruthConfig(
        latitude_deg=scenario.latitude_deg,
        longitude_deg=scenario.longitude_deg,
        height_m=scenario.height_km * 1e3,
        receiver_clock_bias_m=scenario.receiver_clock_bias_m,
        carrier_frequency_hz=scenario.carrier_frequency_hz,
        sat_orbit_radius_m=26_560_000.0,
    )


def _reference_to_truth_history(
    scenario: TrajectoryScenarioConfig,
    reference: ReferenceTrajectory,
    epoch_times_s: np.ndarray,
) -> list[LEGACY_EKF.DynamicTruthState]:
    truth_history: list[LEGACY_EKF.DynamicTruthState] = []
    for t_s in np.asarray(epoch_times_s, dtype=float):
        pos = _interp_vector_series(reference.t_s, reference.position_ecef_m, float(t_s))
        vel = _interp_vector_series(reference.t_s, reference.velocity_ecef_mps, float(t_s))
        clock_bias_m = scenario.receiver_clock_bias_m + scenario.receiver_clock_drift_mps * float(t_s)
        truth_history.append(
            LEGACY_EKF.DynamicTruthState(
                t_s=float(t_s),
                position_ecef_m=pos,
                velocity_ecef_mps=vel,
                clock_bias_m=float(clock_bias_m),
                clock_drift_mps=float(scenario.receiver_clock_drift_mps),
            )
        )
    return truth_history


def _run_epoch_wls_with_imu(
    epoch_batches: Sequence[LEGACY_EKF.EpochObservationBatch],
    legacy_metrics: LEGACY_EKF.LegacyEpochMetrics,
    receiver_cfg: LEGACY_WLS.ReceiverTruthConfig,
    mechanization: ImuMechanizationResult,
) -> list[LEGACY_EKF.EpochWlsResult]:
    results: list[LEGACY_EKF.EpochWlsResult] = []
    previous_state_m: np.ndarray | None = None
    for batch in epoch_batches:
        valid_observations = LEGACY_EKF._to_legacy_pseudorange_observations(batch, legacy_metrics)
        truth_adapter = LEGACY_EKF._truth_adapter_from_state(batch.truth, receiver_cfg)
        if len(valid_observations) < 4:
            results.append(
                LEGACY_EKF.EpochWlsResult(
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
            initial_state_m = build_truth_free_initial_state_from_observations(valid_observations)
        else:
            imu_position = _interp_vector_series(mechanization.t_s, mechanization.position_ecef_m, batch.t_s)
            initial_state_m = previous_state_m.copy()
            initial_state_m[:3] = imu_position
        solution = LEGACY_WLS.solve_pvt_iterative(valid_observations, truth_adapter, weighted=True, initial_state_m=initial_state_m)
        previous_state_m = solution.state_vector_m.copy()
        results.append(
            LEGACY_EKF.EpochWlsResult(
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


def _run_imu_ekf(
    epoch_batches: Sequence[LEGACY_EKF.EpochObservationBatch],
    wls_results: Sequence[LEGACY_EKF.EpochWlsResult],
    mechanization: ImuMechanizationResult,
    scenario: TrajectoryScenarioConfig,
) -> LEGACY_EKF.RunResult:
    init_idx = next((idx for idx, item in enumerate(wls_results) if item.valid), None)
    if init_idx is None:
        raise RuntimeError("No valid WLS epoch available for IMU-aided EKF initialization.")
    x_post = np.zeros(8, dtype=float)
    x_post[0:3] = wls_results[init_idx].state_vector_m[0:3]
    x_post[3:6] = _interp_vector_series(mechanization.t_s, mechanization.velocity_ecef_mps, epoch_batches[init_idx].t_s)
    x_post[6] = wls_results[init_idx].state_vector_m[3]
    x_post[7] = scenario.receiver_clock_drift_mps
    p_post = np.diag([250.0 ** 2, 250.0 ** 2, 250.0 ** 2, 40.0 ** 2, 40.0 ** 2, 40.0 ** 2, 80.0 ** 2, 8.0 ** 2]).astype(float)

    history: list[LEGACY_EKF.EkfEpochResult] = []
    previous_t_s: float | None = None
    for batch in epoch_batches:
        if batch.epoch_idx < init_idx:
            history.append(
                LEGACY_EKF.EkfEpochResult(
                    epoch_idx=batch.epoch_idx,
                    t_s=batch.t_s,
                    mode="ekf_pr_doppler",
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
                    warning="pre-init epoch",
                )
            )
            continue

        if previous_t_s is None:
            x_pred = x_post.copy()
            p_pred = p_post.copy()
        else:
            dt_s = float(batch.t_s - previous_t_s)
            ins_pos = _interp_vector_series(mechanization.t_s, mechanization.position_ecef_m, batch.t_s)
            ins_vel = _interp_vector_series(mechanization.t_s, mechanization.velocity_ecef_mps, batch.t_s)
            x_pred = x_post.copy()
            x_pred[0:3] = ins_pos
            x_pred[3:6] = ins_vel
            x_pred[6] = x_post[6] + x_post[7] * dt_s
            q_matrix = LEGACY_EKF.process_noise_matrix(dt_s, accel_sigma_mps2=0.08, clock_drift_sigma_mps2=0.20)
            p_pred = p_post + q_matrix
            p_pred[0:3, 0:3] += np.eye(3, dtype=float) * 80.0 ** 2
            p_pred[3:6, 3:6] += np.eye(3, dtype=float) * 12.0 ** 2

        h_matrix, z_vector, h_vector, r_matrix, residual_types, num_valid_sats = LEGACY_EKF.build_measurement_stack(
            batch,
            x_pred,
            "ekf_pr_doppler",
        )
        innovation = z_vector - h_vector if len(z_vector) else np.empty(0, dtype=float)
        prediction_only = num_valid_sats < 4 or h_matrix.size == 0
        warning = ""
        if prediction_only:
            x_post = x_pred
            p_post = p_pred
            warning = "prediction only: fewer than 4 valid satellites"
        else:
            s_matrix = h_matrix @ p_pred @ h_matrix.T + r_matrix
            k_matrix = p_pred @ h_matrix.T @ np.linalg.pinv(s_matrix)
            x_post = x_pred + k_matrix @ innovation
            joseph_left = np.eye(8, dtype=float) - k_matrix @ h_matrix
            p_post = joseph_left @ p_pred @ joseph_left.T + k_matrix @ r_matrix @ k_matrix.T

        pr_innov = [innovation[idx] for idx, tag in enumerate(residual_types) if tag == "pr"]
        rr_innov = [innovation[idx] for idx, tag in enumerate(residual_types) if tag == "rr"]
        truth = batch.truth
        history.append(
            LEGACY_EKF.EkfEpochResult(
                epoch_idx=batch.epoch_idx,
                t_s=batch.t_s,
                mode="ekf_pr_doppler",
                state_vector=x_post.copy(),
                covariance_diag=np.diag(p_post).copy(),
                num_valid_sats=num_valid_sats,
                innovation_rms_pr_m=LEGACY_EKF.rms(pr_innov),
                innovation_rms_rr_mps=LEGACY_EKF.rms(rr_innov),
                position_error_3d_m=float(np.linalg.norm(x_post[0:3] - truth.position_ecef_m)),
                velocity_error_3d_mps=float(np.linalg.norm(x_post[3:6] - truth.velocity_ecef_mps)),
                clock_bias_error_m=float(x_post[6] - truth.clock_bias_m),
                clock_drift_error_mps=float(x_post[7] - truth.clock_drift_mps),
                prediction_only=prediction_only,
                diverged=bool(np.any(~np.isfinite(np.diag(p_post)))),
                warning=warning,
            )
        )
        previous_t_s = batch.t_s
    return LEGACY_EKF.RunResult(mode="ekf_pr_doppler", history=tuple(history))


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
            row: list[Any] = []
            for arr in arrays:
                value = arr[idx]
                if np.ndim(value) == 0:
                    row.append(value)
                else:
                    row.extend(np.asarray(value).tolist())
            writer.writerow(row)


def _write_case_summary(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _compute_attitude_error_deg(reference: ReferenceTrajectory, mechanization: ImuMechanizationResult) -> np.ndarray:
    errors_deg = np.empty(len(reference.t_s), dtype=float)
    for idx in range(len(reference.t_s)):
        rot_err = reference.attitude_dcm_bn[idx].T @ mechanization.attitude_dcm_bn[idx]
        trace_val = np.clip((np.trace(rot_err) - 1.0) * 0.5, -1.0, 1.0)
        errors_deg[idx] = math.degrees(math.acos(trace_val))
    return errors_deg


def run_issue04_case(
    scenario: TrajectoryScenarioConfig,
    *,
    output_root: Path,
    imu_profile: ImuProfileConfig | None = None,
) -> dict[str, Any]:
    imu_cfg = imu_profile or ImuProfileConfig()
    receiver_cfg = _scenario_receiver_cfg(scenario)
    reference, measured_imu, mechanization, motion_profile, aiding_profile = mechanize_imu_profile(scenario, imu_cfg)

    single_run = run_textbook_single_channel_for_frequency(
        scenario.carrier_frequency_hz,
        truth_free_runtime=True,
        nav_data_enabled=True,
        motion_profile=motion_profile,
        aiding_profile=aiding_profile,
    )
    channel_background = build_textbook_channel_background(
        receiver_cfg,
        truth_free_runtime=True,
        nav_data_enabled=True,
        motion_profile=motion_profile,
        aiding_profile=aiding_profile,
    )

    exp_cfg = LEGACY_EKF.DynamicExperimentConfig(
        carrier_frequency_hz=scenario.carrier_frequency_hz,
        receiver_velocity_ecef_mps=tuple(float(v) for v in reference.velocity_ecef_mps[0]),
        receiver_clock_bias_m=scenario.receiver_clock_bias_m,
        receiver_clock_drift_mps=scenario.receiver_clock_drift_mps,
        process_accel_sigma_mps2=0.08,
        init_velocity_sigma_mps=25.0,
        rng_seed=int(round(scenario.carrier_frequency_hz / 1e6)) + int(round(scenario.height_km * 10.0)) + int(round(scenario.speed_kms * 100.0)),
    )
    epoch_times_s, legacy_metrics = LEGACY_EKF.build_nav_epoch_metrics(channel_background, receiver_cfg, exp_cfg)
    truth_history = _reference_to_truth_history(scenario, reference, epoch_times_s)
    satellite_templates = LEGACY_EKF.build_satellite_templates(receiver_cfg, exp_cfg)
    epoch_batches = LEGACY_EKF.build_dynamic_observation_batches(
        receiver_cfg,
        exp_cfg,
        channel_background,
        legacy_metrics,
        truth_history,
        satellite_templates,
    )
    wls_results = _run_epoch_wls_with_imu(epoch_batches, legacy_metrics, receiver_cfg, mechanization)
    ekf_result = _run_imu_ekf(epoch_batches, wls_results, mechanization, scenario)

    output_dir = output_root / scenario.label
    output_dir.mkdir(parents=True, exist_ok=True)
    LEGACY_EKF.write_dynamic_observations_csv(epoch_batches, output_dir / "dynamic_observations.csv")
    LEGACY_EKF.write_dynamic_state_history_csv(epoch_batches, wls_results, [ekf_result], output_dir / "dynamic_state_history.csv")
    _write_series_csv(
        output_dir / "imu_ins_state.csv",
        {
            "t_s": mechanization.t_s,
            "gyro_x_radps": measured_imu.gyro_body_radps[:, 0],
            "gyro_y_radps": measured_imu.gyro_body_radps[:, 1],
            "gyro_z_radps": measured_imu.gyro_body_radps[:, 2],
            "accel_x_mps2": measured_imu.accel_body_mps2[:, 0],
            "accel_y_mps2": measured_imu.accel_body_mps2[:, 1],
            "accel_z_mps2": measured_imu.accel_body_mps2[:, 2],
            "ins_pos_ecef_x_m": mechanization.position_ecef_m[:, 0],
            "ins_pos_ecef_y_m": mechanization.position_ecef_m[:, 1],
            "ins_pos_ecef_z_m": mechanization.position_ecef_m[:, 2],
            "ins_vel_ecef_x_mps": mechanization.velocity_ecef_mps[:, 0],
            "ins_vel_ecef_y_mps": mechanization.velocity_ecef_mps[:, 1],
            "ins_vel_ecef_z_mps": mechanization.velocity_ecef_mps[:, 2],
            "ins_quat_w": mechanization.attitude_quat_bn[:, 0],
            "ins_quat_x": mechanization.attitude_quat_bn[:, 1],
            "ins_quat_y": mechanization.attitude_quat_bn[:, 2],
            "ins_quat_z": mechanization.attitude_quat_bn[:, 3],
        },
    )

    ins_pos_err_m = np.linalg.norm(mechanization.position_ecef_m - reference.position_ecef_m, axis=1)
    ins_vel_err_mps = np.linalg.norm(mechanization.velocity_ecef_mps - reference.velocity_ecef_mps, axis=1)
    ins_att_err_deg = _compute_attitude_error_deg(reference, mechanization)
    valid_wls = [item.position_error_3d_m for item in wls_results if item.valid and math.isfinite(item.position_error_3d_m)]
    valid_ekf_pos = [item.position_error_3d_m for item in ekf_result.history if math.isfinite(item.position_error_3d_m)]
    valid_ekf_vel = [item.velocity_error_3d_mps for item in ekf_result.history if math.isfinite(item.velocity_error_3d_mps)]
    summary = {
        "scenario": {
            "label": scenario.label,
            "height_km": scenario.height_km,
            "speed_kms": scenario.speed_kms,
            "carrier_frequency_hz": scenario.carrier_frequency_hz,
            "duration_s": scenario.duration_s,
        },
        "imu_profile": {
            "imu_rate_hz": imu_cfg.imu_rate_hz,
            "gyro_bias_in_run_degph": imu_cfg.gyro_bias_in_run_degph,
            "gyro_arw_deg_rt_hr": imu_cfg.gyro_arw_deg_rt_hr,
            "accel_bias_in_run_mg": imu_cfg.accel_bias_in_run_mg,
            "accel_vrw_mps_rt_hr": imu_cfg.accel_vrw_mps_rt_hr,
        },
        "single_channel": {
            "tau_rmse_ns": float(single_run.metrics["tau_rmse_ns"]),
            "fd_rmse_hz": float(single_run.metrics["fd_rmse_hz"]),
            "effective_pseudorange_sigma_1s_m": float(single_run.metrics["effective_pseudorange_sigma_1s_m"]),
            "imu_code_aiding_rate_mean": float(np.mean(np.asarray(single_run.trk_result["imu_code_aiding_rate_chips_per_s"], dtype=float))),
            "imu_carrier_aiding_rate_mean": float(np.mean(np.asarray(single_run.trk_result["imu_carrier_aiding_rate_hz_per_s"], dtype=float))),
            "aiding_fraction": float(np.mean(np.asarray(single_run.trk_result["aiding_enabled"], dtype=float))),
            "motion_profile_source": motion_profile.source_note,
            "aiding_profile_source": aiding_profile.source_note,
        },
        "ins_diagnostics": {
            "ins_mean_position_error_3d_m": float(np.mean(ins_pos_err_m)),
            "ins_mean_velocity_error_3d_mps": float(np.mean(ins_vel_err_mps)),
            "ins_mean_attitude_error_deg": float(np.mean(ins_att_err_deg)),
            "ins_final_position_error_3d_m": float(ins_pos_err_m[-1]),
            "ins_final_velocity_error_3d_mps": float(ins_vel_err_mps[-1]),
            "ins_final_attitude_error_deg": float(ins_att_err_deg[-1]),
            "ins_aiding_truth_bypassed": True,
        },
        "dynamic_navigation": {
            "num_epochs": len(epoch_batches),
            "mean_wls_position_error_3d_m": float(np.mean(valid_wls)) if valid_wls else None,
            "mean_ekf_position_error_3d_m": float(np.mean(valid_ekf_pos)) if valid_ekf_pos else None,
            "mean_ekf_velocity_error_3d_mps": float(np.mean(valid_ekf_vel)) if valid_ekf_vel else None,
            "valid_wls_epochs": int(sum(item.valid for item in wls_results)),
            "prediction_only_epochs": int(sum(item.prediction_only for item in ekf_result.history)),
        },
        "outputs": {
            "dynamic_observations_csv": str((output_dir / "dynamic_observations.csv").resolve()),
            "dynamic_state_history_csv": str((output_dir / "dynamic_state_history.csv").resolve()),
            "imu_ins_state_csv": str((output_dir / "imu_ins_state.csv").resolve()),
        },
    }
    _write_case_summary(output_dir / "summary.json", summary)
    return summary


def write_issue04_aggregate(output_root: Path, case_rows: Sequence[dict[str, Any]]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "combined_metrics.json").write_text(json.dumps(list(case_rows), ensure_ascii=False, indent=2), encoding="utf-8")
    if not case_rows:
        return
    fieldnames = sorted({key for row in case_rows for key in row.keys()})
    with (output_root / "combined_metrics.csv").open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(case_rows)


__all__ = [
    "ISSUE04_ROOT",
    "ImuProfileConfig",
    "TrajectoryScenarioConfig",
    "ReferenceTrajectory",
    "ImuSampleSeries",
    "ImuMechanizationResult",
    "build_scenario_grid",
    "mechanize_imu_profile",
    "run_issue04_case",
    "write_issue04_aggregate",
]
