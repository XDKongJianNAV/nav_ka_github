from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
SRC_ROOT = PACKAGE_ROOT.parent
REPO_ROOT = SRC_ROOT.parent
ARCHIVE_ROOT = REPO_ROOT / "archive"
CANONICAL_RESULTS_ROOT = ARCHIVE_ROOT / "results" / "canonical"
SCRATCH_RESULTS_ROOT = ARCHIVE_ROOT / "results" / "scratch"
CORRECTIONS_ROOT = ARCHIVE_ROOT / "research" / "corrections"

