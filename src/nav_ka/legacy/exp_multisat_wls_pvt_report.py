# -*- coding: utf-8 -*-
"""
exp_multisat_wls_pvt_report.py
==============================

本文件不是替代单通道真实 WKB / 接收机脚本。
它在该脚本已经完成的“真实电子密度场 -> 真实 WKB -> 单通道捕获/跟踪 -> 单通道观测量”
基础上，补出“多星标准伪距观测 + 单历元 LS/WLS PVT”这一层。

关键原则
--------
1. 旧文件里已经有的真实链路部分尽量直接复用，不再人为降级成手写玩具模型。
2. 当前多星导航层是新增层，因此多星几何、标准伪距方程、LS/WLS 仍是新脚本负责。
3. 所有简化都必须在 summary.json 和 report_summary.md 里显式说明。

特别说明
--------
单通道 DLL 输出的 c * tau_est 是链路内部码时延恢复量，
不是导航层标准伪距本体。标准伪距必须放入统一观测方程：

    pseudorange_m =
        geometric_range_m
        + c * (receiver_clock_bias_s - satellite_clock_bias_s)
        + tropo_delay_m
        + dispersive_delay_m
        + hardware_bias_m
        + noise_m

本脚本的完成方式是：
1. 先调用旧脚本的真实 WKB + 单通道接收机链路，得到真实单通道背景。
2. 再把该真实背景映射到多星标准伪距形成。
3. 最后进行 LS / WLS PVT 与 Monte Carlo。

因此，本结果是“真实单通道 Ka/WKB 背景耦合下的 hybrid 多星导航层实验”，
不是“真实多星端到端 Ka 导航系统”。
"""

from __future__ import annotations

import csv
import json
import math
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from nav_ka import CANONICAL_RESULTS_ROOT
from nav_ka.legacy import ka_multifreq_receiver_common as LEGACY_DEBUG
from nav_ka.studies.issue_01_truth_dependency import build_truth_free_initial_state_from_observations
from nav_ka.studies.issue_03_textbook_correction import build_textbook_channel_background


# ============================================================
# 0. 路径与旧脚本加载
# ============================================================

ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = CANONICAL_RESULTS_ROOT / "results_multisat_wls"


def results_dir_for_frequency(fc_hz: float) -> Path:
    if math.isclose(fc_hz, 22.5e9, rel_tol=0.0, abs_tol=1.0):
        return CANONICAL_RESULTS_ROOT / "results_multisat_wls"
    label = f"{fc_hz / 1e9:.1f}".replace(".", "p")
    return CANONICAL_RESULTS_ROOT / f"results_multisat_wls_{label}GHz"
C_LIGHT = LEGACY_DEBUG.C_LIGHT

plt.rcParams["font.family"] = "serif"
plt.rcParams["xtick.direction"] = "in"
plt.rcParams["ytick.direction"] = "in"


@dataclass
class PlotConfig:
    enabled: bool
    save_dir: Path | None = None


def finalize_figure(fig: plt.Figure, plot_cfg: PlotConfig, stem: str) -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*tight_layout.*", category=UserWarning)
        fig.tight_layout()
    if plot_cfg.save_dir is not None:
        plot_cfg.save_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(plot_cfg.save_dir / f"{stem}.png", dpi=180, bbox_inches="tight")
    if plot_cfg.enabled:
        plt.show()
    else:
        plt.close(fig)


# ============================================================
# 1. 基础工具函数
# ============================================================

WGS84_A_M = 6_378_137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)


def db10(x: np.ndarray | float) -> np.ndarray | float:
    return 10.0 * np.log10(np.maximum(np.asarray(x), 1e-30))


def db20(x: np.ndarray | float) -> np.ndarray | float:
    return 20.0 * np.log10(np.maximum(np.asarray(x), 1e-30))


def rms(x: np.ndarray | float) -> float:
    arr = np.asarray(x, dtype=float)
    if arr.size == 0:
        return float("nan")
    return float(np.sqrt(np.mean(arr ** 2)))


def to_serializable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): to_serializable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_serializable(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, Path):
        return str(value)
    return value


def lla_to_ecef(latitude_deg: float, longitude_deg: float, height_m: float) -> np.ndarray:
    lat_rad = math.radians(latitude_deg)
    lon_rad = math.radians(longitude_deg)

    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    sin_lon = math.sin(lon_rad)
    cos_lon = math.cos(lon_rad)

    n_m = WGS84_A_M / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    x_m = (n_m + height_m) * cos_lat * cos_lon
    y_m = (n_m + height_m) * cos_lat * sin_lon
    z_m = (n_m * (1.0 - WGS84_E2) + height_m) * sin_lat
    return np.array([x_m, y_m, z_m], dtype=float)


def ecef_to_enu_rotation_matrix(latitude_deg: float, longitude_deg: float) -> np.ndarray:
    lat_rad = math.radians(latitude_deg)
    lon_rad = math.radians(longitude_deg)
    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    sin_lon = math.sin(lon_rad)
    cos_lon = math.cos(lon_rad)
    return np.array(
        [
            [-sin_lon, cos_lon, 0.0],
            [-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat],
            [cos_lat * cos_lon, cos_lat * sin_lon, sin_lat],
        ],
        dtype=float,
    )


def ecef_delta_to_enu(delta_ecef_m: np.ndarray, latitude_deg: float, longitude_deg: float) -> np.ndarray:
    return ecef_to_enu_rotation_matrix(latitude_deg, longitude_deg) @ np.asarray(delta_ecef_m, dtype=float)


def los_unit_vector_enu(azimuth_deg: float, elevation_deg: float) -> np.ndarray:
    az_rad = math.radians(azimuth_deg)
    el_rad = math.radians(elevation_deg)
    east = math.cos(el_rad) * math.sin(az_rad)
    north = math.cos(el_rad) * math.cos(az_rad)
    up = math.sin(el_rad)
    return np.array([east, north, up], dtype=float)


def satellite_position_from_local_geometry(
    receiver_ecef_m: np.ndarray,
    latitude_deg: float,
    longitude_deg: float,
    azimuth_deg: float,
    elevation_deg: float,
    sat_orbit_radius_m: float,
) -> tuple[np.ndarray, float]:
    rot_enu_to_ecef = ecef_to_enu_rotation_matrix(latitude_deg, longitude_deg).T
    los_ecef = rot_enu_to_ecef @ los_unit_vector_enu(azimuth_deg, elevation_deg)
    los_ecef = los_ecef / np.linalg.norm(los_ecef)
    receiver_radius_m = float(np.linalg.norm(receiver_ecef_m))
    dot_ru_m = float(np.dot(receiver_ecef_m, los_ecef))
    discriminant = dot_ru_m ** 2 + sat_orbit_radius_m ** 2 - receiver_radius_m ** 2
    if discriminant <= 0.0:
        raise ValueError("卫星半径设置导致几何无实数解。")
    geometric_range_m = -dot_ru_m + math.sqrt(discriminant)
    sat_pos_ecef_m = receiver_ecef_m + geometric_range_m * los_ecef
    return sat_pos_ecef_m, geometric_range_m


def block_average_sigma(x: np.ndarray, block_size: int) -> float:
    n_blocks = len(x) // block_size
    if n_blocks <= 1:
        return float(np.std(x, ddof=1))
    averaged = np.asarray(x[: n_blocks * block_size], dtype=float).reshape(n_blocks, block_size).mean(axis=1)
    return float(np.std(averaged, ddof=1))


# ============================================================
# 2. 数据结构
# ============================================================


@dataclass(frozen=True)
class ReceiverTruthConfig:
    latitude_deg: float = 34.0
    longitude_deg: float = 108.0
    height_m: float = 500.0
    receiver_clock_bias_m: float = 120.0
    carrier_frequency_hz: float = 22.5e9
    sat_orbit_radius_m: float = 26_560_000.0

    @property
    def receiver_ecef_m(self) -> np.ndarray:
        return lla_to_ecef(self.latitude_deg, self.longitude_deg, self.height_m)


@dataclass(frozen=True)
class ExperimentConfig:
    case_name: str
    description: str
    azimuth_deg_list: tuple[float, ...]
    elevation_deg_list: tuple[float, ...]
    single_epoch_noise_draws: tuple[float, ...]
    tropo_zenith_delay_m: float
    sigma_scale_factor: float
    low_elevation_threshold_deg: float
    low_elevation_sigma_boost_factor: float
    hardware_scale_factor: float
    dispersive_scale_factor: float


@dataclass
class LegacyChannelBackground:
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


@dataclass
class SatelliteScenario:
    sat_id: str
    azimuth_deg: float
    elevation_deg: float
    sat_pos_ecef_m: np.ndarray
    sat_clock_bias_s: float
    measurement_sigma_m: float


@dataclass
class PseudorangeObservation:
    sat_id: str
    azimuth_deg: float
    elevation_deg: float
    sat_pos_ecef_m: np.ndarray
    geometric_range_m: float
    receiver_clock_bias_m: float
    sat_clock_bias_s: float
    tropo_delay_m: float
    dispersive_delay_m: float
    hardware_bias_m: float
    noise_m: float
    pseudorange_m: float
    sigma_m: float
    legacy_tau_g_m: float
    legacy_tracking_sigma_reference_m: float
    legacy_source_used: str
    formation_note: str
    residual_ls_m: float = float("nan")
    residual_wls_m: float = float("nan")


