# Issue 01 结果引用索引

## 用途

本文件只说明 `Issue 01` 现有结果各自支持什么审查判断，避免在 `Issue 02` 笔记中反复追目录。

## 结果根目录

- `corrections/issue_01_truth_dependency/comparison`
- `corrections/issue_01_truth_dependency/corrected_fullstack`

## 核心文件

### `comparison/issue_01_diff_summary.json`

支持内容：

- 跨频平均增量、极值和中位数。
- 判断“去掉真值辅助后，哪一层的误差放大最显著”。
- 证明误差不是只停留在单通道内部，而是进入 WLS / EKF。

本轮常用指标：

- `single_tau_rmse_ns`
- `single_fd_rmse_hz`
- `wls_case_b_wls_position_error_3d_m`
- `ekf_pr_doppler_mean_position_error_3d_m`
- `ekf_pr_doppler_mean_velocity_error_3d_mps`

### `comparison/issue_01_diff_tables.json`

支持内容：

- 提取代表频点。
- 比较 baseline 与 corrected 在同一频点的具体差分。
- 解释低频失稳和高频恢复的链路现象。

本轮重点引用频点：

- `19.0 GHz`
- `22.5 GHz`
- `25.0 GHz`
- `31.0 GHz`

### `comparison/issue_01_diff_plots.png`

支持内容：

- 直观呈现 baseline 与 corrected 的跨频差异。
- 作为总览图，不单独承担模型论证，但用于快速说明问题范围。

![Issue 01 baseline/corrected 差分图](../../issue_01_truth_dependency/comparison/issue_01_diff_plots.png)

### `corrected_fullstack/cross_frequency/combined_metrics.json`

支持内容：

- 修正版在各频点的单通道、WLS、EKF 汇总指标。
- 用于判断“去掉真值辅助后，系统在什么频段重新进入可跟踪区”。

### `corrected_fullstack/cross_frequency/combined_metrics_vs_frequency.png`

支持内容：

- 观察修正版自身在全频上的工作区间变化。
- 说明高频恢复不是单点巧合，而是跨频趋势。

![Issue 01 修正版跨频结果](../../issue_01_truth_dependency/corrected_fullstack/cross_frequency/combined_metrics_vs_frequency.png)

### `weekly_report_issue_01_truth_dependency.md`

支持内容：

- 已经形成的模型层解释。
- 本轮可以复用其结论口径，但要进一步收紧为“对象-变换-资格”的审查格式。

## 本轮使用规则

1. `Issue 01` 结果只作为支撑材料，不代替教材定义。
2. 任何合法性判断都必须先有对象定义，再用结果作证据。
3. 如果某个结论只靠结果现象而没有对象语义支撑，则本轮不把它视为完成的审查结论。
