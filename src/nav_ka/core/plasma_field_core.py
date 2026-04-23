"""
plasma_field_core.py
====================

这个文件是“再入等离子体电子密度场构造”的单文件功能内核。
它的职责不是画图，不是交互，也不是导航解算，而是专门做下面几件事情：

1. 读取外部 CSV 数据
   - 大尺度电子密度基准场（例如 Large_Scale_Ne_Smooth.csv）
   - AOA（攻角）时间序列（例如 RAMC_AOA_Sim_Input.csv）
   - 其他 tidy 曲线数据（例如 wpd_datasets_tidy.csv）

2. 构建连续可查询的电子密度场
   - 先把离散的大尺度电子密度数据整理成二维表
   - 再在 log10(Ne) 空间中做二维插值
   - 这样就能从离散数据得到连续形式的 Ne_large(t, z)

3. 在大尺度场基础上构建中尺度调制场
   - 这里采用你当前代码里已经使用的“坐标伸缩 + 幅度修正”模型
   - 数学形式是：
         Ne_meso(t, z) = (1 + a_mid * alpha(t)) * Ne_large(t, z')
         z' = (1 + b_mid * alpha(t)) * z
   - 这个模型本质上是在用 AOA 的变化同时调制：
         (a) 剖面整体幅值
         (b) 剖面在 z 方向上的伸缩

4. 在已有场上叠加小尺度扰动
   - 当前先用高斯随机扰动 Delta(t, z) 做近似
   - 数学形式是：
         Ne_mod(t, z) = Ne_base(t, z) * (1 + Delta(t, z))
   - 这一步不是最终物理模型，只是当前阶段的功能性近似

5. 输出统一的数值阵列
   - 所有函数尽量输出标准的 numpy 数组
   - 便于后续接 WKB、传播计算、观测生成、EKF 等导航部分

----------------------------------------------------------------------
这个文件“故意不做”的事情
----------------------------------------------------------------------

1. 不做交互控件
   - 不使用 ipywidgets
   - 不做 notebook 风格 slider 界面

2. 不做绘图
   - 不包含 plot / pcolormesh / semilogy 等可视化函数
   - 绘图应当由外部脚本单独调用本文件结果完成

3. 不做导航解算
   - 不直接生成伪距、Doppler、EKF 状态估计
   - 本文件只负责“电子密度场”的连续化与调制构造

----------------------------------------------------------------------
输入数据约定
----------------------------------------------------------------------

A. 大尺度基准场 CSV 至少包含以下列：
   - Time_s : 时间（秒）
   - z_m    : 壁面法向距离（米）
   - ne_m3  : 电子密度（m^-3）

B. AOA CSV 至少包含以下列：
   - Time_s  : 时间（秒）
   - AOA_deg : 攻角（度）

C. tidy 曲线 CSV（如果使用）至少包含：
   - curve_id
   - z_m
   - ne_m3
   - log10_ne_m3
   - legend_label

----------------------------------------------------------------------
输出对象的基本约定
----------------------------------------------------------------------

本文件中的核心输出一般是以下几类：

1. 一维坐标轴
   - t_eval : 时间网格
   - z_eval : 空间网格

2. 二维场
   shape = (len(t_eval), len(z_eval))
   - ne_large
   - ne_meso
   - delta_field
   - ne_only_small
   - ne_combined

3. 插值器
   - log_interp_large : (t, z) -> log10(Ne_large)

----------------------------------------------------------------------
当前使用的数学近似
----------------------------------------------------------------------

1. 大尺度场采用 log 域插值
   也就是先对电子密度取 log10，再在 (t, z) 上做二维插值。
   这样做的原因是电子密度跨越多个数量级，在线性域插值往往数值表现较差。

2. 中尺度调制采用经验耦合形式
   这里仍然是你原代码的形式：
       amplitude factor = 1 + a_mid * alpha
       z warp           = (1 + b_mid * alpha) * z
   后续如果你有更严格的论文公式或实验拟合，可以替换这部分。

3. 小尺度扰动当前是随机场近似
   暂不引入更复杂的空间相关结构。
   后续如果你有真实 turbulence / jitter 模型，可以替换。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd
from scipy.interpolate import RegularGridInterpolator, interp1d


# ============================================================================
# 1. 基础数据读取函数
# ============================================================================

def load_tidy_curve_csv(csv_path: str | Path) -> pd.DataFrame:
    """
    读取 tidy 形式的曲线数据。

    这个函数对应你最开始那段“按 curve_id 分组，然后按 z_m 排序”的数据来源。
    它本身不做任何绘图，只负责把数据读入成 DataFrame。

    参数
    ----
    csv_path:
        tidy 曲线 CSV 路径。

    返回
    ----
    df:
        原始 DataFrame，不改列名，不改内容。
        后续若外部需要，可以按 curve_id 分组再处理。
    """
    return pd.read_csv(csv_path)


def load_large_scale_csv(
    csv_path: str | Path,
    min_time: Optional[float] = None,
) -> pd.DataFrame:
    """
    读取大尺度电子密度基准数据。

    数学/物理含义
    --------------
    这个 DataFrame 是后续构建连续电子密度场的原始离散采样数据。
    它通常来自某个预处理后的大尺度基准结果，比如：
        Ne_large(Time_s, z_m)

    该函数会做两件基础清洗：
    1. 过滤掉 ne_m3 <= 0 的非法值
    2. 按时间和空间坐标排序

    参数
    ----
    csv_path:
        大尺度基准 CSV 路径。

    min_time:
        如果给定，则丢弃 Time_s < min_time 的所有数据。
        这常用于把仿真起点统一到某个时刻，比如 400 s。

    返回
    ----
    df:
        清洗后的 DataFrame，至少包含：
        Time_s, z_m, ne_m3
    """
    df = pd.read_csv(csv_path)
    df = df[df["ne_m3"] > 0].copy()

    if min_time is not None:
        df = df[df["Time_s"] >= min_time].copy()

    df = df.sort_values(["Time_s", "z_m"]).reset_index(drop=True)
    return df


def load_aoa_csv(
    csv_path: str | Path,
    min_time: Optional[float] = None,
) -> pd.DataFrame:
    """
    读取 AOA（攻角）时间序列。

    数学/物理含义
    --------------
    这里的 AOA_deg = alpha(t) 是后续中尺度调制的驱动量。
    也就是说，这个序列决定：
        - 剖面整体幅值怎么变化
        - 剖面在 z 方向怎么伸缩

    参数
    ----
    csv_path:
        AOA CSV 路径。

    min_time:
        如果给定，则丢弃 Time_s < min_time 的数据。

    返回
    ----
    df:
        清洗并按时间排序后的 AOA DataFrame。
    """
    df = pd.read_csv(csv_path)

    if min_time is not None:
        df = df[df["Time_s"] >= min_time].copy()

    df = df.sort_values("Time_s").reset_index(drop=True)
    return df


def sync_aoa_and_large_scale(
    aoa_df: pd.DataFrame,
    large_df: pd.DataFrame,
    start_time: Optional[float] = None,
) -> tuple[pd.DataFrame, pd.DataFrame, float, float]:
    """
    统一 AOA 序列与大尺度电子密度场的共同时间区间。

    为什么需要这一步
    ----------------
    你的几段代码里，AOA 数据和大尺度基准数据往往来自不同 CSV。
    它们各自的起止时间不一定完全相同。
    如果不先做时间对齐，后续在构建中尺度场时就可能出现：
        - 某一时刻 AOA 有值但大尺度场没有
        - 或者大尺度场有值但 AOA 没有

    所以这个函数的职责是：
    1. 可选地从某个 start_time 开始截断
    2. 自动取两者的共同时间区间 [t_start, t_end]
    3. 返回同步后的两个 DataFrame

    参数
    ----
    aoa_df:
        AOA 数据。

    large_df:
        大尺度电子密度数据。

    start_time:
        如果给定，先把两者都截断到 start_time 之后。

    返回
    ----
    aoa_sync, large_sync, t_start, t_end
    """
    aoa = aoa_df.copy()
    large = large_df.copy()

    if start_time is not None:
        aoa = aoa[aoa["Time_s"] >= start_time].copy()
        large = large[large["Time_s"] >= start_time].copy()

    t_start = max(aoa["Time_s"].min(), large["Time_s"].min())
    t_end = min(aoa["Time_s"].max(), large["Time_s"].max())

    aoa = aoa[(aoa["Time_s"] >= t_start) & (aoa["Time_s"] <= t_end)].copy()
    large = large[(large["Time_s"] >= t_start) & (large["Time_s"] <= t_end)].copy()

    aoa = aoa.sort_values("Time_s").reset_index(drop=True)
    large = large.sort_values(["Time_s", "z_m"]).reset_index(drop=True)

    return aoa, large, float(t_start), float(t_end)


# ============================================================================
# 2. 插值器与网格构建
# ============================================================================

def build_large_scale_log_interpolator(
    large_df: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, RegularGridInterpolator]:
    """
    从离散大尺度数据构建二维 log 域插值器。

    数学意义
    --------
    给定原始离散数据:
        Ne_large(t_i, z_j)

    我们先整理成矩阵，再构造：
        F(t, z) = log10(Ne_large(t, z))

    然后建立二维插值器：
        (t, z) -> F(t, z)

    这样做的好处是：
    1. 电子密度跨数量级时，log 域插值更稳定
    2. 后续得到连续场时，再取：
           Ne_large(t, z) = 10 ** F(t, z)

    实现步骤
    --------
    1. 提取原始时间轴与 z 坐标轴
    2. 用 pivot 形成矩阵
    3. 对缺失值做双向插值填补
    4. 对矩阵取 log10
    5. 构建 RegularGridInterpolator

    参数
    ----
    large_df:
        大尺度基准 DataFrame，至少包含 Time_s, z_m, ne_m3

    返回
    ----
    times_raw:
        原始离散时间轴

    z_raw:
        原始离散空间轴

    ne_matrix:
        未取对数的二维电子密度矩阵，shape = (nt, nz)

    interp_func:
        二维插值器，输入 (t, z)，输出 log10(Ne_large)
    """
    times_raw = np.sort(large_df["Time_s"].unique())
    z_raw = np.sort(large_df["z_m"].unique())

    ne_matrix_df = large_df.pivot(index="Time_s", columns="z_m", values="ne_m3")

    # 双向插值用于补齐稀疏缺失值。
    # 这里的思路不是“重新建模”，只是为了让二维插值器的输入矩阵完整。
    ne_matrix_df = ne_matrix_df.interpolate(axis=1).interpolate(axis=0)
    ne_matrix = ne_matrix_df.values

    log_ne_matrix = np.log10(ne_matrix)

    interp_func = RegularGridInterpolator(
        (times_raw, z_raw),
        log_ne_matrix,
        bounds_error=False,
        fill_value=None,
    )

    return times_raw, z_raw, ne_matrix, interp_func


def build_aoa_interpolator(
    aoa_df: pd.DataFrame,
) -> Callable[[np.ndarray | float], np.ndarray | float]:
    """
    构造 AOA 时间插值函数 alpha(t)。

    数学意义
    --------
    原始 AOA 数据通常只在若干离散时刻给出。
    但中尺度调制需要在任意 t 上查询 alpha(t)，
    所以这里建立一个一维插值函数：

        alpha(t) = interp(Time_s, AOA_deg)

    当前使用线性插值，这样最直接，也最符合你当前代码的风格。

    参数
    ----
    aoa_df:
        AOA DataFrame，至少包含 Time_s, AOA_deg

    返回
    ----
    f_aoa:
        输入时间 t，输出 alpha(t)
    """
    return interp1d(
        aoa_df["Time_s"].values,
        aoa_df["AOA_deg"].values,
        kind="linear",
        fill_value="extrapolate",
    )


def make_eval_grid(
    t_min: float,
    t_max: float,
    z_min: float = 0.0,
    z_max: float = 0.14,
    nt: int = 800,
    nz: int = 250,
) -> tuple[np.ndarray, np.ndarray]:
    """
    生成统一的时间/空间计算网格。

    为什么单独写成函数
    ------------------
    你的几段代码中，t_fine / z_fine / meshgrid 的生成逻辑重复出现很多次。
    这类重复是最适合先抽出来的，因为它们本身没有争议。

    参数
    ----
    t_min, t_max:
        时间区间

    z_min, z_max:
        空间区间，默认沿壁面法向从 0 到 0.14 m

    nt, nz:
        时间和空间的离散点数

    返回
    ----
    t_eval:
        一维时间网格

    z_eval:
        一维空间网格
    """
    t_eval = np.linspace(t_min, t_max, nt)
    z_eval = np.linspace(z_min, z_max, nz)
    return t_eval, z_eval


# ============================================================================
# 3. 场构造函数：大尺度 / 中尺度 / 小尺度 / 复合调制
# ============================================================================

def evaluate_large_scale_field(
    log_interp_large: RegularGridInterpolator,
    t_eval: np.ndarray,
    z_eval: np.ndarray,
) -> np.ndarray:
    """
    计算大尺度连续电子密度场 Ne_large(t, z)。

    数学形式
    --------
    已知插值器输出：
        F(t, z) = log10(Ne_large(t, z))

    则连续大尺度场为：
        Ne_large(t, z) = 10 ** F(t, z)

    返回
    ----
    ne_large:
        shape = (len(t_eval), len(z_eval))
        第 0 维对应时间，第 1 维对应空间 z
    """
    T_mesh, Z_mesh = np.meshgrid(t_eval, z_eval, indexing="ij")
    pts = np.column_stack([T_mesh.ravel(), Z_mesh.ravel()])
    log_ne = log_interp_large(pts).reshape(T_mesh.shape)
    ne_large = 10.0 ** log_ne
    return ne_large


def evaluate_meso_scale_field(
    log_interp_large: RegularGridInterpolator,
    f_aoa: Callable[[np.ndarray | float], np.ndarray | float],
    t_eval: np.ndarray,
    z_eval: np.ndarray,
    z_min_clip: float,
    z_max_clip: float,
    a_mid: float = 0.1,
    b_mid: float = -1.0 / 14.0,
) -> np.ndarray:
    """
    计算中尺度调制电子密度场 Ne_meso(t, z)。

    数学形式
    --------
    这是你当前代码中已经使用的经验耦合形式：

        amp_factor(t) = 1 + a_mid * alpha(t)
        z'(t, z)      = (1 + b_mid * alpha(t)) * z

        Ne_meso(t, z) = amp_factor(t) * Ne_large(t, z')

    其中：
    - a_mid 控制幅度调制强度
    - b_mid 控制空间坐标伸缩强度
    - alpha(t) 由 AOA 时间序列插值得到

    为什么要 clip
    --------------
    当 z' 超出原始数据 z 轴范围时，插值会变得不可靠。
    所以这里将 z' 截断到 [z_min_clip, z_max_clip] 内。

    参数
    ----
    log_interp_large:
        大尺度场 log 域插值器

    f_aoa:
        AOA 时间插值函数

    t_eval, z_eval:
        目标计算网格

    z_min_clip, z_max_clip:
        插值允许的 z 区间边界

    a_mid, b_mid:
        中尺度调制参数

    返回
    ----
    ne_meso:
        中尺度调制后的二维电子密度场
    """
    ne_meso = np.zeros((len(t_eval), len(z_eval)), dtype=float)

    for i, t in enumerate(t_eval):
        alpha = float(f_aoa(t))

        # 幅度调制因子
        amp_factor = 1.0 + a_mid * alpha

        # 空间坐标伸缩
        z_prime = (1.0 + b_mid * alpha) * z_eval
        z_prime = np.clip(z_prime, z_min_clip, z_max_clip)

        pts = np.column_stack([np.full_like(z_eval, t), z_prime])
        log_base = log_interp_large(pts)

        ne_meso[i, :] = amp_factor * (10.0 ** log_base)

    return ne_meso


def make_small_scale_delta_field(
    shape: tuple[int, int],
    sigma: float = 0.08,
    seed: Optional[int] = 42,
) -> np.ndarray:
    """
    生成小尺度扰动场 Delta(t, z)。

    数学形式
    --------
    当前使用简单高斯随机场近似：
        Delta(t, z) ~ N(0, sigma^2)

    然后后续用：
        Ne_mod(t, z) = Ne_base(t, z) * (1 + Delta(t, z))

    说明
    ----
    这里的 Delta 还不是“严格物理的小尺度湍流模型”，
    只是当前阶段把小尺度抖动从主流程中抽象出来，便于以后替换。

    参数
    ----
    shape:
        目标二维场形状，通常等于 (len(t_eval), len(z_eval))

    sigma:
        扰动标准差

    seed:
        随机种子，用于保证可重复性

    返回
    ----
    delta_field:
        shape 与输入 shape 相同
    """
    rng = np.random.default_rng(seed)
    return rng.normal(loc=0.0, scale=sigma, size=shape)


def apply_small_scale_modulation(
    ne_field: np.ndarray,
    delta_field: np.ndarray,
) -> np.ndarray:
    """
    将小尺度扰动乘到已有电子密度场上。

    数学形式
    --------
        Ne_mod(t, z) = Ne_field(t, z) * (1 + Delta(t, z))

    参数
    ----
    ne_field:
        输入基底场，可以是大尺度场，也可以是中尺度场

    delta_field:
        小尺度扰动场

    返回
    ----
    ne_mod:
        叠加小尺度扰动后的结果
    """
    if ne_field.shape != delta_field.shape:
        raise ValueError("ne_field 与 delta_field 的形状必须一致。")

    return ne_field * (1.0 + delta_field)


def build_combined_fields(
    log_interp_large: RegularGridInterpolator,
    f_aoa: Callable[[np.ndarray | float], np.ndarray | float],
    t_eval: np.ndarray,
    z_eval: np.ndarray,
    z_min_clip: float,
    z_max_clip: float,
    a_mid: float = 0.1,
    b_mid: float = -1.0 / 14.0,
    sigma_small: float = 0.08,
    seed: Optional[int] = 42,
) -> dict[str, np.ndarray]:
    """
    一次性生成当前最常用的几类二维电子密度场。

    输出包含：
    1. ne_large
       纯大尺度连续场

    2. ne_meso
       大尺度场经过 AOA 中尺度调制后的结果

    3. delta_field
       小尺度扰动场

    4. ne_only_small
       大尺度场 + 小尺度扰动
       即：
           Ne_large * (1 + Delta)

    5. ne_combined
       中尺度调制场 + 小尺度扰动
       即：
           Ne_meso * (1 + Delta)

    这样做的意义
    ------------
    你原来的几段 notebook 代码里，这几类场总是连在一起算。
    所以这里直接打包成一个函数，便于后续：
    - 传播计算直接调用
    - 绘图脚本调用
    - 导航分析脚本调用

    返回
    ----
    result:
        一个字典，键为：
        - "ne_large"
        - "ne_meso"
        - "delta_field"
        - "ne_only_small"
        - "ne_combined"
    """
    ne_large = evaluate_large_scale_field(
        log_interp_large=log_interp_large,
        t_eval=t_eval,
        z_eval=z_eval,
    )

    ne_meso = evaluate_meso_scale_field(
        log_interp_large=log_interp_large,
        f_aoa=f_aoa,
        t_eval=t_eval,
        z_eval=z_eval,
        z_min_clip=z_min_clip,
        z_max_clip=z_max_clip,
        a_mid=a_mid,
        b_mid=b_mid,
    )

    delta_field = make_small_scale_delta_field(
        shape=ne_large.shape,
        sigma=sigma_small,
        seed=seed,
    )

    ne_only_small = apply_small_scale_modulation(ne_large, delta_field)
    ne_combined = apply_small_scale_modulation(ne_meso, delta_field)

    return {
        "ne_large": ne_large,
        "ne_meso": ne_meso,
        "delta_field": delta_field,
        "ne_only_small": ne_only_small,
        "ne_combined": ne_combined,
    }


# ============================================================================
# 4. 便捷入口函数：从文件直接走到场
# ============================================================================

def build_large_and_aoa_context(
    large_csv_path: str | Path,
    aoa_csv_path: str | Path,
    start_time: Optional[float] = None,
) -> dict[str, object]:
    """
    从两个 CSV 文件直接构建“统一上下文”。

    这个函数的目的是把下面这些重复操作打包成一步：
    - 读取大尺度数据
    - 读取 AOA 数据
    - 做时间同步
    - 建立大尺度 log 域插值器
    - 建立 AOA 时间插值器

    返回内容
    --------
    返回一个上下文字典，包含后续最常需要的对象：
    - aoa_df
    - large_df
    - t_start
    - t_end
    - times_raw
    - z_raw
    - ne_matrix
    - log_interp_large
    - f_aoa

    这样后续脚本就不需要到处重复“先加载、再同步、再插值器构建”。
    """
    aoa_df = load_aoa_csv(aoa_csv_path, min_time=start_time)
    large_df = load_large_scale_csv(large_csv_path, min_time=start_time)

    aoa_df, large_df, t_start, t_end = sync_aoa_and_large_scale(
        aoa_df=aoa_df,
        large_df=large_df,
        start_time=start_time,
    )

    times_raw, z_raw, ne_matrix, log_interp_large = build_large_scale_log_interpolator(
        large_df=large_df,
    )

    f_aoa = build_aoa_interpolator(aoa_df)

    return {
        "aoa_df": aoa_df,
        "large_df": large_df,
        "t_start": t_start,
        "t_end": t_end,
        "times_raw": times_raw,
        "z_raw": z_raw,
        "ne_matrix": ne_matrix,
        "log_interp_large": log_interp_large,
        "f_aoa": f_aoa,
    }


def build_fields_from_csv(
    large_csv_path: str | Path,
    aoa_csv_path: str | Path,
    start_time: Optional[float] = None,
    z_min: float = 0.0,
    z_max: float = 0.14,
    nt: int = 800,
    nz: int = 250,
    a_mid: float = 0.1,
    b_mid: float = -1.0 / 14.0,
    sigma_small: float = 0.08,
    seed: Optional[int] = 42,
) -> dict[str, object]:
    """
    从 CSV 一步生成最常用的所有场对象。

    返回内容包含三部分：
    1. 上下文：
       - t_start, t_end
       - times_raw, z_raw
       - aoa_df, large_df

    2. 计算网格：
       - t_eval
       - z_eval

    3. 各种场：
       - ne_large
       - ne_meso
       - delta_field
       - ne_only_small
       - ne_combined

    这相当于给后续脚本提供一个“一步到位”的入口。
    如果未来你开始接 WKB、传播偏差、观测生成，这个函数返回结果也最方便继续往下接。
    """
    context = build_large_and_aoa_context(
        large_csv_path=large_csv_path,
        aoa_csv_path=aoa_csv_path,
        start_time=start_time,
    )

    t_eval, z_eval = make_eval_grid(
        t_min=context["t_start"],
        t_max=context["t_end"],
        z_min=z_min,
        z_max=z_max,
        nt=nt,
        nz=nz,
    )

    field_dict = build_combined_fields(
        log_interp_large=context["log_interp_large"],
        f_aoa=context["f_aoa"],
        t_eval=t_eval,
        z_eval=z_eval,
        z_min_clip=float(context["z_raw"].min()),
        z_max_clip=float(context["z_raw"].max()),
        a_mid=a_mid,
        b_mid=b_mid,
        sigma_small=sigma_small,
        seed=seed,
    )

    return {
        **context,
        "t_eval": t_eval,
        "z_eval": z_eval,
        **field_dict,
    }