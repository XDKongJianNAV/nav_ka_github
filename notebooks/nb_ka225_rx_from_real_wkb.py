# -*- coding: utf-8 -*-
"""
nb_ka225_rx_from_real_wkb.py
============================

基于“真实电子密度场 -> 真实 WKB 传播结果”的 Ka 22.5 GHz 基础 PN/BPSK 接收机完整实验脚本。

主链条
------
1. 从 CSV 构造电子密度场：
      Large-scale / Meso-scale / Combined

2. 对 Combined 场做真实 WKB 传播计算：
      A(t), phi(t)

3. 使用中心差分，在 22.5 GHz 附近两个邻近频点再算两次 WKB，
   估计群时延：
      tau_g(t) = - d(phi) / d(omega)

4. 将真实 WKB 序列重采样到接收机采样时间轴

5. 构造 Ka 22.5 GHz 基础 PN/BPSK 复基带接收信号：
      - 几何/机动带来的码时延与频偏先抽象成外部项
      - 等离子体传播使用真实 A(t), phi(t), tau_g(t)
      - 加噪声

6. 捕获：
      - 码相位搜索
      - 频偏搜索

7. 跟踪：
      - 非相干 DLL
      - Costas PLL

8. 输出观测量：
      - pseudorange
      - carrier phase
      - Doppler

重要说明
--------
1. 本文件中的接收机处理时长不是手写的，而是严格继承 WKB 时间轴范围：
       total_time_s = t_eval[-1] - t_eval[0]

2. 本文件中的等离子体传播不做高斯近似，而是调用：
       plasma_field_core.py
       plasma_wkb_core.py

3. 当前“LEO 卫星带来的多普勒 + RAM-C II 400 s 左右机动带来的多普勒”
   仍然先抽象成：
       f_D(t) = f0 + f1 * t
   这一步是为了先把接收机主体建起来。
   你后续完全可以把这里替换成真实几何与动力学结果。

4. 由于这里是完整接收机链，计算量不小。
   为了让整个真实时长仍可运行，我们采用“按块生成和处理”的方式，
   而不是把所有采样点一次性展开到内存中。

依赖
----
- numpy
- matplotlib

并且依赖你已经拆出来的 src 下三个文件：
- plasma_field_core.py
- plasma_field_plot.py
- plasma_wkb_core.py
"""

from __future__ import annotations

from pathlib import Path
import sys
import math
from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np
import matplotlib.pyplot as plt


# ============================================================
# 0. 导入已有核心代码
# ============================================================

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from plasma_field_core import build_fields_from_csv
from plasma_field_plot import (
    plot_three_fields_vertical,
    plot_profile_comparison_from_fields,
)
from plasma_wkb_core import run_wkb_analysis


# ============================================================
# 1. 全局常量与绘图风格
# ============================================================

C_LIGHT = 299_792_458.0

plt.rcParams["font.family"] = "serif"
plt.rcParams["xtick.direction"] = "in"
plt.rcParams["ytick.direction"] = "in"


# ============================================================
# 2. 数据结构
# ============================================================
@dataclass
class SignalConfig:
    """
    接收机信号与时间尺度配置。

    说明
    ----
    total_time_s 由真实 WKB 时间范围给出，但真实时长通常不能与采样率严格整除。
    因此这里额外显式存储 total_samples，并把 total_time_s 反算为 total_samples / fs_hz，
    从而保证离散接收机时间轴内部自洽。
    """
    fc_hz: float
    fs_hz: float
    chip_rate_hz: float
    code_length: int
    coherent_integration_s: float
    total_time_s: float
    total_samples_value: int
    cn0_dbhz: float
    nav_data_enabled: bool

    @property
    def samples_per_chip(self) -> int:
        value = self.fs_hz / self.chip_rate_hz
        if abs(value - round(value)) > 1e-9:
            raise ValueError("fs_hz / chip_rate_hz 必须为整数。")
        return int(round(value))

    @property
    def total_samples(self) -> int:
        return int(self.total_samples_value)

    @property
    def update_samples(self) -> int:
        value = self.coherent_integration_s * self.fs_hz
        if abs(value - round(value)) > 1e-9:
            raise ValueError("coherent_integration_s * fs_hz 必须为整数。")
        return int(round(value))

    @property
    def wavelength_m(self) -> float:
        return C_LIGHT / self.fc_hz

    @property
    def chip_period_s(self) -> float:
        return 1.0 / self.chip_rate_hz

    @property
    def code_period_s(self) -> float:
        return self.code_length / self.chip_rate_hz

@dataclass
class MotionConfig:
    """
    运动/几何项的当前抽象配置。

    说明
    ----
    这里仍先把：
      - LEO 卫星多普勒
      - RAM-C II 再入机动多普勒
    抽象成外部频偏与时延漂移项。

    但接收机内部的 acquisition / DLL / PLL 是显式实现的，
    没有被直接简化成真值观测。
    """
    code_delay_chips_0: float
    code_delay_rate_chips_per_s: float
    doppler_hz_0: float
    doppler_rate_hz_per_s: float


