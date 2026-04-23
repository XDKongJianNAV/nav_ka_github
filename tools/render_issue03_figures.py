from __future__ import annotations

import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC_DIR = REPO_ROOT / "corrections" / "issue_03_textbook_full_correction" / "notes" / "fig_specs"
OUT_DIR = REPO_ROOT / "corrections" / "issue_03_textbook_full_correction" / "notes" / "figures"

DOT_CANDIDATES = [
    Path("/opt/homebrew/opt/graphviz/bin/dot"),
    Path("/opt/homebrew/bin/dot"),
    Path("/usr/local/bin/dot"),
]


def find_dot() -> Path:
    for candidate in DOT_CANDIDATES:
        if candidate.exists():
            return candidate
    raise SystemExit("未找到 Graphviz 的 dot。请先安装 graphviz。")


def render(dot_bin: Path, spec_path: Path) -> None:
    stem = spec_path.stem
    for fmt in ("svg", "png"):
        output_path = OUT_DIR / f"{stem}.{fmt}"
        subprocess.run(
            [str(dot_bin), "-T", fmt, str(spec_path), "-o", str(output_path)],
            check=True,
        )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dot_bin = find_dot()
    spec_paths = sorted(SPEC_DIR.glob("*.dot"))
    if not spec_paths:
        raise SystemExit("未找到任何 .dot 结构化图规格。")
    for spec_path in spec_paths:
        render(dot_bin, spec_path)
    print(f"已生成 {len(spec_paths)} 张图，每张输出 SVG 和 PNG。")


if __name__ == "__main__":
    main()
