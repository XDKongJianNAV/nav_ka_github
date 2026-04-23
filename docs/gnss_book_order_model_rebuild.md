# GNSS 教材序模型重建总纲

## 1. 文档目的

本文档不是结果汇报，也不是某个脚本的使用说明，而是后续 GNSS 代码重构的总纲。目标是把当前仓库中已经存在的传播、接收机、观测形成、定位与滤波内容，重新放回教材和经典工程实现常用的思维顺序中，使代码结构服从模型结构，而不是让模型去迁就当前脚本的堆叠方式。

这里采用的原则是：

1. 模型先于代码。
2. 数学对象先于流程封装。
3. 接收机内部量与导航观测量严格区分。
4. 传播层、信号层、观测层、解算层分别建模，再通过清楚的接口连接。
5. 当前仓库已有实现可以临时复用，但复用必须服从新的模型边界。

当前仓库已经形成三段主链：

1. [src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py) 负责真实电子密度场、WKB、单通道接收机捕获与跟踪。
2. [src/nav_ka/legacy/exp_multisat_wls_pvt_report.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/exp_multisat_wls_pvt_report.py) 负责多星标准伪距与单历元 LS/WLS。
3. [src/nav_ka/legacy/exp_dynamic_multisat_ekf_report.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/exp_dynamic_multisat_ekf_report.py) 负责多历元动态观测与 EKF。

本文件的任务，是按教材顺序解释这三段内容分别属于哪一层模型，以及后续应如何整理成常规 GNSS 工程骨架。

## 2. 教材章序与仓库映射

下文采用“章序占位 + 当前实现映射”的方式组织。这里的“章”不是逐页复述 PDF，而是对齐教材中常见的 GNSS 工程知识顺序。

### 第 1 章 GNSS 系统与问题定义

**本章模型对象**

- 卫星导航系统的基本组成
- 发射端、传播信道、接收端、导航解算端之间的对象边界
- 观测、状态、误差源三类基本变量

**工程上应明确建模的关系**

- 发射信号不是观测量，观测量是接收机处理后的构造结果。
- 接收机链路不是导航解算器，解算器只消费标准观测和协方差。
- 传播误差不会自动变成位置误差，必须经过观测方程和解算器传播。

**当前仓库对应实现**

- 单通道主链已经具备“传播到接收机”的雏形，见 [src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py)。
- 多星标准观测与解算被放在后续两个脚本中，尚未回收到统一模型框架中。

**后续应抽离/重构的模块**

- 建立统一术语表，明确 `signal`、`channel`、`receiver state`、`observable`、`navigation state` 的命名边界。
- 所有脚本入口都应显式声明自己处于哪一层模型，而不是用“legacy/new”区分。

### 第 2 章 坐标、时间与基本测距量

**本章模型对象**

- ECEF、ENU、接收机本地几何
- 接收机钟差、钟漂
- 几何距离、几何距离率

**工程上应明确建模的关系**

- 几何距离和几何距离率属于观测方程中的几何项，不属于接收机环路内部状态。
- 钟差和钟漂是导航层状态，不应通过 DLL/PLL 内部量直接替代。

**当前仓库对应实现**

- [src/nav_ka/legacy/exp_multisat_wls_pvt_report.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/exp_multisat_wls_pvt_report.py) 已实现 `lla_to_ecef`、ENU 旋转、多星几何构造与几何距离。
- [src/nav_ka/legacy/exp_dynamic_multisat_ekf_report.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/exp_dynamic_multisat_ekf_report.py) 已实现几何距离率与时变几何。

**后续应抽离/重构的模块**

- `geometry`: 统一坐标变换、LOS、几何距离、几何距离率。
- `timebase`: 统一接收机时间轴、观测历元、传播时间标记。

### 第 3 章 GNSS 信号表示模型

**本章模型对象**

- PN/BPSK 码信号
- 载波、码片率、码相位
- 基带等效表示

**工程上应明确建模的关系**

- 信号模型需要明确区分发射信号、传播后接收信号、本地复制信号。
- 码相位、载波相位、多普勒是信号与跟踪层的状态变量，不等同于导航解算状态。

**当前仓库对应实现**

- [src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py) 中已经有 `SignalConfig`、`mseq_7`、`sample_code_waveform`、本地信号构造与相关处理。
- [src/nav_ka/legacy/ka_multifreq_receiver_common.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/ka_multifreq_receiver_common.py) 已把这部分以共享模块形式暴露出来，但还是沿用旧脚本边界。

**后续应抽离/重构的模块**

- `signal`: 信号参数、码生成、载波生成、基带表示。
- `replica`: 本地复制信号与相关器所需的本地参考波形。

### 第 4 章 传播与信道效应模型

**本章模型对象**

- 电子密度场
- WKB 幅度、相位、群时延
- 色散传播效应

**工程上应明确建模的关系**

- `A(t)`、`phi(t)`、`tau_g(t)` 是传播层输出，不是导航观测量本体。
- 色散项进入标准观测方程时，应作为非几何传播项，而不是直接把内部链路量改名为伪距。

**当前仓库对应实现**

