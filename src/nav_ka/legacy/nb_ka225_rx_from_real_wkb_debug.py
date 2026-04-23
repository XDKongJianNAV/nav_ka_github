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
from typing import Any, Dict, Tuple

import numpy as np
import matplotlib.pyplot as plt


# ============================================================
# 0. 导入已有核心代码
# ============================================================

ROOT = Path(__file__).resolve().parents[3]
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
    refine_fd_step_hz: float
    refine_code_step_samples: float
    refine_half_span_fd_hz: float
    refine_half_span_code_samples: float


@dataclass
class TrackingConfig:
    dll_spacing_chips: float
    dll_gain: float
    dll_error_clip: float
    dll_update_min_prompt_snr_db: float
    code_aiding_rate_chips_per_s: float
    pll_kp: float
    pll_ki: float
    pll_phase_kp: float
    pll_error_clip_rad: float
    pll_update_min_prompt_snr_db: float
    pll_integrator_limit_hz: float
    pll_freq_min_hz: float
    pll_freq_max_hz: float
    carrier_aiding_rate_hz_per_s: float
    fll_gain: float
    fll_assist_time_s: float
    carrier_lock_metric_threshold: float


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


@dataclass
class ReceiverRuntimeContext:
    """
    接收机运行时上下文。

    只封装“接收机链路真正共享的状态/资源”，
    不把纯数学工具函数硬塞进类里。
    """
    cfg_sig: SignalConfig
    cfg_motion: MotionConfig
    cfg_acq: AcquisitionConfig
    cfg_trk: TrackingConfig
    code_chips: np.ndarray
    plasma_rx: Dict[str, np.ndarray]
    global_rx_time_s: np.ndarray

    def make_received_block(self, t_block_s: np.ndarray) -> np.ndarray:
        return make_received_block(
            t_block_s=t_block_s,
            code_chips=self.code_chips,
            cfg_sig=self.cfg_sig,
            cfg_motion=self.cfg_motion,
            plasma_rx=self.plasma_rx,
            global_rx_time_s=self.global_rx_time_s,
        )


@dataclass
class ReceiverRunArtifacts:
    acq_result: Dict[str, Any]
    acq_diag: Dict[str, Any]
    trk_result: Dict[str, Any]
    trk_diag: Dict[str, Any]


@dataclass(frozen=True)
class SignalBlockTrace:
    """
    审阅/可视化专用的信号块中间量快照。

    这个结构只暴露现有真实链路已经计算出的中间量，
    不引入第二套信号生成逻辑。
    """

    t_block_s: np.ndarray
    tau_geom_s: np.ndarray
    tau_g_s: np.ndarray
    tau_total_s: np.ndarray
    fd_total_hz: np.ndarray
    A_t: np.ndarray
    phi_p_t: np.ndarray
    delayed_code: np.ndarray
    delayed_data: np.ndarray | None
    phase_total: np.ndarray
    rx_clean: np.ndarray
    noise: np.ndarray
    rx_block: np.ndarray


@dataclass
class PlotConfig:
    enabled: bool
    show_field_context: bool = False
    show_receiver_overview: bool = True
    show_acquisition_internal: bool = True
    show_tracking_internal: bool = True
    show_tracking_snapshots: bool = True
    save_dir: Path | None = None


# ============================================================
# 3. 基础工具函数
# ============================================================

def wrap_to_pi(x: np.ndarray | float) -> np.ndarray | float:
    return (np.asarray(x) + np.pi) % (2.0 * np.pi) - np.pi


def db20(x: np.ndarray | float) -> np.ndarray | float:
    return 20.0 * np.log10(np.maximum(np.asarray(x), 1e-30))


def db10(x: np.ndarray | float) -> np.ndarray | float:
    return 10.0 * np.log10(np.maximum(np.asarray(x), 1e-30))


def rms(x: np.ndarray | float) -> float:
    arr = np.asarray(x, dtype=float)
    if arr.size == 0:
        return float("nan")
    return float(np.sqrt(np.mean(arr ** 2)))


def wrap_to_interval(x: float, period: float) -> float:
    return float((x + 0.5 * period) % period - 0.5 * period)


def find_first_sustained_true(mask: np.ndarray, min_run: int) -> tuple[bool, int, int]:
    run_length = 0
    start_idx = -1

    for i, flag in enumerate(np.asarray(mask, dtype=bool)):
        if flag:
            if run_length == 0:
                start_idx = i
            run_length += 1
            if run_length >= min_run:
                return True, start_idx, run_length
        else:
            run_length = 0
            start_idx = -1

    return False, -1, 0