@dataclass
class AcquisitionConfig:
    search_fd_min_hz: float
    search_fd_max_hz: float
    search_fd_step_hz: float
    code_search_step_samples: int
    acq_time_s: float


@dataclass
class TrackingConfig:
    dll_spacing_chips: float
    dll_gain: float
    pll_kp: float
    pll_ki: float


@dataclass
class ReceiverState:
    """
    跟踪环内部状态。
    """
    tau_est_s: float
    carrier_freq_hz: float
    carrier_phase_start_rad: float
    pll_integrator: float
    carrier_phase_total_rad: float


# ============================================================
# 3. 基础工具函数
# ============================================================

def wrap_to_pi(x: np.ndarray | float) -> np.ndarray | float:
    return (np.asarray(x) + np.pi) % (2.0 * np.pi) - np.pi


def db20(x: np.ndarray | float) -> np.ndarray | float:
    return 20.0 * np.log10(np.maximum(np.asarray(x), 1e-30))


def mseq_7() -> np.ndarray:
    """
    生成长度 127 的 m 序列，输出 ±1。
    """
    reg = [1, 1, 1, 1, 1, 1, 1]
    seq = []
    for _ in range(127):
        out = reg[-1]
        seq.append(out)
        feedback = reg[-1] ^ reg[-5]   # x^7 + x^3 + 1 的一种实现
        reg = [feedback] + reg[:-1]
    seq = np.array(seq, dtype=int)
    return 2 * seq - 1


def sample_code_waveform(
    code_chips: np.ndarray,
    chip_rate_hz: float,
    t_s: np.ndarray,
) -> np.ndarray:
    """
    在任意连续时间点上采样矩形 PN 码波形。

    数学形式
    --------
    令码周期：
        T_code = N_code / f_chip

    对任意时间 t：
        t_mod = t mod T_code
        chip_idx = floor(t_mod * f_chip)

    然后输出：
        c(t) = code_chips[chip_idx]

    说明
    ----
    这样可以直接对“任意延迟后的码时间”取样，
    不需要先整段展开后再做插值。
    """
    code_length = len(code_chips)
    code_period_s = code_length / chip_rate_hz

    t_mod = np.mod(t_s, code_period_s)
    chip_idx = np.floor(t_mod * chip_rate_hz).astype(int)
    chip_idx = np.clip(chip_idx, 0, code_length - 1)

    return code_chips[chip_idx].astype(np.complex128)

def build_signal_config_from_wkb_time(
    wkb_time_s: np.ndarray,
    *,
    fc_hz: float,
    fs_hz: float,
    chip_rate_hz: float,
    coherent_integration_s: float,
    code_length: int,
    cn0_dbhz: float,
    nav_data_enabled: bool,
) -> SignalConfig:
    """
    根据真实 WKB 时间轴构造接收机配置。

    关键处理
    --------
    真实时间范围:
        T_real = wkb_time_s[-1] - wkb_time_s[0]

    但接收机必须工作在离散采样网格上，因此不能要求 T_real * fs 恰好是整数。
    正确做法是：
        N = round(T_real * fs)
        T_used = N / fs

    这样既保持“接收机时长来自真实 WKB 时间范围”，
    又保证离散采样实现完全自洽。
    """
    t0 = float(wkb_time_s[0])
    t1 = float(wkb_time_s[-1])

    total_time_real_s = t1 - t0
    total_samples = int(round(total_time_real_s * fs_hz))
    total_time_used_s = total_samples / fs_hz

    if total_samples <= 0:
        raise ValueError("由 WKB 时间范围得到的 total_samples 非法。")

    print("\n[接收机时间轴构造]")
    print(f"  - 真实 WKB 时长 T_real = {total_time_real_s:.9f} s")
    print(f"  - 接收机采样率 fs = {fs_hz:.3f} Hz")
    print(f"  - 离散化后总采样点 N = {total_samples}")
    print(f"  - 接收机实际使用时长 T_used = {total_time_used_s:.9f} s")
    print(f"  - 离散化误差 = {total_time_used_s - total_time_real_s:+.3e} s")

    return SignalConfig(
        fc_hz=fc_hz,
        fs_hz=fs_hz,
        chip_rate_hz=chip_rate_hz,
        code_length=code_length,
        coherent_integration_s=coherent_integration_s,
        total_time_s=total_time_used_s,
        total_samples_value=total_samples,
        cn0_dbhz=cn0_dbhz,
        nav_data_enabled=nav_data_enabled,
    )

# ============================================================
# 4. 真实 WKB 传播结果构造
# ============================================================

