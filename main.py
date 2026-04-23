from __future__ import annotations


def main() -> None:
    print("nav_ka_github repository navigator")
    print("")
    print("Core package:")
    print("  - src/nav_ka/core")
    print("  - src/nav_ka/models")
    print("  - src/nav_ka/studies")
    print("")
    print("Stable entrypoints:")
    print("  - uv run python scripts/run_ka_multifreq_full_stack.py")
    print("  - uv run python scripts/run_issue_01_truth_dependency_full_stack.py")
    print("  - uv run python scripts/run_issue_03_textbook_full_correction.py")
    print("")
    print("Canonical results: archive/results/canonical")
    print("Scratch results:   archive/results/scratch")
    print("Corrections:       archive/research/corrections")
    print("Review queue:      review/REVIEW_QUEUE.md")


if __name__ == "__main__":
    main()
