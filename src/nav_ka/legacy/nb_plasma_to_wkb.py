from pathlib import Path
import sys

import numpy as np
import matplotlib.pyplot as plt


# ============================================================
# 0. 路径准备：把仓库根目录下的 src 加入 Python 搜索路径
# ============================================================

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from plasma_field_core import build_fields_from_csv
from plasma_field_plot import (
    plot_scalar_field_2d,
    plot_three_fields_vertical,
    plot_profile_comparison_from_fields,
)
from plasma_wkb_core import run_wkb_pipeline


# ============================================================
# 1. 数据文件路径
#    如果你的 CSV 不在仓库根目录，请改这里
# ============================================================

large_csv = ROOT / "notebooks" / "Large_Scale_Ne_Smooth.csv"
aoa_csv = ROOT / "notebooks" / "RAMC_AOA_Sim_Input.csv"

print("ROOT =", ROOT)
print("large_csv =", large_csv)
print("aoa_csv =", aoa_csv)

if not large_csv.exists():
    raise FileNotFoundError(f"找不到大尺度数据文件: {large_csv}")

if not aoa_csv.exists():
    raise FileNotFoundError(f"找不到 AOA 数据文件: {aoa_csv}")


# ============================================================
# 2. 生成电子密度场
# ============================================================

result = build_fields_from_csv(
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

t_eval = result["t_eval"]
z_eval = result["z_eval"]

ne_large = result["ne_large"]
ne_meso = result["ne_meso"]
ne_only_small = result["ne_only_small"]
ne_combined = result["ne_combined"]

print(">>> 电子密度场生成完成")
print("t_eval shape =", t_eval.shape)
print("z_eval shape =", z_eval.shape)
print("ne_combined shape =", ne_combined.shape)


# ============================================================
# 3. 先看电子密度场
# ============================================================

plot_three_fields_vertical(
    t_eval=t_eval,
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


# ============================================================
# 4. 看一个固定时刻的剖面对比
#    这里选中间时刻
# ============================================================

mid_idx = len(t_eval) // 2

plot_profile_comparison_from_fields(
    t_eval=t_eval,
    z_eval=z_eval,
    field_dict={
        "Large-scale": ne_large,
        "Meso-scale": ne_meso,
        "Only Small-scale": ne_only_small,
        "Combined": ne_combined,
    },
    time_index=mid_idx,
    title_prefix="Electron Density Profile Comparison",
)


# ============================================================
# 5. 进入 WKB 传播计算
# ============================================================

f_em = 2.3e9       # S 波段示例
nu_en = 1.0e9      # 碰撞频率示例，当前按 Hz 输入

wkb_result = run_wkb_pipeline(
    f_EM=f_em,
    z_grid=z_eval,
    Ne_matrix=ne_combined,
    nu_en=nu_en,
    collision_input_unit="Hz",
    amplitude_floor=1e-20,
    fix_physics=True,
    verbose=True,
)

A_t = wkb_result["amplitude"]
atten_dB = wkb_result["attenuation_dB"]
phi_t = wkb_result["phase_shift_rad"]
h_p_t = wkb_result["transmission_coeff"]
summary = wkb_result["summary"]

print("\n>>> WKB 传播计算完成")
for k, v in summary.items():
    print(f"{k}: {v}")


# ============================================================
# 6. WKB 结果图：幅度衰减 / dB 衰减 / 相移
# ============================================================

fig, axes = plt.subplots(3, 1, figsize=(12, 10), dpi=120)

# (1) 线性幅度 A(t)
axes[0].plot(t_eval, A_t, color="tab:blue", lw=1.5)
axes[0].set_title("WKB Amplitude Attenuation A(t)")
axes[0].set_ylabel("A(t)")
axes[0].grid(True, ls=":", alpha=0.5)

# (2) dB 衰减
finite_atten = atten_dB[np.isfinite(atten_dB)]
if finite_atten.size > 0:
    dynamic_min = np.percentile(finite_atten, 2)
    plot_min = max(dynamic_min, -100)
else:
    plot_min = -100

axes[1].plot(t_eval, atten_dB, color="tab:green", lw=1.5)
axes[1].axvline(x=412, color="gray", linestyle="--", alpha=0.5)
axes[1].set_ylim(plot_min, 2)
axes[1].set_title("WKB Attenuation in dB")
axes[1].set_ylabel("Attenuation (dB)")
axes[1].grid(True, ls=":", alpha=0.5)

# (3) 相移
finite_phi = phi_t[np.isfinite(phi_t)]
axes[2].plot(t_eval, phi_t, color="tab:red", lw=1.5)
if finite_phi.size > 0:
    axes[2].set_ylim(np.min(finite_phi) - 1.0, np.max(finite_phi) + 1.0)
axes[2].set_title("WKB Phase Shift")
axes[2].set_xlabel("Time (s)")
axes[2].set_ylabel("Phase (rad)")
axes[2].grid(True, ls=":", alpha=0.5)

plt.tight_layout()
plt.show()


# ============================================================
# 7. 看某几个时刻的传播系数
# ============================================================

sample_indices = [0, len(t_eval) // 4, len(t_eval) // 2, 3 * len(t_eval) // 4, len(t_eval) - 1]

print("\n>>> 采样时刻的传播结果")
for idx in sample_indices:
    print(
        f"t = {t_eval[idx]:.3f} s | "
        f"A = {A_t[idx]:.4e} | "
        f"atten_dB = {atten_dB[idx]:.3f} dB | "
        f"phi = {phi_t[idx]:.3f} rad | "
        f"hp = {h_p_t[idx]}"
    )
