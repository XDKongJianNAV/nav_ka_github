"""
plasma_field_plot.py
====================

这个文件专门负责“电子密度场相关结果的绘图与可视化”，
它不负责任何场计算、插值器构建、随机扰动生成、AOA 耦合计算等功能。

也就是说，这个文件的职责非常单一：

    输入：已经计算好的数组 / 场
    输出：Matplotlib 图像

----------------------------------------------------------------------
设计原则
----------------------------------------------------------------------

1. 本文件只做可视化，不做数值建模
   - 不读 CSV
   - 不构建插值器
   - 不生成中尺度、小尺度场
   - 不做 WKB、传播、导航观测或 EKF

2. 所有画图函数都尽量接收“已经算好的数组”
   例如：
   - t_eval
   - z_eval
   - ne_large
   - ne_meso
   - ne_combined
   - delta_field
   这样可视化层和计算层保持清晰分离。

3. 函数尽量保持“单一图像职责”
   每个函数只负责一种图：
   - tidy 曲线图
   - 2D 连续场图
   - 两个场对比图
   - 多曲线剖面对比图
   - AOA 参考轨迹图
   - 组合图（主图 + 参考轨迹）

4. 不做交互
   - 不使用 ipywidgets
   - 不使用 slider
   - 不使用 notebook 内嵌交互逻辑

5. 允许外部脚本自行决定是否 show / save
   这里大多数函数都返回 fig, ax，方便你在外部：
   - plt.show()
   - fig.savefig(...)
   - 后续组合进 report 脚本

----------------------------------------------------------------------
和 plasma_field_core.py 的关系
----------------------------------------------------------------------

推荐配套用法：

    from plasma_field_core import build_fields_from_csv
    from plasma_field_plot import plot_scalar_field_2d

    result = build_fields_from_csv(...)
    fig, ax = plot_scalar_field_2d(
        t_eval=result["t_eval"],
        z_eval=result["z_eval"],
        field=result["ne_meso"],
        title="Meso-scale Electron Density"
    )

----------------------------------------------------------------------
约定
----------------------------------------------------------------------

1. 所有二维场默认 shape 为：
       (len(t_eval), len(z_eval))
   其中：
       第 0 维 = 时间
       第 1 维 = 空间 z

2. 如果 field 的物理量是电子密度 Ne（单位 m^-3），
   大多数 2D 图会默认画 log10(field)。

3. 如果 field 中可能存在非正数，则取 log10 前会进行裁剪，
   避免出现 log10(<=0) 导致的错误。

4. 本文件的绘图风格偏“科研默认风格”，不追求花哨交互。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# ============================================================================
# 全局绘图风格设置
# ============================================================================

plt.rcParams["font.family"] = "serif"
plt.rcParams["xtick.direction"] = "in"
plt.rcParams["ytick.direction"] = "in"


# ============================================================================
# 1. 内部辅助函数
# ============================================================================

def _ensure_positive_for_log10(field: np.ndarray, floor: float = 1e-30) -> np.ndarray:
    """
    保证输入数组在取 log10 之前为正。

    为什么需要这个函数
    ------------------
    电子密度图常常使用 log10(Ne) 作图，因为数值跨越多个数量级。
    但是如果 field 中出现非正值，例如：
    - 小尺度扰动过大导致局部出现 <= 0
    - 数值噪声
    - 上游数据不完整

    那么直接做 np.log10(field) 会报错或出现无穷值。

    处理方式
    --------
    这里采用一个非常温和的“下限裁剪”方法：
        field_safe = max(field, floor)

    这不是物理修正，只是为了保证绘图函数数值稳定。

    参数
    ----
    field:
        待取 log10 的数组

    floor:
        最小正值下限

    返回
    ----
    field_safe:
        可安全取 log10 的数组
    """
    return np.maximum(field, floor)


def _make_mesh(
    t_eval: np.ndarray,
    z_eval: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    根据一维时间轴和空间轴生成二维 mesh。

    数组约定
    --------
    我们约定 field 的 shape = (len(t_eval), len(z_eval))
    因此这里必须使用：
        indexing='ij'
    这样生成的 T_mesh, Z_mesh 的 shape 才与 field 一致。

    返回
    ----
    T_mesh, Z_mesh
    """
    return np.meshgrid(t_eval, z_eval, indexing="ij")


