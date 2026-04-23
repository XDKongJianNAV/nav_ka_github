# 04 导航层

## 1. 本层对象定义

### 输入对象

- 来自观测形成层的标准伪距和距离率观测。
- 卫星位置、卫星速度、卫星钟差、卫星钟漂。
- 接收机状态先验或初始化。

### 内部操作对象

- WLS/LS 的设计矩阵、残差向量、权矩阵。
- EKF 的状态向量、协方差、过程模型、测量模型。
- 导航层的残差与创新。

### 输出对象

- 单历元位置/钟差解。
- 多历元位置/速度/钟差/钟漂状态。
- 与解相关的残差、创新、置信度指标。

本层消费的是“观测”，不是接收机内部相关器输出。

## 2. 本层合法变换

### 2.1 WLS

WLS 的标准残差组织方式是：

$$
z = h(x) + \varepsilon
$$

在伪距问题中，迭代更新可写成：

$$
\Delta x = (H^T W H)^{-1} H^T W \, (z-h(x))
$$

这一步的合法前提不是“矩阵写对了”而已，而是：

- `z` 必须真的是标准伪距观测。
- `h(x)` 必须与 `z` 使用同一语义和同一改正项口径。

### 2.2 EKF

当前动态 EKF 使用 8 维 CV 状态：

$$
x=[r,\ v,\ cb,\ cd]^T
$$

预测阶段是动力学传播，更新阶段使用伪距或伪距加距离率：

$$
x_{k|k}=x_{k|k-1}+K_k(z_k-h(x_{k|k-1}))
$$

这里最关键的合法性前提仍然不是矩阵运算本身，而是测量栈里的观测对象是否已经清楚。

## 3. 当前代码映射

### 3.1 WLS 求解器

`notebooks/exp_multisat_wls_pvt_report.py:670-772`

- `solve_pvt_iterative()` 用标准几何距离和钟差项构造 `predicted_pseudorange_m`。
- 残差与设计矩阵的形式是规范的。
- `Issue 01` 之后，truth-free 初值已经通过 `build_truth_free_initial_state_from_observations()` 明确分离出来。

### 3.2 单历元实验与蒙特卡洛

`notebooks/exp_multisat_wls_pvt_report.py:838-930`

- `run_experiment_case()` 和 `run_monte_carlo()` 现在都支持 `truth_free_initialization=True`。
- 这一步修正的是运行独立性，不是观测语义本身。

### 3.3 动态 epoch-wise WLS 与 EKF

`notebooks/exp_dynamic_multisat_ekf_report.py:842-908`

- `run_epoch_wls_series()` 首历元已支持 truth-free 初始化。
- 之后使用上一历元估计值 warm start，属于估计链内部传递，语义上是成立的。

### 3.4 EKF 测量方程

`notebooks/exp_dynamic_multisat_ekf_report.py:960-1034`

- `build_measurement_stack()` 中的 `predicted_pr_m` 与 `predicted_rr_mps` 形式上是标准的。

### 3.5 EKF 初始化与运行

`notebooks/exp_dynamic_multisat_ekf_report.py:1037-1206`

- `initialize_ekf_state()` 用 WLS 序列拟合初始速度和钟漂。
- `run_ekf()` 做标准 predict/update。
- truth 在这里主要用于解后误差评估，而不再进入运行更新。

## 4. 合法性判断

| 项目 | 判断 | 说明 |
| --- | --- | --- |
| WLS 残差方程与设计矩阵 | 合法 | 前提是输入伪距已经是标准观测 |
| truth-free WLS 初始化 | 合法 | 属于求解先验设置，不再依赖真值 |
| 原始 truth-offset 初始化 | 不合法 | 运行机制直接缩短了本应存在的推断链条，已由 `Issue 01` 纠正 |
| EKF CV 状态与 predict/update 结构 | 合法 | 这是标准动态导航框架 |
| EKF 测量模型中的 `predicted_rr_mps` | 条件合法 | 仅当输入 `range_rate_mps` 语义已清楚时成立 |
| 若前端把自然测量量直接改名为观测 | 条件失效 | 此时 WLS/EKF 数学仍可运行，但解释资格下降 |

导航层当前不是“公式层面的大问题”，而是“输入对象资格依赖上一层是否把观测语义说清楚”。

## 5. 与 Issue 01 结果的联系

`Issue 01` 结果给导航层审查提供了一个很强的经验判据：如果前端自然测量量恶化，下游导航解并不会神奇地保持稳定。

### 5.1 低频段

- `19.0 GHz` 的 WLS Case B 3D 误差从 `427.824 m` 增加到 `4426.806 m`
- `22.5 GHz` 的 EKF PR+D 位置误差从 `15.091 m` 增加到 `43577.243 m`

这说明导航层确实在消费上游对象质量，而不是独立于前端存在。

### 5.2 高频段

- `25.0 GHz` 与 `31.0 GHz` 下，WLS 已明显恢复
- EKF 仍较前端更敏感，说明动态估计器会进一步放大观测层语义缺口和噪声缺口

这支持一个重要判断：

```text
front-end quality restored
  -> observables become usable
  -> WLS stabilizes first
  -> EKF still remains more sensitive to residual modeling gaps
```

## 6. 对下游的接口资格

### 导航层能合法消费的对象

- 带时标、带卫星编号、带噪声标准差的标准观测记录。
- 明确了符号和单位的伪距/距离率。

### 导航层不应直接消费的对象

- `tau_est_s`
- `carrier_phase_total_rad`
- `carrier_freq_hz`
- 单通道 notebook 中未经正式解释的 `pseudorange_hist` / `doppler_hist`

### 当前最需要补的接口约束

```text
NavigationInput
  - observable records only
  - no raw loop states
  - explicit time-tag and sign convention
  - explicit propagation/hardware terms already defined
```

只要导航层继续直接或间接吞入“语义未完成的前端内部量”，那么即便方程写得再标准，结果也只能算“数值上运行”，不能算“模型上自洽”。
