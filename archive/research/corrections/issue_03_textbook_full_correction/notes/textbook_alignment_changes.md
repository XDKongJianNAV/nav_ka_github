# Issue 03: 教材对齐修正清单

## 本轮新增的正式层次

1. `signal model`：把导航数据符号真实加入发射/接收信号对象。
2. `receiver natural measurements`：接收机层只输出 `tau_est_s / carrier_phase_rad / carrier_frequency_hz`。
3. `observable formation`：新增标准伪距、载波相位、距离率形成层。
4. `navigation`：WLS/EKF 继续使用 truth-free 初始化，但只消费标准观测。

## 与 legacy / issue01 的关系

- legacy：存在运行时真值依赖，并在接收机层把内部状态直接命名为观测。
- issue01：去掉了真值依赖，但仍保留未完全教材化的信号/观测接口。
- issue03：在 issue01 基础上继续修正信号对象、环路结构表达和观测形成边界。

## 代码层落点

- `src/issue_03_textbook_correction.py`：Issue 03 corrected 单通道、自然测量量、标准观测和三方对比工具。
- `notebooks/exp_multisat_wls_pvt_report.py`：新增 `channel_background_mode`，允许 WLS 使用 corrected 背景。
- `notebooks/exp_dynamic_multisat_ekf_report.py`：新增 `channel_background_mode`，允许 EKF 使用 corrected 背景。

## 默认口径

- `truth_free_runtime=True`
- `truth_free_initialization=True`
- `channel_background_mode=issue03_textbook`
- `nav_data_enabled=True`
