from pathlib import Path
import sys

# ------------------------------------------------------------
# 1. 把仓库根目录下的 src 加入 Python 搜索路径
# ------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# 现在就可以直接导入 src 里的单文件模块
from plasma_field_core import build_fields_from_csv
from plasma_field_plot import plot_scalar_field_2d, plot_three_fields_vertical

# ------------------------------------------------------------
# 2. 数据文件路径
#    用绝对路径拼接，避免运行目录变化导致找不到 CSV
# ------------------------------------------------------------
large_csv = ROOT / "notebooks" / "Large_Scale_Ne_Smooth.csv"
aoa_csv = ROOT / "notebooks" / "RAMC_AOA_Sim_Input.csv"

# ------------------------------------------------------------
# 3. 计算场
# ------------------------------------------------------------
result = build_fields_from_csv(
    large_csv_path=large_csv,
    aoa_csv_path=aoa_csv,
    start_time=400.0,
)

plot_scalar_field_2d(
    t_eval=result["t_eval"],
    z_eval=result["z_eval"],
    field=result["ne_meso"],
    title="Meso-scale Electron Density",
    vmin=14,
    vmax=18.5,
)

plot_three_fields_vertical(
    t_eval=result["t_eval"],
    z_eval=result["z_eval"],
    field1=result["ne_large"],
    field2=result["ne_meso"],
    field3=result["ne_combined"],
    title1="Large-scale Baseline",
    title2="Meso-scale Modulated",
    title3="Combined Field",
    vmin=14,
    vmax=18.5,
)