def _finalize_figure(
    fig: plt.Figure,
    save_path: Optional[str | Path] = None,
    show: bool = True,
) -> None:
    """
    统一处理图像的保存与显示。

    说明
    ----
    大多数画图函数最后都可以调用这个辅助函数：
    - 如果给了 save_path，就先保存
    - 如果 show=True，就显示
    - 如果 show=False，就只返回 fig, ax，不主动显示

    这样便于后续在脚本和 notebook 两边都能统一使用。
    """
    if save_path is not None:
        fig.savefig(save_path, dpi=300, bbox_inches="tight")

    if show:
        plt.show()


# ============================================================================
# 2. tidy 曲线图
# ============================================================================

def plot_tidy_curves(
    df: pd.DataFrame,
    x_col: str = "z_m",
    y_col: str = "log10_ne_m3",
    group_col: str = "curve_id",
    label_col: str = "legend_label",
    sort_col: str = "z_m",
    xlabel: str = "z (m)",
    ylabel: str = r"$\log_{10}(N_e)$ (m$^{-3}$)",
    title: str = "Electron Density Curves",
    figsize: tuple[float, float] = (6, 4),
    legend_fontsize: int = 8,
    show: bool = True,
    save_path: Optional[str | Path] = None,
) -> tuple[plt.Figure, plt.Axes]:
    """
    绘制 tidy 格式曲线数据。

    对应场景
    --------
    这个函数对应你最开始那段：
        for cid, g in df.groupby("curve_id"):
            g = g.sort_values("z_m")
            plt.plot(g["z_m"], g["log10_ne_m3"], ...)

    也就是说，它适合画“多条一维剖面曲线”的对比图。

    参数
    ----
    df:
        tidy 形式 DataFrame。

    x_col, y_col:
        横纵坐标列名。

    group_col:
        按哪个列分组，一般是 curve_id。

    label_col:
        图例列名。

    sort_col:
        每组内部按哪个列排序，一般是 z_m。
        这一步很重要，否则曲线可能来回折返。

    返回
    ----
    fig, ax
    """
    fig, ax = plt.subplots(figsize=figsize)

    for _, g in df.groupby(group_col):
        g = g.sort_values(sort_col)
        label = str(g[label_col].iloc[0]) if label_col in g.columns else None
        ax.plot(g[x_col], g[y_col], label=label)

    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)

    if label_col in df.columns:
        ax.legend(fontsize=legend_fontsize)

    fig.tight_layout()
    _finalize_figure(fig, save_path=save_path, show=show)
    return fig, ax


# ============================================================================
# 3. 单个二维场图
# ============================================================================

def plot_scalar_field_2d(
    t_eval: np.ndarray,
    z_eval: np.ndarray,
    field: np.ndarray,
    title: str,
    xlabel: str = "Time (s)",
    ylabel: str = "Distance z (m)",
    colorbar_label: str = r"$\log_{10}(N_e)$ (m$^{-3}$)",
    cmap: str = "jet",
    figsize: tuple[float, float] = (11, 6),
    dpi: int = 120,
    shading: str = "auto",
    use_log10: bool = True,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    show: bool = True,
    save_path: Optional[str | Path] = None,
) -> tuple[plt.Figure, plt.Axes]:
    """
    绘制单个二维标量场。

    典型用途
    --------
    用来画：
    - 大尺度电子密度场
    - 中尺度调制场
    - 小尺度调制结果
    - 复合调制结果

    数学说明
    --------
    如果 use_log10=True，则画的是：
        plot_field = log10(field)

    这通常适用于电子密度 Ne，因为 Ne 往往跨好几个数量级。

    参数
    ----
    t_eval, z_eval:
        一维时间轴和空间轴。

    field:
        shape = (len(t_eval), len(z_eval))

    use_log10:
        是否对 field 取 log10 再画。

    vmin, vmax:
        pcolormesh 的颜色范围控制。

    返回
    ----
    fig, ax
    """
    T_mesh, Z_mesh = _make_mesh(t_eval, z_eval)

    if use_log10:
        plot_field = np.log10(_ensure_positive_for_log10(field))
    else:
        plot_field = field

    fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

    mesh = ax.pcolormesh(
        T_mesh,
        Z_mesh,
        plot_field,
        cmap=cmap,
        shading=shading,
        vmin=vmin,
        vmax=vmax,
    )

    cbar = fig.colorbar(mesh, ax=ax, pad=0.02)
    cbar.set_label(colorbar_label)

    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)

    fig.tight_layout()
    _finalize_figure(fig, save_path=save_path, show=show)
    return fig, ax