def compute_real_wkb_series(
    t_eval: np.ndarray,
    z_eval: np.ndarray,
    ne_matrix: np.ndarray,
    *,
    fc_hz: float,
    nu_en_hz: float,
    delta_f_hz: float,
    verbose: bool = True,
) -> Dict[str, np.ndarray]:
    """
    基于真实电子密度矩阵计算 22.5 GHz 附近的真实 WKB 时序。

    输出
    ----
    - A_t      : 中心频率处幅度衰减
    - phi_t    : 中心频率处相位
    - hp_t     : 中心频率处复传输系数
    - tau_g_t  : 由中心差分估计的群时延

    群时延估计
    ----------
    通过相位对角频率求导：
        tau_g = - d(phi) / d(omega)

    用中心差分：
        d(phi)/d(omega) ≈ [phi(f+df) - phi(f-df)] / (2 * 2*pi*df)

    因此：
        tau_g ≈ - [phi(f+df) - phi(f-df)] / (4*pi*df)
    """
    if verbose:
        print("\n[步骤 A] 真实 WKB 传播计算")
        print(f"  - 中心频率 = {fc_hz/1e9:.6f} GHz")
        print(f"  - 群时延差分频移 = ±{delta_f_hz/1e6:.3f} MHz")
        print(f"  - 碰撞频率 = {nu_en_hz/1e9:.3f} GHz")

    # f0 - df
    A_minus, phi_minus, hp_minus = run_wkb_analysis(
        f_EM=fc_hz - delta_f_hz,
        z_grid=z_eval,
        Ne_matrix=ne_matrix,
        nu_en=nu_en_hz,
        collision_input_unit="Hz",
        amplitude_floor=1e-20,
        fix_physics=True,
        verbose=False,
    )

    # f0
    A_0, phi_0, hp_0 = run_wkb_analysis(
        f_EM=fc_hz,
        z_grid=z_eval,
        Ne_matrix=ne_matrix,
        nu_en=nu_en_hz,
        collision_input_unit="Hz",
        amplitude_floor=1e-20,
        fix_physics=True,
        verbose=False,
    )

    # f0 + df
    A_plus, phi_plus, hp_plus = run_wkb_analysis(
        f_EM=fc_hz + delta_f_hz,
        z_grid=z_eval,
        Ne_matrix=ne_matrix,
        nu_en=nu_en_hz,
        collision_input_unit="Hz",
        amplitude_floor=1e-20,
        fix_physics=True,
        verbose=False,
    )

    tau_g_t = - (phi_plus - phi_minus) / (4.0 * np.pi * delta_f_hz)

    if verbose:
        print(f"  - A(t) 范围 = [{np.min(A_0):.4e}, {np.max(A_0):.4e}]")
        print(f"  - phi(t) 范围 = [{np.min(phi_0):.4f}, {np.max(phi_0):.4f}] rad")
        print(f"  - tau_g(t) 范围 = [{np.min(tau_g_t)*1e9:.4f}, {np.max(tau_g_t)*1e9:.4f}] ns")

    return {
        "wkb_time_s": t_eval - t_eval[0],   # 统一减去起点，便于接收机从 0 开始计时
        "A_t": A_0,
        "phi_t": phi_0,
        "hp_t": hp_0,
        "tau_g_t": tau_g_t,
        "A_minus": A_minus,
        "A_plus": A_plus,
        "phi_minus": phi_minus,
        "phi_plus": phi_plus,
    }


def resample_wkb_to_receiver_time(
    rx_time_s: np.ndarray,
    wkb_time_s: np.ndarray,
    A_t: np.ndarray,
    phi_t: np.ndarray,
    tau_g_t: np.ndarray,
) -> Dict[str, np.ndarray]:
    """
    将真实 WKB 结果重采样到接收机采样时间轴。
    """
    A_rx = np.interp(rx_time_s, wkb_time_s, A_t)
    phi_rx = np.interp(rx_time_s, wkb_time_s, phi_t)
    tau_g_rx = np.interp(rx_time_s, wkb_time_s, tau_g_t)

    return {
        "A_t": A_rx,
        "phi_t": phi_rx,
        "tau_g_t": tau_g_rx,
    }


# ============================================================
# 5. 发射信号
# ============================================================

def build_transmitter_signal_tools(cfg_sig: SignalConfig) -> Dict[str, np.ndarray]:
    """
    生成发射端基础码。
    当前基础体制仍为 PN/BPSK。
    """
    print("\n[步骤 B] 构造 Ka 22.5 GHz 基础 PN/BPSK 发射模型")
    print(f"  - λ = {cfg_sig.wavelength_m*100:.4f} cm")
    print(f"  - 采样率 fs = {cfg_sig.fs_hz/1e3:.3f} kHz")
    print(f"  - 码率 chip_rate = {cfg_sig.chip_rate_hz/1e3:.3f} kcps")
    print(f"  - 每码片采样点 = {cfg_sig.samples_per_chip}")
    print(f"  - 总时长 = {cfg_sig.total_time_s:.6f} s（完全继承真实 WKB 时间范围）")

    code_chips = mseq_7()
    return {
        "code_chips": code_chips,
    }


# ============================================================
# 6. 接收信号真实构造（按块）
# ============================================================

