from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS_DIR = REPO_ROOT / "notebooks"
DEFAULT_OUTPUT = REPO_ROOT / "reports" / "published" / "notebook_review_compendium.docx"
INPUT_NOTEBOOKS = [
    NOTEBOOKS_DIR / "signal_review_overview.ipynb",
    NOTEBOOKS_DIR / "receiver_review_overview.ipynb",
]
PART_TITLES = {
    "signal_review_overview": "第一部分：真实信号审阅",
    "receiver_review_overview": "第二部分：接收机审阅",
}


def run_checked(cmd: list[str], *, cwd: Path | None = None, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        check=True,
        text=True,
        capture_output=capture_output,
    )


def extract_readme_sections(readme_path: Path) -> tuple[list[str], list[str]]:
    notebook_lines: list[str] = []
    rule_lines: list[str] = []
    mode: str | None = None
    for raw in readme_path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            if line == "## 当前 notebook":
                mode = "notebooks"
            elif line == "## 标注规则":
                mode = "rules"
            else:
                mode = None
            continue
        if not line.strip():
            continue
        if mode == "notebooks" and line.lstrip().startswith("- "):
            notebook_lines.append(line.strip())
        elif mode == "rules" and line.lstrip().startswith("- "):
            rule_lines.append(line.strip())
    return notebook_lines, rule_lines


def demote_headings(markdown: str, *, shift: int = 1) -> str:
    lines = markdown.splitlines()
    out: list[str] = []
    for line in lines:
        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if match:
            level = min(6, len(match.group(1)) + shift)
            out.append(f"{'#' * level} {match.group(2)}")
        else:
            out.append(line)
    return "\n".join(out).strip() + "\n"


def clean_notebook_markdown(markdown: str) -> str:
    lines = markdown.splitlines()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("<div "):
            continue
        if stripped == "</div>":
            continue
        if stripped.startswith(":::"):
            continue
        out.append(line)
    cleaned = "\n".join(out)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() + "\n"


def notebook_to_markdown(notebook_path: Path, build_dir: Path) -> str:
    media_dir = Path("media") / notebook_path.stem
    result = run_checked(
        [
            "pandoc",
            "-f",
            "ipynb",
            "-t",
            "gfm",
            "--wrap=none",
            f"--extract-media={media_dir.as_posix()}",
            str(notebook_path),
        ],
        cwd=build_dir,
        capture_output=True,
    )
    return clean_notebook_markdown(result.stdout)


def build_intro(title: str, readme_path: Path) -> str:
    notebook_lines, rule_lines = extract_readme_sections(readme_path)
    notebook_bullets = "\n".join(notebook_lines) if notebook_lines else "- 当前正式 notebook 汇总"
    rule_bullets = "\n".join(rule_lines) if rule_lines else "- 保留讲解、代码、表格与图"
    return (
        f"% {title}\n"
        "%\n"
        "%\n\n"
        "# 导读\n\n"
        "这份 Word 文档把 `notebooks/` 下当前正式 notebook 汇编为一份连续可审阅的文档。"
        "保留 notebook 中已经执行出来的图、代码、表格和讲解，不手工重绘图片，也不改写核心内容。\n\n"
        "## 当前纳入的 notebook\n\n"
        f"{notebook_bullets}\n\n"
        "## 内容标记\n\n"
        f"{rule_bullets}\n\n"
        "下面先进入真实信号部分，再自然过渡到接收机部分。\n"
    )


def build_transition() -> str:
    return (
        "\n\\newpage\n\n"
        "# 从信号到接收机\n\n"
        "前一部分回答的是“真实信号如何生成、延迟、调制并形成接收输入”。"
        "下一部分开始回答“接收机如何消费这些输入，并把它们变成 acquisition、tracking、diagnostics 和 observables”。\n"
    )


def export_docx(output_path: Path, title: str) -> None:
    if shutil.which("pandoc") is None:
        raise RuntimeError("pandoc 未安装或不在 PATH 中。")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="notebook-docx-build-") as tmp:
        build_dir = Path(tmp)
        readme_path = NOTEBOOKS_DIR / "README.md"

        parts = [build_intro(title, readme_path)]
        first = True
        for notebook_path in INPUT_NOTEBOOKS:
            markdown = notebook_to_markdown(notebook_path, build_dir)
            markdown = demote_headings(markdown, shift=1)
            if not first:
                parts.append(build_transition())
            part_title = PART_TITLES.get(notebook_path.stem)
            if part_title:
                parts.append(f"# {part_title}\n")
            parts.append(markdown)
            first = False

        merged_markdown = "\n\n".join(parts).strip() + "\n"
        merged_path = build_dir / "merged_notebooks.md"
        merged_path.write_text(merged_markdown, encoding="utf-8")

        run_checked(
            [
                "pandoc",
                str(merged_path),
                "--toc",
                "--standalone",
                "--highlight-style",
                "tango",
                "-o",
                str(output_path),
            ],
            cwd=build_dir,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export reviewed notebooks to a single DOCX via pandoc.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output .docx path.")
    parser.add_argument("--title", default="Notebook 审阅汇编", help="Document title.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    export_docx(args.output.resolve(), args.title)
    print(f"Wrote DOCX to: {args.output.resolve()}")


if __name__ == "__main__":
    main()
