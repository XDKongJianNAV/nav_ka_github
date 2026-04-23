# Receiver Notebook Map

对应 notebook：

- [notebooks/receiver_review_overview.ipynb](/Users/guozehao/Documents/ka-Nav/nav_ka_github/notebooks/receiver_review_overview.ipynb)

这本 notebook 现在不再只按“结果图”组织，而是对每个模块都固定回答四件事：

1. 它在整体里负责什么
2. 方法本身怎么工作
3. 真实中间量长什么样
4. 最终输出或诊断怎么解释

## 主线章节

1. 总体结构
   对应 `ReceiverRuntimeContext`、`AcquisitionEngine`、`TrackingEngine`、`KaBpskReceiver`
   关键图：模块连接图、时序图、数据对象流图
2. 接收机配置
   对应 `SignalConfig`、`MotionConfig`、`AcquisitionConfig`、`TrackingConfig`
   关键图：搜索网格、环路关键参数
3. Acquisition
   对应 `run_acquisition()`、`diagnose_acquisition_physics()`
   关键图：二维搜索平面、单假设打分流程、coarse/refine 热图、峰比图
4. Correlator / E-P-L
   对应 `correlate_block()`、`build_tracking_snapshot()`
   关键图：wipeoff 前后、本地码副本、逐样本乘积、E/P/L 复平面
5. DLL
   对应 `dll_discriminator()`、`tau_est_s` 更新
   关键图：S-curve、限幅与门控、`tau_true / tau_predict / tau_est`
6. PLL + FLL assist
   对应 `costas_pll_discriminator()`、`pll_integrator_hz`、`pll_freq_cmd_hz`、`fll_err_hz`
   关键图：Costas 相位几何、三支路汇总、频率命令与真值
7. 锁定、门控与失锁
   对应 `run_tracking()`、`diagnose_tracking_physics()`
   关键图：判据关系图、SNR/lock 指标、门控状态、`sustained_loss`
8. 观测量
   对应 `pseudorange_m`、`carrier_phase_cycles`、`doppler_hz`
   关键图：形成关系图、三条观测量轨迹
9. 三阶段快照
   对应 `build_tracking_snapshot()`
   关键图：`start / mid / end` 的 baseband、本地码副本、E/P/L 对照
10. 总对照
   对应“理论对象 -> 真实代码 -> 关键中间量 -> notebook 图”的总表

## 当前不覆盖

- WLS / EKF
- 多星几何与融合
- `issue_03_textbook_correction` 的标准观测链
- `BOC / BCS / pilot` 等未在当前接收机主链实现的体制