def evaluate_true_channel_and_motion(
    t_rel_s: np.ndarray,
    cfg_sig: SignalConfig,
    cfg_motion: MotionConfig,
    plasma_rx: Dict[str, np.ndarray],
    global_rx_time_s: np.ndarray,
) -> Dict[str, np.ndarray]:
    """
    在给定接收机时间点上计算真实外部输入。

    包括：
    - 运动/几何码时延
    - 运动/几何频偏
    - 等离子体真实 A(t), phi(t), tau_g(t)

    说明
    ----
    这里多普勒与运动项仍然是抽象外部输入；
    但等离子体传播项是来自真实 WKB 结果，不做近似。
    """
    code_delay_geom_s = (
        cfg_motion.code_delay_chips_0 / cfg_sig.chip_rate_hz
        + (cfg_motion.code_delay_rate_chips_per_s / cfg_sig.chip_rate_hz) * t_rel_s
    )

    fd_total_hz = cfg_motion.doppler_hz_0 + cfg_motion.doppler_rate_hz_per_s * t_rel_s

    A_t = np.interp(t_rel_s, global_rx_time_s, plasma_rx["A_t"])
    phi_p_t = np.interp(t_rel_s, global_rx_time_s, plasma_rx["phi_t"])
    tau_g_t = np.interp(t_rel_s, global_rx_time_s, plasma_rx["tau_g_t"])

    tau_total_s = code_delay_geom_s + tau_g_t

    return {
        "tau_geom_s": code_delay_geom_s,
        "tau_g_s": tau_g_t,
        "tau_total_s": tau_total_s,
        "fd_total_hz": fd_total_hz,
        "A_t": A_t,
        "phi_p_t": phi_p_t,
    }


def make_received_block(
    t_block_s: np.ndarray,
    code_chips: np.ndarray,
    cfg_sig: SignalConfig,
    cfg_motion: MotionConfig,
    plasma_rx: Dict[str, np.ndarray],
    global_rx_time_s: np.ndarray,
) -> np.ndarray:
    """
    生成一个接收机时间块上的复基带来波。

    数学形式
    --------
    r(t) = A(t) * c(t - tau_total(t)) * exp(j * phi_total(t)) + n(t)

    其中：
    phi_total(t) = 2*pi * [ f0*t + 0.5*fd_rate*t^2 ] + phi_p(t)

    说明
    ----
    - 这里 c(t - tau_total) 是真正经过时延后的 PN 码波形
    - 不直接从真值时延“读伪距”
    - 接收机必须通过相关与 DLL 自己恢复时延
    """
    ch = evaluate_true_channel_and_motion(
        t_rel_s=t_block_s,
        cfg_sig=cfg_sig,
        cfg_motion=cfg_motion,
        plasma_rx=plasma_rx,
        global_rx_time_s=global_rx_time_s,
    )

    delayed_code = sample_code_waveform(
        code_chips=code_chips,
        chip_rate_hz=cfg_sig.chip_rate_hz,
        t_s=t_block_s - ch["tau_total_s"],
    )

    # 外部总相位：由频偏积分 + 等离子体附加相位组成
    phase_doppler = 2.0 * np.pi * (
        cfg_motion.doppler_hz_0 * t_block_s
        + 0.5 * cfg_motion.doppler_rate_hz_per_s * (t_block_s ** 2)
    )
    phase_total = phase_doppler + ch["phi_p_t"]

    rx_clean = ch["A_t"] * delayed_code * np.exp(1j * phase_total)

    # AWGN
    cn0_linear = 10.0 ** (cfg_sig.cn0_dbhz / 10.0)
    n0 = 1.0 / cn0_linear
    noise_var = n0 * cfg_sig.fs_hz / 2.0
    sigma = math.sqrt(noise_var / 2.0)

    noise = sigma * (
        np.random.randn(len(t_block_s)) + 1j * np.random.randn(len(t_block_s))
    )

    return rx_clean + noise


# ============================================================
# 7. 捕获
# ============================================================

def run_acquisition(
    cfg_sig: SignalConfig,
    cfg_motion: MotionConfig,
    cfg_acq: AcquisitionConfig,
    code_chips: np.ndarray,
    plasma_rx: Dict[str, np.ndarray],
    global_rx_time_s: np.ndarray,
) -> Dict[str, np.ndarray | float]:
    """
    二维捕获：
    - 码相位搜索
    - 频偏搜索

    数学形式
    --------
    对每个候选 (tau, f)：
        metric = | sum r(t) * c(t - tau) * exp(-j 2*pi f t) |^2
    """
    print("\n[步骤 C] 捕获：搜索粗码时延与粗频偏")

    N = int(round(cfg_acq.acq_time_s * cfg_sig.fs_hz))
    t_block = np.arange(N) / cfg_sig.fs_hz

    rx_block = make_received_block(
        t_block_s=t_block,
        code_chips=code_chips,
        cfg_sig=cfg_sig,
        cfg_motion=cfg_motion,
        plasma_rx=plasma_rx,
        global_rx_time_s=global_rx_time_s,
    )

    fd_grid = np.arange(
        cfg_acq.search_fd_min_hz,
        cfg_acq.search_fd_max_hz + cfg_acq.search_fd_step_hz,
        cfg_acq.search_fd_step_hz,
    )

    code_period_samples = int(round(cfg_sig.code_period_s * cfg_sig.fs_hz))
    code_offsets = np.arange(0, code_period_samples, cfg_acq.code_search_step_samples)

    metric = np.zeros((len(fd_grid), len(code_offsets)), dtype=float)

    for i_f, fd in enumerate(fd_grid):
        carrier_wipeoff = np.exp(-1j * 2.0 * np.pi * fd * t_block)
        mixed = rx_block * carrier_wipeoff

        for i_c, code_offset_samples in enumerate(code_offsets):
            tau_cand_s = code_offset_samples / cfg_sig.fs_hz
            local_code = sample_code_waveform(
                code_chips=code_chips,
                chip_rate_hz=cfg_sig.chip_rate_hz,
                t_s=t_block - tau_cand_s,
            )
            corr = np.vdot(local_code, mixed)
            metric[i_f, i_c] = np.abs(corr) ** 2

    idx = np.unravel_index(np.argmax(metric), metric.shape)
    fd_hat = float(fd_grid[idx[0]])
    tau_hat_s = code_offsets[idx[1]] / cfg_sig.fs_hz

    peak = metric[idx]
    mean_metric = np.mean(metric)
    peak_ratio = float(peak / max(mean_metric, 1e-30))

    print(f"  - 粗频偏估计 = {fd_hat/1e3:.3f} kHz")
    print(f"  - 粗码时延估计 = {tau_hat_s*1e6:.3f} us")
    print(f"  - 峰值/均值比 = {peak_ratio:.3f}")

    return {
        "fd_grid": fd_grid,
        "code_offsets": code_offsets,
        "metric": metric,
        "fd_hat_hz": fd_hat,
        "tau_hat_s": tau_hat_s,
        "peak_ratio": peak_ratio,
    }


