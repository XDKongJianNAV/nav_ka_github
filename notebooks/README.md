# Notebooks

这个目录放“可视化审阅与概念解释”的正式 Jupyter 资产，不再作为历史脚本堆放区。

## 运行方式

```bash
uv sync
uv run jupyter lab
```

如果只想批量执行并更新输出：

```bash
uv run jupyter nbconvert --execute --inplace notebooks/signal_review_overview.ipynb
uv run jupyter nbconvert --execute --inplace notebooks/receiver_review_overview.ipynb
uv run jupyter nbconvert --execute --inplace notebooks/imu_aided_receiver_dynamics_review.ipynb
uv run python tools/export_notebooks_to_docx.py
```

## 当前 notebook

- `signal_review_overview.ipynb`
  信号部分总览 notebook。主题只到“信号生成到接收机输入 `rx_block`”。
- `receiver_review_overview.ipynb`
  接收机部分总览 notebook。主题到 acquisition、tracking、observables 和 diagnostics。
- `imu_aided_receiver_dynamics_review.ipynb`
  IMU 辅助动态接收机专题 notebook。主题是“纯接收机基线”和“IMU/INS 接入后的动态耦合链路”对照，并补充报告里的细节图。

## 标注规则

notebook 里的内容固定分三类：

- `真实代码调用`
  直接导入并调用仓库现有源码。核心信号函数不能在 notebook 里复制一遍。
- `概念推导`
  为了说明教材概念而写在 notebook 里的解析推导或教学可视化。
- `未实现但相关的概念`
  例如 `BOC`、`BCS`、`pilot`。这些可以被解释和可视化，但必须显式标注“当前仓库信号链未实现”。

## 单一来源

总览类 notebook 的真实链路单元，只允许从这两处导入：

- `nav_ka.legacy.ka_multifreq_receiver_common`
- `nav_ka.studies.issue_03_textbook_correction`

专题类 notebook 允许额外导入：

- `nav_ka.studies.issue_04_imu_aided`

其中真实可视化主要依赖：

- `mseq_7`
- `sample_code_waveform`
- `build_default_field_context`
- `compute_real_wkb_series`
- `resample_wkb_to_receiver_time`
- `build_transmitter_signal_tools`
- `build_signal_block_trace`
- `build_navigation_data_model`
- `sample_navigation_waveform`
- `build_textbook_signal_block_trace`

## 边界

总览 notebook 第一版不展开这些层：

- WLS / EKF
- 独立 pilot 通道实现

这些边界和 [review/signal_generation_to_rx_review.md](/Users/guozehao/Documents/ka-Nav/nav_ka_github/review/signal_generation_to_rx_review.md) 保持一致。

专题 notebook 可以在明确标注目标的前提下延伸到动态导航层，但必须复用仓库现有核心代码，不得在 notebook 内复制实现一遍。
