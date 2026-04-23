# Issue 01: 真值依赖纠正说明

## 本轮去掉的运行时真值依赖

1. 单通道跟踪中的 `code_aiding_rate_chips_per_s` 真值注入已关闭。
2. 单通道跟踪中的 `carrier_aiding_rate_hz_per_s` 真值注入已关闭。
3. WLS 单历元求解不再用接收机真值位置/钟差构造默认初值。
4. 动态 epoch-wise WLS 首历元不再用真值位置/钟差构造 warm start。

## 本轮仍保留 truth 的位置

1. synthetic observation 的生成仍然使用 truth，这属于仿真造数层。
2. 误差统计、图表 reference curve、baseline/corrected 对比仍然使用 truth，这属于离线评估层。

## 目录

- baseline: `/Users/guozehao/Documents/ka-Nav/nav_ka_github/results_ka_multifreq`
- corrected: `/Users/guozehao/Documents/ka-Nav/nav_ka_github/corrections/issue_01_truth_dependency/corrected_fullstack`

## 指标差分摘要

- `single_tau_rmse_ns`: mean delta = 3913.06, median delta = 35.8851, min delta = -4.80129, max delta = 11856.8
- `single_fd_rmse_hz`: mean delta = 1529.81, median delta = -19.6982, min delta = -29.4923, max delta = 3723.9
- `wls_case_b_wls_position_error_3d_m`: mean delta = 1543.99, median delta = -18.1811, min delta = -69.9731, max delta = 3998.98
- `ekf_pr_doppler_mean_position_error_3d_m`: mean delta = 39773.7, median delta = 170.487, min delta = 4.46686, max delta = 321557
- `ekf_pr_doppler_mean_velocity_error_3d_mps`: mean delta = 4328.83, median delta = 0.259397, min delta = 0.012335, max delta = 32288.6
