# nav_ka_github

Ka 波段等离子体传播、WKB 接收机链路、多星 WLS/EKF 导航实验仓库。

仓库已经按“核心代码 + 稳定入口 + 正式结果 + 归档 + review”分层整理，默认先看下面这些位置：

- 核心包：`src/nav_ka/core`、`src/nav_ka/models`、`src/nav_ka/studies`
- 稳定入口：`scripts/`
- 可视化审阅 notebook：`notebooks/`
- 输入数据：`data/raw/`
- 正式报告：`reports/builders/`、`reports/published/`
- 正式结果：`archive/results/canonical/`
- 研究修正过程：`archive/research/corrections/`
- 人工 review 路线：`review/REVIEW_QUEUE.md`

## 运行

```bash
uv sync
uv run python scripts/run_ka_multifreq_full_stack.py
uv run python scripts/run_issue_01_truth_dependency_full_stack.py
uv run python scripts/run_issue_03_textbook_full_correction.py
uv run python scripts/run_issue_04_imu_aided_full_stack.py
```

也可以先看仓库导航入口：

```bash
uv run python main.py
```

## 目录说明

- `src/nav_ka/core/`：稳定物理与绘图基础层。
- `src/nav_ka/models/`：教材/抽象模型层。
- `src/nav_ka/studies/`：Issue 研究与修正逻辑。
- `src/nav_ka/legacy/`：保留的历史研究脚本与桥接层，不作为默认公共接口。
- `scripts/`：当前受支持的批量实验入口。
- `notebooks/`：Jupyter 可视化审阅与概念解释。
- `data/raw/`：原始 CSV 输入。
- `reports/builders/`：报告构建器。
- `reports/published/`：正式导出的报告文件。
- `archive/results/canonical/`：正式结果集。
- `archive/results/scratch/`：中间产物、smoke 输出和临时结果。
- `archive/research/corrections/`：Issue 01/02/03 的过程档案。
- `docs/`：仓库地图、说明文档和知识资产。
- `review/`：全仓清单与人工 review 队列。

## 导入约定

正式代码统一从 `nav_ka.*` 导入，例如：

```python
from nav_ka.core.plasma_wkb_core import run_wkb_frequency_sweep
from nav_ka.studies.issue_03_textbook_correction import build_textbook_channel_background
```

`src/` 根下保留了少量兼容 wrapper，仅用于避免旧脚本彻底断裂；新代码不要继续依赖这些顶层模块名。

## 补充索引

- 仓库地图：[docs/repo_map.md](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/repo_map.md)
- 归档说明：[archive/README.md](/Users/guozehao/Documents/ka-Nav/nav_ka_github/archive/README.md)
- 数据说明：[data/README.md](/Users/guozehao/Documents/ka-Nav/nav_ka_github/data/README.md)
- review 队列：[review/REVIEW_QUEUE.md](/Users/guozehao/Documents/ka-Nav/nav_ka_github/review/REVIEW_QUEUE.md)