# ============================================================================
# 4. 两个二维场上下对比图
# ============================================================================

def plot_two_scalar_fields_vertical(
    t_eval: np.ndarray,
    z_eval: np.ndarray,
    field_top: np.ndarray,
    field_bottom: np.ndarray,
    title_top: str,
    title_bottom: str,
    xlabel_bottom: str = "Time (s)",
    ylabel: str = "Distance z (m)",
    colorbar_label: str = r"$\log_{10}(N_e)$ (m$^{-3}$)",
    cmap: str = "jet",
    figsize: tuple[float, float] = (12, 10),
    dpi: int = 120,
    shading: str = "auto",
    use_log10: bool = True,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    show: bool = True,
    save_path: Optional[str | Path] = None,
) -> tuple[plt.Figure, tuple[plt.Axes, plt.Axes]]:
    """
    绘制两个二维场的上下对比图。

    对应场景
    --------
    这个函数对应你前面那段“双图上下排列”的代码，例如：
    - 纯小尺度调制
    - 中尺度 + 小尺度复合调制

    数学说明
    --------
    如果 use_log10=True，则对两个 field 都先取 log10 再绘图。
    这样可以保证两个图的色标意义一致。

    返回
    ----
    fig, (ax1, ax2)
    """
    T_mesh, Z_mesh = _make_mesh(t_eval, z_eval)

    if use_log10:
        plot_top = np.log10(_ensure_positive_for_log10(field_top))
        plot_bottom = np.log10(_ensure_positive_for_log10(field_bottom))
    else:
        plot_top = field_top
        plot_bottom = field_bottom

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=figsize, dpi=dpi)

    mesh1 = ax1.pcolormesh(
        T_mesh,
        Z_mesh,
        plot_top,
        cmap=cmap,
        shading=shading,
        vmin=vmin,
        vmax=vmax,
    )
    ax1.set_title(title_top)
    ax1.set_ylabel(ylabel)
    fig.colorbar(mesh1, ax=ax1, pad=0.02, label=colorbar_label)

    mesh2 = ax2.pcolormesh(
        T_mesh,
        Z_mesh,
        plot_bottom,
        cmap=cmap,
        shading=shading,
        vmin=vmin,
        vmax=vmax,
    )
    ax2.set_title(title_bottom)
    ax2.set_ylabel(ylabel)
    ax2.set_xlabel(xlabel_bottom)
    fig.colorbar(mesh2, ax=ax2, pad=0.02, label=colorbar_label)

    fig.tight_layout()
    _finalize_figure(fig, save_path=save_path, show=show)
    return fig, (ax1, ax2)


# ============================================================================
# 5. 单时刻剖面对比图
# ============================================================================

def plot_profiles_at_time(
    z_eval: np.ndarray,
    profiles: dict[str, np.ndarray],
    xlabel: str = "Distance z (m)",
    ylabel: str = r"Electron Density $N_e$ (m$^{-3}$)",
    title: str = "Electron Density Profiles",
    use_semilogy: bool = True,
    figsize: tuple[float, float] = (8, 5),
    linewidth: float = 2.0,
    show: bool = True,
    save_path: Optional[str | Path] = None,
) -> tuple[plt.Figure, plt.Axes]:
    """
    绘制同一时刻下多个电子密度剖面对比图。

    对应场景
    --------
    你前面的 notebook 里经常会在一个固定时刻画：
    - baseline
    - meso-scale modulated
    - 可能再加 combined

    这个函数就是把这类“单时刻多剖面对比”抽象出来。

    输入格式
    --------
    profiles 是一个字典，例如：
        {
            "Baseline": ne_large[idx],
            "Meso-scale": ne_meso[idx],
            "Combined": ne_combined[idx],
        }

    参数
    ----
    use_semilogy:
        是否用半对数坐标。
        对电子密度剖面通常建议 True。

    返回
    ----
    fig, ax
    """
    fig, ax = plt.subplots(figsize=figsize)

    for label, profile in profiles.items():
        if use_semilogy:
            ax.semilogy(z_eval, profile, linewidth=linewidth, label=label)
        else:
            ax.plot(z_eval, profile, linewidth=linewidth, label=label)

    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(frameon=False)
    ax.grid(True, which="both", linestyle=":", alpha=0.5)

    fig.tight_layout()
    _finalize_figure(fig, save_path=save_path, show=show)
    return fig, ax


