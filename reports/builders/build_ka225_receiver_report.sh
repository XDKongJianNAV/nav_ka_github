#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
FONT_DIR="/mnt/c/Windows/Fonts"
DOCX_PAGE_DIR="$ROOT_DIR/reports/assets/ka225_receiver/docx_pages"

cd "$ROOT_DIR"

uv run python reports/builders/generate_ka225_receiver_report_assets.py
~/.cargo/bin/typst compile \
  --font-path "$FONT_DIR" \
  reports/published/ka225_receiver/ka225_receiver_work_report.typ \
  reports/published/ka225_receiver/ka225_receiver_work_report.pdf
uv run python -c "from pathlib import Path; import shutil; p = Path(r'$DOCX_PAGE_DIR'); shutil.rmtree(p, ignore_errors=True); p.mkdir(parents=True, exist_ok=True)"
~/.cargo/bin/typst compile \
  --font-path "$FONT_DIR" \
  --format png \
  --ppi 220 \
  reports/published/ka225_receiver/ka225_receiver_work_report.typ \
  "$DOCX_PAGE_DIR/page-{0p}.png"
uv run python reports/builders/build_ka225_receiver_report_docx.py
