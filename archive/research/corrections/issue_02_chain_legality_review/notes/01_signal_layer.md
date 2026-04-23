# 01 信号层

## 1. 本层对象定义

### 输入对象

- 发射端给出的扩频码与载波结构。
- 传播层给出的幅度、相位、群时延等作用。
- 离散接收时间轴。

教材视角下，本层的输入不是“伪距”或“观测”，而是一个尚未被接收机解释的物理信号对象。

### 内部操作对象

- 发射复包络。
- 传播后复基带。
- 码延迟后的扩频波形。
- 附加到信号上的传播振幅项 `A(t)`、相位项 `phi(t)`、群时延项 `tau_g(t)`。

可写成简化形式：

$$
s_{\mathrm{tx}}(t)=d(t)c(t)\exp(j 2\pi f_c t + j\phi_0)
$$

$$
r(t)=A(t)\,c\!\left(t-\tau_{\mathrm{total}}(t)\right)\exp\!\left(j\phi_{\mathrm{total}}(t)\right)+n(t)
$$

当前实现中的 `make_received_block()` 直接采用了第二种层级的表达。

### 输出对象

- 一段接收机时间块上的复基带样本。
- 与该时间块一致的采样时间轴和信号配置。

这一本层输出仍然是“信号对象”，不是观测量，也不是内部接收机状态。

## 2. 本层合法变换

### 2.1 传播印记进入信号

```text
transmitted spreading/carrier
  -> delay imprint tau_total(t)
  -> phase imprint phi_total(t)
  -> amplitude imprint A(t)
  -> received complex block r(t)
```

这一步的主角色是“物理建模”，不是估计，也不是导航观测形成。

### 2.2 复包络表示

把带通信号写成复包络并在离散时间上生成 `rx_block`，属于合法的信号表示变换。只要：

- 载波参考频率定义清楚。
- 相位定义和延迟定义保持一致。
- 噪声模型与采样模型自洽。

则这一步是教材和工程中都常见的规范做法。

### 2.3 本层不应做的事

本层不应直接做以下事情：

- 从 `tau_total` 直接宣布“这就是标准伪距”。
- 在信号对象内部夹带接收机锁定状态语义。
- 在生成信号时把下游导航层对象提前命名出来。

## 3. 当前代码映射

### 3.1 信号配置对象

`notebooks/nb_ka225_rx_from_real_wkb_debug.py:115-133`

- `SignalConfig` 明确定义了 `fc_hz`、`fs_hz`、`chip_rate_hz`、`code_length`、`cn0_dbhz`、`nav_data_enabled`。
- 这部分在对象定义上基本属于信号层。

### 3.2 接收块生成

`notebooks/nb_ka225_rx_from_real_wkb_debug.py:648-705`

- `make_received_block()` 文档字符串已经明确写出：

  $$
  r(t)=A(t)\,c(t-\tau_{\mathrm{total}}(t))\exp(j\phi_{\mathrm{total}}(t))+n(t)
  $$

- `evaluate_true_channel_and_motion()` 负责提供传播印记。
- `sample_code_waveform()` 负责生成延迟后的本地码形。
- `phase_doppler + ch["phi_p_t"]` 共同形成总相位。

### 3.3 当前信号结构的一个硬缺口

`notebooks/nb_ka225_rx_from_real_wkb_debug.py:133`

- `nav_data_enabled` 被放进了 `SignalConfig`。
- 但在 `make_received_block()` 内部没有真正进入信号构造。

这意味着当前工程虽然在配置层承认“可能有导航数据”，但实际进入接收机的信号对象仍然近似为 dataless / pilot-like 通道。

## 4. 合法性判断

| 项目 | 判断 | 说明 |
| --- | --- | --- |
| 用 `A(t), phi(t), tau_g(t)` 明确构造传播后接收信号 | 合法 | 本层对象仍是信号，不是观测；物理角色清楚 |
| 用复基带块 `rx_block` 作为接收机输入 | 合法 | 这是标准的离散接收机输入表示 |
| 在信号层保留传播项显式可见 | 合法 | 有利于区分传播层与接收机层 |
| `nav_data_enabled` 存在但未进入信号生成 | 条件合法 | 只在“当前仿真等价于 dataless 信道近似”时成立；不能再声称已验证数据比特影响 |
| 若将本层输出直接当伪距或多普勒 | 语义越层 | 本层输出只是复信号块，还没有经过同步与观测形成 |

当前信号层最大的问题不是“公式错”，而是“对象身份有一个未完成分支”：配置里允许数据分量，但真正进入接收机的对象仍然不含该语义。

## 5. 与 Issue 01 结果的联系

`Issue 01` 去掉真值辅助后，低频段单通道误差急剧上升，而高频段重新进入稳定区。这首先说明的是：信号层提供给接收机的工作条件在不同频段并不等价。

代表频点见 `../references/representative_frequency_metrics.md`。

可以把现象压缩成下面的链条：

```text
低频段传播恶化
  -> 输入信号的有效工作条件下降
  -> 相关后 SNR 下降
  -> 接收机层更难维持正确锁定

高频段传播改善
  -> 输入信号质量回升
  -> 接收机层重新落回可跟踪区
```

因此，`Issue 01` 在本层支撑的不是“某个接收机参数该怎么调”，而是一个更基础的判断：

本层输出对象的统计品质，会直接决定接收机层是否还有资格把自己解释为一个稳定同步系统。

## 6. 对下游的接口资格

本层输出可以合法进入下一层，但资格条件必须写清：

### 可以进入接收机层的对象

- `rx_block`
- 与之配套的离散时间轴
- 信号配置参数

### 不能在本层提前声明的对象

- 标准伪距
- 标准载波相位观测
- 标准距离率 / 多普勒观测

### 当前建议的接口表述

```text
SignalLayerOutput
  - sample_times_s
  - complex_block
  - signal_structure
  - propagation_context
```

如果前端输出还是这种“纯信号对象”，那么接收机层后续的捕获、相关、环路同步才有明确对象基础；否则就会在最前端发生语义跳跃。
