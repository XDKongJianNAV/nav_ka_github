# Review Queue

按下面顺序人工过目，能最快建立对仓库的整体把握。

1. 核心数值层：`src/nav_ka/core/`
2. 教材与接口层：`src/nav_ka/models/`
3. 研究修正层：`src/nav_ka/studies/`
4. 正式运行入口：`scripts/`
5. 报告构建器：`reports/builders/`
6. 正式结果：`archive/results/canonical/`
7. 专题修正档案：`archive/research/corrections/`
8. legacy 研究脚本：`src/nav_ka/legacy/`

建议先 review：

- `src/nav_ka/core/plasma_wkb_core.py`
- `src/nav_ka/legacy/ka_multifreq_receiver_common.py`
- `src/nav_ka/studies/issue_01_truth_dependency.py`
- `src/nav_ka/studies/issue_03_textbook_correction.py`
- `scripts/run_ka_multifreq_full_stack.py`
- `scripts/run_issue_01_truth_dependency_full_stack.py`
- `scripts/run_issue_03_textbook_full_correction.py`

`review/FILE_INVENTORY.csv` 提供全仓逐文件清单，可配合这一顺序逐项勾看。
