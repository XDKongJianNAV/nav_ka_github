# 多历元动态多星导航 EKF 汇报摘要

## 复用的旧脚本能力

本次没有重写旧的真实链路，而是直接复用了以下已有函数和结论：

1. `build_fields_from_csv`
2. `compute_real_wkb_series`
3. `build_signal_config_from_wkb_time`
4. `resample_wkb_to_receiver_time`
5. `KaBpskReceiver.run`
6. `solve_pvt_iterative`

因此，真实电子密度场、真实 WKB、重采样到接收机时间轴、Ka PN/BPSK 接收机链路、
单通道 `pseudorange / Doppler / SNR / lock metric` 背景都来自旧脚本，而不是这里重新手写的替代品。

## 本次新增的动态层内容

新脚本新增了以下导航层能力：

1. 多历元接收机真值轨迹
2. 多历元多星时间变化几何与卫星速度
3. 每个 epoch 的标准 `pseudorange` 与 `range-rate` 观测形成
4. 单历元 WLS 串联基线
5. 8 维动态 EKF：位置、速度、钟差、钟漂
6. 退化观测段注入与有效观测门限/降权

## 输入与中间量图片

本次动态报告现在不只输出结果图，也补上了输入和中间量图片：

1. `legacy_channel_overview.png`
   - 展示复用旧链路得到的 `A(t)`、`phi(t)`、`tau_g(t)`、legacy 伪距误差、legacy SNR
2. `sky_geometry_dynamic.png`
   - 展示起始、中段、退化段、结束的动态天空几何
3. `geometry_3d_timeslices.png`
   - 展示接收机中心 ENU 下的 3D 几何和 LOS 连线
4. `geometry_timeseries.png`
   - 展示 visibility，以及相对起点的 elevation、geometric range、range-rate 变化
5. `observation_formation_overview.png`
   - 展示观测形成里的非几何项、sigma、legacy SNR、lock、valid mask

因此，这份报告现在可以同时回答：

1. 输入背景是什么
2. 动态几何是什么
3. 标准观测是如何形成的
4. 滤波结果最终如何表现

## 状态定义

主状态向量采用：

`x = [rx, ry, rz, vx, vy, vz, cb, cd]^T`

其中：

- `r` 为接收机 ECEF 位置，单位 m
- `v` 为接收机 ECEF 速度，单位 m/s
- `cb` 为接收机钟差，单位 m
- `cd` 为接收机钟漂，单位 m/s

## 状态方程

首版采用常速度模型：

- `r(k+1) = r(k) + v(k) * dt`
- `v(k+1) = v(k) + w_v`
- `cb(k+1) = cb(k) + cd(k) * dt`
- `cd(k+1) = cd(k) + w_c`

其中过程噪声 `Q` 在代码中显式按白加速度和钟漂随机游走离散化。

## 观测方程

伪距模型：

`rho = ||rs-r|| + cb - c*dts + tropo + dispersive + hardware + noise`

距离率 / Doppler 模型：

`rhodot = u_LOS^T (vs-vr) + cd - c*ddts + noise`

脚本内部统一使用距离率单位 `m/s`，并按：

`range_rate_mps = -(c / fc) * doppler_hz`

把旧单通道 Doppler 误差统计映射到 EKF 权重。

## 时间轴

- 接收机内部采样率：继承旧脚本真实接收机配置
- 跟踪输出率：`1 ms` 积分块，即约 `1000 Hz`
- 导航解算率：`10.0 Hz`

卫星几何采用接收机本地 `az/el/range` 的时变参数化，再逐 epoch 映射到 ECEF，并用有限差分构造卫星速度。

## 主要数值结果

- Epoch-wise WLS 平均 3D 位置误差：583.656 m
- EKF PR only 平均 3D 位置误差：891.783 m
- EKF PR + Doppler 平均 3D 位置误差：15.091 m
- EKF PR only 平均 3D 速度误差：149.889 m/s
- EKF PR + Doppler 平均 3D 速度误差：0.043 m/s
- EKF PR + Doppler 平均伪距创新 RMS：526.383 m
- EKF PR + Doppler 平均距离率创新 RMS：0.652 m/s

## 主要简化项

1. 多星几何是本地 `az/el/range` 参数化后映射到 ECEF 的时变构造，不是广播星历
2. 接收机真值是连续常速度 ECEF 轨迹，不是 RAM-C 六自由度真轨迹
3. 所有卫星共享同一条旧脚本单通道真实 WKB/接收机背景，再映射到多星多历元观测
4. 对流层、卫星钟差、硬件偏差仍为导航层参数化项
5. 首版主实验只做 `pseudorange + Doppler`，没有把 carrier phase ambiguity 扩展进主滤波器

## 首版限制

1. 这不是完整真实多星端到端 Ka 动态导航系统定标
2. 多星各链路没有独立真实射线/等离子体路径
3. 观测相关性来自共享 legacy 背景映射，不是独立多通道同步接收机跟踪
4. carrier phase 暂未进入主 EKF，因此不能给出整周相关结论

## 下一步建议

1. 将卫星几何从当前自洽模型升级到真实星历驱动
2. 为 carrier phase 引入每星 float ambiguity 状态，形成 `PR + Doppler + Phase` 扩展滤波
3. 把多星各 LOS 的色散项从共享背景映射升级为独立传播路径
4. 若后续有真实飞行轨迹，再用真实动力学替换当前常速度接收机真值

## 边界声明

本结果代表：

**真实单通道 Ka/WKB 背景耦合下的 hybrid 多历元动态多星 EKF 实验**

不代表：

**真实端到端多星 Ka 动态导航系统性能定标**

完整长报告见：

`report_full.md`
