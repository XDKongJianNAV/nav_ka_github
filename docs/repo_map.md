# Repo Map

## Primary

- `src/nav_ka/core/`
  核心数值与绘图逻辑。
- `src/nav_ka/models/`
  教材对齐的信号、跟踪和观测抽象。
- `src/nav_ka/studies/`
  Issue 纠正与对比逻辑。
- `scripts/`
  当前推荐运行入口。

## Secondary

- `reports/builders/`
  构建正式报告的脚本。
- `reports/published/`
  可直接查看的正式报告产物。
- `docs/gnss_book_ai/`
  知识资产与拆书结果，保留在文档层，不参与正式代码导入。

## Archived

- `archive/results/canonical/`
  正式实验结果。
- `archive/results/scratch/`
  中间结果与 smoke 输出。
- `archive/research/corrections/`
  研究修正过程与专题周报。

## Legacy

- `src/nav_ka/legacy/`
  可追溯的历史脚本。默认不作为公共接口，但为了复现实验和对照仍完整保留。

## Review Order

1. `src/nav_ka/core/`
2. `src/nav_ka/models/`
3. `src/nav_ka/studies/`
4. `scripts/`
5. `reports/builders/`
6. `archive/results/canonical/`
7. `archive/research/corrections/`
8. `src/nav_ka/legacy/`
