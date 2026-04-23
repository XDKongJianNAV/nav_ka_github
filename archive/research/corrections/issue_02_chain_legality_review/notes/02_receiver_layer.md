# 02 接收机层

## 1. 本层对象定义

### 输入对象

- 信号层给出的复基带接收块 `r(t)`。
- 本地复制结构，包括本地载波与本地码。
- 配置好的环路参数、积分时间、相关器布局。

### 内部操作对象

接收机层不是直接操作“伪距”，而是操作以下内部对象：

- 捕获搜索面上的候选 `(tau, f)`。
- Early / Prompt / Late 相关器输出 `E, P, L`。
- DLL、PLL、FLL 的误差信号。
- NCO 状态，例如 `tau_est_s`、`carrier_freq_hz`、`carrier_phase_total_rad`。

### 输出对象

本层合法输出首先应当是“自然测量量”：

- `tau_est_s`
- `carrier_phase_total_rad`
- `carrier_freq_hz`

这些量表示接收机已经建立起来的本地复制状态，但它们还不是标准导航观测。

## 2. 本层合法变换

### 2.1 捕获

捕获的角色是同步初始化，不是观测形成。

当前实现使用的搜索形式是：

$$
\Lambda(\tau,f)=\left|\sum r(t)\,c(t-\tau)\,\exp(-j2\pi f t)\right|^2
$$

输出：

- `tau_hat_0`
- `fd_hat_0`

它们的资格只是“跟踪环初值”，还没有资格被称为标准伪距或标准多普勒。

### 2.2 跟踪

跟踪层的主角色是“同步控制 + 状态估计”。

相关器结构：

```text
received block
  -> carrier wipeoff
  -> baseband
  -> Early / Prompt / Late code correlation
  -> discriminator outputs
  -> loop state updates
```

当前 DLL 判别器：

$$
D_{\mathrm{DLL}}=\frac{|E|-|L|}{|E|+|L|}
$$

当前 Costas PLL 判别器：

$$
D_{\mathrm{PLL}}=\operatorname{atan2}(Q_P,\ |I_P|)
$$

短时 FLL 误差：

$$
D_{\mathrm{FLL}} \approx \frac{\angle(P_k P_{k-1}^*)}{2\pi \Delta t}
$$

### 2.3 自然测量量

教材意义上，接收机最自然恢复的是：

- 复制码相位，或等价的发射时刻估计。
- 复制载波相位。
- 复制载波频率。

因此本层的终点应是：

```text
tracking states
  -> tau_est_s
  -> carrier_phase_total_rad
  -> carrier_freq_hz
```

而不是直接跳成：

```text
pseudorange / range-rate / navigation solution
```

## 3. 当前代码映射

### 3.1 捕获

`notebooks/nb_ka225_rx_from_real_wkb_debug.py:712-823`

- `run_acquisition()` 通过二维搜索返回 `fd_hat_hz`、`tau_hat_s`。
- 这一步与教材的“同步初值搜索”是对齐的。

### 3.2 相关器

`notebooks/nb_ka225_rx_from_real_wkb_debug.py:958-1004`

- `correlate_block()` 明确构造了 Early / Prompt / Late 三路相关器。
- 这是接收机层内部的“相关统计量生成”，不是导航观测形成。

### 3.3 判别器

`notebooks/nb_ka225_rx_from_real_wkb_debug.py:1007-1022`

- `dll_discriminator()` 是归一化非相干早晚门。
- `costas_pll_discriminator()` 使用 `atan2(Q, |I|)`，属于 Costas 形式。

### 3.4 跟踪主循环

`notebooks/nb_ka225_rx_from_real_wkb_debug.py:1090-1406`

这里同时包含：

- DLL 更新 `tau_est_s`
- PLL/FLL 更新 `carrier_freq_hz`
- 相位累加得到 `carrier_phase_total_rad`
- 原始实现中还包含真值辅助：
  - `code_aiding_rate_chips_per_s`
  - `carrier_aiding_rate_hz_per_s`

`Issue 01` 已在 `src/issue_01_truth_dependency.py` 和相关 runner 中切断这两条运行时真值注入路径。

### 3.5 一个显式越层点

`notebooks/nb_ka225_rx_from_real_wkb_debug.py:1321-1323`

- `pseudorange_hist.append(C_LIGHT * state.tau_est_s)`
- `carrier_phase_cycles_hist.append(...)`
- `doppler_hist.append(state.carrier_freq_hz)`

这三行把接收机内部状态直接贴上了观测名，属于本层最明确的语义越层点。

## 4. 合法性判断

| 项目 | 判断 | 说明 |
| --- | --- | --- |
| 捕获作为 `(tau, f)` 初始化搜索 | 合法 | 同步角色清楚，输出是初值，不是导航观测 |
| E/P/L 相关器作为环路输入统计量 | 合法 | 属于标准接收机结构 |
| 非相干 DLL 判别器 | 合法 | 与教材常见形式一致 |
| Costas PLL 判别器 | 合法 | 对当前近似 dataless/BPSK-R 结构仍然合理 |
| FLL 辅助 PLL | 条件合法 | 结构合理，但其稳定域与切换策略需要更正式建模 |
| 当前 `run_tracking` 内部的整体更新律 | 启发式近似 | 可以工作，但没有被拆成可独立分析的正式环路滤波器模型 |
| 原始代码中的 `code_aiding_rate` / `carrier_aiding_rate` 真值注入 | 不合法 | 这不是离线评估，而是直接进入运行机制，已由 `Issue 01` 纠正 |
| 直接把 `tau_est_s`、`carrier_freq_hz` 记为伪距/多普勒 | 语义越层 | 自然测量量与标准观测被混为一层 |

这里最重要的结论是：当前接收机层并不是“完全错误”，而是“前半段结构基本成立，后半段接口语义过早跳层”。

## 5. 与 Issue 01 结果的联系

`Issue 01` 结果直接证明了两件事：

### 5.1 真值注入确实改变了接收机行为

低频段代表点：

- `19.0 GHz` 的 `tau RMSE` 从 `1141.415 ns` 增大到 `12998.231 ns`
- `22.5 GHz` 的 `fd RMSE` 从 `106.476 Hz` 增大到 `3201.179 Hz`

这说明原来的运行机制并不是在“纯靠相关器和环路”工作，而是被真值动态稳定过。

### 5.2 高频段说明本层仍有独立运行能力

- `25.0 GHz` 的 `tau RMSE` 由 `566.501 ns` 变为 `561.699 ns`
- `31.0 GHz` 的 `fd RMSE` 由 `96.585 Hz` 变为 `75.566 Hz`

这说明本层在传播条件较好时，确实具备不依赖真值辅助的自稳能力。

换句话说，`Issue 01` 不是只告诉我们“结果退化了”，而是告诉我们：

当前接收机层的合法部分和脆弱部分已经被区分出来了。

## 6. 对下游的接口资格

### 本层有资格输出的对象

- `tau_est_s`
- `carrier_phase_total_rad`
- `carrier_freq_hz`
- 锁定质量指标，例如后相关 SNR、carrier lock metric

### 本层还没有自动具备资格输出的对象

- 标准伪距
- 标准载波相位观测
- 标准距离率 / Doppler 观测

### 合法接口建议

```text
ReceiverNaturalMeasurements
  - receive_time_tag
  - tau_est_s
  - carrier_phase_total_rad
  - carrier_freq_hz
  - lock_metrics
  - sat_id / channel_id
```

只有先把这层接口独立出来，下一层的观测形成才不会继续混淆“内部复制状态”和“标准导航观测”。
