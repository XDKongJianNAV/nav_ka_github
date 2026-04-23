from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "corrections" / "issue_03_textbook_full_correction" / "notes" / "loop_design_comparison_spec.json"
SVG_PATH = ROOT / "corrections" / "issue_03_textbook_full_correction" / "notes" / "loop_design_comparison.svg"
PNG_PATH = ROOT / "corrections" / "issue_03_textbook_full_correction" / "notes" / "loop_design_comparison.png"

FIG_W = 18
FIG_H = 11
PANEL_W = 4.8
PANEL_H = 8.8
PANEL_GAP = 0.45
BOX_W = 3.2
BOX_H = 0.72
TOP_Y = 8.2
ROW_STEP = 0.98

THEMES = {
    "warn": {
        "panel_face": "#fffaf5",
        "panel_edge": "#d8c3a5",
        "box_face": "#ffffff",
        "box_edge": "#8b5e34",
        "title": "#7b341e",
        "main": "#8b5e34",
        "feedback": "#2f855a",
        "callout": "#c05621",
    },
    "good": {
        "panel_face": "#f6fffb",
        "panel_edge": "#b7d7c5",
        "box_face": "#ffffff",
        "box_edge": "#2f855a",
        "title": "#276749",
        "main": "#2f855a",
        "feedback": "#2b6cb0",
        "callout": "#2f855a",
    },
    "neutral": {
        "panel_face": "#fbfdff",
        "panel_edge": "#cbd5e0",
        "box_face": "#ffffff",
        "box_edge": "#3b5b7a",
        "title": "#2d3748",
        "main": "#3b5b7a",
        "feedback": "#3b5b7a",
        "callout": "#5a6b7f",
    },
}

