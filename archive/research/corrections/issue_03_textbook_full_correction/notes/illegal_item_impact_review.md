# Issue 03: 不合法 / 不标准项影响复核

本文件采用三段对比口径：

- `legacy -> issue01`：隔离真值依赖的影响。
- `issue01 -> issue03`：隔离教材分层修正后的影响。
- `legacy -> issue03`：观察从原始实现到教材修正版的总效果。

## 1. 运行时真值注入

教材标准：环路应由相关器输出和内部状态驱动，不应由真值动态直接稳定。

- `single_tau_rmse_ns` 平均变化（issue01 - legacy）= 3913.059
- `wls_case_b_wls_position_error_3d_m` 平均变化（issue01 - legacy）= 1543.994
- `ekf_pr_doppler_mean_position_error_3d_m` 平均变化（issue01 - legacy）= 39773.698

说明：这一步已经在 Issue 01 完成，Issue 03 直接继承其 truth-free 运行边界。

## 2. 信号层未真实包含导航数据

教材标准：若宣称数据分量存在，则信号对象中必须真实包含数据调制，而不是只停留在配置层。

- `single_fd_rmse_hz` 平均变化（issue03 - issue01）= 5721.196
- `single_tau_rmse_ns` 平均变化（issue03 - issue01）= 9584.076

说明：Issue 03 把 `nav_data_enabled` 真实注入了 BPSK 数据符号，当前结果反映的是加入数据分量后，捕获/跟踪/WLS/EKF 的整体变化。

## 3. 接收机层把自然测量量直接命名为标准观测

教材标准：接收机层先输出 natural measurements，标准伪距和距离率必须在独立的观测形成层内构造。

- `wls_case_b_wls_position_error_3d_m` 平均变化（issue03 - issue01）= 2508.314
- `ekf_pr_doppler_mean_position_error_3d_m` 平均变化（issue03 - issue01）= 54314.189

说明：数值变化代表 formal observables 接入导航层后的总影响；更重要的是接口资格被恢复，WLS/EKF 不再消费原始环路状态。

## 4. 环路结构只靠整体工程控制律表达

教材标准：应把 discriminator、loop filter、NCO/state propagation 拆开，而不是只留下整段更新律。

- `single_fd_rmse_hz` 平均变化（issue03 - issue01）= 5721.196
- `ekf_pr_doppler_mean_velocity_error_3d_mps` 平均变化（issue03 - issue01）= 4724.641

说明：Issue 03 将 carrier/code loop 重写为显式的判别器-滤波器-NCO 更新结构，这一比较反映它对前端和动态层的联动影响。

## 5. 代表频点

| 频点 | `tau RMSE` issue03-issue01 (ns) | `fd RMSE` issue03-issue01 (Hz) | WLS Case B issue03-issue01 (m) | EKF PR+D pos issue03-issue01 (m) |
| --- | ---: | ---: | ---: | ---: |
| 19.0 GHz | -4011.766 | -0.595 | -1063.674 | 14319.163 |
| 22.5 GHz | -10.320 | 7.962 | 172.208 | 27595.510 |
| 25.0 GHz | 8195.382 | 3093.341 | 3393.038 | 74037.171 |
| 31.0 GHz | 32625.128 | 21183.227 | 8132.092 | 170814.076 |

## 6. 结论

Issue 03 的核心不只是继续优化数值，而是把 signal / receiver / observable / navigation 的对象边界重新立起来。
如果某些频点数值变差，报告口径仍然是：教材约束恢复后暴露了真实性能，而不是系统被“做坏了”。