- [src/plasma_wkb_core.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/plasma_wkb_core.py) 与 [src/plasma_field_core.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/plasma_field_core.py) 已提供电子密度场和 WKB 相关计算。
- [src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py) 用 `compute_real_wkb_series` 把传播结果接到接收机时间轴。

**后续应抽离/重构的模块**

- `physics.plasma`
- `channel.propagation`
- `channel.dispersive_delay`

这些模块应只输出传播层物理量，并明确到观测层的映射接口，例如“给定频率、仰角和时间，返回传播附加时延和不确定度”。

### 第 5 章 接收信号构造

**本章模型对象**

- 传播后接收基带信号
- 噪声、动态码延迟、动态多普勒
- 发射端与传播端共同作用后的接收块

**工程上应明确建模的关系**

- 接收信号是物理信号样本，不是观测表。
- 码延迟、频偏、载波相位应先体现在信号构造中，再由接收机估计。

**当前仓库对应实现**

- [src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py) 中的 `evaluate_true_channel_and_motion`、`make_received_block` 已承担这一层。

**后续应抽离/重构的模块**

- `channel.synthetic_rx`
- `receiver.frontend`

前者给出物理上自洽的接收样本，后者负责采样、分块和前端接口，不应提前混入导航解算逻辑。

### 第 6 章 捕获模型

**本章模型对象**

- 二维搜索平面
- 码相位粗捕获
- 载波频偏粗估计

**工程上应明确建模的关系**

- 捕获输出的是接收机内部初值，如码相位和频偏初值。
- 捕获结果不是标准伪距，也不是标准多普勒观测。

**当前仓库对应实现**

- [src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py) 中的 `run_acquisition` 与 `diagnose_acquisition_physics` 已实现粗搜索与局部细化。
- [reports/ka225_receiver_work_report.typ](/Users/guozehao/Documents/ka-Nav/nav_ka_github/reports/ka225_receiver_work_report.typ) 已将这一层的公式和诊断量做过整理。

**后续应抽离/重构的模块**

- `receiver.acquisition`
- `receiver.acquisition_diagnostics`

### 第 7 章 跟踪环路模型

**本章模型对象**

- DLL
- PLL
- FLL 辅助
- 相关器 Early/Prompt/Late

**工程上应明确建模的关系**

- DLL 负责码相位误差驱动。
- PLL/FLL 负责载波相位与频率误差驱动。
- 环路状态更新是接收机内部动态系统，不应直接被解释成导航状态估计。

**当前仓库对应实现**

- [src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py) 中的 `correlate_block`、`dll_discriminator`、`costas_pll_discriminator`、`run_tracking` 已形成完整跟踪链。
- [reports/ka225_receiver_work_report.typ](/Users/guozehao/Documents/ka-Nav/nav_ka_github/reports/ka225_receiver_work_report.typ) 已明确 DLL/PLL/FLL 的内部诊断与门控逻辑。

**后续应抽离/重构的模块**

- `receiver.tracking`
- `receiver.loops`
- `receiver.lock_metrics`

这里必须保留明确接口：输入为相关器观测与当前环路状态，输出为下一步环路命令和内部质量指标。

### 第 8 章 观测量形成

**本章模型对象**

- 伪距
- 载波相位
- 多普勒或距离率
- 观测噪声和协方差

**工程上应明确建模的关系**

- `c * tau_est` 不是标准伪距本体，只是码时延恢复量。
- 链路内部频偏也不是标准距离率本体，必须通过统一观测定义映射。
- 传播项、钟差项、硬件项必须在同一观测方程中显式出现。

**当前仓库对应实现**

- [src/nav_ka/legacy/exp_multisat_wls_pvt_report.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/exp_multisat_wls_pvt_report.py) 已明确写出标准伪距方程。
- [src/nav_ka/legacy/exp_dynamic_multisat_ekf_report.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/exp_dynamic_multisat_ekf_report.py) 已把 legacy Doppler 映射为标准距离率观测。

**后续应抽离/重构的模块**

- `observables.pseudorange`
- `observables.carrier_phase`
- `observables.range_rate`
- `observables.noise_model`

每类观测都应有统一数据结构，至少显式包含：

- `value`
- `geometry_term`
- `clock_term`
- `propagation_term`
- `hardware_term`
- `sigma`
- `quality_flags`

### 第 9 章 单历元定位模型

**本章模型对象**

- 线性化观测方程
- LS / WLS
- 几何矩阵与 DOP

**工程上应明确建模的关系**

- 定位器只消费标准观测，不应直接读取 DLL/PLL 内部中间量。
- 权阵来自观测协方差，而不是来自某个脚本里零散的经验系数。

**当前仓库对应实现**

- [src/nav_ka/legacy/exp_multisat_wls_pvt_report.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/exp_multisat_wls_pvt_report.py) 已包含单历元 LS/WLS、DOP、Monte Carlo 和逐星观测表。

**后续应抽离/重构的模块**

- `estimation.wls`
- `estimation.design_matrix`
- `estimation.dop`

### 第 10 章 多历元状态空间与滤波模型

**本章模型对象**

