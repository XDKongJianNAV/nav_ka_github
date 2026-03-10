"""
plasma_wkb_core.py
==================

这个文件专门负责“电子密度场 -> WKB 传播响应”的功能计算。

它从已经生成好的电子密度剖面或二维电子密度场出发，计算电磁波穿过
非均匀等离子体鞘套后的传播结果，包括：

1. 单个电子密度剖面的 WKB 传输系数
2. 全时域电子密度矩阵的 WKB 扫描结果
3. 电子密度场的物理合规性自检与数值修正
4. 传播结果的后处理整理（例如 attenuation_dB）

----------------------------------------------------------------------
本文件负责的内容
----------------------------------------------------------------------

- 电子密度场合法性检查
- 局部等离子体频率计算
- 含碰撞项的局部传播常数 alpha(z), beta(z) 计算
- 沿 z 方向积分得到幅度衰减和总相移
- 全时域扫描得到 A(t), phi(t), h_p(t)

----------------------------------------------------------------------
本文件故意不负责的内容
----------------------------------------------------------------------

1. 不做绘图
2. 不做 notebook 交互
3. 不做 BPSK/QPSK 星座构造
4. 不做导航观测生成
5. 不做 EKF / IMU 融合

也就是说，这个文件的功能边界是：

    电子密度场  --->  WKB 传播结果

后续你可以在新的文件里接：
- 传播结果 -> 观测量
- 传播结果 -> 绘图
- 传播结果 -> 信号失真与导航分析

----------------------------------------------------------------------
当前物理近似
----------------------------------------------------------------------

1. 冷等离子体近似 + 碰撞项
2. 局部等离子体频率：
       omega_p = sqrt(Ne * e^2 / (eps0 * me))
3. 局部传播常数由 eps_real, eps_imag 推出 alpha(z), beta(z)
4. 使用 WKB 近似沿 z 方向积分
5. 当前默认输入 nu_en 为普通频率 Hz，内部统一乘 2*pi 作为角频率量纲处理

如果后续你确认某批 nu_en 数据已经是 rad/s，可以在函数中将
collision_input_unit 设置为 "rad_s"。
"""

from __future__ import annotations

from typing import Literal, Optional

import numpy as np
from scipy.integrate import trapezoid


# ============================================================================
# 1. 物理常数
# ============================================================================

C_LIGHT = 2.99792458e8
E_CHARGE = 1.60217663e-19
EPS0 = 8.85418781e-12
M_E = 9.10938356e-31


# ============================================================================
# 2. 基础工具函数
# ============================================================================

def _to_angular_collision_frequency(
    nu_en: float | np.ndarray,
    collision_input_unit: Literal["Hz", "rad_s"] = "Hz",
) -> float | np.ndarray:
    """
    将碰撞频率统一转换为角频率量纲。

    参数
    ----
    nu_en:
        输入碰撞频率，可以是标量或数组。

    collision_input_unit:
        - "Hz"    : 输入是普通频率，内部乘 2*pi
        - "rad_s" : 输入已经是角频率，不再转换
    """
    if collision_input_unit == "Hz":
        return 2.0 * np.pi * nu_en
    if collision_input_unit == "rad_s":
        return nu_en
    raise ValueError("collision_input_unit 只能是 'Hz' 或 'rad_s'。")