# ============================================================
# 8. 跟踪：DLL + Costas PLL
# ============================================================

def correlate_block(
    rx_block: np.ndarray,
    t_block_s: np.ndarray,
    code_chips: np.ndarray,
    cfg_sig: SignalConfig,
    state: ReceiverState,
    cfg_trk: TrackingConfig,
) -> Dict[str, complex]:
    """
    对单个积分块做 Early / Prompt / Late 相关。
    """
    local_carrier = np.exp(
        -1j * (
            state.carrier_phase_start_rad
            + 2.0 * np.pi * state.carrier_freq_hz * (t_block_s - t_block_s[0])
        )
    )

    baseband = rx_block * local_carrier

    half_spacing_s = 0.5 * cfg_trk.dll_spacing_chips / cfg_sig.chip_rate_hz

    prompt_code = sample_code_waveform(
        code_chips=code_chips,
        chip_rate_hz=cfg_sig.chip_rate_hz,
        t_s=t_block_s - state.tau_est_s,
    )
    early_code = sample_code_waveform(
        code_chips=code_chips,
        chip_rate_hz=cfg_sig.chip_rate_hz,
        t_s=t_block_s - (state.tau_est_s - half_spacing_s),
    )
    late_code = sample_code_waveform(
        code_chips=code_chips,
        chip_rate_hz=cfg_sig.chip_rate_hz,
        t_s=t_block_s - (state.tau_est_s + half_spacing_s),
    )

    E = np.vdot(early_code, baseband)
    P = np.vdot(prompt_code, baseband)
    L = np.vdot(late_code, baseband)

    return {
        "E": E,
        "P": P,
        "L": L,
    }


def dll_discriminator(E: complex, L: complex) -> float:
    """
    非相干早晚门判别器：
        D = (|E| - |L|) / (|E| + |L|)
    """
    e = abs(E)
    l = abs(L)
    return float((e - l) / (e + l + 1e-30))


def costas_pll_discriminator(P: complex) -> float:
    """
    Costas PLL 相位判别器。
    """
    return float(math.atan2(P.imag, P.real))