def build_segment_slices(n: int) -> Dict[str, slice]:
    one_third = max(n // 3, 1)
    two_thirds = max((2 * n) // 3, one_third + 1)
    two_thirds = min(two_thirds, n)

    return {
        "前段": slice(0, one_third),
        "中段": slice(one_third, two_thirds),
        "后段": slice(two_thirds, n),
    }


def compute_spectrum_db(x: np.ndarray, fs_hz: float) -> tuple[np.ndarray, np.ndarray]:
    x_arr = np.asarray(x, dtype=np.complex128)
    window = np.hanning(len(x_arr))
    spec = np.fft.fftshift(np.fft.fft(x_arr * window))
    freq_hz = np.fft.fftshift(np.fft.fftfreq(len(x_arr), d=1.0 / fs_hz))
    return freq_hz, np.asarray(db20(np.abs(spec)))


def finalize_figure(fig: plt.Figure, plot_cfg: PlotConfig, stem: str) -> None:
    fig.tight_layout()

    if plot_cfg.save_dir is not None:
        plot_cfg.save_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(plot_cfg.save_dir / f"{stem}.png", dpi=180, bbox_inches="tight")

    if plot_cfg.enabled:
        plt.show()
    else:
        plt.close(fig)


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


def build_signal_block_trace(
    t_block_s: np.ndarray,
    code_chips: np.ndarray,
    cfg_sig: SignalConfig,
    cfg_motion: MotionConfig,
    plasma_rx: Dict[str, np.ndarray],
    global_rx_time_s: np.ndarray,
    *,
    rng: np.random.Generator | None = None,
) -> SignalBlockTrace:
    """
    返回 legacy 信号块的中间量，供 notebook 和 review 可视化使用。

    这里复用与 make_received_block() 相同的真实公式，
    只是把已有中间量结构化返回，避免在 notebook 中重复抄写核心逻辑。
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

    phase_doppler = 2.0 * np.pi * (
        cfg_motion.doppler_hz_0 * t_block_s
        + 0.5 * cfg_motion.doppler_rate_hz_per_s * (t_block_s ** 2)
    )
    phase_total = phase_doppler + ch["phi_p_t"]
    rx_clean = ch["A_t"] * delayed_code * np.exp(1j * phase_total)

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

    return SignalBlockTrace(
        t_block_s=np.asarray(t_block_s, dtype=float),
        tau_geom_s=np.asarray(ch["tau_geom_s"], dtype=float),
        tau_g_s=np.asarray(ch["tau_g_s"], dtype=float),
        tau_total_s=np.asarray(ch["tau_total_s"], dtype=float),
        fd_total_hz=np.asarray(ch["fd_total_hz"], dtype=float),
        A_t=np.asarray(ch["A_t"], dtype=float),
        phi_p_t=np.asarray(ch["phi_p_t"], dtype=float),
        delayed_code=np.asarray(delayed_code, dtype=np.complex128),
        delayed_data=None,
        phase_total=np.asarray(phase_total, dtype=float),
        rx_clean=np.asarray(rx_clean, dtype=np.complex128),
        noise=np.asarray(noise, dtype=np.complex128),
        rx_block=np.asarray(rx_block, dtype=np.complex128),
    )


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
    fd_hat_coarse = float(fd_grid[idx[0]])
    tau_hat_coarse_s = code_offsets[idx[1]] / cfg_sig.fs_hz

    fd_refine_grid = np.arange(
        fd_hat_coarse - cfg_acq.refine_half_span_fd_hz,
        fd_hat_coarse + cfg_acq.refine_half_span_fd_hz + 0.5 * cfg_acq.refine_fd_step_hz,
        cfg_acq.refine_fd_step_hz,
    )
    tau_refine_samples = np.arange(
        code_offsets[idx[1]] - cfg_acq.refine_half_span_code_samples,
        code_offsets[idx[1]] + cfg_acq.refine_half_span_code_samples + 0.5 * cfg_acq.refine_code_step_samples,
        cfg_acq.refine_code_step_samples,
    )
    tau_refine_s = tau_refine_samples / cfg_sig.fs_hz

    refine_metric = np.zeros((len(fd_refine_grid), len(tau_refine_s)), dtype=float)
    for i_f, fd in enumerate(fd_refine_grid):
        carrier_wipeoff = np.exp(-1j * 2.0 * np.pi * fd * t_block)
        mixed = rx_block * carrier_wipeoff

        for i_c, tau_cand_s in enumerate(tau_refine_s):
            local_code = sample_code_waveform(
                code_chips=code_chips,
                chip_rate_hz=cfg_sig.chip_rate_hz,
                t_s=t_block - tau_cand_s,
            )
            corr = np.vdot(local_code, mixed)
            refine_metric[i_f, i_c] = np.abs(corr) ** 2

    refine_idx = np.unravel_index(np.argmax(refine_metric), refine_metric.shape)
    fd_hat = float(fd_refine_grid[refine_idx[0]])
    tau_hat_s = float(tau_refine_s[refine_idx[1]])

    peak = metric[idx]
    mean_metric = np.mean(metric)
    peak_ratio = float(peak / max(mean_metric, 1e-30))
    best_mixed = rx_block * np.exp(-1j * 2.0 * np.pi * fd_hat * t_block)
    best_local_code = sample_code_waveform(
        code_chips=code_chips,
        chip_rate_hz=cfg_sig.chip_rate_hz,
        t_s=t_block - tau_hat_s,
    )

    print(f"  - 粗频偏估计 = {fd_hat_coarse/1e3:.3f} kHz")
    print(f"  - 粗码时延估计 = {tau_hat_coarse_s*1e6:.3f} us")
    print(f"  - 细频偏估计 = {fd_hat/1e3:.3f} kHz")
    print(f"  - 细码时延估计 = {tau_hat_s*1e6:.3f} us")
    print(f"  - 峰值/均值比 = {peak_ratio:.3f}")

    return {
        "fd_grid": fd_grid,
        "code_offsets": code_offsets,
        "metric": metric,
        "refine_fd_grid": fd_refine_grid,
        "refine_tau_s": tau_refine_s,
        "refine_metric": refine_metric,
        "fd_hat_coarse_hz": fd_hat_coarse,
        "tau_hat_coarse_s": tau_hat_coarse_s,
        "fd_hat_hz": fd_hat,
        "tau_hat_s": tau_hat_s,
        "peak_ratio": peak_ratio,
        "t_block_s": t_block,
        "rx_block": rx_block,
        "best_mixed": best_mixed,
        "best_local_code": best_local_code,
    }


def diagnose_acquisition_physics(
    cfg_sig: SignalConfig,
    cfg_motion: MotionConfig,
    cfg_acq: AcquisitionConfig,
    acq_result: Dict[str, np.ndarray | float],
    plasma_rx: Dict[str, np.ndarray],
    global_rx_time_s: np.ndarray,
    *,
    top_k: int = 5,
) -> Dict[str, np.ndarray | float]:
    """
    捕获阶段接收机物理诊断。

    关注点：
    - 主峰/次峰结构是否足够突出
    - 粗频偏与粗码相位相对真值的误差
    - 真值附近是否落在搜索网格可分辨范围内
    """
    print("\n[步骤 C+] 捕获物理诊断")

    metric = np.asarray(acq_result["metric"], dtype=float)
    fd_grid = np.asarray(acq_result["fd_grid"], dtype=float)
    code_offsets = np.asarray(acq_result["code_offsets"], dtype=float)

    phi_rate_hz = np.gradient(
        plasma_rx["phi_t"], global_rx_time_s, edge_order=1
    ) / (2.0 * np.pi)
    t_ref = 0.5 * cfg_acq.acq_time_s

    tau_true_s = (
        cfg_motion.code_delay_chips_0 / cfg_sig.chip_rate_hz
        + (cfg_motion.code_delay_rate_chips_per_s / cfg_sig.chip_rate_hz) * t_ref
        + np.interp(t_ref, global_rx_time_s, plasma_rx["tau_g_t"])
    )
    fd_true_hz = (
        cfg_motion.doppler_hz_0
        + cfg_motion.doppler_rate_hz_per_s * t_ref
        + np.interp(t_ref, global_rx_time_s, phi_rate_hz)
    )

    tau_hat_s = float(acq_result["tau_hat_s"])
    fd_hat_hz = float(acq_result["fd_hat_hz"])

    tau_true_mod_s = tau_true_s % cfg_sig.code_period_s
    tau_err_mod_s = wrap_to_interval(
        tau_hat_s - tau_true_mod_s,
        cfg_sig.code_period_s,
    )
    tau_err_samples = tau_err_mod_s * cfg_sig.fs_hz
    tau_err_chips = tau_err_mod_s * cfg_sig.chip_rate_hz
    fd_err_hz = fd_hat_hz - fd_true_hz

    flat_metric = metric.ravel()
    top_k = min(top_k, flat_metric.size)
    top_idx = np.argpartition(flat_metric, -top_k)[-top_k:]
    top_idx = top_idx[np.argsort(flat_metric[top_idx])[::-1]]

    peak_values = flat_metric[top_idx]
    second_peak = float(peak_values[1]) if top_k >= 2 else float(peak_values[0])
    peak_to_second_ratio = float(peak_values[0] / max(second_peak, 1e-30))
    peak_to_second_db = float(db10(peak_to_second_ratio))

    top_fd_hz = []
    top_tau_s = []
    top_metric = []

    print(f"  - 真值参考时刻 = {t_ref*1e3:.3f} ms")
    print(f"  - 真值频偏 = {fd_true_hz/1e3:.3f} kHz")
    print(f"  - 真值码时延(模一码周期) = {tau_true_mod_s*1e6:.3f} us")
    print(f"  - 粗频偏误差 = {fd_err_hz:+.3f} Hz")
    print(
        "  - 粗码相位误差 = "
        f"{tau_err_mod_s*1e9:+.3f} ns ({tau_err_samples:+.3f} samples, {tau_err_chips:+.4f} chips)"
    )
    print(f"  - 主峰/次峰比 = {peak_to_second_ratio:.3f} ({peak_to_second_db:.3f} dB)")
    print(f"  - 频偏搜索步进 = {cfg_acq.search_fd_step_hz:.1f} Hz")
    print(f"  - 码相位搜索步进 = {cfg_acq.code_search_step_samples} samples")

    for rank, flat_i in enumerate(top_idx, start=1):
        i_f, i_c = np.unravel_index(int(flat_i), metric.shape)
        peak_fd_hz = float(fd_grid[i_f])
        peak_tau_s = float(code_offsets[i_c] / cfg_sig.fs_hz)
        peak_metric = float(metric[i_f, i_c])
        peak_tau_err_s = wrap_to_interval(
            peak_tau_s - tau_true_mod_s,
            cfg_sig.code_period_s,
        )

        top_fd_hz.append(peak_fd_hz)
        top_tau_s.append(peak_tau_s)
        top_metric.append(peak_metric)

        print(
            f"    top{rank}: fd = {peak_fd_hz/1e3:.3f} kHz, "
            f"tau = {peak_tau_s*1e6:.3f} us, "
            f"metric = {db10(peak_metric):.3f} dB, "
            f"fd_err = {peak_fd_hz - fd_true_hz:+.1f} Hz, "
            f"tau_err = {peak_tau_err_s*1e9:+.1f} ns"
        )

    return {
        "t_ref_s": t_ref,
        "fd_true_hz": fd_true_hz,
        "tau_true_mod_s": tau_true_mod_s,
        "fd_err_hz": fd_err_hz,
        "tau_err_mod_s": tau_err_mod_s,
        "tau_err_samples": tau_err_samples,
        "tau_err_chips": tau_err_chips,
        "peak_to_second_ratio": peak_to_second_ratio,
        "peak_to_second_db": peak_to_second_db,
        "top_fd_hz": np.asarray(top_fd_hz, dtype=float),
        "top_tau_s": np.asarray(top_tau_s, dtype=float),
        "top_metric": np.asarray(top_metric, dtype=float),
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
    # BPSK Costas: 用 |I| 抑制 180° 翻转引入的符号二义性。
    return float(math.atan2(P.imag, abs(P.real) + 1e-30))


def build_tracking_snapshot(
    t_block_s: np.ndarray,
    rx_block: np.ndarray,
    code_chips: np.ndarray,
    cfg_sig: SignalConfig,
    cfg_trk: TrackingConfig,
    state: ReceiverState,
    *,
    block_index: int,
    t_mid_s: float,
    E: complex,
    P: complex,
    L: complex,
    d_dll: float,
    d_pll: float,
    post_corr_snr_db: float,
    carrier_lock_metric: float,
) -> Dict[str, Any]:
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

    return {
        "block_index": block_index,
        "t_mid_s": t_mid_s,
        "t_block_s": t_block_s - t_block_s[0],
        "rx_block": rx_block.copy(),
        "local_carrier": local_carrier,
        "baseband": baseband,
        "prompt_code": prompt_code,
        "early_code": early_code,
        "late_code": late_code,
        "tau_est_s": state.tau_est_s,
        "carrier_freq_hz": state.carrier_freq_hz,
        "E": E,
        "P": P,
        "L": L,
        "dll_err": d_dll,
        "pll_err": d_pll,
        "post_corr_snr_db": post_corr_snr_db,
        "carrier_lock_metric": carrier_lock_metric,
    }


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
    if n_blocks <= 0:
        raise ValueError("跟踪块数为 0，请检查 coherent_integration_s 和总时长。")

    # 等离子体相位随时间变化会贡献一个小的附加“等效多普勒”项。
    phi_rate_hz = np.gradient(
        plasma_rx["phi_t"], global_rx_time_s, edge_order=1
    ) / (2.0 * np.pi)

    state = ReceiverState(
        tau_est_s=float(acq_result["tau_hat_s"]),
        carrier_freq_hz=float(acq_result["fd_hat_hz"]),
        carrier_phase_start_rad=0.0,
        pll_integrator=0.0,
        carrier_phase_total_rad=0.0,
    )
    cn0_linear = 10.0 ** (cfg_sig.cn0_dbhz / 10.0)
    n0 = 1.0 / cn0_linear
    noise_var = n0 * cfg_sig.fs_hz / 2.0
    prompt_noise_power = Nblk * noise_var

    t_hist = []
    tau_est_hist = []
    tau_true_hist = []
    fd_est_hist = []
    fd_true_hist = []
    phase_est_hist = []
    dll_err_hist = []
    pll_err_hist = []

    I_E_hist, Q_E_hist = [], []
    I_P_hist, Q_P_hist = [], []
    I_L_hist, Q_L_hist = [], []

    mag_E_hist = []
    mag_P_hist = []
    mag_L_hist = []
    prompt_phase_hist = []
    prompt_quadrature_ratio_hist = []
    post_corr_snr_db_hist = []
    predicted_cn0_dbhz_hist = []
    predicted_post_corr_snr_db_hist = []
    rx_input_amp_hist = []
    carrier_lock_metric_hist = []
    fll_err_hist = []
    fll_active_hist = []
    dll_update_enabled_hist = []
    pll_update_enabled_hist = []
    pll_integrator_hist = []
    pll_integrator_clamped_hist = []
    pll_freq_cmd_hist = []
    pll_freq_clamped_hist = []
    carrier_freq_center_hist = []
    tau_predict_hist = []

    pseudorange_hist = []
    carrier_phase_cycles_hist = []
    doppler_hist = []
    prev_prompt: complex | None = None
    snapshot_indices = {
        0: "start",
        max(n_blocks // 2, 0): "mid",
        max(n_blocks - 1, 0): "end",
    }
    tracking_snapshots: Dict[str, Dict[str, Any]] = {}

    for k in range(n_blocks):
        i0 = k * Nblk
        i1 = i0 + Nblk
        t_block = np.arange(i0, i1) / cfg_sig.fs_hz
        t_mid = 0.5 * (t_block[0] + t_block[-1])
        if k > 0:
            state.tau_est_s += (
                cfg_trk.code_aiding_rate_chips_per_s / cfg_sig.chip_rate_hz
            ) * dt
        carrier_freq_used_hz = state.carrier_freq_hz

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

        rx_input_amp = float(np.interp(t_mid, global_rx_time_s, plasma_rx["A_t"]))
        predicted_cn0_dbhz = float(cfg_sig.cn0_dbhz + db20(rx_input_amp))
        predicted_post_corr_snr_db = float(predicted_cn0_dbhz + 10.0 * math.log10(dt))
        prompt_power = float(np.abs(P) ** 2)
        post_corr_snr_db = float(db10(prompt_power / max(prompt_noise_power, 1e-30)))
        e_mag = float(abs(E))
        p_mag = float(abs(P))
        l_mag = float(abs(L))
        carrier_lock_metric = float(
            (P.real * P.real - P.imag * P.imag) / (prompt_power + 1e-30)
        )
        fll_err_hz = 0.0
        if prev_prompt is not None:
            fll_err_hz = float(np.angle(P * np.conj(prev_prompt)) / (2.0 * np.pi * dt))

        d_dll = float(np.clip(dll_discriminator(E, L), -cfg_trk.dll_error_clip, cfg_trk.dll_error_clip))
        d_pll = float(np.clip(costas_pll_discriminator(P), -cfg_trk.pll_error_clip_rad, cfg_trk.pll_error_clip_rad))

        dll_update_enabled = (
            post_corr_snr_db >= cfg_trk.dll_update_min_prompt_snr_db
            and carrier_lock_metric >= cfg_trk.carrier_lock_metric_threshold
        )
        pll_update_enabled = post_corr_snr_db >= cfg_trk.pll_update_min_prompt_snr_db
        fll_active = (k * dt) < cfg_trk.fll_assist_time_s or carrier_lock_metric < cfg_trk.carrier_lock_metric_threshold

        if dll_update_enabled:
            state.tau_est_s -= cfg_trk.dll_gain * d_dll * cfg_sig.chip_period_s

        if pll_update_enabled:
            pll_integrator_unclipped = state.pll_integrator + cfg_trk.pll_ki * d_pll * dt
        else:
            pll_integrator_unclipped = state.pll_integrator
        state.pll_integrator = float(
            np.clip(
                pll_integrator_unclipped,
                -cfg_trk.pll_integrator_limit_hz,
                cfg_trk.pll_integrator_limit_hz,
            )
        )

        carrier_freq_center_hz = float(acq_result["fd_hat_hz"]) + cfg_trk.carrier_aiding_rate_hz_per_s * t_mid
        pll_freq_cmd_hz = carrier_freq_center_hz + state.pll_integrator
        if pll_update_enabled:
            pll_freq_cmd_hz += cfg_trk.pll_kp * d_pll
        if prev_prompt is not None and fll_active:
            pll_freq_cmd_hz += cfg_trk.fll_gain * fll_err_hz

        state.carrier_freq_hz = float(
            np.clip(
                pll_freq_cmd_hz,
                cfg_trk.pll_freq_min_hz,
                cfg_trk.pll_freq_max_hz,
            )
        )

        phase_correction_rad = cfg_trk.pll_phase_kp * d_pll if pll_update_enabled else 0.0
        state.carrier_phase_total_rad += 2.0 * np.pi * 0.5 * (carrier_freq_used_hz + state.carrier_freq_hz) * dt
        state.carrier_phase_total_rad += phase_correction_rad
        state.carrier_phase_start_rad = float(wrap_to_pi(state.carrier_phase_total_rad))

        tau_true = (
            cfg_motion.code_delay_chips_0 / cfg_sig.chip_rate_hz
            + (cfg_motion.code_delay_rate_chips_per_s / cfg_sig.chip_rate_hz) * t_mid
            + np.interp(t_mid, global_rx_time_s, plasma_rx["tau_g_t"])
        )
        fd_true = (
            cfg_motion.doppler_hz_0
            + cfg_motion.doppler_rate_hz_per_s * t_mid
            + np.interp(t_mid, global_rx_time_s, phi_rate_hz)
        )

        # 保存
        t_hist.append(t_mid)
        tau_est_hist.append(state.tau_est_s)
        tau_true_hist.append(tau_true)
        fd_est_hist.append(state.carrier_freq_hz)
        fd_true_hist.append(fd_true)
        phase_est_hist.append(state.carrier_phase_total_rad)
        dll_err_hist.append(d_dll)
        pll_err_hist.append(d_pll)

        I_E_hist.append(E.real); Q_E_hist.append(E.imag)
        I_P_hist.append(P.real); Q_P_hist.append(P.imag)
        I_L_hist.append(L.real); Q_L_hist.append(L.imag)
        mag_E_hist.append(e_mag)
        mag_P_hist.append(p_mag)
        mag_L_hist.append(l_mag)
        prompt_phase_hist.append(float(np.angle(P)))
        prompt_quadrature_ratio_hist.append(float(abs(P.imag) / (abs(P.real) + 1e-30)))
        post_corr_snr_db_hist.append(post_corr_snr_db)
        predicted_cn0_dbhz_hist.append(predicted_cn0_dbhz)
        predicted_post_corr_snr_db_hist.append(predicted_post_corr_snr_db)
        rx_input_amp_hist.append(rx_input_amp)
        carrier_lock_metric_hist.append(carrier_lock_metric)
        fll_err_hist.append(fll_err_hz)
        fll_active_hist.append(fll_active)
        dll_update_enabled_hist.append(dll_update_enabled)
        pll_update_enabled_hist.append(pll_update_enabled)
        pll_integrator_hist.append(state.pll_integrator)
        pll_integrator_clamped_hist.append(
            abs(pll_integrator_unclipped - state.pll_integrator) > 1e-12
        )
        pll_freq_cmd_hist.append(pll_freq_cmd_hz)
        pll_freq_clamped_hist.append(abs(pll_freq_cmd_hz - state.carrier_freq_hz) > 1e-12)
        carrier_freq_center_hist.append(carrier_freq_center_hz)
        tau_predict_hist.append(
            cfg_motion.code_delay_chips_0 / cfg_sig.chip_rate_hz
            + (cfg_trk.code_aiding_rate_chips_per_s / cfg_sig.chip_rate_hz) * t_mid
        )

        pseudorange_hist.append(C_LIGHT * state.tau_est_s)
        carrier_phase_cycles_hist.append(state.carrier_phase_total_rad / (2.0 * np.pi))
        doppler_hist.append(state.carrier_freq_hz)
        if k in snapshot_indices:
            tracking_snapshots[snapshot_indices[k]] = build_tracking_snapshot(
                t_block_s=t_block,
                rx_block=rx_block,
                code_chips=code_chips,
                cfg_sig=cfg_sig,
                cfg_trk=cfg_trk,
                state=state,
                block_index=k,
                t_mid_s=t_mid,
                E=E,
                P=P,
                L=L,
                d_dll=d_dll,
                d_pll=d_pll,
                post_corr_snr_db=post_corr_snr_db,
                carrier_lock_metric=carrier_lock_metric,
            )
        prev_prompt = P

    tau_est_arr = np.asarray(tau_est_hist)
    tau_true_arr = np.asarray(tau_true_hist)
    fd_est_arr = np.asarray(fd_est_hist)
    fd_true_arr = np.asarray(fd_true_hist)

    tau_err_s = tau_est_arr - tau_true_arr
    fd_err_hz = fd_est_arr - fd_true_arr

    tau_rmse_ns = float(np.sqrt(np.mean(tau_err_s ** 2)) * 1e9)
    fd_rmse_hz = float(np.sqrt(np.mean(fd_err_hz ** 2)))

    print(f"  - 积分周期 = {dt*1e3:.3f} ms")
    print(f"  - 跟踪块数 = {n_blocks}")
    print(f"  - 最终载波频率估计 = {fd_est_arr[-1]/1e3:.3f} kHz")
    print(f"  - 最终载波频率真值 = {fd_true_arr[-1]/1e3:.3f} kHz")
    print(f"  - 频偏 RMSE = {fd_rmse_hz:.3f} Hz")
    print(f"  - 最终码时延估计 = {tau_est_arr[-1]*1e6:.3f} us")
    print(f"  - 最终码时延真值 = {tau_true_arr[-1]*1e6:.3f} us")
    print(f"  - 码时延 RMSE = {tau_rmse_ns:.3f} ns")

    return {
        "t": np.asarray(t_hist),
        "tau_est_s": tau_est_arr,
        "tau_true_s": tau_true_arr,
        "tau_err_s": tau_err_s,
        "fd_est_hz": fd_est_arr,
        "fd_true_hz": fd_true_arr,
        "fd_err_hz": fd_err_hz,
        "phase_est_rad": np.asarray(phase_est_hist),
        "dll_err": np.asarray(dll_err_hist),
        "pll_err": np.asarray(pll_err_hist),

        "I_E": np.asarray(I_E_hist), "Q_E": np.asarray(Q_E_hist),
        "I_P": np.asarray(I_P_hist), "Q_P": np.asarray(Q_P_hist),
        "I_L": np.asarray(I_L_hist), "Q_L": np.asarray(Q_L_hist),
        "mag_E": np.asarray(mag_E_hist),
        "mag_P": np.asarray(mag_P_hist),
        "mag_L": np.asarray(mag_L_hist),
        "prompt_phase_rad": np.asarray(prompt_phase_hist),
        "prompt_quadrature_ratio": np.asarray(prompt_quadrature_ratio_hist),
        "post_corr_snr_db": np.asarray(post_corr_snr_db_hist),
        "predicted_cn0_dbhz": np.asarray(predicted_cn0_dbhz_hist),
        "predicted_post_corr_snr_db": np.asarray(predicted_post_corr_snr_db_hist),
        "rx_input_amp": np.asarray(rx_input_amp_hist),
        "carrier_lock_metric": np.asarray(carrier_lock_metric_hist),
        "fll_err_hz": np.asarray(fll_err_hist),
        "fll_active": np.asarray(fll_active_hist, dtype=bool),
        "dll_update_enabled": np.asarray(dll_update_enabled_hist, dtype=bool),
        "pll_update_enabled": np.asarray(pll_update_enabled_hist, dtype=bool),
        "pll_integrator_hz": np.asarray(pll_integrator_hist),
        "pll_integrator_clamped": np.asarray(pll_integrator_clamped_hist, dtype=bool),
        "pll_freq_cmd_hz": np.asarray(pll_freq_cmd_hist),
        "pll_freq_clamped": np.asarray(pll_freq_clamped_hist, dtype=bool),
        "carrier_freq_center_hz": np.asarray(carrier_freq_center_hist),
        "tau_predict_s": np.asarray(tau_predict_hist),
        "tracking_snapshots": tracking_snapshots,

        "pseudorange_m": np.asarray(pseudorange_hist),
        "carrier_phase_cycles": np.asarray(carrier_phase_cycles_hist),
        "doppler_hz": np.asarray(doppler_hist),
        "tau_rmse_ns": np.asarray([tau_rmse_ns]),
        "fd_rmse_hz": np.asarray([fd_rmse_hz]),
    }


def diagnose_tracking_physics(
    cfg_sig: SignalConfig,
    cfg_trk: TrackingConfig,
    trk_result: Dict[str, np.ndarray],
) -> Dict[str, np.ndarray | float]:
    """
    跟踪阶段接收机物理诊断。

    关注点：
    - Prompt/Early/Late 输出是否仍处在有效相关区
    - DLL / PLL 判别器是否长时间离开近线性工作区
    - 后相关 SNR 是否跌到噪声主导区间
    - 环路积分器或频率命令是否频繁顶到边界
    """
    print("\n[步骤 D+] 跟踪物理诊断")

    t = np.asarray(trk_result["t"], dtype=float)
    tau_err_s = np.asarray(trk_result["tau_err_s"], dtype=float)
    fd_err_hz = np.asarray(trk_result["fd_err_hz"], dtype=float)
    dll_err = np.asarray(trk_result["dll_err"], dtype=float)
    pll_err = np.asarray(trk_result["pll_err"], dtype=float)
    mag_E = np.asarray(trk_result["mag_E"], dtype=float)
    mag_P = np.asarray(trk_result["mag_P"], dtype=float)
    mag_L = np.asarray(trk_result["mag_L"], dtype=float)
    post_corr_snr_db = np.asarray(trk_result["post_corr_snr_db"], dtype=float)
    predicted_cn0_dbhz = np.asarray(trk_result["predicted_cn0_dbhz"], dtype=float)
    predicted_post_corr_snr_db = np.asarray(trk_result["predicted_post_corr_snr_db"], dtype=float)
    prompt_quadrature_ratio = np.asarray(trk_result["prompt_quadrature_ratio"], dtype=float)
    carrier_lock_metric = np.asarray(trk_result["carrier_lock_metric"], dtype=float)
    fll_err_hz = np.asarray(trk_result["fll_err_hz"], dtype=float)
    fll_active = np.asarray(trk_result["fll_active"], dtype=bool)
    dll_update_enabled = np.asarray(trk_result["dll_update_enabled"], dtype=bool)
    pll_update_enabled = np.asarray(trk_result["pll_update_enabled"], dtype=bool)
    pll_integrator = np.asarray(trk_result["pll_integrator_hz"], dtype=float)
    pll_integrator_clamped = np.asarray(trk_result["pll_integrator_clamped"], dtype=bool)
    pll_freq_cmd_hz = np.asarray(trk_result["pll_freq_cmd_hz"], dtype=float)
    pll_freq_clamped = np.asarray(trk_result["pll_freq_clamped"], dtype=bool)
    fd_true_hz = np.asarray(trk_result["fd_true_hz"], dtype=float)
    tau_true_s = np.asarray(trk_result["tau_true_s"], dtype=float)

    pll_linear_limit_rad = 0.35
    dll_linear_limit = 0.20
    weak_prompt_snr_db = 0.0
    min_loss_run_blocks = max(int(round(0.020 / cfg_sig.coherent_integration_s)), 5)

    pll_out_of_linear = np.abs(pll_err) > pll_linear_limit_rad
    dll_out_of_linear = np.abs(dll_err) > dll_linear_limit
    weak_prompt = post_corr_snr_db < weak_prompt_snr_db
    carrier_lock_weak = carrier_lock_metric < cfg_trk.carrier_lock_metric_threshold
    quadrature_dominant = prompt_quadrature_ratio > 1.0

    loss_score = (
        weak_prompt.astype(int)
        + (pll_out_of_linear & (quadrature_dominant | carrier_lock_weak)).astype(int)
        + dll_out_of_linear.astype(int)
    )
    sustained_loss = loss_score >= 2
    loss_found, loss_start_idx, _ = find_first_sustained_true(
        sustained_loss,
        min_loss_run_blocks,
    )

    fd_true_rate_hz_per_s = np.gradient(fd_true_hz, t, edge_order=1)
    tau_true_rate_ns_per_s = np.gradient(tau_true_s * 1e9, t, edge_order=1)
    prompt_early_late_ratio = mag_P / np.maximum(0.5 * (mag_E + mag_L), 1e-30)

    print(
        "  - 预测输入 C/N0 范围 = "
        f"[{np.min(predicted_cn0_dbhz):.3f}, {np.max(predicted_cn0_dbhz):.3f}] dB-Hz"
    )
    print(
        "  - 预测 1 ms 后相关 SNR 范围 = "
        f"[{np.min(predicted_post_corr_snr_db):.3f}, {np.max(predicted_post_corr_snr_db):.3f}] dB"
    )
    print(
        "  - 实测 Prompt 后相关 SNR 范围 = "
        f"[{np.min(post_corr_snr_db):.3f}, {np.max(post_corr_snr_db):.3f}] dB"
    )
    print(
        "  - Prompt/(Early+Late)/2 中位数 = "
        f"{np.median(prompt_early_late_ratio):.3f}"
    )
    print(
        "  - 载波锁定指标范围 = "
        f"[{np.min(carrier_lock_metric):.3f}, {np.max(carrier_lock_metric):.3f}], "
        f"弱锁定占比 = {100.0 * np.mean(carrier_lock_weak):.2f}%"
    )
    print(
        "  - PLL 判别器超线性区占比 = "
        f"{100.0 * np.mean(pll_out_of_linear):.2f}% "
        f"(阈值 |e_pll| > {pll_linear_limit_rad:.2f} rad)"
    )
    print(
        "  - DLL 判别器超线性区占比 = "
        f"{100.0 * np.mean(dll_out_of_linear):.2f}% "
        f"(阈值 |e_dll| > {dll_linear_limit:.2f})"
    )
    print(f"  - Prompt SNR < {weak_prompt_snr_db:.1f} dB 占比 = {100.0 * np.mean(weak_prompt):.2f}%")
    print(f"  - FLL 辅助占比 = {100.0 * np.mean(fll_active):.2f}%")
    print(f"  - DLL 冻结占比 = {100.0 * (1.0 - np.mean(dll_update_enabled)):.2f}%")
    print(f"  - PLL 冻结占比 = {100.0 * (1.0 - np.mean(pll_update_enabled)):.2f}%")
    print(f"  - PLL 积分器夹限次数 = {int(pll_integrator_clamped.sum())}")
    print(f"  - PLL 频率命令夹限次数 = {int(pll_freq_clamped.sum())}")
    print(
        "  - 真值多普勒范围 = "
        f"[{np.min(fd_true_hz)/1e3:.3f}, {np.max(fd_true_hz)/1e3:.3f}] kHz, "
        f"最大变化率 = {np.max(np.abs(fd_true_rate_hz_per_s)):.3f} Hz/s"
    )
    print(
        "  - 真值码时延变化率范围 = "
        f"[{np.min(tau_true_rate_ns_per_s):.3f}, {np.max(tau_true_rate_ns_per_s):.3f}] ns/s"
    )
    print(
        "  - PLL 积分器工作范围 = "
        f"[{np.min(pll_integrator)/1e3:.3f}, {np.max(pll_integrator)/1e3:.3f}] kHz"
    )
    print(
        "  - PLL 频率命令范围 = "
        f"[{np.min(pll_freq_cmd_hz)/1e3:.3f}, {np.max(pll_freq_cmd_hz)/1e3:.3f}] kHz"
    )
    print(
        "  - FLL 误差范围 = "
        f"[{np.min(fll_err_hz):.3f}, {np.max(fll_err_hz):.3f}] Hz"
    )

    if loss_found:
        print(
            "  - 首次持续失锁时刻 = "
            f"{t[loss_start_idx]:.6f} s "
            f"(连续 {min_loss_run_blocks} 个积分块满足失锁判据)"
        )
    else:
        print(
            "  - 首次持续失锁时刻 = 未检测到 "
            f"(判据窗口 {min_loss_run_blocks} blocks)"
        )

    segment_tau_rmse_ns = []
    segment_fd_rmse_hz = []
    segment_prompt_snr_db = []
    segment_pll_rms = []
    segment_dll_rms = []
    segment_loss_frac = []

    for name, slc in build_segment_slices(len(t)).items():
        tau_rmse_ns = rms(tau_err_s[slc]) * 1e9
        fd_rmse_local_hz = rms(fd_err_hz[slc])
        prompt_snr_local_db = float(np.median(post_corr_snr_db[slc]))
        pll_rms_local = rms(pll_err[slc])
        dll_rms_local = rms(dll_err[slc])
        loss_frac_local = float(np.mean(sustained_loss[slc]))

        segment_tau_rmse_ns.append(tau_rmse_ns)
        segment_fd_rmse_hz.append(fd_rmse_local_hz)
        segment_prompt_snr_db.append(prompt_snr_local_db)
        segment_pll_rms.append(pll_rms_local)
        segment_dll_rms.append(dll_rms_local)
        segment_loss_frac.append(loss_frac_local)

        print(
            f"    {name}: tau_RMSE = {tau_rmse_ns:.3f} ns, "
            f"fd_RMSE = {fd_rmse_local_hz:.3f} Hz, "
            f"Prompt_SNR_med = {prompt_snr_local_db:.3f} dB, "
            f"PLL_RMS = {pll_rms_local:.4f} rad, "
            f"DLL_RMS = {dll_rms_local:.4f}, "
            f"loss_frac = {100.0 * loss_frac_local:.2f}%"
        )

    return {
        "pll_linear_limit_rad": pll_linear_limit_rad,
        "dll_linear_limit": dll_linear_limit,
        "weak_prompt_snr_db": weak_prompt_snr_db,
        "min_loss_run_blocks": int(min_loss_run_blocks),
        "pll_out_of_linear": pll_out_of_linear,
        "dll_out_of_linear": dll_out_of_linear,
        "weak_prompt": weak_prompt,
        "carrier_lock_weak": carrier_lock_weak,
        "quadrature_dominant": quadrature_dominant,
        "sustained_loss": sustained_loss,
        "loss_found": bool(loss_found),
        "loss_start_idx": int(loss_start_idx),
        "fd_true_rate_hz_per_s": fd_true_rate_hz_per_s,
        "tau_true_rate_ns_per_s": tau_true_rate_ns_per_s,
        "prompt_early_late_ratio": prompt_early_late_ratio,
        "segment_tau_rmse_ns": np.asarray(segment_tau_rmse_ns, dtype=float),
        "segment_fd_rmse_hz": np.asarray(segment_fd_rmse_hz, dtype=float),
        "segment_prompt_snr_db": np.asarray(segment_prompt_snr_db, dtype=float),
        "segment_pll_rms": np.asarray(segment_pll_rms, dtype=float),
        "segment_dll_rms": np.asarray(segment_dll_rms, dtype=float),
        "segment_loss_frac": np.asarray(segment_loss_frac, dtype=float),
    }


# ============================================================
# 9. 接收机对象化封装
# ============================================================

class AcquisitionEngine:
    def __init__(self, context: ReceiverRuntimeContext) -> None:
        self.context = context

    def run(self) -> Dict[str, Any]:
        return run_acquisition(
            cfg_sig=self.context.cfg_sig,
            cfg_motion=self.context.cfg_motion,
            cfg_acq=self.context.cfg_acq,
            code_chips=self.context.code_chips,
            plasma_rx=self.context.plasma_rx,
            global_rx_time_s=self.context.global_rx_time_s,
        )

    def diagnose(self, acq_result: Dict[str, Any]) -> Dict[str, Any]:
        return diagnose_acquisition_physics(
            cfg_sig=self.context.cfg_sig,
            cfg_motion=self.context.cfg_motion,
            cfg_acq=self.context.cfg_acq,
            acq_result=acq_result,
            plasma_rx=self.context.plasma_rx,
            global_rx_time_s=self.context.global_rx_time_s,
        )


class TrackingEngine:
    def __init__(self, context: ReceiverRuntimeContext) -> None:
        self.context = context

    def run(self, acq_result: Dict[str, Any]) -> Dict[str, Any]:
        return run_tracking(
            cfg_sig=self.context.cfg_sig,
            cfg_motion=self.context.cfg_motion,
            cfg_trk=self.context.cfg_trk,
            code_chips=self.context.code_chips,
            plasma_rx=self.context.plasma_rx,
            global_rx_time_s=self.context.global_rx_time_s,
            acq_result=acq_result,
        )

    def diagnose(self, trk_result: Dict[str, Any]) -> Dict[str, Any]:
        return diagnose_tracking_physics(
            cfg_sig=self.context.cfg_sig,
            cfg_trk=self.context.cfg_trk,
            trk_result=trk_result,
        )


class KaBpskReceiver:
    """
    接收机编排层。

    职责只有两个：
    1. 固化 acquisition -> tracking -> diagnostics 的执行顺序
    2. 给后续协作留一个稳定入口
    """
    def __init__(self, context: ReceiverRuntimeContext) -> None:
        self.context = context
        self.acquisition = AcquisitionEngine(context)
        self.tracking = TrackingEngine(context)

    def run(self) -> ReceiverRunArtifacts:
        acq_result = self.acquisition.run()
        acq_diag = self.acquisition.diagnose(acq_result)
        trk_result = self.tracking.run(acq_result)
        trk_diag = self.tracking.diagnose(trk_result)

        return ReceiverRunArtifacts(
            acq_result=acq_result,
            acq_diag=acq_diag,
            trk_result=trk_result,
            trk_diag=trk_diag,
        )


# ============================================================
# 10. 绘图
# ============================================================

def plot_receiver_results(
    plot_cfg: PlotConfig,
    t_eval_rel: np.ndarray,
    ne_large: np.ndarray,
    ne_meso: np.ndarray,
    ne_combined: np.ndarray,
    z_eval: np.ndarray,
    wkb_result: Dict[str, np.ndarray],
    cfg_sig: SignalConfig,
    cfg_acq: AcquisitionConfig,
    cfg_trk: TrackingConfig,
    acq_result: Dict[str, np.ndarray | float],
    acq_diag: Dict[str, np.ndarray | float],
    trk_result: Dict[str, np.ndarray],
    trk_diag: Dict[str, np.ndarray | float],
) -> None:
    """
    绘制接收机内部链路的可选图形。
    """
    if not plot_cfg.enabled and plot_cfg.save_dir is None:
        return

    print("\n[步骤 E] 绘制可选图形")

    if plot_cfg.show_field_context and plot_cfg.enabled:
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

    if plot_cfg.show_receiver_overview:
        fig, axes = plt.subplots(4, 2, figsize=(16, 18), dpi=120)
        ax = axes.ravel()

        ax[0].plot(wkb_result["wkb_time_s"], db20(wkb_result["A_t"]), lw=1.3)
        ax[0].set_title("Channel Amplitude A(t)")
        ax[0].set_xlabel("Time (s)")
        ax[0].set_ylabel("Amplitude (dB)")
        ax[0].grid(True, ls=":", alpha=0.5)

        ax[1].plot(wkb_result["wkb_time_s"], wkb_result["tau_g_t"] * 1e9, lw=1.3, color="tab:green")
        ax[1].set_title("Group Delay")
        ax[1].set_xlabel("Time (s)")
        ax[1].set_ylabel("Delay (ns)")
        ax[1].grid(True, ls=":", alpha=0.5)

        ax[2].plot(trk_result["t"], trk_result["tau_est_s"] * 1e6, lw=1.2, label="Estimate")
        ax[2].plot(trk_result["t"], trk_result["tau_true_s"] * 1e6, lw=1.0, ls="--", color="black", label="Truth")
        ax[2].plot(trk_result["t"], trk_result["tau_predict_s"] * 1e6, lw=1.0, color="tab:gray", alpha=0.9, label="Predictor")
        ax[2].set_title("Code Delay: Truth / Predictor / Estimate")
        ax[2].set_xlabel("Time (s)")
        ax[2].set_ylabel("Delay (us)")
        ax[2].legend()
        ax[2].grid(True, ls=":", alpha=0.5)

        ax[3].plot(trk_result["t"], trk_result["fd_est_hz"] / 1e3, lw=1.2, label="Estimate")
        ax[3].plot(trk_result["t"], trk_result["fd_true_hz"] / 1e3, lw=1.0, ls="--", color="black", label="Truth")
        ax[3].plot(trk_result["t"], trk_result["carrier_freq_center_hz"] / 1e3, lw=1.0, color="tab:gray", alpha=0.9, label="Predictor")
        ax[3].set_title("Carrier Frequency: Truth / Predictor / Estimate")
        ax[3].set_xlabel("Time (s)")
        ax[3].set_ylabel("Frequency (kHz)")
        ax[3].legend()
        ax[3].grid(True, ls=":", alpha=0.5)

        ax[4].plot(trk_result["t"], trk_result["post_corr_snr_db"], lw=1.2, label="Measured")
        ax[4].plot(trk_result["t"], trk_result["predicted_post_corr_snr_db"], lw=1.0, color="tab:red", label="Predicted")
        ax[4].axhline(0.0, color="black", ls="--", lw=1.0)
        ax[4].set_title("Post-correlation SNR")
        ax[4].set_xlabel("Time (s)")
        ax[4].set_ylabel("SNR (dB)")
        ax[4].legend()
        ax[4].grid(True, ls=":", alpha=0.5)

        ax[5].plot(trk_result["t"], trk_result["mag_E"], lw=1.1, label="|E|")
        ax[5].plot(trk_result["t"], trk_result["mag_P"], lw=1.1, label="|P|")
        ax[5].plot(trk_result["t"], trk_result["mag_L"], lw=1.1, label="|L|")
        ax[5].set_title("Correlator Magnitudes")
        ax[5].set_xlabel("Time (s)")
        ax[5].set_ylabel("Magnitude")
        ax[5].legend()
        ax[5].grid(True, ls=":", alpha=0.5)

        ax[6].plot(trk_result["t"], trk_result["pseudorange_m"], lw=1.2, color="tab:orange", label="Estimate")
        ax[6].plot(trk_result["t"], C_LIGHT * trk_result["tau_true_s"], lw=1.0, ls="--", color="black", label="Truth")
        ax[6].set_title("Pseudorange Observable")
        ax[6].set_xlabel("Time (s)")
        ax[6].set_ylabel("Range (m)")
        ax[6].legend()
        ax[6].grid(True, ls=":", alpha=0.5)

        ax[7].scatter(trk_result["I_P"], trk_result["Q_P"], s=5, alpha=0.35)
        ax[7].set_title("Prompt Constellation")
        ax[7].set_xlabel("I")
        ax[7].set_ylabel("Q")
        ax[7].grid(True, ls=":", alpha=0.5)
        ax[7].set_aspect("equal", adjustable="box")

        finalize_figure(fig, plot_cfg, "receiver_overview")

    if plot_cfg.show_acquisition_internal:
        t_block_ms = np.asarray(acq_result["t_block_s"]) * 1e3
        rx_block = np.asarray(acq_result["rx_block"])
        best_mixed = np.asarray(acq_result["best_mixed"])
        best_local_code = np.asarray(acq_result["best_local_code"])
        coarse_metric_db = np.asarray(db10(acq_result["metric"]))
        refine_metric_db = np.asarray(db10(acq_result["refine_metric"]))
        freq_hz, spec_db = compute_spectrum_db(rx_block, cfg_sig.fs_hz)
        fine_freq_hz, fine_spec_db = compute_spectrum_db(best_mixed, cfg_sig.fs_hz)

        fig, axes = plt.subplots(3, 2, figsize=(16, 16), dpi=120)

        axes[0, 0].plot(t_block_ms, rx_block.real, lw=1.0, label="I")
        axes[0, 0].plot(t_block_ms, rx_block.imag, lw=1.0, label="Q")
        axes[0, 0].plot(t_block_ms, np.abs(rx_block), lw=1.2, color="black", alpha=0.8, label="|r|")
        axes[0, 0].set_title("Acquisition Block: Raw Complex Samples")
        axes[0, 0].set_xlabel("Time (ms)")
        axes[0, 0].set_ylabel("Amplitude")
        axes[0, 0].legend()
        axes[0, 0].grid(True, ls=":", alpha=0.5)

        axes[0, 1].plot(freq_hz / 1e3, spec_db, lw=1.0, label="Raw")
        axes[0, 1].plot(fine_freq_hz / 1e3, fine_spec_db, lw=1.0, label="After best wipeoff")
        axes[0, 1].set_title("Acquisition Block Spectrum")
        axes[0, 1].set_xlabel("Frequency (kHz)")
        axes[0, 1].set_ylabel("Magnitude (dB)")
        axes[0, 1].legend()
        axes[0, 1].grid(True, ls=":", alpha=0.5)

        im0 = axes[1, 0].imshow(
            coarse_metric_db,
            origin="lower",
            aspect="auto",
            extent=[
                acq_result["code_offsets"][0] / cfg_sig.fs_hz * 1e6,
                acq_result["code_offsets"][-1] / cfg_sig.fs_hz * 1e6,
                acq_result["fd_grid"][0] / 1e3,
                acq_result["fd_grid"][-1] / 1e3,
            ],
            cmap="viridis",
        )
        axes[1, 0].scatter(
            [acq_diag["tau_true_mod_s"] * 1e6],
            [acq_diag["fd_true_hz"] / 1e3],
            color="white",
            marker="x",
            s=60,
            label="Truth",
        )
        axes[1, 0].scatter(
            [acq_result["tau_hat_coarse_s"] * 1e6],
            [acq_result["fd_hat_coarse_hz"] / 1e3],
            color="red",
            marker="o",
            s=36,
            label="Coarse peak",
        )
        axes[1, 0].set_title("Coarse Acquisition Metric")
        axes[1, 0].set_xlabel("Code delay (us)")
        axes[1, 0].set_ylabel("Frequency (kHz)")
        axes[1, 0].legend()
        fig.colorbar(im0, ax=axes[1, 0], label="Metric (dB)")

        im1 = axes[1, 1].imshow(
            refine_metric_db,
            origin="lower",
            aspect="auto",
            extent=[
                acq_result["refine_tau_s"][0] * 1e6,
                acq_result["refine_tau_s"][-1] * 1e6,
                acq_result["refine_fd_grid"][0] / 1e3,
                acq_result["refine_fd_grid"][-1] / 1e3,
            ],
            cmap="viridis",
        )
        axes[1, 1].scatter(
            [acq_diag["tau_true_mod_s"] * 1e6],
            [acq_diag["fd_true_hz"] / 1e3],
            color="white",
            marker="x",
            s=60,
            label="Truth",
        )
        axes[1, 1].scatter(
            [acq_result["tau_hat_s"] * 1e6],
            [acq_result["fd_hat_hz"] / 1e3],
            color="red",
            marker="o",
            s=36,
            label="Refined peak",
        )
        axes[1, 1].set_title("Refined Acquisition Metric")
        axes[1, 1].set_xlabel("Code delay (us)")
        axes[1, 1].set_ylabel("Frequency (kHz)")
        axes[1, 1].legend()
        fig.colorbar(im1, ax=axes[1, 1], label="Metric (dB)")

        coarse_fd_idx = int(np.argmin(np.abs(acq_result["fd_grid"] - acq_result["fd_hat_coarse_hz"])))
        code_delay_us = np.asarray(acq_result["code_offsets"]) / cfg_sig.fs_hz * 1e6
        axes[2, 0].plot(code_delay_us, coarse_metric_db[coarse_fd_idx, :], lw=1.2)
        axes[2, 0].axvline(acq_diag["tau_true_mod_s"] * 1e6, color="black", ls="--", lw=1.0, label="Truth")
        axes[2, 0].axvline(acq_result["tau_hat_coarse_s"] * 1e6, color="tab:red", lw=1.0, label="Coarse")
        axes[2, 0].axvline(acq_result["tau_hat_s"] * 1e6, color="tab:green", lw=1.0, label="Refined")
        axes[2, 0].set_title("Code-delay Cut at Best Coarse Frequency")
        axes[2, 0].set_xlabel("Code delay (us)")
        axes[2, 0].set_ylabel("Metric (dB)")
        axes[2, 0].legend()
        axes[2, 0].grid(True, ls=":", alpha=0.5)

        axes[2, 1].plot(t_block_ms, best_mixed.real, lw=1.0, label="Baseband I")
        axes[2, 1].plot(t_block_ms, best_mixed.imag, lw=1.0, label="Baseband Q")
        axes[2, 1].plot(t_block_ms, best_local_code.real, lw=1.0, color="black", alpha=0.8, label="Local code")
        axes[2, 1].set_title("Best Acquisition Hypothesis: Wipeoff + Local Code")
        axes[2, 1].set_xlabel("Time (ms)")
        axes[2, 1].set_ylabel("Amplitude")
        axes[2, 1].legend()
        axes[2, 1].grid(True, ls=":", alpha=0.5)

        finalize_figure(fig, plot_cfg, "receiver_acquisition_internal")

    if plot_cfg.show_tracking_internal:
        fig, axes = plt.subplots(4, 2, figsize=(16, 18), dpi=120)

        axes[0, 0].plot(trk_result["t"], trk_result["dll_err"], lw=1.1, label="DLL error")
        axes[0, 0].axhline(0.20, color="black", ls="--", lw=1.0)
        axes[0, 0].axhline(-0.20, color="black", ls="--", lw=1.0)
        axes[0, 0].set_title("DLL Discriminator")
        axes[0, 0].set_xlabel("Time (s)")
        axes[0, 0].set_ylabel("Error")
        axes[0, 0].legend()
        axes[0, 0].grid(True, ls=":", alpha=0.5)

        axes[0, 1].plot(trk_result["t"], trk_result["pll_err"], lw=1.1, label="PLL error")
        axes[0, 1].axhline(0.35, color="black", ls="--", lw=1.0)
        axes[0, 1].axhline(-0.35, color="black", ls="--", lw=1.0)
        axes[0, 1].set_title("PLL Phase Discriminator")
        axes[0, 1].set_xlabel("Time (s)")
        axes[0, 1].set_ylabel("Error (rad)")
        axes[0, 1].legend()
        axes[0, 1].grid(True, ls=":", alpha=0.5)

        axes[1, 0].plot(trk_result["t"], trk_result["carrier_lock_metric"], lw=1.1, label="Lock metric")
        axes[1, 0].axhline(cfg_trk.carrier_lock_metric_threshold, color="black", ls="--", lw=1.0, label="Threshold")
        axes[1, 0].plot(trk_result["t"], trk_result["prompt_quadrature_ratio"], lw=1.0, alpha=0.8, label="|Q|/|I|")
        axes[1, 0].set_title("Carrier Lock Indicators")
        axes[1, 0].set_xlabel("Time (s)")
        axes[1, 0].set_ylabel("Metric")
        axes[1, 0].legend()
        axes[1, 0].grid(True, ls=":", alpha=0.5)

        axes[1, 1].plot(trk_result["t"], trk_result["pll_integrator_hz"] / 1e3, lw=1.1, label="PLL integrator")
        axes[1, 1].plot(trk_result["t"], trk_result["pll_freq_cmd_hz"] / 1e3, lw=1.1, label="PLL cmd")
        axes[1, 1].plot(trk_result["t"], trk_result["carrier_freq_center_hz"] / 1e3, lw=1.0, color="tab:gray", label="Predictor")
        axes[1, 1].set_title("Carrier NCO Internals")
        axes[1, 1].set_xlabel("Time (s)")
        axes[1, 1].set_ylabel("Frequency (kHz)")
        axes[1, 1].legend()
        axes[1, 1].grid(True, ls=":", alpha=0.5)

        axes[2, 0].plot(trk_result["t"], trk_result["fll_err_hz"], lw=1.1, label="FLL error")
        axes[2, 0].set_title("FLL Assistance Error")
        axes[2, 0].set_xlabel("Time (s)")
        axes[2, 0].set_ylabel("Error (Hz)")
        axes[2, 0].legend()
        axes[2, 0].grid(True, ls=":", alpha=0.5)

        axes[2, 1].step(trk_result["t"], trk_result["dll_update_enabled"].astype(float), where="mid", lw=1.0, label="DLL enabled")
        axes[2, 1].step(trk_result["t"], trk_result["pll_update_enabled"].astype(float), where="mid", lw=1.0, label="PLL enabled")
        axes[2, 1].step(trk_result["t"], trk_result["fll_active"].astype(float), where="mid", lw=1.0, label="FLL active")
        axes[2, 1].step(trk_result["t"], trk_diag["sustained_loss"].astype(float), where="mid", lw=1.0, label="Loss flag")
        axes[2, 1].set_title("Loop Gating and Loss Flags")
        axes[2, 1].set_xlabel("Time (s)")
        axes[2, 1].set_ylabel("State")
        axes[2, 1].set_ylim(-0.1, 1.1)
        axes[2, 1].legend()
        axes[2, 1].grid(True, ls=":", alpha=0.5)

        axes[3, 0].plot(trk_result["t"], trk_result["tau_err_s"] * 1e9, lw=1.1, label="Code error")
        axes[3, 0].plot(trk_result["t"], trk_result["fd_err_hz"], lw=1.1, label="Carrier error")
        axes[3, 0].set_title("Tracking Errors")
        axes[3, 0].set_xlabel("Time (s)")
        axes[3, 0].set_ylabel("Error (ns / Hz)")
        axes[3, 0].legend()
        axes[3, 0].grid(True, ls=":", alpha=0.5)

        axes[3, 1].plot(trk_result["t"], trk_result["I_P"], lw=1.0, label="I_P")
        axes[3, 1].plot(trk_result["t"], trk_result["Q_P"], lw=1.0, label="Q_P")
        axes[3, 1].set_title("Prompt Correlator Outputs")
        axes[3, 1].set_xlabel("Time (s)")
        axes[3, 1].set_ylabel("Correlation")
        axes[3, 1].legend()
        axes[3, 1].grid(True, ls=":", alpha=0.5)

        finalize_figure(fig, plot_cfg, "receiver_tracking_internal")

    if plot_cfg.show_tracking_snapshots:
        snapshots = trk_result.get("tracking_snapshots", {})
        if snapshots:
            order = [key for key in ("start", "mid", "end") if key in snapshots]
            fig, axes = plt.subplots(len(order), 4, figsize=(18, 5 * len(order)), dpi=120, squeeze=False)

            for row, key in enumerate(order):
                snap = snapshots[key]
                t_ms = np.asarray(snap["t_block_s"]) * 1e3
                raw_freq_hz, raw_spec_db = compute_spectrum_db(np.asarray(snap["rx_block"]), cfg_sig.fs_hz)
                bb_freq_hz, bb_spec_db = compute_spectrum_db(np.asarray(snap["baseband"]), cfg_sig.fs_hz)

                axes[row, 0].plot(t_ms, np.asarray(snap["rx_block"]).real, lw=1.0, label="Raw I")
                axes[row, 0].plot(t_ms, np.asarray(snap["rx_block"]).imag, lw=1.0, label="Raw Q")
                axes[row, 0].plot(t_ms, np.abs(np.asarray(snap["rx_block"])), lw=1.1, color="black", alpha=0.8, label="|r|")
                axes[row, 0].set_title(f"{key} block: raw samples")
                axes[row, 0].set_xlabel("Time (ms)")
                axes[row, 0].set_ylabel("Amplitude")
                axes[row, 0].legend()
                axes[row, 0].grid(True, ls=":", alpha=0.5)

                axes[row, 1].plot(t_ms, np.asarray(snap["baseband"]).real, lw=1.0, label="BB I")
                axes[row, 1].plot(t_ms, np.asarray(snap["baseband"]).imag, lw=1.0, label="BB Q")
                axes[row, 1].plot(t_ms, np.abs(np.asarray(snap["baseband"])), lw=1.1, color="black", alpha=0.8, label="|bb|")
                axes[row, 1].set_title(
                    f"{key} block: carrier wiped\n"
                    f"t={snap['t_mid_s']:.3f}s, fd={snap['carrier_freq_hz']/1e3:.3f}kHz"
                )
                axes[row, 1].set_xlabel("Time (ms)")
                axes[row, 1].set_ylabel("Amplitude")
                axes[row, 1].legend()
                axes[row, 1].grid(True, ls=":", alpha=0.5)

                axes[row, 2].plot(t_ms, np.asarray(snap["prompt_code"]).real, lw=1.0, label="Prompt")
                axes[row, 2].plot(t_ms, np.asarray(snap["early_code"]).real, lw=1.0, label="Early")
                axes[row, 2].plot(t_ms, np.asarray(snap["late_code"]).real, lw=1.0, label="Late")
                axes[row, 2].set_title(
                    f"{key} block: local code replicas\n"
                    f"DLL={snap['dll_err']:+.3f}, PLL={snap['pll_err']:+.3f}"
                )
                axes[row, 2].set_xlabel("Time (ms)")
                axes[row, 2].set_ylabel("Code value")
                axes[row, 2].legend()
                axes[row, 2].grid(True, ls=":", alpha=0.5)

                axes[row, 3].plot(raw_freq_hz / 1e3, raw_spec_db, lw=1.0, label="Raw")
                axes[row, 3].plot(bb_freq_hz / 1e3, bb_spec_db, lw=1.0, label="Baseband")
                axes[row, 3].set_title(
                    f"{key} block spectrum\n"
                    f"SNR={snap['post_corr_snr_db']:.2f}dB, lock={snap['carrier_lock_metric']:.2f}"
                )
                axes[row, 3].set_xlabel("Frequency (kHz)")
                axes[row, 3].set_ylabel("Magnitude (dB)")
                axes[row, 3].legend()
                axes[row, 3].grid(True, ls=":", alpha=0.5)

            finalize_figure(fig, plot_cfg, "receiver_tracking_snapshots")


# ============================================================
# 11. 主流程
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
        refine_fd_step_hz=100.0,
        refine_code_step_samples=0.1,
        refine_half_span_fd_hz=1.0e3,
        refine_half_span_code_samples=2.0,
    )

    cfg_trk = TrackingConfig(
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
    # G. 接收机链路（捕获 + 跟踪 + 诊断）
    # --------------------------------------------------------
    receiver_context = ReceiverRuntimeContext(
        cfg_sig=cfg_sig,
        cfg_motion=cfg_motion,
        cfg_acq=cfg_acq,
        cfg_trk=cfg_trk,
        code_chips=code_chips,
        plasma_rx=plasma_rx,
        global_rx_time_s=rx_time_s,
    )
    receiver = KaBpskReceiver(receiver_context)
    receiver_outputs = receiver.run()
    acq_result = receiver_outputs.acq_result
    acq_diag = receiver_outputs.acq_diag

    # --------------------------------------------------------
    # H. 取出关键结果
    # --------------------------------------------------------
    trk_result = receiver_outputs.trk_result
    trk_diag = receiver_outputs.trk_diag

    # --------------------------------------------------------
    # I. 输出总结
    # --------------------------------------------------------
    print("\n[最终输出观测量]")
    print(f"  - pseudorange 样本数 = {len(trk_result['pseudorange_m'])}")
    print(f"  - carrier phase 样本数 = {len(trk_result['carrier_phase_cycles'])}")
    print(f"  - Doppler 样本数 = {len(trk_result['doppler_hz'])}")
    print(f"  - 码时延 RMSE = {float(trk_result['tau_rmse_ns'][0]):.3f} ns")
    print(f"  - 频偏 RMSE = {float(trk_result['fd_rmse_hz'][0]):.3f} Hz")
    print(
        "  - 捕获主峰/次峰比 = "
        f"{float(acq_diag['peak_to_second_ratio']):.3f} "
        f"({float(acq_diag['peak_to_second_db']):.3f} dB)"
    )
    print(
        "  - PLL 积分器夹限次数 = "
        f"{int(np.sum(trk_result['pll_integrator_clamped']))}"
    )
    print(
        "  - PLL 频率命令夹限次数 = "
        f"{int(np.sum(trk_result['pll_freq_clamped']))}"
    )
    if bool(trk_diag["loss_found"]):
        loss_idx = int(trk_diag["loss_start_idx"])
        print(f"  - 首次持续失锁时刻 = {trk_result['t'][loss_idx]:.6f} s")
    else:
        print("  - 首次持续失锁时刻 = 未检测到")

    print("\n[接收机说明]")
    print("  - 当前接收机处理时长 = 真实 WKB 时间范围")
    print("  - 当前等离子体传播 = 真实 WKB A(t), phi(t), tau_g(t)")
    print("  - 当前卫星/机动多普勒 = 外部抽象输入")
    print("  - acquisition / DLL / PLL = 显式实现，并未直接跳成理想观测")
    print("  - 当前 NCO 预测器 = 线性码率先验 + 线性多普勒率先验 + FLL 辅助 PLL")
    print("  - 当前架构 = ReceiverRuntimeContext / AcquisitionEngine / TrackingEngine / KaBpskReceiver")
    print("  - 当前调试重点 = 捕获峰结构、后相关 SNR、环路线性区、失锁判据、夹限统计")

    # --------------------------------------------------------
    # J. 可选绘图（默认关闭）
    # --------------------------------------------------------
    plot_cfg = PlotConfig(
        enabled=False,
        show_field_context=False,
        show_receiver_overview=True,
        show_acquisition_internal=True,
        show_tracking_internal=True,
        show_tracking_snapshots=True,
        save_dir=None,
    )

    if plot_cfg.enabled or plot_cfg.save_dir is not None:
        plot_receiver_results(
            plot_cfg=plot_cfg,
            t_eval_rel=t_eval_rel,
            ne_large=ne_large,
            ne_meso=ne_meso,
            ne_combined=ne_combined,
            z_eval=z_eval,
            wkb_result=wkb_result,
            cfg_sig=cfg_sig,
            cfg_acq=cfg_acq,
            cfg_trk=cfg_trk,
            acq_result=acq_result,
            acq_diag=acq_diag,
            trk_result=trk_result,
            trk_diag=trk_diag,
        )


if __name__ == "__main__":
    np.random.seed(2026)
    main()