@dataclass
class PvtSolution:
    method: str
    state_vector_m: np.ndarray
    receiver_clock_bias_s: float
    residuals_m: np.ndarray
    enu_error_m: np.ndarray
    position_error_3d_m: float
    converged: bool
    iterations: int
    residual_rms_m: float
    weighted_residual_rms_m: float
    design_matrix: np.ndarray


@dataclass
class ExperimentCaseResult:
    case_name: str
    description: str
    satellites: list[SatelliteScenario]
    observations: list[PseudorangeObservation]
    ls_solution: PvtSolution
    wls_solution: PvtSolution
    dops: dict[str, float]


@dataclass
class MonteCarloResult:
    num_runs: int
    based_on_case: str
    ls_position_error_3d_m: np.ndarray
    wls_position_error_3d_m: np.ndarray
    stats: dict[str, dict[str, float]]


# ============================================================
# 3. 旧脚本真实背景构造
# ============================================================


def find_legacy_input_files() -> tuple[Path, Path]:
    large_candidates = [
        ROOT / "Large_Scale_Ne_Smooth.csv",
        ROOT / "data" / "Large_Scale_Ne_Smooth.csv",
        ROOT / "notebooks" / "Large_Scale_Ne_Smooth.csv",
    ]
    aoa_candidates = [
        ROOT / "RAMC_AOA_Sim_Input.csv",
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


def build_legacy_channel_background(
    receiver_cfg: ReceiverTruthConfig,
    *,
    truth_free_runtime: bool = False,
) -> LegacyChannelBackground:
    print("\n[步骤 1] 复用共享真实单通道背景")
    large_csv, aoa_csv = find_legacy_input_files()
    print(f"  - large_csv = {large_csv}")
    print(f"  - aoa_csv   = {aoa_csv}")

    field_result = LEGACY_DEBUG.build_fields_from_csv(
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
    z_eval = field_result["z_eval"]
    ne_combined = field_result["ne_combined"]

    wkb_result = LEGACY_DEBUG.compute_real_wkb_series(
        t_eval=t_eval,
        z_eval=z_eval,
        ne_matrix=ne_combined,
        fc_hz=receiver_cfg.carrier_frequency_hz,
        nu_en_hz=1.0e9,
        delta_f_hz=5.0e6,
        verbose=True,
    )

    cfg_sig = LEGACY_DEBUG.build_signal_config_from_wkb_time(
        wkb_time_s=wkb_result["wkb_time_s"],
        fc_hz=receiver_cfg.carrier_frequency_hz,
        fs_hz=500e3,
        chip_rate_hz=50e3,
        coherent_integration_s=1e-3,
        code_length=127,
        cn0_dbhz=45.0,
        nav_data_enabled=False,
    )
    cfg_motion = LEGACY_DEBUG.MotionConfig(
        code_delay_chips_0=17.30,
        code_delay_rate_chips_per_s=0.20,
        doppler_hz_0=48e3,
        doppler_rate_hz_per_s=-1.8e3,
    )
    cfg_acq = LEGACY_DEBUG.AcquisitionConfig(
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
    cfg_trk = (
        LEGACY_DEBUG.build_truth_free_tracking_config()
        if truth_free_runtime
        else LEGACY_DEBUG.build_default_tracking_config()
    )

    rx_time_s = np.arange(cfg_sig.total_samples) / cfg_sig.fs_hz
    plasma_rx = LEGACY_DEBUG.resample_wkb_to_receiver_time(
        rx_time_s=rx_time_s,
        wkb_time_s=wkb_result["wkb_time_s"],
        A_t=wkb_result["A_t"],
        phi_t=wkb_result["phi_t"],
        tau_g_t=wkb_result["tau_g_t"],
    )
    code_chips = LEGACY_DEBUG.build_transmitter_signal_tools(cfg_sig)["code_chips"]
    receiver_context = LEGACY_DEBUG.ReceiverRuntimeContext(
        cfg_sig=cfg_sig,
        cfg_motion=cfg_motion,
        cfg_acq=cfg_acq,
        cfg_trk=cfg_trk,
        code_chips=code_chips,
        plasma_rx=plasma_rx,
        global_rx_time_s=rx_time_s,
    )

    np.random.seed(2026)
    receiver_outputs = LEGACY_DEBUG.KaBpskReceiver(receiver_context).run()
    trk_result = receiver_outputs.trk_result
    acq_diag = receiver_outputs.acq_diag
    trk_diag = receiver_outputs.trk_diag

    pseudorange_error_m = np.asarray(trk_result["pseudorange_m"] - C_LIGHT * trk_result["tau_true_s"], dtype=float)
    effective_sigma_100ms_m = block_average_sigma(pseudorange_error_m, 100)
    effective_sigma_1s_m = block_average_sigma(pseudorange_error_m, 1000)
    effective_rmse_m = float(np.sqrt(np.mean((pseudorange_error_m[: len(pseudorange_error_m) // 1000 * 1000].reshape(-1, 1000).mean(axis=1)) ** 2)))
    effective_bias_m = float(np.mean(pseudorange_error_m))
    tau_g_m = C_LIGHT * np.asarray(wkb_result["tau_g_t"], dtype=float)

    print("  - 已复用共享真实链路 = build_fields_from_csv / compute_real_wkb_series / build_signal_config_from_wkb_time / resample_wkb_to_receiver_time / KaBpskReceiver.run")
    print(f"  - 真实 tau_g 中位数 = {float(np.median(tau_g_m)):.4f} m")
    print(f"  - 真实 tau_g 跨度 = {float(np.max(tau_g_m) - np.min(tau_g_m)):.4f} m")
    print(f"  - 单通道伪距误差 100 ms 平滑 sigma = {effective_sigma_100ms_m:.3f} m")
    print(f"  - 单通道伪距误差 1 s 平滑 sigma = {effective_sigma_1s_m:.3f} m")

    return LegacyChannelBackground(
        large_csv=large_csv,
        aoa_csv=aoa_csv,
        wkb_result=wkb_result,
        trk_result=trk_result,
        acq_diag=acq_diag,
        trk_diag=trk_diag,
        effective_pseudorange_sigma_1s_m=effective_sigma_1s_m,
        effective_pseudorange_sigma_100ms_m=effective_sigma_100ms_m,
        effective_pseudorange_rmse_m=effective_rmse_m,
        effective_pseudorange_bias_m=effective_bias_m,
        tau_g_median_m=float(np.median(tau_g_m)),
        tau_g_span_m=float(np.max(tau_g_m) - np.min(tau_g_m)),
        reused_components=[
            "build_fields_from_csv",
            "compute_real_wkb_series",
            "build_signal_config_from_wkb_time",
            "resample_wkb_to_receiver_time",
            "KaBpskReceiver.run",
        ],
    )


def build_channel_background(
    receiver_cfg: ReceiverTruthConfig,
    *,
    truth_free_runtime: bool = False,
    channel_background_mode: str = "legacy",
) -> Any:
    if channel_background_mode == "legacy":
        return build_legacy_channel_background(receiver_cfg, truth_free_runtime=truth_free_runtime)
    if channel_background_mode == "issue03_textbook":
        return build_textbook_channel_background(
            receiver_cfg,
            truth_free_runtime=truth_free_runtime,
            nav_data_enabled=True,
        )
    raise ValueError(f"Unsupported channel background mode: {channel_background_mode}")


# ============================================================
# 4. 多星场景与标准伪距形成
# ============================================================


def build_experiment_configs() -> tuple[ExperimentConfig, ExperimentConfig]:
    config_a = ExperimentConfig(
        case_name="A",
        description="几何较好、噪声中等；验证在真实单通道背景映射下 LS/WLS 都能工作。",
        azimuth_deg_list=(12.0, 58.0, 103.0, 148.0, 202.0, 248.0, 302.0, 340.0),
        elevation_deg_list=(74.0, 66.0, 58.0, 50.0, 44.0, 37.0, 31.0, 27.0),
        single_epoch_noise_draws=(0.18, -0.15, 0.22, -0.18, 0.24, -0.16, 0.20, -0.14),
        tropo_zenith_delay_m=2.3,
        sigma_scale_factor=0.45,
        low_elevation_threshold_deg=0.0,
        low_elevation_sigma_boost_factor=0.0,
        hardware_scale_factor=1.0,
        dispersive_scale_factor=1.0,
    )
    config_b = ExperimentConfig(
        case_name="B",
        description="引入低仰角大误差；低仰角星更容易放大真实单通道背景映射出的测量不确定性。",
        azimuth_deg_list=(18.0, 63.0, 110.0, 155.0, 212.0, 258.0, 306.0, 346.0),
        elevation_deg_list=(75.0, 60.0, 46.0, 31.0, 19.0, 13.0, 9.0, 7.0),
        single_epoch_noise_draws=(0.12, -0.20, 0.35, -0.60, 0.95, 1.15, -1.60, 2.20),
        tropo_zenith_delay_m=2.6,
        sigma_scale_factor=0.55,
        low_elevation_threshold_deg=15.0,
        low_elevation_sigma_boost_factor=1.4,
        hardware_scale_factor=1.3,
        dispersive_scale_factor=1.4,
    )
    return config_a, config_b


def compute_tropo_delay_m(tropo_zenith_delay_m: float, elevation_deg: float) -> float:
    sin_el = max(math.sin(math.radians(elevation_deg)), 0.10)
    mapping = 1.001 / math.sqrt(0.002001 + sin_el ** 2)
    return tropo_zenith_delay_m * mapping


def compute_measurement_sigma_m(
    legacy_bg: LegacyChannelBackground,
    config: ExperimentConfig,
    elevation_deg: float,
) -> float:
    sin_el = max(math.sin(math.radians(elevation_deg)), 0.12)
    sigma_m = legacy_bg.effective_pseudorange_sigma_1s_m * config.sigma_scale_factor / (sin_el ** 0.70)
    if config.low_elevation_threshold_deg > 0.0 and elevation_deg < config.low_elevation_threshold_deg:
        scale = 1.0 - elevation_deg / config.low_elevation_threshold_deg
        sigma_m += legacy_bg.effective_pseudorange_sigma_1s_m * config.low_elevation_sigma_boost_factor * scale
    return float(sigma_m)


def build_multisat_scenario(
    receiver_cfg: ReceiverTruthConfig,
    legacy_bg: LegacyChannelBackground,
    config: ExperimentConfig,
) -> list[SatelliteScenario]:
    sat_clock_bias_ns_list = (28.0, -17.0, 13.0, -31.0, 22.0, -8.0, 36.0, -15.0)
    receiver_ecef_m = receiver_cfg.receiver_ecef_m
    satellites: list[SatelliteScenario] = []

    for idx, (azimuth_deg, elevation_deg) in enumerate(
        zip(config.azimuth_deg_list, config.elevation_deg_list, strict=True)
    ):
        sat_pos_ecef_m, _ = satellite_position_from_local_geometry(
            receiver_ecef_m=receiver_ecef_m,
            latitude_deg=receiver_cfg.latitude_deg,
            longitude_deg=receiver_cfg.longitude_deg,
            azimuth_deg=azimuth_deg,
            elevation_deg=elevation_deg,
            sat_orbit_radius_m=receiver_cfg.sat_orbit_radius_m,
        )
        sigma_m = compute_measurement_sigma_m(legacy_bg, config, elevation_deg)
        satellites.append(
            SatelliteScenario(
                sat_id=f"G{idx + 1:02d}",
                azimuth_deg=azimuth_deg,
                elevation_deg=elevation_deg,
                sat_pos_ecef_m=sat_pos_ecef_m,
                sat_clock_bias_s=sat_clock_bias_ns_list[idx] * 1e-9,
                measurement_sigma_m=sigma_m,
            )
        )
    return satellites


def build_pseudorange_observations_from_channel_outputs(
    legacy_bg: LegacyChannelBackground,
    receiver_cfg: ReceiverTruthConfig,
    config: ExperimentConfig,
    satellites: Sequence[SatelliteScenario],
    *,
    deterministic_noise: bool,
    rng: np.random.Generator,
) -> list[PseudorangeObservation]:
    base_hardware_bias_m = np.array([0.8, -0.6, 1.1, -0.9, 0.4, -0.7, 1.6, -1.3], dtype=float)
    observations: list[PseudorangeObservation] = []

    for idx, sat in enumerate(satellites):
        geometric_range_m = float(np.linalg.norm(sat.sat_pos_ecef_m - receiver_cfg.receiver_ecef_m))
        tropo_delay_m = compute_tropo_delay_m(config.tropo_zenith_delay_m, sat.elevation_deg)

        sin_el = max(math.sin(math.radians(sat.elevation_deg)), 0.10)
        dispersive_delay_m = legacy_bg.tau_g_median_m * config.dispersive_scale_factor / (sin_el ** 1.25)
        hardware_bias_m = config.hardware_scale_factor * float(base_hardware_bias_m[idx])

        if deterministic_noise:
            noise_m = sat.measurement_sigma_m * float(config.single_epoch_noise_draws[idx])
            formation_note = "single_epoch deterministic draw scaled by legacy 1 s sigma"
        else:
            noise_m = float(rng.normal(loc=0.0, scale=sat.measurement_sigma_m))
            formation_note = "monte_carlo random draw scaled by legacy 1 s sigma"

        pseudorange_m = (
            geometric_range_m
            + receiver_cfg.receiver_clock_bias_m
            - C_LIGHT * sat.sat_clock_bias_s
            + tropo_delay_m
            + dispersive_delay_m
            + hardware_bias_m
            + noise_m
        )

        observations.append(
            PseudorangeObservation(
                sat_id=sat.sat_id,
                azimuth_deg=sat.azimuth_deg,
                elevation_deg=sat.elevation_deg,
                sat_pos_ecef_m=sat.sat_pos_ecef_m.copy(),
                geometric_range_m=geometric_range_m,
                receiver_clock_bias_m=receiver_cfg.receiver_clock_bias_m,
                sat_clock_bias_s=sat.sat_clock_bias_s,
                tropo_delay_m=tropo_delay_m,
                dispersive_delay_m=dispersive_delay_m,
                hardware_bias_m=hardware_bias_m,
                noise_m=float(noise_m),
                pseudorange_m=float(pseudorange_m),
                sigma_m=sat.measurement_sigma_m,
                legacy_tau_g_m=dispersive_delay_m,
                legacy_tracking_sigma_reference_m=legacy_bg.effective_pseudorange_sigma_1s_m,
                legacy_source_used="tau_g median and tracking error statistics derived from ka_multifreq_receiver_common.py",
                formation_note=formation_note,
            )
        )

    return observations


# ============================================================
# 5. LS / WLS 单历元 PVT
# ============================================================


def solve_pvt_iterative(
    observations: Sequence[PseudorangeObservation],
    receiver_truth_cfg: ReceiverTruthConfig,
    *,
    weighted: bool,
    initial_state_m: np.ndarray | None = None,
    max_iterations: int = 10,
    tol_position_m: float = 1e-4,
    tol_clock_m: float = 1e-4,
) -> PvtSolution:
    if len(observations) < 4:
        raise ValueError("伪距观测数不足 4，无法求解单历元位置/钟差。")

    truth_ecef_m = receiver_truth_cfg.receiver_ecef_m
    if initial_state_m is None:
        initial_state_m = np.array(
            [
                truth_ecef_m[0] + 1_200.0,
                truth_ecef_m[1] - 900.0,
                truth_ecef_m[2] + 650.0,
                receiver_truth_cfg.receiver_clock_bias_m + 180.0,
            ],
            dtype=float,
        )

    state_m = np.asarray(initial_state_m, dtype=float).copy()
    sigma_m = np.array([obs.sigma_m for obs in observations], dtype=float)
    method_name = "WLS" if weighted else "LS"
    converged = False
    last_h = np.empty((0, 4), dtype=float)

    for iteration_idx in range(max_iterations):
        h_rows = []
        residual_vector_m = []

        for obs in observations:
            line_of_sight_m = obs.sat_pos_ecef_m - state_m[:3]
            geometric_range_m = float(np.linalg.norm(line_of_sight_m))
            los_unit = line_of_sight_m / geometric_range_m
            predicted_pseudorange_m = (
                geometric_range_m
                + state_m[3]
                - C_LIGHT * obs.sat_clock_bias_s
                + obs.tropo_delay_m
                + obs.dispersive_delay_m
                + obs.hardware_bias_m
            )
            residual_m = obs.pseudorange_m - predicted_pseudorange_m
            h_rows.append([-los_unit[0], -los_unit[1], -los_unit[2], 1.0])
            residual_vector_m.append(residual_m)

        h_matrix = np.asarray(h_rows, dtype=float)
        residual_vector_m = np.asarray(residual_vector_m, dtype=float)
        last_h = h_matrix

        if weighted:
            weight_matrix = np.diag(1.0 / np.maximum(sigma_m, 1e-6) ** 2)
            normal_matrix = h_matrix.T @ weight_matrix @ h_matrix
            rhs_vector = h_matrix.T @ weight_matrix @ residual_vector_m
        else:
            normal_matrix = h_matrix.T @ h_matrix
            rhs_vector = h_matrix.T @ residual_vector_m

        delta_state_m = np.linalg.solve(normal_matrix, rhs_vector)
        state_m += delta_state_m
        if np.linalg.norm(delta_state_m[:3]) < tol_position_m and abs(delta_state_m[3]) < tol_clock_m:
            converged = True
            break

    final_residuals_m = []
    for obs in observations:
        geometric_range_m = float(np.linalg.norm(obs.sat_pos_ecef_m - state_m[:3]))
        predicted_pseudorange_m = (
            geometric_range_m
            + state_m[3]
            - C_LIGHT * obs.sat_clock_bias_s
            + obs.tropo_delay_m
            + obs.dispersive_delay_m
            + obs.hardware_bias_m
        )
        final_residuals_m.append(obs.pseudorange_m - predicted_pseudorange_m)

    final_residuals_m = np.asarray(final_residuals_m, dtype=float)
    enu_error_m = ecef_delta_to_enu(
        state_m[:3] - truth_ecef_m,
        receiver_truth_cfg.latitude_deg,
        receiver_truth_cfg.longitude_deg,
    )
    weighted_residual_rms_m = float(np.sqrt(np.mean((final_residuals_m / np.maximum(sigma_m, 1e-6)) ** 2)))

    return PvtSolution(
        method=method_name,
        state_vector_m=state_m,
        receiver_clock_bias_s=float(state_m[3] / C_LIGHT),
        residuals_m=final_residuals_m,
        enu_error_m=enu_error_m,
        position_error_3d_m=float(np.linalg.norm(state_m[:3] - truth_ecef_m)),
        converged=converged,
        iterations=iteration_idx + 1,
        residual_rms_m=rms(final_residuals_m),
        weighted_residual_rms_m=weighted_residual_rms_m,
        design_matrix=last_h,
    )


def compute_dops(satellites: Sequence[SatelliteScenario], receiver_cfg: ReceiverTruthConfig) -> dict[str, float]:
    if len(satellites) < 4:
        raise ValueError("卫星数不足 4，无法计算 DOP。")

    receiver_ecef_m = receiver_cfg.receiver_ecef_m
    h_rows = []
    for sat in satellites:
        los_m = sat.sat_pos_ecef_m - receiver_ecef_m
        los_unit = los_m / np.linalg.norm(los_m)
        h_rows.append([-los_unit[0], -los_unit[1], -los_unit[2], 1.0])

    h_matrix = np.asarray(h_rows, dtype=float)
    q_xyzb = np.linalg.inv(h_matrix.T @ h_matrix)
    q_xyz = q_xyzb[:3, :3]
    rot = ecef_to_enu_rotation_matrix(receiver_cfg.latitude_deg, receiver_cfg.longitude_deg)
    q_enu = rot @ q_xyz @ rot.T
    return {
        "GDOP": math.sqrt(float(np.trace(q_xyzb))),
        "PDOP": math.sqrt(float(np.trace(q_xyz))),
        "HDOP": math.sqrt(float(max(q_enu[0, 0] + q_enu[1, 1], 0.0))),
        "VDOP": math.sqrt(float(max(q_enu[2, 2], 0.0))),
        "TDOP": math.sqrt(float(max(q_xyzb[3, 3], 0.0))),
    }


def attach_solution_residuals(
    observations: Sequence[PseudorangeObservation],
    ls_solution: PvtSolution,
    wls_solution: PvtSolution,
) -> list[PseudorangeObservation]:
    enriched: list[PseudorangeObservation] = []
    for obs, residual_ls_m, residual_wls_m in zip(observations, ls_solution.residuals_m, wls_solution.residuals_m, strict=True):
        enriched.append(
            PseudorangeObservation(
                sat_id=obs.sat_id,
                azimuth_deg=obs.azimuth_deg,
                elevation_deg=obs.elevation_deg,
                sat_pos_ecef_m=obs.sat_pos_ecef_m.copy(),
                geometric_range_m=obs.geometric_range_m,
                receiver_clock_bias_m=obs.receiver_clock_bias_m,
                sat_clock_bias_s=obs.sat_clock_bias_s,
                tropo_delay_m=obs.tropo_delay_m,
                dispersive_delay_m=obs.dispersive_delay_m,
                hardware_bias_m=obs.hardware_bias_m,
                noise_m=obs.noise_m,
                pseudorange_m=obs.pseudorange_m,
                sigma_m=obs.sigma_m,
                legacy_tau_g_m=obs.legacy_tau_g_m,
                legacy_tracking_sigma_reference_m=obs.legacy_tracking_sigma_reference_m,
                legacy_source_used=obs.legacy_source_used,
                formation_note=obs.formation_note,
                residual_ls_m=float(residual_ls_m),
                residual_wls_m=float(residual_wls_m),
            )
        )
    return enriched


# ============================================================
# 6. 实验编排
# ============================================================


def run_experiment_case(
    receiver_cfg: ReceiverTruthConfig,
    legacy_bg: LegacyChannelBackground,
    config: ExperimentConfig,
    rng: np.random.Generator,
    *,
    truth_free_initialization: bool = False,
) -> ExperimentCaseResult:
    satellites = build_multisat_scenario(receiver_cfg, legacy_bg, config)
    observations = build_pseudorange_observations_from_channel_outputs(
        legacy_bg,
        receiver_cfg,
        config,
        satellites,
        deterministic_noise=True,
        rng=rng,
    )

    if truth_free_initialization:
        initial_state_m = build_truth_free_initial_state_from_observations(observations)
    else:
        initial_state_m = np.array(
            [
                receiver_cfg.receiver_ecef_m[0] + 1_200.0,
                receiver_cfg.receiver_ecef_m[1] - 900.0,
                receiver_cfg.receiver_ecef_m[2] + 650.0,
                receiver_cfg.receiver_clock_bias_m + 180.0,
            ],
            dtype=float,
        )
    ls_solution = solve_pvt_iterative(observations, receiver_cfg, weighted=False, initial_state_m=initial_state_m)
    wls_solution = solve_pvt_iterative(observations, receiver_cfg, weighted=True, initial_state_m=initial_state_m)
    observations = attach_solution_residuals(observations, ls_solution, wls_solution)
    dops = compute_dops(satellites, receiver_cfg)

    return ExperimentCaseResult(
        case_name=config.case_name,
        description=config.description,
        satellites=satellites,
        observations=observations,
        ls_solution=ls_solution,
        wls_solution=wls_solution,
        dops=dops,
    )


def summarize_position_errors(position_error_m: np.ndarray) -> dict[str, float]:
    return {
        "mean_m": float(np.mean(position_error_m)),
        "std_m": float(np.std(position_error_m, ddof=1)),
        "p90_m": float(np.percentile(position_error_m, 90.0)),
    }


def run_monte_carlo(
    receiver_cfg: ReceiverTruthConfig,
    legacy_bg: LegacyChannelBackground,
    config: ExperimentConfig,
    *,
    num_runs: int,
    rng_seed: int,
    truth_free_initialization: bool = False,
) -> MonteCarloResult:
    satellites = build_multisat_scenario(receiver_cfg, legacy_bg, config)
    ls_errors_m = []
    wls_errors_m = []

    for run_idx in range(num_runs):
        rng = np.random.default_rng(rng_seed + run_idx)
        observations = build_pseudorange_observations_from_channel_outputs(
            legacy_bg,
            receiver_cfg,
            config,
            satellites,
            deterministic_noise=False,
            rng=rng,
        )
        if truth_free_initialization:
            initial_state_m = build_truth_free_initial_state_from_observations(observations)
        else:
            initial_state_m = np.array(
                [
                    receiver_cfg.receiver_ecef_m[0] + 1_200.0,
                    receiver_cfg.receiver_ecef_m[1] - 900.0,
                    receiver_cfg.receiver_ecef_m[2] + 650.0,
                    receiver_cfg.receiver_clock_bias_m + 180.0,
                ],
                dtype=float,
            )
        ls_errors_m.append(
            solve_pvt_iterative(observations, receiver_cfg, weighted=False, initial_state_m=initial_state_m).position_error_3d_m
        )
        wls_errors_m.append(
            solve_pvt_iterative(observations, receiver_cfg, weighted=True, initial_state_m=initial_state_m).position_error_3d_m
        )

    ls_errors_m = np.asarray(ls_errors_m, dtype=float)
    wls_errors_m = np.asarray(wls_errors_m, dtype=float)
    return MonteCarloResult(
        num_runs=num_runs,
        based_on_case=config.case_name,
        ls_position_error_3d_m=ls_errors_m,
        wls_position_error_3d_m=wls_errors_m,
        stats={
            "LS": summarize_position_errors(ls_errors_m),
            "WLS": summarize_position_errors(wls_errors_m),
        },
    )


# ============================================================
# 7. 绘图
# ============================================================


def sort_observations_by_elevation(observations: Sequence[PseudorangeObservation]) -> list[PseudorangeObservation]:
    return sorted(observations, key=lambda item: item.elevation_deg, reverse=True)


def plot_sky_geometry(case_results: Sequence[ExperimentCaseResult], plot_cfg: PlotConfig) -> None:
    fig, axes = plt.subplots(1, len(case_results), subplot_kw={"projection": "polar"}, figsize=(14, 6), dpi=140)
    if len(case_results) == 1:
        axes = [axes]

    for ax, case_result in zip(axes, case_results, strict=True):
        theta_rad = np.deg2rad([sat.azimuth_deg for sat in case_result.satellites])
        radius_deg = 90.0 - np.array([sat.elevation_deg for sat in case_result.satellites], dtype=float)
        colors = np.array([sat.measurement_sigma_m for sat in case_result.satellites], dtype=float)
        scatter = ax.scatter(theta_rad, radius_deg, c=colors, s=110, cmap="viridis", edgecolors="black", linewidths=0.6)
        for sat, theta, radius in zip(case_result.satellites, theta_rad, radius_deg, strict=True):
            text_radius = min(radius + 4.5, 88.0)
            ax.annotate(
                sat.sat_id,
                xy=(theta, radius),
                xytext=(theta, text_radius),
                fontsize=9,
                ha="center",
                va="center",
                arrowprops=dict(arrowstyle="-", lw=0.5, color="0.35"),
            )
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        ax.set_rlim(90.0, 0.0)
        ax.set_rticks([10, 25, 40, 55, 70, 85])
        ax.set_yticklabels(["80°", "65°", "50°", "35°", "20°", "5°"])
        ax.tick_params(labelsize=9)
        ax.set_title(f"Case {case_result.case_name}\nPDOP={case_result.dops['PDOP']:.2f}", pad=22)
        ax.grid(True, ls=":", alpha=0.5)

    cbar = fig.colorbar(scatter, ax=axes, pad=0.10, fraction=0.04)
    cbar.set_label("Sigma (m)")
    cbar.ax.tick_params(labelsize=9)
    fig.suptitle("Sky geometry and observation sigma", y=0.98, fontsize=13)
    finalize_figure(fig, plot_cfg, "sky_geometry")


def plot_geometry_3d(
    receiver_cfg: ReceiverTruthConfig,
    case_results: Sequence[ExperimentCaseResult],
    plot_cfg: PlotConfig,
) -> None:
    fig = plt.figure(figsize=(13, 6), dpi=140)
    for idx, case_result in enumerate(case_results, start=1):
        ax = fig.add_subplot(1, len(case_results), idx, projection="3d")
        receiver = receiver_cfg.receiver_ecef_m / 1e6
        ax.scatter([receiver[0]], [receiver[1]], [receiver[2]], s=90, c="black", label="Receiver")

        for sat in case_result.satellites:
            sat_xyz = sat.sat_pos_ecef_m / 1e6
            ax.scatter([sat_xyz[0]], [sat_xyz[1]], [sat_xyz[2]], s=60, label=sat.sat_id)
            ax.plot([receiver[0], sat_xyz[0]], [receiver[1], sat_xyz[1]], [receiver[2], sat_xyz[2]], lw=0.9, alpha=0.65)

        ax.set_title(f"Case {case_result.case_name} 3D geometry")
        ax.set_xlabel("X (Mm)")
        ax.set_ylabel("Y (Mm)")
        ax.set_zlabel("Z (Mm)")
        ax.grid(True)

    finalize_figure(fig, plot_cfg, "geometry_3d")


def plot_legacy_channel_overview(legacy_bg: LegacyChannelBackground, plot_cfg: PlotConfig) -> None:
    wkb_result = legacy_bg.wkb_result
    trk_result = legacy_bg.trk_result
    pseudorange_truth_m = C_LIGHT * np.asarray(trk_result["tau_true_s"], dtype=float)
    pseudorange_est_m = np.asarray(trk_result["pseudorange_m"], dtype=float)
    pseudorange_error_m = pseudorange_est_m - pseudorange_truth_m

    fig, axes = plt.subplots(3, 2, figsize=(14, 12), dpi=140)
    ax = axes.ravel()

    ax[0].plot(wkb_result["wkb_time_s"], db20(wkb_result["A_t"]), lw=1.2)
    ax[0].set_title("Legacy WKB amplitude")
    ax[0].set_xlabel("Time (s)")
    ax[0].set_ylabel("Amplitude (dB)")
    ax[0].grid(True, ls=":", alpha=0.5)

    ax[1].plot(wkb_result["wkb_time_s"], wkb_result["phi_t"], lw=1.2, color="tab:purple")
    ax[1].set_title("Legacy WKB phase")
    ax[1].set_xlabel("Time (s)")
    ax[1].set_ylabel("Phase (rad)")
    ax[1].grid(True, ls=":", alpha=0.5)

    ax[2].plot(wkb_result["wkb_time_s"], C_LIGHT * np.asarray(wkb_result["tau_g_t"]) * 1e2, lw=1.2, color="tab:green")
    ax[2].set_title("Legacy group delay")
    ax[2].set_xlabel("Time (s)")
    ax[2].set_ylabel("Delay (cm)")
    ax[2].grid(True, ls=":", alpha=0.5)

    ax[3].plot(trk_result["t"], pseudorange_error_m, lw=1.0, color="tab:red")
    ax[3].axhline(0.0, color="black", lw=1.0)
    ax[3].set_title("Legacy single-channel pseudorange error")
    ax[3].set_xlabel("Time (s)")
    ax[3].set_ylabel("Error (m)")
    ax[3].grid(True, ls=":", alpha=0.5)

    ax[4].plot(trk_result["t"], trk_result["post_corr_snr_db"], lw=1.1, label="Measured")
    ax[4].plot(trk_result["t"], trk_result["predicted_post_corr_snr_db"], lw=1.0, label="Predicted")
    ax[4].set_title("Legacy post-correlation SNR")
    ax[4].set_xlabel("Time (s)")
    ax[4].set_ylabel("SNR (dB)")
    ax[4].legend()
    ax[4].grid(True, ls=":", alpha=0.5)

    ax[5].plot(trk_result["t"], trk_result["pseudorange_m"], lw=1.0, label="Estimate")
    ax[5].plot(trk_result["t"], pseudorange_truth_m, lw=1.0, ls="--", color="black", label="Truth")
    ax[5].set_title("Legacy single-channel pseudorange")
    ax[5].set_xlabel("Time (s)")
    ax[5].set_ylabel("Range (m)")
    ax[5].legend()
    ax[5].grid(True, ls=":", alpha=0.5)

    finalize_figure(fig, plot_cfg, "legacy_channel_overview")


def plot_pseudorange_formation(case_results: Sequence[ExperimentCaseResult], plot_cfg: PlotConfig) -> None:
    fig, axes = plt.subplots(len(case_results), 1, figsize=(14, 4.8 * len(case_results)), dpi=140, squeeze=False)

    for ax, case_result in zip(axes.ravel(), case_results, strict=True):
        observations = sort_observations_by_elevation(case_result.observations)
        sat_ids = [obs.sat_id for obs in observations]
        x_index = np.arange(len(observations))
        bar_width = 0.17

        tropo = np.array([obs.tropo_delay_m for obs in observations], dtype=float)
        dispersive = np.array([obs.dispersive_delay_m for obs in observations], dtype=float)
        hardware = np.array([obs.hardware_bias_m for obs in observations], dtype=float)
        noise = np.array([obs.noise_m for obs in observations], dtype=float)
        sigma = np.array([obs.sigma_m for obs in observations], dtype=float)

        ax.bar(x_index - 1.5 * bar_width, tropo, width=bar_width, label="Troposphere", color="#4C78A8")
        ax.bar(x_index - 0.5 * bar_width, dispersive, width=bar_width, label="Legacy dispersive", color="#F58518")
        ax.bar(x_index + 0.5 * bar_width, hardware, width=bar_width, label="Hardware", color="#54A24B")
        ax.bar(x_index + 1.5 * bar_width, noise, width=bar_width, label="Noise", color="#E45756")
        ax.plot(x_index, sigma, color="black", marker="o", lw=1.2, label="Sigma")

        ax.set_xticks(x_index)
        ax.set_xticklabels([f"{sat_id}\n{obs.elevation_deg:.0f}°" for sat_id, obs in zip(sat_ids, observations, strict=True)])
        ax.set_ylabel("Meters")
        ax.set_title(f"Case {case_result.case_name} pseudorange formation (non-geometric terms)")
        ax.grid(True, axis="y", ls=":", alpha=0.5)
        ax.legend(ncol=5, fontsize=9)

    finalize_figure(fig, plot_cfg, "pseudorange_formation")


def plot_ls_vs_wls_residuals(case_results: Sequence[ExperimentCaseResult], plot_cfg: PlotConfig) -> None:
    fig, axes = plt.subplots(len(case_results), 1, figsize=(14, 4.8 * len(case_results)), dpi=140, squeeze=False)

    for ax, case_result in zip(axes.ravel(), case_results, strict=True):
        observations = sort_observations_by_elevation(case_result.observations)
        sat_ids = [obs.sat_id for obs in observations]
        x_index = np.arange(len(observations))
        bar_width = 0.36

        residual_ls_m = np.array([obs.residual_ls_m for obs in observations], dtype=float)
        residual_wls_m = np.array([obs.residual_wls_m for obs in observations], dtype=float)

        ax.bar(x_index - 0.5 * bar_width, residual_ls_m, width=bar_width, color="#E45756", label="LS")
        ax.bar(x_index + 0.5 * bar_width, residual_wls_m, width=bar_width, color="#4C78A8", label="WLS")
        ax.axhline(0.0, color="black", lw=1.0)
        ax.set_xticks(x_index)
        ax.set_xticklabels([f"{sat_id}\n{obs.elevation_deg:.0f}°" for sat_id, obs in zip(sat_ids, observations, strict=True)])
        ax.set_ylabel("Residual (m)")
        ax.set_title(
            f"Case {case_result.case_name} residuals | "
            f"LS 3D={case_result.ls_solution.position_error_3d_m:.1f} m, "
            f"WLS 3D={case_result.wls_solution.position_error_3d_m:.1f} m"
        )
        ax.grid(True, axis="y", ls=":", alpha=0.5)
        ax.legend()

    finalize_figure(fig, plot_cfg, "ls_vs_wls_residuals")


def plot_monte_carlo_position_error(monte_carlo_result: MonteCarloResult, plot_cfg: PlotConfig) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), dpi=140)
    bins = np.linspace(
        0.0,
        max(float(np.max(monte_carlo_result.ls_position_error_3d_m)), float(np.max(monte_carlo_result.wls_position_error_3d_m))) * 1.05,
        24,
    )

    axes[0].hist(monte_carlo_result.ls_position_error_3d_m, bins=bins, density=True, alpha=0.55, color="#E45756", label="LS")
    axes[0].hist(monte_carlo_result.wls_position_error_3d_m, bins=bins, density=True, alpha=0.55, color="#4C78A8", label="WLS")
    axes[0].set_title("Monte Carlo 3D position error")
    axes[0].set_xlabel("Error (m)")
    axes[0].set_ylabel("Density")
    axes[0].legend()
    axes[0].grid(True, ls=":", alpha=0.5)

    for values, color, label in (
        (monte_carlo_result.ls_position_error_3d_m, "#E45756", "LS"),
        (monte_carlo_result.wls_position_error_3d_m, "#4C78A8", "WLS"),
    ):
        x = np.sort(values)
        y = np.arange(1, len(x) + 1, dtype=float) / len(x)
        axes[1].plot(x, y, lw=2.0, color=color, label=label)
    axes[1].axhline(0.90, color="black", ls="--", lw=1.0)
    axes[1].set_title("Monte Carlo CDF")
    axes[1].set_xlabel("Error (m)")
    axes[1].set_ylabel("CDF")
    axes[1].legend()
    axes[1].grid(True, ls=":", alpha=0.5)

    stats_text = (
        f"LS mean={monte_carlo_result.stats['LS']['mean_m']:.1f} m, p90={monte_carlo_result.stats['LS']['p90_m']:.1f} m\n"
        f"WLS mean={monte_carlo_result.stats['WLS']['mean_m']:.1f} m, p90={monte_carlo_result.stats['WLS']['p90_m']:.1f} m"
    )
    axes[1].text(
        0.03,
        0.03,
        stats_text,
        transform=axes[1].transAxes,
        fontsize=9,
        bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "0.7"},
    )

    finalize_figure(fig, plot_cfg, "monte_carlo_position_error")


def plot_dop_summary(case_results: Sequence[ExperimentCaseResult], plot_cfg: PlotConfig) -> None:
    fig, ax = plt.subplots(figsize=(11, 5), dpi=140)
    dop_names = ["GDOP", "PDOP", "HDOP", "VDOP", "TDOP"]
    x_index = np.arange(len(dop_names))
    bar_width = 0.36

    for case_offset, case_result in enumerate(case_results):
        values = np.array([case_result.dops[name] for name in dop_names], dtype=float)
        offset = (-0.5 + case_offset) * bar_width
        ax.bar(x_index + offset, values, width=bar_width, label=f"Case {case_result.case_name}", alpha=0.85)

    ax.set_xticks(x_index)
    ax.set_xticklabels(dop_names)
    ax.set_ylabel("DOP")
    ax.set_title("DOP summary")
    ax.legend()
    ax.grid(True, axis="y", ls=":", alpha=0.5)
    finalize_figure(fig, plot_cfg, "dop_summary")


# ============================================================
# 8. 结果导出
# ============================================================


def write_satellite_observations_csv(case_results: Sequence[ExperimentCaseResult], output_path: Path) -> None:
    fieldnames = [
        "case_name",
        "sat_id",
        "azimuth_deg",
        "elevation_deg",
        "geometric_range_m",
        "sat_clock_bias_s",
        "tropo_delay_m",
        "dispersive_delay_m",
        "hardware_bias_m",
        "noise_m",
        "pseudorange_m",
        "sigma_m",
        "legacy_tau_g_m",
        "legacy_tracking_sigma_reference_m",
        "legacy_source_used",
        "formation_note",
        "residual_ls_m",
        "residual_wls_m",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for case_result in case_results:
            for obs in sort_observations_by_elevation(case_result.observations):
                writer.writerow(
                    {
                        "case_name": case_result.case_name,
                        "sat_id": obs.sat_id,
                        "azimuth_deg": f"{obs.azimuth_deg:.3f}",
                        "elevation_deg": f"{obs.elevation_deg:.3f}",
                        "geometric_range_m": f"{obs.geometric_range_m:.6f}",
                        "sat_clock_bias_s": f"{obs.sat_clock_bias_s:.12e}",
                        "tropo_delay_m": f"{obs.tropo_delay_m:.6f}",
                        "dispersive_delay_m": f"{obs.dispersive_delay_m:.6f}",
                        "hardware_bias_m": f"{obs.hardware_bias_m:.6f}",
                        "noise_m": f"{obs.noise_m:.6f}",
                        "pseudorange_m": f"{obs.pseudorange_m:.6f}",
                        "sigma_m": f"{obs.sigma_m:.6f}",
                        "legacy_tau_g_m": f"{obs.legacy_tau_g_m:.6f}",
                        "legacy_tracking_sigma_reference_m": f"{obs.legacy_tracking_sigma_reference_m:.6f}",
                        "legacy_source_used": obs.legacy_source_used,
                        "formation_note": obs.formation_note,
                        "residual_ls_m": f"{obs.residual_ls_m:.6f}",
                        "residual_wls_m": f"{obs.residual_wls_m:.6f}",
                    }
                )


def build_case_summary_dict(case_result: ExperimentCaseResult) -> dict[str, Any]:
    ls_enu = case_result.ls_solution.enu_error_m
    wls_enu = case_result.wls_solution.enu_error_m
    return {
        "case_name": case_result.case_name,
        "description": case_result.description,
        "num_satellites": len(case_result.satellites),
        "dops": case_result.dops,
        "ls": {
            "converged": case_result.ls_solution.converged,
            "iterations": case_result.ls_solution.iterations,
            "position_ecef_m": case_result.ls_solution.state_vector_m[:3],
            "clock_bias_m": case_result.ls_solution.state_vector_m[3],
            "clock_bias_s": case_result.ls_solution.receiver_clock_bias_s,
            "enu_error_m": {"east": ls_enu[0], "north": ls_enu[1], "up": ls_enu[2]},
            "position_error_3d_m": case_result.ls_solution.position_error_3d_m,
            "residual_rms_m": case_result.ls_solution.residual_rms_m,
        },
        "wls": {
            "converged": case_result.wls_solution.converged,
            "iterations": case_result.wls_solution.iterations,
            "position_ecef_m": case_result.wls_solution.state_vector_m[:3],
            "clock_bias_m": case_result.wls_solution.state_vector_m[3],
            "clock_bias_s": case_result.wls_solution.receiver_clock_bias_s,
            "enu_error_m": {"east": wls_enu[0], "north": wls_enu[1], "up": wls_enu[2]},
            "position_error_3d_m": case_result.wls_solution.position_error_3d_m,
            "weighted_residual_rms_m": case_result.wls_solution.weighted_residual_rms_m,
        },
    }


def write_summary_json(
    receiver_cfg: ReceiverTruthConfig,
    legacy_bg: LegacyChannelBackground,
    case_results: Sequence[ExperimentCaseResult],
    monte_carlo_result: MonteCarloResult,
    output_path: Path,
) -> None:
    summary = {
        "receiver_truth": {
            "latitude_deg": receiver_cfg.latitude_deg,
            "longitude_deg": receiver_cfg.longitude_deg,
            "height_m": receiver_cfg.height_m,
            "receiver_clock_bias_m": receiver_cfg.receiver_clock_bias_m,
            "carrier_frequency_hz": receiver_cfg.carrier_frequency_hz,
        },
        "legacy_coupling_level": "real WKB and single-channel receiver reused; multisat geometry and navigation solution added here",
        "real_reused_components": legacy_bg.reused_components,
        "simplified_components": [
            "多星几何使用静态自洽 az/el 场景，不是真实星历。",
            "所有卫星共享同一真实单通道 WKB/接收机背景，再按仰角映射到多星伪距形成。",
            "对流层、卫星钟差、硬件偏差使用参数化项。",
            "多星伪距方差由旧脚本单通道伪距误差统计映射得到，不是真实多星同步跟踪输出。",
        ],
        "claim_boundary": "本结果代表真实单通道 Ka/WKB 背景耦合下的 hybrid 多星标准伪距/WLS 实验，不代表真实多星端到端 Ka 导航系统。",
        "legacy_channel_metrics": {
            "effective_pseudorange_sigma_100ms_m": legacy_bg.effective_pseudorange_sigma_100ms_m,
            "effective_pseudorange_sigma_1s_m": legacy_bg.effective_pseudorange_sigma_1s_m,
            "effective_pseudorange_rmse_m": legacy_bg.effective_pseudorange_rmse_m,
            "effective_pseudorange_bias_m": legacy_bg.effective_pseudorange_bias_m,
            "tau_g_median_m": legacy_bg.tau_g_median_m,
            "tau_g_span_m": legacy_bg.tau_g_span_m,
        },
        "experiments": {case_result.case_name: build_case_summary_dict(case_result) for case_result in case_results},
        "monte_carlo": {
            "based_on_case": monte_carlo_result.based_on_case,
            "num_runs": monte_carlo_result.num_runs,
            "stats": monte_carlo_result.stats,
        },
        "output_files": {
            "results_dir": RESULTS_DIR,
            "sky_geometry_png": RESULTS_DIR / "sky_geometry.png",
            "geometry_3d_png": RESULTS_DIR / "geometry_3d.png",
            "legacy_channel_overview_png": RESULTS_DIR / "legacy_channel_overview.png",
            "pseudorange_formation_png": RESULTS_DIR / "pseudorange_formation.png",
            "ls_vs_wls_residuals_png": RESULTS_DIR / "ls_vs_wls_residuals.png",
            "monte_carlo_position_error_png": RESULTS_DIR / "monte_carlo_position_error.png",
            "dop_summary_png": RESULTS_DIR / "dop_summary.png",
            "satellite_observations_csv": RESULTS_DIR / "satellite_observations.csv",
            "summary_json": RESULTS_DIR / "summary.json",
            "report_summary_md": RESULTS_DIR / "report_summary.md",
        },
    }
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(to_serializable(summary), f, ensure_ascii=False, indent=2)


def write_report_summary_md(
    receiver_cfg: ReceiverTruthConfig,
    legacy_bg: LegacyChannelBackground,
    case_results: Sequence[ExperimentCaseResult],
    monte_carlo_result: MonteCarloResult,
    output_path: Path,
) -> None:
    case_a = next(case_result for case_result in case_results if case_result.case_name == "A")
    case_b = next(case_result for case_result in case_results if case_result.case_name == "B")
    text = f"""# 多星标准伪距 + WLS 单历元 PVT 汇报摘要

## 本次完成的改进

本次不是另起炉灶写一个纯导航层玩具，而是在 `ka_multifreq_receiver_common.py`
已有“真实电子密度场 -> 真实 WKB -> 单通道接收机链路”的基础上，
补出了“多星标准伪距观测 + 单历元 LS/WLS PVT”这一层。

## 这次到底用到了旧文件里的什么

本次直接复用了旧文件中的真实链路部分：

1. `build_fields_from_csv`
2. `compute_real_wkb_series`
3. `build_signal_config_from_wkb_time`
4. `resample_wkb_to_receiver_time`
5. `KaBpskReceiver.run`

因此，本次报告中的 `legacy_channel_overview.png` 里展示的 `A(t)`、`phi(t)`、`tau_g(t)`、
以及单通道 `pseudorange` / SNR 背景，来自旧文件真实链路，而不是新脚本重新手写的简化替代。

## 为什么现在的导航层结果不该直接理解成“真实多星端到端指标”

虽然旧文件里的真实单通道 Ka/WKB 背景已经接入，但多星部分仍然是新增的导航层构造：

1. 卫星几何仍是静态自洽 az/el 场景，不是真实星历
2. 所有卫星共享同一真实单通道传播背景，再按视线条件映射
3. 对流层、硬件偏差、卫星钟差仍是参数化项
4. 多星伪距方差来自旧文件单通道观测误差统计映射，而不是真实多星同步跟踪输出

所以，本次结果代表的是：

**真实单通道 Ka/WKB 背景耦合下的 hybrid 多星标准伪距/WLS 实验**

而不是：

**真实多星端到端 Ka 导航系统性能定标**

## 旧文件真实背景给出的关键量级

- 真实 `tau_g` 中位数：{legacy_bg.tau_g_median_m:.4f} m
- 真实 `tau_g` 跨度：{legacy_bg.tau_g_span_m:.4f} m
- 单通道伪距误差 100 ms 平滑 sigma：{legacy_bg.effective_pseudorange_sigma_100ms_m:.3f} m
- 单通道伪距误差 1 s 平滑 sigma：{legacy_bg.effective_pseudorange_sigma_1s_m:.3f} m
- 单通道伪距误差 1 s 平滑 RMSE：{legacy_bg.effective_pseudorange_rmse_m:.3f} m

这说明当前 Ka/WKB 背景下，色散传播项本身是存在的，但单通道码跟踪误差的量级并不小。
因此，如果多星导航层给出特别理想的个位数米结果，就必须谨慎解释，不应直接当成真实系统结论。

## LS 与 WLS 结果

实验 A：

- LS 3D 位置误差：{case_a.ls_solution.position_error_3d_m:.3f} m
- WLS 3D 位置误差：{case_a.wls_solution.position_error_3d_m:.3f} m
- PDOP：{case_a.dops['PDOP']:.3f}

实验 B：

- LS 3D 位置误差：{case_b.ls_solution.position_error_3d_m:.3f} m
- WLS 3D 位置误差：{case_b.wls_solution.position_error_3d_m:.3f} m
- PDOP：{case_b.dops['PDOP']:.3f}

Monte Carlo（基于实验 B，{monte_carlo_result.num_runs} 次）：

- LS：均值 {monte_carlo_result.stats['LS']['mean_m']:.3f} m，标准差 {monte_carlo_result.stats['LS']['std_m']:.3f} m，90% 分位数 {monte_carlo_result.stats['LS']['p90_m']:.3f} m
- WLS：均值 {monte_carlo_result.stats['WLS']['mean_m']:.3f} m，标准差 {monte_carlo_result.stats['WLS']['std_m']:.3f} m，90% 分位数 {monte_carlo_result.stats['WLS']['p90_m']:.3f} m

## 本次仍然采用的简化

1. 多星几何不是广播星历，而是静态自洽场景
2. 多颗卫星没有各自独立真实鞘套路径，而是共享同一真实单通道传播背景后再映射
3. 对流层、硬件偏差、卫星钟差仍是新增的导航层参数化项
4. 单通道 `c*tau_est` 仍被视为链路观测来源，而不是直接当作标准伪距

## 这次成果在系统层面的意义

原脚本已经证明了真实传播与单通道接收机链路可以跑通；
本次新脚本则把系统推进到了多星标准观测与位置/钟差解算层。
因此，现在项目不再只停留在单链路实验台，而是具备了：

1. 多星标准伪距形成
2. 单历元 LS/WLS PVT
3. 残差、ENU 误差、DOP、Monte Carlo 统计

同时，报告中也明确交代了当前哪些部分是真实复用、哪些部分仍是简化，从而避免把导航层结果误解为完整端到端真实性能。
"""
    with output_path.open("w", encoding="utf-8") as f:
        f.write(text)


# ============================================================
# 9. 主流程
# ============================================================


def print_case_result(case_result: ExperimentCaseResult) -> None:
    ls_enu = case_result.ls_solution.enu_error_m
    wls_enu = case_result.wls_solution.enu_error_m
    print(f"\n[实验 {case_result.case_name}] {case_result.description}")
    print(
        "  - DOP = "
        f"GDOP {case_result.dops['GDOP']:.3f}, "
        f"PDOP {case_result.dops['PDOP']:.3f}, "
        f"HDOP {case_result.dops['HDOP']:.3f}, "
        f"VDOP {case_result.dops['VDOP']:.3f}, "
        f"TDOP {case_result.dops['TDOP']:.3f}"
    )
    print(
        "  - LS  : "
        f"3D误差 {case_result.ls_solution.position_error_3d_m:.3f} m, "
        f"ENU = [{ls_enu[0]:+.3f}, {ls_enu[1]:+.3f}, {ls_enu[2]:+.3f}] m, "
        f"钟差 = {case_result.ls_solution.state_vector_m[3]:+.3f} m"
    )
    print(
        "  - WLS : "
        f"3D误差 {case_result.wls_solution.position_error_3d_m:.3f} m, "
        f"ENU = [{wls_enu[0]:+.3f}, {wls_enu[1]:+.3f}, {wls_enu[2]:+.3f}] m, "
        f"钟差 = {case_result.wls_solution.state_vector_m[3]:+.3f} m"
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
    legacy = summary["legacy_channel_metrics"]
    exp_a = summary["experiments"]["A"]
    exp_b = summary["experiments"]["B"]
    mc = summary["monte_carlo"]["stats"]
    row = {
        "frequency_hz": float(fc_hz),
        "tau_g_median_m": float(legacy["tau_g_median_m"]),
        "tau_g_span_m": float(legacy["tau_g_span_m"]),
        "effective_pseudorange_sigma_100ms_m": float(legacy["effective_pseudorange_sigma_100ms_m"]),
        "effective_pseudorange_sigma_1s_m": float(legacy["effective_pseudorange_sigma_1s_m"]),
        "effective_pseudorange_rmse_m": float(legacy["effective_pseudorange_rmse_m"]),
        "effective_pseudorange_bias_m": float(legacy["effective_pseudorange_bias_m"]),
        "case_a_ls_position_error_3d_m": float(exp_a["ls"]["position_error_3d_m"]),
        "case_a_wls_position_error_3d_m": float(exp_a["wls"]["position_error_3d_m"]),
        "case_b_ls_position_error_3d_m": float(exp_b["ls"]["position_error_3d_m"]),
        "case_b_wls_position_error_3d_m": float(exp_b["wls"]["position_error_3d_m"]),
        "case_a_pdop": float(exp_a["dops"]["PDOP"]),
        "case_b_pdop": float(exp_b["dops"]["PDOP"]),
        "monte_carlo_ls_mean_m": float(mc["LS"]["mean_m"]),
        "monte_carlo_wls_mean_m": float(mc["WLS"]["mean_m"]),
        "monte_carlo_ls_p90_m": float(mc["LS"]["p90_m"]),
        "monte_carlo_wls_p90_m": float(mc["WLS"]["p90_m"]),
    }
    # 除核心列外，把 summary 中可量化的指标都纳入跨频分析。
    row.update(_flatten_numeric_scalars(summary.get("legacy_channel_metrics", {}), prefix="legacy"))
    row.update(_flatten_numeric_scalars(summary.get("experiments", {}), prefix="experiments"))
    row.update(_flatten_numeric_scalars(summary.get("monte_carlo", {}), prefix="monte_carlo"))
    return row


def _write_cross_frequency_outputs(
    rows: list[dict[str, float]],
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    key_union = {key for row in rows for key in row.keys()}
    fieldnames = ["frequency_hz"] + sorted(key for key in key_union if key != "frequency_hz")
    csv_path = output_dir / "wls_metrics.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    json_path = output_dir / "wls_metrics.json"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    freq_ghz = np.asarray([row["frequency_hz"] for row in rows], dtype=float) / 1e9
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), dpi=160)

    axes[0, 0].plot(freq_ghz, [row["tau_g_median_m"] for row in rows], marker="o", label="tau_g median")
    axes[0, 0].plot(freq_ghz, [row["tau_g_span_m"] for row in rows], marker="o", label="tau_g span")
    axes[0, 0].set_title("Legacy dispersive metrics")
    axes[0, 0].set_xlabel("Frequency (GHz)")
    axes[0, 0].set_ylabel("m")
    axes[0, 0].grid(True, ls=":", alpha=0.5)
    axes[0, 0].legend()

    axes[0, 1].plot(freq_ghz, [row["case_a_wls_position_error_3d_m"] for row in rows], marker="o", label="Case A WLS")
    axes[0, 1].plot(freq_ghz, [row["case_b_wls_position_error_3d_m"] for row in rows], marker="o", label="Case B WLS")
    axes[0, 1].set_title("WLS position error")
    axes[0, 1].set_xlabel("Frequency (GHz)")
    axes[0, 1].set_ylabel("m")
    axes[0, 1].grid(True, ls=":", alpha=0.5)
    axes[0, 1].legend()

    axes[1, 0].plot(freq_ghz, [row["effective_pseudorange_sigma_1s_m"] for row in rows], marker="o", label="1 s sigma")
    axes[1, 0].plot(freq_ghz, [row["effective_pseudorange_rmse_m"] for row in rows], marker="o", label="1 s RMSE")
    axes[1, 0].set_title("Legacy pseudorange statistics")
    axes[1, 0].set_xlabel("Frequency (GHz)")
    axes[1, 0].set_ylabel("m")
    axes[1, 0].grid(True, ls=":", alpha=0.5)
    axes[1, 0].legend()

    axes[1, 1].plot(freq_ghz, [row["monte_carlo_ls_mean_m"] for row in rows], marker="o", label="MC LS mean")
    axes[1, 1].plot(freq_ghz, [row["monte_carlo_wls_mean_m"] for row in rows], marker="o", label="MC WLS mean")
    axes[1, 1].plot(freq_ghz, [row["monte_carlo_ls_p90_m"] for row in rows], marker="o", label="MC LS p90")
    axes[1, 1].plot(freq_ghz, [row["monte_carlo_wls_p90_m"] for row in rows], marker="o", label="MC WLS p90")
    axes[1, 1].set_title("Monte Carlo statistics")
    axes[1, 1].set_xlabel("Frequency (GHz)")
    axes[1, 1].set_ylabel("m")
    axes[1, 1].grid(True, ls=":", alpha=0.5)
    axes[1, 1].legend()

    fig.tight_layout()
    fig.savefig(output_dir / "wls_metrics_vs_frequency.png", dpi=180, bbox_inches="tight")
    plt.close(fig)


def run_wls_for_frequency(
    fc_hz: float,
    *,
    results_dir: Path | None = None,
    monte_carlo_runs: int = 120,
    rng_seed_base: int = 2026,
    truth_free_runtime: bool = False,
    truth_free_initialization: bool = False,
    channel_background_mode: str = "legacy",
) -> dict[str, Any]:
    global RESULTS_DIR
    prev_results_dir = RESULTS_DIR
    receiver_cfg = ReceiverTruthConfig(carrier_frequency_hz=float(fc_hz))
    RESULTS_DIR = results_dir if results_dir is not None else results_dir_for_frequency(receiver_cfg.carrier_frequency_hz)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        legacy_bg = build_channel_background(
            receiver_cfg,
            truth_free_runtime=truth_free_runtime,
            channel_background_mode=channel_background_mode,
        )
        experiment_a_cfg, experiment_b_cfg = build_experiment_configs()
        plot_cfg = PlotConfig(enabled=False, save_dir=RESULTS_DIR)

        rng_case_a = np.random.default_rng(rng_seed_base + 319)
        rng_case_b = np.random.default_rng(rng_seed_base + 320)
        case_a_result = run_experiment_case(
            receiver_cfg,
            legacy_bg,
            experiment_a_cfg,
            rng_case_a,
            truth_free_initialization=truth_free_initialization,
        )
        case_b_result = run_experiment_case(
            receiver_cfg,
            legacy_bg,
            experiment_b_cfg,
            rng_case_b,
            truth_free_initialization=truth_free_initialization,
        )
        case_results = [case_a_result, case_b_result]

        monte_carlo_result = run_monte_carlo(
            receiver_cfg,
            legacy_bg,
            experiment_b_cfg,
            num_runs=monte_carlo_runs,
            rng_seed=rng_seed_base + 1001,
            truth_free_initialization=truth_free_initialization,
        )

        plot_sky_geometry(case_results, plot_cfg)
        plot_geometry_3d(receiver_cfg, case_results, plot_cfg)
        plot_legacy_channel_overview(legacy_bg, plot_cfg)
        plot_pseudorange_formation(case_results, plot_cfg)
        plot_ls_vs_wls_residuals(case_results, plot_cfg)
        plot_monte_carlo_position_error(monte_carlo_result, plot_cfg)
        plot_dop_summary(case_results, plot_cfg)

        write_satellite_observations_csv(case_results, RESULTS_DIR / "satellite_observations.csv")
        write_summary_json(receiver_cfg, legacy_bg, case_results, monte_carlo_result, RESULTS_DIR / "summary.json")
        write_report_summary_md(receiver_cfg, legacy_bg, case_results, monte_carlo_result, RESULTS_DIR / "report_summary.md")

        summary = json.loads((RESULTS_DIR / "summary.json").read_text(encoding="utf-8"))
        return {
            "frequency_hz": float(fc_hz),
            "results_dir": RESULTS_DIR,
            "receiver_cfg": receiver_cfg,
            "legacy_bg": legacy_bg,
            "case_results": case_results,
            "monte_carlo_result": monte_carlo_result,
            "summary": summary,
        }
    finally:
        RESULTS_DIR = prev_results_dir


def run_wls_frequency_grid(
    frequencies_hz: Sequence[float],
    *,
    root_output_dir: Path | None = None,
    monte_carlo_runs: int = 120,
    rng_seed_base: int = 2026,
    truth_free_runtime: bool = False,
    truth_free_initialization: bool = False,
    channel_background_mode: str = "legacy",
) -> dict[str, Any]:
    if len(frequencies_hz) == 0:
        raise ValueError("frequencies_hz 不能为空。")
    root_dir = root_output_dir if root_output_dir is not None else (CANONICAL_RESULTS_ROOT / "results_ka_multifreq" / "wls")
    root_dir.mkdir(parents=True, exist_ok=True)

    per_frequency: list[dict[str, Any]] = []
    rows: list[dict[str, float]] = []
    for idx, fc_hz in enumerate(frequencies_hz):
        label = _frequency_label(float(fc_hz))
        result = run_wls_for_frequency(
            float(fc_hz),
            results_dir=root_dir / label,
            monte_carlo_runs=monte_carlo_runs,
            rng_seed_base=rng_seed_base + idx * 10000,
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
    print("多星标准伪距 + 单历元 LS/WLS PVT 实验")
    print("=" * 100)
    print("说明：本文件会输出单频全指标结果，且可被上层全频批处理直接复用。")

    run_wls_for_frequency(22.5e9, results_dir=results_dir_for_frequency(22.5e9), monte_carlo_runs=120, rng_seed_base=2026)

    print("\n[结果输出]")
    print(f"  - 结果目录 = {RESULTS_DIR}")
    print("  - 图片：sky_geometry.png, geometry_3d.png, legacy_channel_overview.png, pseudorange_formation.png, ls_vs_wls_residuals.png, monte_carlo_position_error.png, dop_summary.png")
    print("  - 表格：satellite_observations.csv")
    print("  - 摘要：summary.json, report_summary.md")


if __name__ == "__main__":
    np.random.seed(2026)
    main()