def run_tracking(
    cfg_sig: SignalConfig,
    cfg_motion: MotionConfig,
    cfg_trk: TrackingConfig,
    code_chips: np.ndarray,
    plasma_rx: Dict[str, np.ndarray],
    global_rx_time_s: np.ndarray,
    acq_result: Dict[str, np.ndarray | float],
) -> Dict[str, np.ndarray]:
    """
    完整跟踪主循环。

    每个积分周期：
    1. 构造真实接收块
    2. 用本地 NCO 做载波去旋
    3. 用 Early / Prompt / Late 做相关
    4. DLL 更新 tau_est
    5. PLL 更新 carrier_freq 和相位
    6. 形成伪距 / 载波相位 / Doppler 观测量
    """
    print("\n[步骤 D] 跟踪：显式 DLL + Costas PLL")

    dt = cfg_sig.coherent_integration_s
    Nblk = cfg_sig.update_samples
    n_blocks = cfg_sig.total_samples // Nblk

    state = ReceiverState(
        tau_est_s=float(acq_result["tau_hat_s"]),
        carrier_freq_hz=float(acq_result["fd_hat_hz"]),
        carrier_phase_start_rad=0.0,
        pll_integrator=0.0,
        carrier_phase_total_rad=0.0,
    )

    t_hist = []
    tau_est_hist = []
    fd_est_hist = []
    phase_est_hist = []
    dll_err_hist = []
    pll_err_hist = []

    I_E_hist, Q_E_hist = [], []
    I_P_hist, Q_P_hist = [], []
    I_L_hist, Q_L_hist = [], []

    pseudorange_hist = []
    carrier_phase_cycles_hist = []
    doppler_hist = []

    for k in range(n_blocks):
        i0 = k * Nblk
        i1 = i0 + Nblk
        t_block = np.arange(i0, i1) / cfg_sig.fs_hz
        t_mid = 0.5 * (t_block[0] + t_block[-1])

        rx_block = make_received_block(
            t_block_s=t_block,
            code_chips=code_chips,
            cfg_sig=cfg_sig,
            cfg_motion=cfg_motion,
            plasma_rx=plasma_rx,
            global_rx_time_s=global_rx_time_s,
        )

        corr = correlate_block(
            rx_block=rx_block,
            t_block_s=t_block,
            code_chips=code_chips,
            cfg_sig=cfg_sig,
            state=state,
            cfg_trk=cfg_trk,
        )

        E, P, L = corr["E"], corr["P"], corr["L"]

        d_dll = dll_discriminator(E, L)
        d_pll = costas_pll_discriminator(P)

        # DLL 更新：注意符号方向
        state.tau_est_s -= cfg_trk.dll_gain * d_dll * cfg_sig.chip_period_s

        # PLL 二阶更新
        state.pll_integrator += cfg_trk.pll_ki * d_pll * dt
        state.carrier_freq_hz += cfg_trk.pll_kp * d_pll + state.pll_integrator

        # 累积总相位与下一个块起点相位
        state.carrier_phase_total_rad += 2.0 * np.pi * state.carrier_freq_hz * dt
        state.carrier_phase_start_rad = state.carrier_phase_total_rad

        # 保存
        t_hist.append(t_mid)
        tau_est_hist.append(state.tau_est_s)
        fd_est_hist.append(state.carrier_freq_hz)
        phase_est_hist.append(state.carrier_phase_total_rad)
        dll_err_hist.append(d_dll)
        pll_err_hist.append(d_pll)

        I_E_hist.append(E.real); Q_E_hist.append(E.imag)
        I_P_hist.append(P.real); Q_P_hist.append(P.imag)
        I_L_hist.append(L.real); Q_L_hist.append(L.imag)

        pseudorange_hist.append(C_LIGHT * state.tau_est_s)
        carrier_phase_cycles_hist.append(state.carrier_phase_total_rad / (2.0 * np.pi))
        doppler_hist.append(state.carrier_freq_hz)

    print(f"  - 积分周期 = {dt*1e3:.3f} ms")
    print(f"  - 跟踪块数 = {n_blocks}")
    print(f"  - 最终载波频率估计 = {fd_est_hist[-1]/1e3:.3f} kHz")
    print(f"  - 最终码时延估计 = {tau_est_hist[-1]*1e6:.3f} us")

    return {
        "t": np.asarray(t_hist),
        "tau_est_s": np.asarray(tau_est_hist),
        "fd_est_hz": np.asarray(fd_est_hist),
        "phase_est_rad": np.asarray(phase_est_hist),
        "dll_err": np.asarray(dll_err_hist),
        "pll_err": np.asarray(pll_err_hist),

        "I_E": np.asarray(I_E_hist), "Q_E": np.asarray(Q_E_hist),
        "I_P": np.asarray(I_P_hist), "Q_P": np.asarray(Q_P_hist),
        "I_L": np.asarray(I_L_hist), "Q_L": np.asarray(Q_L_hist),

        "pseudorange_m": np.asarray(pseudorange_hist),
        "carrier_phase_cycles": np.asarray(carrier_phase_cycles_hist),
        "doppler_hz": np.asarray(doppler_hist),
    }


# ============================================================
# 9. 绘图
# ============================================================