# ============================================================================
# 6. AOA 时间序列图
# ============================================================================

def plot_aoa_series(
    aoa_df: pd.DataFrame,
    xlabel: str = "Time (s)",
    ylabel: str = r"AOA ($^\circ$)",
    title: str = "Angle of Attack Time Series",
    figsize: tuple[float, float] = (10, 3),
    color: str = "gray",
    linewidth: float = 1.5,
    alpha: float = 0.8,
    show: bool = True,
    save_path: Optional[str | Path] = None,
) -> tuple[plt.Figure, plt.Axes]:
    """
    绘制 AOA 时间序列。

    作用
    ----
    这个图通常不是主结果图，而是参考图。
    它帮助你把电子密度场变化与 AOA 的时间演化对应起来。

    返回
    ----
    fig, ax
    """
    fig, ax = plt.subplots(figsize=figsize)

    ax.plot(
        aoa_df["Time_s"].values,
        aoa_df["AOA_deg"].values,
        color=color,
        linewidth=linewidth,
        alpha=alpha,
    )

    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)

    fig.tight_layout()
    _finalize_figure(fig, save_path=save_path, show=show)
    return fig, ax


# ============================================================================
# 7. 主图 + AOA 参考轨迹组合图
# ============================================================================

def plot_field_with_aoa_reference(
    t_eval: np.ndarray,
    z_eval: np.ndarray,
    field: np.ndarray,
    aoa_df: pd.DataFrame,
    field_title: str,
    field_ylabel: str = "Distance z (m)",
    aoa_ylabel: str = r"AOA ($^\circ$)",
    time_xlabel: str = "Time (s)",
    colorbar_label: str = r"$\log_{10}(N_e)$ (m$^{-3}$)",
    cmap: str = "jet",
    figsize: tuple[float, float] = (12, 8),
    dpi: int = 120,
    shading: str = "auto",
    use_log10: bool = True,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    show: bool = True,
    save_path: Optional[str | Path] = None,
) -> tuple[plt.Figure, tuple[plt.Axes, plt.Axes]]:
    """
    绘制“主二维场 + 下方 AOA 参考轨迹”的组合图。

    对应场景
    --------
    你前面的交互代码里，上面是电子密度剖面或场，
    下面是 AOA 的参考轨迹，用来定位当前时间点。

    这里虽然不做交互，但仍保留“主图 + AOA 参考图”的静态组合方式，
    非常适合论文或汇报图。

    数学说明
    --------
    主图默认画 log10(field)。
    AOA 子图只作为时间参考，不做额外数学变换。

    返回
    ----
    fig, (ax1, ax2)
    """
    T_mesh, Z_mesh = _make_mesh(t_eval, z_eval)

    if use_log10:
        plot_field = np.log10(_ensure_positive_for_log10(field))
    else:
        plot_field = field

    fig = plt.figure(figsize=figsize, dpi=dpi)
    gs = fig.add_gridspec(2, 1, height_ratios=[1.2, 0.35])

    ax1 = fig.add_subplot(gs[0])
    mesh = ax1.pcolormesh(
        T_mesh,
        Z_mesh,
        plot_field,
        cmap=cmap,
        shading=shading,
        vmin=vmin,
        vmax=vmax,
    )
    cbar = fig.colorbar(mesh, ax=ax1, pad=0.02)
    cbar.set_label(colorbar_label)

    ax1.set_title(field_title)
    ax1.set_ylabel(field_ylabel)

    ax2 = fig.add_subplot(gs[1])
    ax2.plot(
        aoa_df["Time_s"].values,
        aoa_df["AOA_deg"].values,
        color="gray",
        alpha=0.6,
    )
    ax2.set_ylabel(aoa_ylabel)
    ax2.set_xlabel(time_xlabel)

    fig.tight_layout()
    _finalize_figure(fig, save_path=save_path, show=show)
    return fig, (ax1, ax2)