- 位置、速度、钟差、钟漂状态
- 状态转移矩阵
- 过程噪声
- 观测更新

**工程上应明确建模的关系**

- WLS 是静态观测求解器，EKF 是状态空间滤波器，两者角色不同。
- PR-only 与 PR + Doppler 的可观测性差异应在模型层明示，而不是只在结果图中体现。

**当前仓库对应实现**

- [src/nav_ka/legacy/exp_dynamic_multisat_ekf_report.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/exp_dynamic_multisat_ekf_report.py) 已建立 8 状态 EKF，并区分 `epoch-wise WLS` 基线、`PR only` 与 `PR + Doppler`。
- [archive/results/canonical/results_dynamic_multisat_ekf/report_full.md](/Users/guozehao/Documents/ka-Nav/nav_ka_github/archive/results/canonical/archive/results/canonical/results_dynamic_multisat_ekf/report_full.md) 已对状态方程、观测方程和初始化策略给出较完整说明。

**后续应抽离/重构的模块**

- `estimation.state_space`
- `estimation.ekf`
- `estimation.initialization`
- `estimation.innovation_monitor`

### 第 11 章 完整性、验证与工程约束

**本章模型对象**

- 模型一致性检查
- 单元测试与人工核验
- 误差预算与接口守恒

**工程上应明确建模的关系**

- 测试只验证“在给定场景下是否输出预期结果”。
- 模型约束验证“该输出是否来自正确的观测定义与状态关系”。
- 工程实践要求二者同时成立。

**当前仓库对应实现**

- 当前仓库主要以实验脚本和报告形式留存证据，模型约束尚未沉淀成统一接口检查。

**后续应抽离/重构的模块**

- `validation.model_checks`
- `validation.regression_cases`
- `validation.reference_scenarios`

重点需要建立以下检查：

1. 传播层输出能否被唯一映射到观测层非几何项。
2. 接收机内部量是否被错误地直接拿来充当标准观测。
3. WLS/EKF 是否只依赖标准观测接口。
4. 观测协方差是否与质量门限和噪声定标一致。

## 3. 当前仓库的关键模型边界

后续重构时，必须把下面几条边界当成硬约束。

### 3.1 接收机内部量不等于导航观测量

- DLL 输出的码时延估计是接收机内部恢复量。
- PLL/FLL 输出的频率、相位估计是接收机内部恢复量。
- 这些量可以参与构造标准观测，但不能跳过观测定义直接送入解算器。

### 3.2 WKB 传播量不等于伪距本体

- `tau_g(t)`、`phi(t)`、`A(t)` 是传播层结果。
- 它们进入导航层时，应显式作为色散时延、相位附加项、链路质量背景。
- 后续若加入载波相位观测，也应保持这种“先物理项、后观测项”的映射关系。

### 3.3 WLS 与 EKF 之间应通过标准观测接口连接

- WLS 负责单历元位置与钟差解。
- EKF 负责状态时间推进与多历元融合。
- 两者共享的是同一套标准观测定义，而不是共享某个脚本内部数组约定。

## 4. 目标代码架构蓝图

后续代码重构建议形成以下模型层级：

```text
src/
  gnss/
    physics/
    geometry/
    signal/
    channel/
    receiver/
    observables/
    estimation/
    validation/
```

各层职责固定如下：

- `physics`: 电子密度场、WKB、传播物理量。
- `geometry`: 坐标、时间、LOS、几何距离、几何距离率。
- `signal`: 发射信号、码、载波、基带表示。
- `channel`: 传播映射、接收信号构造、噪声与传播附加项。
- `receiver`: 捕获、跟踪、环路、锁定指标、前端数据流。
- `observables`: 伪距、载波相位、多普勒/距离率的统一观测结构。
- `estimation`: 单历元 LS/WLS、多历元 EKF、初始化与一致性监控。
- `validation`: 模型约束检查、回归基线、参考场景与人工核验脚本。

## 5. 重构优先级

建议按照以下顺序推进，而不是同时大改所有脚本。

1. 先把标准观测接口独立出来。
2. 再把几何与时间基线独立出来。
3. 然后把接收机捕获/跟踪从 notebook 编排中抽成明确模块。
4. 最后再把 WLS/EKF 统一改写为只消费 `observables` 层对象。

这个顺序的原因是：当前仓库最大风险不是某个公式完全缺失，而是层次之间仍有“内部量直接跨层使用”的隐性耦合。只有先把观测接口固定下来，后续传播层和解算层才能真正解耦。

## 6. 本轮默认约束

为了让后续实现具有可操作性，本总纲默认采用以下约束：

1. 当前 notebook 中已经跑通的公式与流程可以临时引用，不要求本轮立即重写。
2. 新增实现必须先说明它属于 `physics`、`receiver`、`observables` 还是 `estimation` 中的哪一层。
3. 任何导航解算器都不得直接读取 DLL/PLL/FLL 中间变量，除非经过显式观测定义。
4. 任何传播效应都不得直接伪装成“测出来的伪距”，必须通过标准观测方程进入。
5. 验证标准同时包括数值测试和模型一致性检查，二者缺一不可。