def plot_receiver_results(
    t_eval_rel: np.ndarray,
    ne_large: np.ndarray,
    ne_meso: np.ndarray,
    ne_combined: np.ndarray,
    z_eval: np.ndarray,
    wkb_result: Dict[str, np.ndarray],
    acq_result: Dict[str, np.ndarray | float],
    trk_result: Dict[str, np.ndarray],
) -> None:
    """
    绘制完整结果图。
    """
    print("\n[步骤 E] 绘制结果图")

    # 先看电子密度场
    plot_three_fields_vertical(
        t_eval=t_eval_rel,
        z_eval=z_eval,
        field1=ne_large,
        field2=ne_meso,
        field3=ne_combined,
        title1="Large-scale Baseline Electron Density",
        title2="Meso-scale Modulated Electron Density",
        title3="Combined Electron Density",
        vmin=14,
        vmax=18.5,
    )

    mid_idx = len(t_eval_rel) // 2
    plot_profile_comparison_from_fields(
        t_eval=t_eval_rel,
        z_eval=z_eval,
        field_dict={
            "Large-scale": ne_large,
            "Meso-scale": ne_meso,
            "Combined": ne_combined,
        },
        time_index=mid_idx,
        title_prefix="Electron Density Profile Comparison",
    )

    fig = plt.figure(figsize=(16, 18), dpi=120)
    gs = fig.add_gridspec(5, 2, hspace=0.42, wspace=0.30)

    # 1. WKB 幅度
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.plot(wkb_result["wkb_time_s"], db20(wkb_result["A_t"]), lw=1.4)
    ax1.set_title("Real WKB Amplitude Attenuation")
    ax1.set_xlabel("Time (s)")
    ax1.set_ylabel("A(t) [dB]")
    ax1.grid(True, ls=":", alpha=0.5)

    # 2. WKB 相位
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.plot(wkb_result["wkb_time_s"], wkb_result["phi_t"], lw=1.4, color="tab:red")
    ax2.set_title("Real WKB Phase Shift")
    ax2.set_xlabel("Time (s)")
    ax2.set_ylabel(r"$\phi(t)$ [rad]")
    ax2.grid(True, ls=":", alpha=0.5)

    # 3. WKB 群时延
    ax3 = fig.add_subplot(gs[1, 0])
    ax3.plot(wkb_result["wkb_time_s"], wkb_result["tau_g_t"] * 1e9, lw=1.4, color="tab:green")
    ax3.set_title("Real WKB Group Delay")
    ax3.set_xlabel("Time (s)")
    ax3.set_ylabel(r"$\tau_g(t)$ [ns]")
    ax3.grid(True, ls=":", alpha=0.5)

    # 4. 捕获图
    ax4 = fig.add_subplot(gs[1, 1])
    metric_db = 10.0 * np.log10(acq_result["metric"] + 1e-30)
    im = ax4.imshow(
        metric_db,
        origin="lower",
        aspect="auto",
        extent=[
            acq_result["code_offsets"][0],
            acq_result["code_offsets"][-1],
            acq_result["fd_grid"][0] / 1e3,
            acq_result["fd_grid"][-1] / 1e3,
        ],
        cmap="jet",
    )
    ax4.set_title("Acquisition Metric")
    ax4.set_xlabel("Code Offset (samples)")
    ax4.set_ylabel("Frequency Bin (kHz)")
    plt.colorbar(im, ax=ax4, label="Metric [dB]")

    # 5. Prompt I/Q
    ax5 = fig.add_subplot(gs[2, 0])
    ax5.plot(trk_result["t"], trk_result["I_P"], label="I_P", lw=1.2)
    ax5.plot(trk_result["t"], trk_result["Q_P"], label="Q_P", lw=1.2)
    ax5.set_title("Prompt Correlator Outputs")
    ax5.set_xlabel("Time (s)")
    ax5.set_ylabel("Correlation")
    ax5.legend()
    ax5.grid(True, ls=":", alpha=0.5)

    # 6. DLL / PLL 误差
    ax6 = fig.add_subplot(gs[2, 1])
    ax6.plot(trk_result["t"], trk_result["dll_err"], label="DLL error", lw=1.2)
    ax6.plot(trk_result["t"], trk_result["pll_err"], label="PLL error", lw=1.2)
    ax6.set_title("Loop Discriminator Outputs")
    ax6.set_xlabel("Time (s)")
    ax6.set_ylabel("Error")
    ax6.legend()
    ax6.grid(True, ls=":", alpha=0.5)

    # 7. 伪距
    ax7 = fig.add_subplot(gs[3, 0])
    ax7.plot(trk_result["t"], trk_result["pseudorange_m"], lw=1.2, color="tab:orange")
    ax7.set_title("Pseudorange Observable")
    ax7.set_xlabel("Time (s)")
    ax7.set_ylabel("Pseudorange (m)")
    ax7.grid(True, ls=":", alpha=0.5)

    # 8. Doppler
    ax8 = fig.add_subplot(gs[3, 1])
    ax8.plot(trk_result["t"], trk_result["doppler_hz"] / 1e3, lw=1.2, color="tab:brown")
    ax8.set_title("Doppler Observable")
    ax8.set_xlabel("Time (s)")
    ax8.set_ylabel("Doppler (kHz)")
    ax8.grid(True, ls=":", alpha=0.5)

    # 9. 载波相位
    ax9 = fig.add_subplot(gs[4, 0])
    ax9.plot(trk_result["t"], trk_result["carrier_phase_cycles"], lw=1.2, color="tab:purple")
    ax9.set_title("Carrier Phase Observable")
    ax9.set_xlabel("Time (s)")
    ax9.set_ylabel("Cycles")
    ax9.grid(True, ls=":", alpha=0.5)

    # 10. 星座
    ax10 = fig.add_subplot(gs[4, 1])
    ax10.scatter(trk_result["I_P"], trk_result["Q_P"], s=8, alpha=0.7)
    ax10.set_title("Prompt Constellation")
    ax10.set_xlabel("I")
    ax10.set_ylabel("Q")
    ax10.grid(True, ls=":", alpha=0.5)
    ax10.set_aspect("equal", adjustable="box")

    plt.tight_layout()
    plt.show()


# ============================================================
# 10. 主流程
# ============================================================