def _validate_profile_inputs(
    z_grid: np.ndarray,
    ne_profile: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    检查单剖面输入是否合法。

    要求：
    1. z_grid 和 ne_profile 都是一维
    2. 长度一致
    3. z_grid 至少两个点
    4. z_grid 严格递增
    """
    z = np.asarray(z_grid, dtype=float).reshape(-1)
    ne = np.asarray(ne_profile, dtype=float).reshape(-1)

    if z.size != ne.size:
        raise ValueError("z_grid 与 ne_profile 长度不一致。")
    if z.size < 2:
        raise ValueError("z_grid 至少需要两个点。")
    if not np.all(np.diff(z) > 0):
        raise ValueError("z_grid 必须严格递增。")

    return z, ne


def _broadcast_collision_frequency(
    nu_en: float | np.ndarray,
    z_grid: np.ndarray,
) -> np.ndarray:
    """
    将碰撞频率整理成与 z_grid 同长度的一维数组。
    """
    nu = np.asarray(nu_en, dtype=float)

    if nu.ndim == 0:
        return np.full_like(z_grid, float(nu), dtype=float)

    nu = nu.reshape(-1)
    if nu.size != z_grid.size:
        raise ValueError("nu_en 若为数组，则长度必须与 z_grid 一致。")
    return nu


def _compute_local_wkb_coefficients(
    f_em: float,
    ne_profile: np.ndarray,
    nu_en: np.ndarray,
    collision_input_unit: Literal["Hz", "rad_s"] = "Hz",
) -> tuple[np.ndarray, np.ndarray]:
    """
    计算局部传播常数 alpha(z) 和 beta(z)。

    数学说明
    --------
    入射波角频率：
        omega = 2*pi*f_em

    局部等离子体频率：
        omega_p = sqrt(Ne * e^2 / (eps0 * me))

    含碰撞项的等效量：
        denom    = omega^2 + nu^2
        eps_real = 1 - omega_p^2 / denom
        eps_imag = (nu / omega) * (omega_p^2 / denom)

    然后：
        common = sqrt(eps_real^2 + eps_imag^2)
        alpha  = (omega / (sqrt(2)*c)) * sqrt(-eps_real + common)
        beta   = (omega / (sqrt(2)*c)) * sqrt( eps_real + common)

    数值保护
    --------
    对根号内部统一做 maximum(0, ·)，防止数值误差造成极小负值。
    """
    omega = 2.0 * np.pi * f_em
    v_en = _to_angular_collision_frequency(
        nu_en,
        collision_input_unit=collision_input_unit,
    )

    omega_p = np.sqrt(np.maximum(0.0, ne_profile) * E_CHARGE**2 / (EPS0 * M_E))

    denom = omega**2 + v_en**2
    eps_real = 1.0 - (omega_p**2 / denom)
    eps_imag = (v_en / omega) * (omega_p**2 / denom)

    common = np.sqrt(eps_real**2 + eps_imag**2 + 1e-30)

    alpha_z = (omega / (np.sqrt(2.0) * C_LIGHT)) * np.sqrt(
        np.maximum(0.0, -eps_real + common)
    )
    beta_z = (omega / (np.sqrt(2.0) * C_LIGHT)) * np.sqrt(
        np.maximum(0.0, eps_real + common)
    )

    return alpha_z, beta_z


# ============================================================================
# 3. 单剖面传播求解
# ============================================================================

def calculate_wkb_transmission(
    f_EM: float,
    z_grid: np.ndarray,
    Ne_profile: np.ndarray,
    nu_en: float | np.ndarray,
    return_components: bool = False,
    collision_input_unit: Literal["Hz", "rad_s"] = "Hz",
    amplitude_floor: float = 1e-20,
) -> dict:
    """
    基于 WKB 近似计算单个非均匀等离子体剖面的电磁波传输系数。

    这是你前面两个版本函数的统一版本：
    - calculate_wkb_transmission(...)
    - calculate_wkb_transmission_robust(...)

    主要特征
    --------
    1. 保留原始字典返回风格，方便你继续沿用旧代码
    2. 引入更稳健的数值保护
    3. 支持 nu_en 为标量或沿 z 变化的数组
    4. 明确 nu_en 的输入量纲处理方式

    参数
    ----
    f_EM:
        入射电磁波频率 (Hz)

    z_grid:
        沿鞘套厚度方向的一维空间网格 (m)

    Ne_profile:
        对应的电子密度剖面 (m^-3)

    nu_en:
        电子-中性碰撞频率
        - 标量：整层统一碰撞频率
        - 数组：沿 z 变化的碰撞频率

    return_components:
        是否返回 alpha_profile 与 beta_profile

    collision_input_unit:
        指定 nu_en 的输入量纲：
        - "Hz"
        - "rad_s"

    amplitude_floor:
        对 exp(-tau) 设置下限，避免数值下溢成 0

    返回
    ----
    result:
        包含：
        - transmission_coeff
        - amplitude_attenuation
        - attenuation_dB
        - phase_shift_rad
        - alpha_profile (可选)
        - beta_profile  (可选)
    """
    z, ne = _validate_profile_inputs(z_grid, Ne_profile)
    nu_profile = _broadcast_collision_frequency(nu_en, z)

    alpha_z, beta_z = _compute_local_wkb_coefficients(
        f_em=f_EM,
        ne_profile=ne,
        nu_en=nu_profile,
        collision_input_unit=collision_input_unit,
    )

    total_attenuation_log = trapezoid(alpha_z, z)
    total_phase_shift = -trapezoid(beta_z, z)

    amplitude_attenuation = np.maximum(np.exp(-total_attenuation_log), amplitude_floor)
    transmission_coeff = amplitude_attenuation * np.exp(1j * total_phase_shift)
    attenuation_dB = 20.0 * np.log10(amplitude_attenuation + 1e-30)

    result = {
        "transmission_coeff": transmission_coeff,
        "amplitude_attenuation": float(amplitude_attenuation),
        "attenuation_dB": float(attenuation_dB),
        "phase_shift_rad": float(total_phase_shift),
    }

    if return_components:
        result["alpha_profile"] = alpha_z
        result["beta_profile"] = beta_z

    return result


def calculate_wkb_transmission_robust(
    f_EM: float,
    z_grid: np.ndarray,
    Ne_profile: np.ndarray,
    nu_en: float | np.ndarray,
    collision_input_unit: Literal["Hz", "rad_s"] = "Hz",
    amplitude_floor: float = 1e-20,
) -> dict:
    """
    与旧 notebook 习惯兼容的简化版返回接口。

    返回字段：
    - hp
    - A
    - phi

    本质上只是 calculate_wkb_transmission(...) 的简化包装。
    """
    raw = calculate_wkb_transmission(
        f_EM=f_EM,
        z_grid=z_grid,
        Ne_profile=Ne_profile,
        nu_en=nu_en,
        return_components=False,
        collision_input_unit=collision_input_unit,
        amplitude_floor=amplitude_floor,
    )

    return {
        "hp": raw["transmission_coeff"],
        "A": raw["amplitude_attenuation"],
        "phi": raw["phase_shift_rad"],
    }


# ============================================================================
# 4. 电子密度场自检与修正
# ============================================================================

def diagnose_and_fix_physics(
    ne_field: np.ndarray,
    *,
    log_threshold: float = 100.0,
    physical_floor: float = 1e10,
    verbose: bool = True,
) -> np.ndarray:
    """
    对电子密度场做基础物理与数值自检。

    这个函数对应你 notebook 里的 diagnose_and_fix_physics(ne_field)。

    当前检查三类问题：

    1. NaN / Inf
       - 这些值会直接破坏后续 sqrt、积分和 log 运算
       - 这里统一用 nan_to_num 做基础修复

    2. log 空间 / 线性空间混淆
       - 如果最大值很小（例如 < 100），对电子密度来说几乎不可能是线性量纲
       - 很可能说明当前数组其实是 log10(Ne)
       - 这时自动还原成 10 ** ne_field

    3. 非物理负值
       - 电子密度不应为负
       - 如果小尺度扰动引入负值，就用物理底噪截断到 physical_floor

    参数
    ----
    ne_field:
        输入电子密度场，可以是一维剖面，也可以是二维时间-空间矩阵

    log_threshold:
        如果 max(ne_field) < log_threshold，则认为它很可能还在 log10 空间

    physical_floor:
        对负值和过小值采用的物理下限

    verbose:
        是否打印诊断信息

    返回
    ----
    ne_fixed:
        修复后的线性量纲电子密度场
    """
    ne_fixed = np.array(ne_field, dtype=float, copy=True)

    if verbose:
        print(">>> 物理场合规性自检中...")

    # 1. 检查 NaN / Inf
    invalid_mask = ~np.isfinite(ne_fixed)
    invalid_count = int(invalid_mask.sum())
    if invalid_count > 0:
        if verbose:
            print(f"  [警告] 发现 {invalid_count} 个 NaN/Inf，已用 nan_to_num 修复。")
        ne_fixed = np.nan_to_num(ne_fixed, nan=0.0, posinf=0.0, neginf=0.0)

    # 2. 检查是否误处于 log10 空间
    ne_max = float(np.max(ne_fixed))
    if ne_max < log_threshold:
        if verbose:
            print(f"  [警告] 最大值仅为 {ne_max:.3f}，疑似仍处于 log10 空间。")
            print("  [修复] 正在执行 10**Ne，还原到线性电子密度空间。")
        ne_fixed = 10.0 ** ne_fixed
    else:
        if verbose:
            print(f"  [正常] 数据量级检测通过: Max Ne = {ne_max:.3e} m^-3")

    # 3. 检查负值
    neg_count = int((ne_fixed < 0).sum())
    if neg_count > 0:
        if verbose:
            print(f"  [警告] 发现 {neg_count} 个负值点，已截断到物理底噪 {physical_floor:.1e}。")

    ne_fixed = np.maximum(ne_fixed, physical_floor)
    return ne_fixed


# ============================================================================
# 5. 全时域 WKB 扫描
# ============================================================================

def run_wkb_analysis(
    f_EM: float,
    z_grid: np.ndarray,
    Ne_matrix: np.ndarray,
    nu_en: float | np.ndarray,
    collision_input_unit: Literal["Hz", "rad_s"] = "Hz",
    amplitude_floor: float = 1e-20,
    fix_physics: bool = True,
    verbose: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    对全时域二维电子密度场执行 WKB 扫描。

    输入
    ----
    Ne_matrix:
        shape = (nt, nz)
        其中每一行 Ne_matrix[i, :] 都表示某一时刻的电子密度剖面。

    计算流程
    --------
    对每个时间帧 i：
    1. 取出 profile = Ne_matrix[i, :]
    2. 调用单剖面 WKB 传播计算
    3. 保存：
       - A(i)
       - phi(i)
       - h_p(i)

    参数
    ----
    f_EM:
        入射电磁波频率 (Hz)

    z_grid:
        空间网格，与 Ne_matrix 的第二维一致

    Ne_matrix:
        二维电子密度矩阵，shape = (nt, nz)

    nu_en:
        碰撞频率，可以是：
        - 标量：全时域、全空间统一
        - 一维数组：与 z_grid 对应
        暂不支持 shape=(nt,nz) 的时空碰撞频率矩阵；若后续需要再扩展

    fix_physics:
        是否在计算前先对 Ne_matrix 做 diagnose_and_fix_physics

    返回
    ----
    A_t:
        幅度衰减时间序列

    phi_t:
        相移时间序列

    h_p_t:
        复传输系数时间序列
    """
    z = np.asarray(z_grid, dtype=float).reshape(-1)
    ne_mat = np.asarray(Ne_matrix, dtype=float)

    if ne_mat.ndim != 2:
        raise ValueError("Ne_matrix 必须是二维数组，shape=(nt, nz)。")
    if ne_mat.shape[1] != z.size:
        raise ValueError("Ne_matrix 的第二维长度必须与 z_grid 一致。")

    if fix_physics:
        ne_mat = diagnose_and_fix_physics(ne_mat, verbose=verbose)

    A_list = []
    phi_list = []
    hp_list = []

    n_frames = ne_mat.shape[0]

    if verbose:
        print(f">>> 开始执行全时域 WKB 扫描，总帧数: {n_frames}")

    for i in range(n_frames):
        profile = ne_mat[i, :]

        result = calculate_wkb_transmission(
            f_EM=f_EM,
            z_grid=z,
            Ne_profile=profile,
            nu_en=nu_en,
            return_components=False,
            collision_input_unit=collision_input_unit,
            amplitude_floor=amplitude_floor,
        )

        A_list.append(result["amplitude_attenuation"])
        phi_list.append(result["phase_shift_rad"])
        hp_list.append(result["transmission_coeff"])

    A_t = np.asarray(A_list)
    phi_t = np.asarray(phi_list)
    h_p_t = np.asarray(hp_list)

    return A_t, phi_t, h_p_t


# ============================================================================
# 6. 全时域结果整理
# ============================================================================

def build_wkb_series_result(
    A_t: np.ndarray,
    phi_t: np.ndarray,
    h_p_t: np.ndarray,
) -> dict:
    """
    将 run_wkb_analysis(...) 的原始输出整理成统一字典。

    这个函数的作用不是新增物理，而是把后续绘图、观测生成、导航分析
    最常用的数据提前整理好，减少 notebook 或脚本中的重复代码。

    输出字段
    --------
    - amplitude
    - attenuation_dB
    - phase_shift_rad
    - transmission_coeff
    - finite_mask
    - finite_attenuation_dB
    - finite_phase_shift_rad
    """
    A_t = np.asarray(A_t, dtype=float)
    phi_t = np.asarray(phi_t, dtype=float)
    h_p_t = np.asarray(h_p_t)

    attenuation_dB = 20.0 * np.log10(A_t + 1e-30)

    finite_mask = np.isfinite(attenuation_dB) & np.isfinite(phi_t)
    finite_attenuation_dB = attenuation_dB[finite_mask]
    finite_phase_shift_rad = phi_t[finite_mask]

    return {
        "amplitude": A_t,
        "attenuation_dB": attenuation_dB,
        "phase_shift_rad": phi_t,
        "transmission_coeff": h_p_t,
        "finite_mask": finite_mask,
        "finite_attenuation_dB": finite_attenuation_dB,
        "finite_phase_shift_rad": finite_phase_shift_rad,
    }


def summarize_wkb_series(
    A_t: np.ndarray,
    phi_t: np.ndarray,
) -> dict:
    """
    生成一份简洁的全时域传播结果统计摘要。

    这适合后面做自动日志、报告摘要或调试输出。

    输出字段
    --------
    - amp_min
    - amp_max
    - atten_db_min
    - atten_db_max
    - phi_min
    - phi_max
    """
    A_t = np.asarray(A_t, dtype=float)
    phi_t = np.asarray(phi_t, dtype=float)
    atten_dB = 20.0 * np.log10(A_t + 1e-30)

    finite_atten = atten_dB[np.isfinite(atten_dB)]
    finite_phi = phi_t[np.isfinite(phi_t)]

    return {
        "amp_min": float(np.min(A_t)),
        "amp_max": float(np.max(A_t)),
        "atten_db_min": float(np.min(finite_atten)) if finite_atten.size else np.nan,
        "atten_db_max": float(np.max(finite_atten)) if finite_atten.size else np.nan,
        "phi_min": float(np.min(finite_phi)) if finite_phi.size else np.nan,
        "phi_max": float(np.max(finite_phi)) if finite_phi.size else np.nan,
    }


# ============================================================================
# 7. 一步入口：从二维电子密度场直接到传播结果
# ============================================================================

def run_wkb_pipeline(
    f_EM: float,
    z_grid: np.ndarray,
    Ne_matrix: np.ndarray,
    nu_en: float | np.ndarray,
    collision_input_unit: Literal["Hz", "rad_s"] = "Hz",
    amplitude_floor: float = 1e-20,
    fix_physics: bool = True,
    verbose: bool = True,
) -> dict:
    """
    一步完成：

        二维电子密度场
            -> 物理自检
            -> 全时域 WKB 扫描
            -> 结果整理
            -> 摘要统计

    返回字段
    --------
    - amplitude
    - attenuation_dB
    - phase_shift_rad
    - transmission_coeff
    - finite_mask
    - finite_attenuation_dB
    - finite_phase_shift_rad
    - summary
    """
    A_t, phi_t, h_p_t = run_wkb_analysis(
        f_EM=f_EM,
        z_grid=z_grid,
        Ne_matrix=Ne_matrix,
        nu_en=nu_en,
        collision_input_unit=collision_input_unit,
        amplitude_floor=amplitude_floor,
        fix_physics=fix_physics,
        verbose=verbose,
    )

    result = build_wkb_series_result(A_t=A_t, phi_t=phi_t, h_p_t=h_p_t)
    result["summary"] = summarize_wkb_series(A_t=A_t, phi_t=phi_t)
    return result