# ============================================================================
# 8. 多场剖面对比：指定时间索引
# ============================================================================

def plot_profile_comparison_from_fields(
    t_eval: np.ndarray,
    z_eval: np.ndarray,
    field_dict: dict[str, np.ndarray],
    time_index: int,
    title_prefix: str = "Profile Comparison",
    use_semilogy: bool = True,
    figsize: tuple[float, float] = (8, 5),
    show: bool = True,
    save_path: Optional[str | Path] = None,
) -> tuple[plt.Figure, plt.Axes]:
    """
    从多个二维场中取同一个时间索引，绘制剖面对比图。

    典型用途
    --------
    如果你已经有：
        ne_large
        ne_meso
        ne_only_small
        ne_combined

    想在同一时刻 t_eval[idx] 比较它们的剖面，
    就可以直接调用这个函数。

    输入格式
    --------
    field_dict 例如：
        {
            "Large": ne_large,
            "Meso": ne_meso,
            "Only Small": ne_only_small,
            "Combined": ne_combined,
        }

    参数
    ----
    time_index:
        要取的时间索引，而不是实际时间值。
        这样函数保持简单，不再引入“找最近时间点”的额外逻辑。

    返回
    ----
    fig, ax
    """
    if time_index < 0 or time_index >= len(t_eval):
        raise IndexError("time_index 超出 t_eval 范围。")

    t_curr = float(t_eval[time_index])

    profiles = {}
    for name, field in field_dict.items():
        profiles[name] = field[time_index, :]

    title = f"{title_prefix} | t = {t_curr:.4f} s"

    fig, ax = plot_profiles_at_time(
        z_eval=z_eval,
        profiles=profiles,
        title=title,
        use_semilogy=use_semilogy,
        figsize=figsize,
        show=False,
    )

    _finalize_figure(fig, save_path=save_path, show=show)
    return fig, ax


# ============================================================================
# 9. 三联图：Large / Meso / Combined
# ============================================================================

def plot_three_fields_vertical(
    t_eval: np.ndarray,
    z_eval: np.ndarray,
    field1: np.ndarray,
    field2: np.ndarray,
    field3: np.ndarray,
    title1: str,
    title2: str,
    title3: str,
    xlabel_bottom: str = "Time (s)",
    ylabel: str = "Distance z (m)",
    colorbar_label: str = r"$\log_{10}(N_e)$ (m$^{-3}$)",
    cmap: str = "jet",
    figsize: tuple[float, float] = (12, 14),
    dpi: int = 120,
    shading: str = "auto",
    use_log10: bool = True,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    show: bool = True,
    save_path: Optional[str | Path] = None,
) -> tuple[plt.Figure, tuple[plt.Axes, plt.Axes, plt.Axes]]:
    """
    绘制三个二维场的纵向对比图。

    典型用途
    --------
    适合一次性对比：
    - Large-scale baseline
    - Meso-scale modulated
    - Combined field

    这样在写报告或论文时，逻辑会比较完整。

    返回
    ----
    fig, (ax1, ax2, ax3)
    """
    T_mesh, Z_mesh = _make_mesh(t_eval, z_eval)

    if use_log10:
        p1 = np.log10(_ensure_positive_for_log10(field1))
        p2 = np.log10(_ensure_positive_for_log10(field2))
        p3 = np.log10(_ensure_positive_for_log10(field3))
    else:
        p1, p2, p3 = field1, field2, field3

    fig, axes = plt.subplots(3, 1, figsize=figsize, dpi=dpi)
    ax1, ax2, ax3 = axes

    for ax, plot_field, title in [
        (ax1, p1, title1),
        (ax2, p2, title2),
        (ax3, p3, title3),
    ]:
        mesh = ax.pcolormesh(
            T_mesh,
            Z_mesh,
            plot_field,
            cmap=cmap,
            shading=shading,
            vmin=vmin,
            vmax=vmax,
        )
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        fig.colorbar(mesh, ax=ax, pad=0.02, label=colorbar_label)

    ax3.set_xlabel(xlabel_bottom)

    fig.tight_layout()
    _finalize_figure(fig, save_path=save_path, show=show)
    return fig, (ax1, ax2, ax3)