FONT_CANDIDATES = [
    "/System/Library/AssetsV2/com_apple_MobileAsset_Font8/86ba2c91f017a3749571a82f2c6d890ac7ffb2fb.asset/AssetData/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]


def configure_fonts() -> None:
    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if not path.exists():
            continue
        try:
            font_name = fm.FontProperties(fname=str(path)).get_name()
            plt.rcParams["font.family"] = font_name
            plt.rcParams["axes.unicode_minus"] = False
            return
        except Exception:
            continue
    plt.rcParams["axes.unicode_minus"] = False


def load_spec() -> dict:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def panel_origin(panel_index: int) -> tuple[float, float]:
    x = 0.45 + panel_index * (PANEL_W + PANEL_GAP)
    y = 0.7
    return x, y


def node_rect(panel_x: float, row: int) -> tuple[float, float, float, float]:
    x = panel_x + (PANEL_W - BOX_W) / 2.0
    y = TOP_Y - row * ROW_STEP
    return x, y, BOX_W, BOX_H


def node_anchor(rect: tuple[float, float, float, float], side: str) -> tuple[float, float]:
    x, y, w, h = rect
    if side == "top":
        return x + w / 2.0, y + h
    if side == "bottom":
        return x + w / 2.0, y
    if side == "left":
        return x, y + h / 2.0
    if side == "right":
        return x + w, y + h / 2.0
    raise ValueError(side)


def draw_arrow(ax, start, end, color, linestyle="-", rad=0.0, lw=2.0):
    arrow = FancyArrowPatch(
        start,
        end,
        connectionstyle=f"arc3,rad={rad}",
        arrowstyle="-|>",
        mutation_scale=14,
        linewidth=lw,
        color=color,
        linestyle=linestyle,
        shrinkA=6,
        shrinkB=6,
    )
    ax.add_patch(arrow)


def draw_panel(ax, panel_index: int, panel_spec: dict):
    theme = THEMES[panel_spec["theme"]]
    px, py = panel_origin(panel_index)

    panel = FancyBboxPatch(
        (px, py),
        PANEL_W,
        PANEL_H,
        boxstyle="round,pad=0.02,rounding_size=0.08",
        linewidth=1.8,
        edgecolor=theme["panel_edge"],
        facecolor=theme["panel_face"],
    )
    ax.add_patch(panel)
    ax.text(px + PANEL_W / 2.0, py + PANEL_H - 0.25, panel_spec["title"], ha="center", va="center", fontsize=18, color=theme["title"], fontweight="bold")

    node_map: dict[str, tuple[float, float, float, float]] = {}
    for node in panel_spec["nodes"]:
        rect = node_rect(px, node["row"])
        node_map[node["id"]] = rect
        x, y, w, h = rect
        box = FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.02,rounding_size=0.06",
            linewidth=1.8,
            edgecolor=theme["box_edge"],
            facecolor=theme["box_face"],
        )
        ax.add_patch(box)
        ax.text(x + w / 2.0, y + h * 0.62, node["title"], ha="center", va="center", fontsize=13.5, color="#1f2933", fontweight="bold")
        ax.text(x + w / 2.0, y + h * 0.28, node["subtitle"], ha="center", va="center", fontsize=11.5, color="#486581")

    for edge in panel_spec["edges"]:
        src = node_map[edge["from"]]
        dst = node_map[edge["to"]]
        if edge["kind"] == "main":
            start = node_anchor(src, "bottom")
            end = node_anchor(dst, "top")
            if dst[1] > src[1]:
                start = node_anchor(src, "top")
                end = node_anchor(dst, "bottom")
            draw_arrow(ax, start, end, theme["main"])
        elif edge["kind"] == "feedback":
            start = node_anchor(src, "right")
            end = node_anchor(dst, "right")
            if dst[0] < src[0]:
                start = node_anchor(src, "left")
                end = node_anchor(dst, "left")
            draw_arrow(ax, start, end, theme["feedback"], rad=0.28, lw=2.1)

    for callout in panel_spec.get("callouts", []):
        target = node_map[callout["target"]]
        tx, ty = node_anchor(target, "left" if callout["side"] == "left" else "right")
        bw = 1.3 if len(callout["text"]) < 12 else 1.9
        bh = 0.44
        cx = tx - bw - 0.22 if callout["side"] == "left" else tx + 0.22
        cy = ty - bh / 2.0
        box = FancyBboxPatch(
            (cx, cy),
            bw,
            bh,
            boxstyle="round,pad=0.02,rounding_size=0.05",
            linewidth=1.5,
            edgecolor=theme["callout"],
            facecolor="#fffdf8",
        )
        ax.add_patch(box)
        ax.text(cx + bw / 2.0, cy + bh / 2.0, callout["text"], ha="center", va="center", fontsize=10.5, color=theme["callout"])
        draw_arrow(ax, (cx + bw, cy + bh / 2.0) if callout["side"] == "left" else (cx, cy + bh / 2.0), (tx, ty), theme["callout"], linestyle="--", lw=1.7)

    ax.text(px + PANEL_W / 2.0, py + 0.22, panel_spec["footer"], ha="center", va="center", fontsize=10.8, color="#52606d")


def main():
    configure_fonts()
    spec = load_spec()
    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    fig.patch.set_facecolor("#f6f9fc")
    ax.set_facecolor("#f6f9fc")
    ax.set_xlim(0, 15.5)
    ax.set_ylim(0, 10.2)
    ax.axis("off")

    ax.text(7.75, 9.82, spec["title"], ha="center", va="center", fontsize=22, color="#102a43", fontweight="bold")
    ax.text(7.75, 9.48, spec["subtitle"], ha="center", va="center", fontsize=12, color="#486581")

    for idx, panel in enumerate(spec["panels"]):
        draw_panel(ax, idx, panel)

    SVG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(SVG_PATH, format="svg", bbox_inches="tight")
    fig.savefig(PNG_PATH, format="png", dpi=220, bbox_inches="tight")
    plt.close(fig)
    print(f"svg: {SVG_PATH}")
    print(f"png: {PNG_PATH}")


if __name__ == "__main__":
    main()
