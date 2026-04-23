# -*- coding: utf-8 -*-
"""
plot_sky_geometry_only.py
=========================

只从现有结果文件读取数据，生成 `results_multisat_wls/sky_geometry.png`。

输入
----
- `results_multisat_wls/satellite_observations.csv`
- `results_multisat_wls/summary.json`

输出
----
- `results_multisat_wls/sky_geometry.png`

说明
----
1. 不重新跑接收机，不重新跑解算。
2. 直接使用已经生成的逐星观测数据。
3. 只负责把天空几何画清楚。
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = ROOT / "archive" / "results" / "canonical" / "results_multisat_wls"
CSV_PATH = RESULTS_DIR / "satellite_observations.csv"
SUMMARY_PATH = RESULTS_DIR / "summary.json"
OUTPUT_PATH = RESULTS_DIR / "sky_geometry.png"


@dataclass(frozen=True)
class SkyRow:
    case_name: str
    sat_id: str
    azimuth_deg: float
    elevation_deg: float
    sigma_m: float


def load_rows() -> list[SkyRow]:
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"找不到观测文件: {CSV_PATH}")
    if not SUMMARY_PATH.exists():
        raise FileNotFoundError(f"找不到摘要文件: {SUMMARY_PATH}")

    rows: list[SkyRow] = []
    with CSV_PATH.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                SkyRow(
                    case_name=row["case_name"],
                    sat_id=row["sat_id"],
                    azimuth_deg=float(row["azimuth_deg"]),
                    elevation_deg=float(row["elevation_deg"]),
                    sigma_m=float(row["sigma_m"]),
                )
            )
    return rows


def load_case_pdop() -> dict[str, float]:
    with SUMMARY_PATH.open("r", encoding="utf-8") as f:
        summary = json.load(f)
    experiments = summary.get("experiments", {})
    pdop_map: dict[str, float] = {}
    for case_name, case_info in experiments.items():
        dops = case_info.get("dops", {})
        pdop_map[case_name] = float(dops.get("PDOP", float("nan")))
    return pdop_map


def plot_sky_geometry(rows: list[SkyRow], pdop_map: dict[str, float]) -> None:
    case_names = sorted({row.case_name for row in rows})
    fig, axes = plt.subplots(
        1,
        len(case_names),
        subplot_kw={"projection": "polar"},
        figsize=(13.5, 6.0),
        dpi=160,
    )
    if len(case_names) == 1:
        axes = [axes]

    cmap = plt.get_cmap("viridis")
    norm = plt.Normalize(vmin=min(row.sigma_m for row in rows), vmax=max(row.sigma_m for row in rows))
    last_scatter = None

    for ax, case_name in zip(axes, case_names, strict=True):
        case_rows = [row for row in rows if row.case_name == case_name]
        theta_rad = np.deg2rad([row.azimuth_deg for row in case_rows])
        radius_deg = 90.0 - np.array([row.elevation_deg for row in case_rows], dtype=float)
        colors = [cmap(norm(row.sigma_m)) for row in case_rows]

        last_scatter = ax.scatter(
            theta_rad,
            radius_deg,
            s=120,
            c=colors,
            edgecolors="black",
            linewidths=0.6,
            zorder=3,
        )

        for row, theta, radius in zip(case_rows, theta_rad, radius_deg, strict=True):
            label_radius = min(radius + 3.5, 88.0)
            ax.annotate(
                row.sat_id,
                xy=(theta, radius),
                xytext=(theta, label_radius),
                ha="center",
                va="center",
                fontsize=9,
                arrowprops=dict(arrowstyle="-", lw=0.5, color="0.35"),
            )

        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        ax.set_rlim(90.0, 0.0)
        ax.set_rticks([10, 25, 40, 55, 70, 85])
        ax.set_yticklabels(["80°", "65°", "50°", "35°", "20°", "5°"])
        ax.tick_params(labelsize=9)
        pdop = pdop_map.get(case_name, float("nan"))
        ax.set_title(f"Case {case_name}\nPDOP={pdop:.2f}", pad=20, fontsize=12)
        ax.grid(True, ls=":", alpha=0.55)

    fig.subplots_adjust(left=0.04, right=0.87, top=0.88, bottom=0.10, wspace=0.42)
    cbar_ax = fig.add_axes([0.90, 0.18, 0.018, 0.64])
    cbar = fig.colorbar(last_scatter, cax=cbar_ax)
    cbar.set_label("Sigma (m)")
    cbar.ax.tick_params(labelsize=9)
    fig.suptitle("Sky geometry and observation sigma", y=0.98, fontsize=13)
    fig.savefig(OUTPUT_PATH, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_rows()
    pdop_map = load_case_pdop()
    plot_sky_geometry(rows, pdop_map)
    print(f"已生成: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
