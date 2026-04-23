# Archive Layout

- `archive/results/canonical/`
  当前认可的正式结果集。顶层主入口不再直接暴露这些目录。
- `archive/results/scratch/`
  临时、smoke、试跑和中间结果。保留但默认不纳入首页工作流。
- `archive/research/corrections/`
  专题修正过程、差分图、周报和笔记。
- `archive/research/legacy/`
  预留给后续需要继续下沉的历史资料；当前主要 legacy 代码已收口到 `src/nav_ka/legacy/` 以便可导入。

归档原则：

- 不删除已有源文件和结果文件。
- 优先下沉暴露面，而不是销毁历史。
- 正式入口只指向 `canonical`，不指向 `scratch`。