def main() -> None:
    print("=" * 100)
    print("Ka 22.5 GHz | 真实 WKB 传播 -> PN/BPSK 接收机 -> 观测量")
    print("=" * 100)

    # --------------------------------------------------------
    # A. 数据文件路径
    # --------------------------------------------------------
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

    print(f"[文件] large_csv = {large_csv}")
    print(f"[文件] aoa_csv   = {aoa_csv}")

    # --------------------------------------------------------
    # B. 先生成电子密度场
    # --------------------------------------------------------
    field_result = build_fields_from_csv(
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

    ne_large = field_result["ne_large"]
    ne_meso = field_result["ne_meso"]
    ne_combined = field_result["ne_combined"]

    print("\n[场模型]")
    print(f"  - 原始时间范围 = [{t_eval[0]:.6f}, {t_eval[-1]:.6f}] s")
    print(f"  - 继承给接收机的真实时长 = {t_eval_rel[-1]:.6f} s")
    print(f"  - ne_combined shape = {ne_combined.shape}")

    # --------------------------------------------------------
    # C. 真实 WKB 传播计算（22.5 GHz）
    # --------------------------------------------------------
    fc_hz = 22.5e9
    nu_en_hz = 1.0e9
    delta_f_hz = 5.0e6

    wkb_result = compute_real_wkb_series(
        t_eval=t_eval,
        z_eval=z_eval,
        ne_matrix=ne_combined,
        fc_hz=fc_hz,
        nu_en_hz=nu_en_hz,
        delta_f_hz=delta_f_hz,
        verbose=True,
    )

    # --------------------------------------------------------
    # D. 根据信号真实时长构造接收机配置
    #    注意：时长完全来自真实 WKB 时间范围
    # --------------------------------------------------------
    cfg_sig = build_signal_config_from_wkb_time(
        wkb_time_s=wkb_result["wkb_time_s"],
        fc_hz=22.5e9,
        fs_hz=500e3,                 # 明确给定接收机复基带采样率
        chip_rate_hz=50e3,           # 明确给定基础 PN/BPSK 码率
        coherent_integration_s=1e-3, # 1 ms
        code_length=127,
        cn0_dbhz=45.0,
        nav_data_enabled=False,
    )

    cfg_motion = MotionConfig(
        code_delay_chips_0=17.30,
        code_delay_rate_chips_per_s=0.20,
        doppler_hz_0=48e3,
        doppler_rate_hz_per_s=-1.8e3,
    )

    cfg_acq = AcquisitionConfig(
        search_fd_min_hz=-80e3,
        search_fd_max_hz=80e3,
        search_fd_step_hz=2e3,
        code_search_step_samples=1,
        acq_time_s=0.010,
    )

    cfg_trk = TrackingConfig(
        dll_spacing_chips=0.50,
        dll_gain=0.08,
        pll_kp=18.0,
        pll_ki=150.0,
    )

    # --------------------------------------------------------
    # E. 把真实 WKB 序列重采样到接收机采样时间轴
    # --------------------------------------------------------
    rx_time_s = np.arange(cfg_sig.total_samples) / cfg_sig.fs_hz

    plasma_rx = resample_wkb_to_receiver_time(
        rx_time_s=rx_time_s,
        wkb_time_s=wkb_result["wkb_time_s"],
        A_t=wkb_result["A_t"],
        phi_t=wkb_result["phi_t"],
        tau_g_t=wkb_result["tau_g_t"],
    )

    # --------------------------------------------------------
    # F. 发射模型
    # --------------------------------------------------------
    tx_tools = build_transmitter_signal_tools(cfg_sig)
    code_chips = tx_tools["code_chips"]

    # --------------------------------------------------------
    # G. 捕获
    # --------------------------------------------------------
    acq_result = run_acquisition(
        cfg_sig=cfg_sig,
        cfg_motion=cfg_motion,
        cfg_acq=cfg_acq,
        code_chips=code_chips,
        plasma_rx=plasma_rx,
        global_rx_time_s=rx_time_s,
    )

    # --------------------------------------------------------
    # H. 跟踪
    # --------------------------------------------------------
    trk_result = run_tracking(
        cfg_sig=cfg_sig,
        cfg_motion=cfg_motion,
        cfg_trk=cfg_trk,
        code_chips=code_chips,
        plasma_rx=plasma_rx,
        global_rx_time_s=rx_time_s,
        acq_result=acq_result,
    )

    # --------------------------------------------------------
    # I. 输出总结
    # --------------------------------------------------------
    print("\n[最终输出观测量]")
    print(f"  - pseudorange 样本数 = {len(trk_result['pseudorange_m'])}")
    print(f"  - carrier phase 样本数 = {len(trk_result['carrier_phase_cycles'])}")
    print(f"  - Doppler 样本数 = {len(trk_result['doppler_hz'])}")

    print("\n[接收机说明]")
    print("  - 当前接收机处理时长 = 真实 WKB 时间范围")
    print("  - 当前等离子体传播 = 真实 WKB A(t), phi(t), tau_g(t)")
    print("  - 当前卫星/机动多普勒 = 外部抽象输入")
    print("  - acquisition / DLL / PLL = 显式实现，并未直接跳成理想观测")

    # --------------------------------------------------------
    # J. 绘图
    # --------------------------------------------------------
    plot_receiver_results(
        t_eval_rel=t_eval_rel,
        ne_large=ne_large,
        ne_meso=ne_meso,
        ne_combined=ne_combined,
        z_eval=z_eval,
        wkb_result=wkb_result,
        acq_result=acq_result,
        trk_result=trk_result,
    )


if __name__ == "__main__":
    np.random.seed(2026)
    main()