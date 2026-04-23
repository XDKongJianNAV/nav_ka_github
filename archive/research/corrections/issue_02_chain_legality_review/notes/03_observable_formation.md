# 03 观测形成层

## 1. 本层对象定义

### 输入对象

- 接收机层给出的自然测量量：
  - `tau_est_s`
  - `carrier_phase_total_rad`
  - `carrier_freq_hz`
- 卫星星历与卫星时钟信息。
- 接收机接收时刻标签。
- 大气、色散、硬件等改正项定义。

### 内部操作对象

- 发射时刻解释。
- 几何距离与视线方向。
- 钟差、钟漂、传播附加项、硬件偏差。
- 观测符号约定和单位约定。

### 输出对象

- 标准伪距观测。
- 标准载波相位观测。
- 标准距离率 / range-rate 观测。

这一步是“观测形成”，不是再做环路控制。

## 2. 本层合法变换

### 2.1 从自然测量量到发射时刻

若 `tau_est_s` 是接收机复制码时延，则它首先更接近：

$$
t_{\mathrm{tx}} \approx t_{\mathrm{rx}} - \tau_{\mathrm{est}}
$$

它描述的是“发射时刻或复制码相位”的恢复，不是标准伪距方程本身。

### 2.2 伪距

标准伪距应写成：

$$
\rho = \|r_s-r_r\| + c(\delta t_r-\delta t_s) + d_{\mathrm{trop}} + d_{\mathrm{disp}} + d_{\mathrm{hw}} + \varepsilon_\rho
$$

因此，`c * tau_est_s` 最多只能被解释为一个链路内部的距离量纲派生量；它只有在以下前提都清楚时，才可能进入标准伪距接口：

- 接收时标明确。
- 发射时刻解释明确。
- 卫星钟差项与接收机钟差项放在同一方程里。
- 传播改正和硬件项被统一纳入观测模型。

### 2.3 距离率 / Doppler

标准距离率形式：

$$
\dot{\rho} = u_{\mathrm{LOS}}^T(v_s-v_r) + c(\dot{\delta t}_r-\dot{\delta t}_s) + \varepsilon_{\dot{\rho}}
$$

因此 `carrier_freq_hz` 也不能自动等价于标准距离率。中间至少还需要：

- 符号约定。
- 参考载波频率与波长关系。
- 接收机时钟漂移与卫星时钟漂移处理。

### 2.4 载波相位

标准载波相位观测应包含：

$$
\Phi = \frac{1}{\lambda}\Big(\rho + c(\delta t_r-\delta t_s) + d_{\mathrm{prop}} + d_{\mathrm{hw}}\Big) + N + \varepsilon_\Phi
$$

而 `carrier_phase_total_rad` 只是接收机复制载波的累计相位状态。它和标准载波相位观测相关，但不等价。

## 3. 当前代码映射

### 3.1 单通道 debug 脚本中的直接命名

`notebooks/nb_ka225_rx_from_real_wkb_debug.py:1321-1323`

- `C_LIGHT * state.tau_est_s`
- `state.carrier_phase_total_rad / (2*pi)`
- `state.carrier_freq_hz`

这三者在当前 notebook 中被直接叫做 `pseudorange`、`carrier_phase_cycles`、`doppler`。从教材分层看，这只是“名称提前下沉”，没有真正完成标准观测形成。

### 3.2 WLS 中的伪距观测形成

`notebooks/exp_multisat_wls_pvt_report.py:640-660`

- `PseudorangeObservation` 已把几何距离、卫星钟差、对流层、色散、硬件偏置、噪声方差等放到同一对象中。
- 这一层的对象语义更接近标准伪距观测。

### 3.3 EKF 中的测量栈

`notebooks/exp_dynamic_multisat_ekf_report.py:960-1034`

- `build_measurement_stack()` 里的 `predicted_pr_m` 与 `predicted_rr_mps` 是标准观测模型侧的写法。
- 但它们成立的前提是 `obs.pseudorange_m` 与 `obs.range_rate_mps` 已经具备正确语义。

## 4. 合法性判断

| 项目 | 判断 | 说明 |
| --- | --- | --- |
| 用统一观测方程组织几何、钟差、传播和硬件项 | 合法 | 这是标准导航观测形成方式 |
| `PseudorangeObservation` 作为标准观测容器 | 合法 | 对象语义基本完整 |
| 把 `c * tau_est_s` 直接叫作 `pseudorange` | 语义越层 | 它缺少时标解释和统一观测方程 |
| 把 `carrier_freq_hz` 直接叫作 `doppler` | 条件合法 | 只有在符号、波长、钟漂语义统一后才成立 |
| 把 `carrier_phase_total_rad` 直接当标准载波相位观测 | 条件合法 | 还缺模糊度、参考时标和单位约定 |

本层最关键的问题不是“公式没写”，而是“前端自然测量量到标准观测的正式接口还没有被单独立为一层”。

## 5. 与 Issue 01 结果的联系

`Issue 01` 的结果恰好支持“先有自然测量量恶化，再有标准观测退化”的链条。

```text
truth aiding removed
  -> tau_est / f_est quality drops
  -> pseudorange / range-rate quality drops
  -> WLS / EKF errors inflate
```

代表点：

- `19.0 GHz` 下，`tau RMSE` 放大到 `12998.231 ns`，随后 WLS 3D 误差变为 `4426.806 m`
- `22.5 GHz` 下，EKF PR+D 位置误差进一步放大到 `43577.243 m`
- `25.0 GHz` 与 `31.0 GHz` 下，前端恢复后，WLS 误差显著下降

这说明观测形成层不是名义上的“中转站”，而是真正的语义边界：前端内部状态一旦质量恶化，这一层输出就不可能再是高质量观测。

## 6. 对下游的接口资格

### 合法观测接口至少应包含

```text
ObservableRecord
  - receive_time_tag
  - sat_id
  - observable_type
  - value
  - sigma
  - sign_convention
  - model_terms_used
```

### 当前系统最需要补清的内容

- `tau_est_s -> pseudorange` 的正式解释链。
- `carrier_freq_hz -> range-rate` 的波长与符号约定。
- `carrier_phase_total_rad -> carrier phase observable` 的模糊度与参考时刻定义。

只要这层接口被明确，下游导航层就不需要再猜“输入到底是接收机内部状态，还是已经成型的观测量”。
