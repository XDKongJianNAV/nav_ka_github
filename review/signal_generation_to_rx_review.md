# 信号生成到接收输入审阅

## 1. 审阅边界

这份文档只审阅“信号从定义、生成、传播项注入，到接收机输入复基带块 `rx_block` 形成”为止的代码。

明确不展开的内容：

- acquisition
- DLL / PLL / FLL
- 自然测量量与标准观测形成
- WLS / EKF

边界位置在 [nb_ka225_rx_from_real_wkb_debug.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:648) 的 `make_received_block()` 返回 `rx_block` 处；其后的 `run_acquisition()` 已属于下一层。

## 2. 一页结论

基于当前可执行代码，我能确认的事实是：

1. 当前真正执行的基础信号体制是单一 `PN/BPSK`，不是 data/pilot 双分量结构。[build_transmitter_signal_tools()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:583)
2. 当前伪随机码来自 `mseq_7()`，长度固定为 `127`，输出符号为 `±1`。[mseq_7()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:356)
3. 当前本地码波形是矩形码片波形，通过连续时间取样 `sample_code_waveform()` 得到，不是先整段展开再插值。[sample_code_waveform()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:371)
4. 真实传播项中，等离子体相关的 `A(t)`、`phi(t)`、`tau_g(t)` 来自 WKB 结果，并会先重采样到接收机时间轴。[compute_real_wkb_series()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:465) [resample_wkb_to_receiver_time()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:558)
5. 当前“运动 / 几何”部分的码时延和多普勒仍是外部抽象输入，而不是由完整几何动力学直接算出的真实星历链路。[MotionConfig](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:165) [evaluate_true_channel_and_motion()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:605)
6. legacy 主链路里的 `make_received_block()` 只把 `A(t)`、延迟后的 PN 码和总相位相乘，再加 AWGN；这里没有导航数据位注入。[make_received_block()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:648)
7. 显式的数据位注入只出现在 Issue 03 的 `make_textbook_received_block()`，它在延迟后的 PN 码之外再乘一个 `delayed_data`。[build_navigation_data_model()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/studies/issue_03_textbook_correction.py:186) [sample_navigation_waveform()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/studies/issue_03_textbook_correction.py:204) [make_textbook_received_block()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/studies/issue_03_textbook_correction.py:212)
8. 我没有在可执行信号链里发现独立的导频信号 `pilot channel`、secondary code 或独立 pilot correlator。`pilot` 只在抽象模型中作为概念出现，不能当作“已经实现”的证据。[gnss_signal_tracking_textbook_model.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/models/gnss_signal_tracking_textbook_model.py:1) [SignalComponentKind](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/models/gnss_signal_tracking_textbook_model.py:57) [SignalStructureModel](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/models/gnss_signal_tracking_textbook_model.py:99)
9. `ka_multifreq_receiver_common.py` 不是独立实现，它只是把 legacy 单文件里的信号链接口再导出一遍，供其他实验复用。[ka_multifreq_receiver_common.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/ka_multifreq_receiver_common.py:1)

## 3. 关键文件与角色

### 3.1 主实现

- [src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:115)
  这是当前“信号定义、码生成、传播项注入、接收输入形成”的主实现文件。

### 3.2 共享出口

- [src/nav_ka/legacy/ka_multifreq_receiver_common.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/ka_multifreq_receiver_common.py:24)
  这里只是 re-export。它把 `mseq_7`、`sample_code_waveform`、`compute_real_wkb_series`、`make_received_block` 等直接从 legacy 主实现导出，没有再实现一套新的信号链。

### 3.3 Issue 03 的信号侧扩展

- [src/nav_ka/studies/issue_03_textbook_correction.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/studies/issue_03_textbook_correction.py:35)
  这个文件在信号侧真正新增的是导航数据位模型和带数据位的 `make_textbook_received_block()`，不是导频通道。

### 3.4 抽象模型，不算实现

- [src/nav_ka/models/gnss_signal_tracking_textbook_model.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/models/gnss_signal_tracking_textbook_model.py:1)
  这个文件自述就是 reference model layer。它对术语澄清有帮助，但不应被当作“真实信号链已经支持 pilot”的证据。

## 4. 当前真实信号定义

### 4.1 配置层

`SignalConfig` 里真正决定这段信号链的关键量包括：

- 载频 `fc_hz`
- 采样率 `fs_hz`
- 码率 `chip_rate_hz`
- 码长 `code_length`
- 接收总时长 `total_time_s`
- 总采样点 `total_samples_value`
- 载噪比 `cn0_dbhz`
- 是否启用导航数据 `nav_data_enabled`

见 [SignalConfig](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:115)。

### 4.2 当前实际信号形式

legacy 主链中，接收输入按下面的代码事实形成：

`r(t) = A(t) * c(t - tau_total(t)) * exp(j * phi_total(t)) + n(t)`

其中：

- `A(t)` 来自 WKB 传播结果
- `c(t - tau_total(t))` 是延迟后的 PN 码波形
- `phi_total(t)` 由抽象多普勒积分项和等离子体相位项相加
- `n(t)` 是复高斯白噪声

这不是文档猜测，而是 [make_received_block()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:656) 里直接写出的数学形式。

### 4.3 当前没有实现的信号结构

在“可执行信号形成”这一层，我没有发现这些东西：

- 独立 pilot 通道
- data/pilot 并行分量
- secondary code
- BOC 调制
- 独立 pilot 无数据调制路径

因此，如果别处使用了 “pilot” 这个词，当前更诚实的说法应当是“概念层出现过 pilot 术语，但在可执行信号生成链中未发现对应实现”。

## 5. 术语澄清：伪随机码、数据位、导频不是一回事

### 5.1 伪随机码

当前伪随机码是 `mseq_7()` 返回的 127 长 m 序列，符号取值为 `±1`。[mseq_7()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:356)

### 5.2 码波形

`sample_code_waveform()` 把离散 `code_chips` 映射成连续时间上的矩形码波形。它先对时间做码周期取模，再按 `floor(t_mod * f_chip)` 取码片索引。[sample_code_waveform()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:371)

### 5.3 导航数据位

Issue 03 才显式实现了导航数据位：

- `build_navigation_data_model()` 生成一个确定性的伪随机 `50 bps` BPSK 数据位序列，符号仍是 `±1`。[build_navigation_data_model()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/studies/issue_03_textbook_correction.py:186)
- `sample_navigation_waveform()` 按比特周期对该序列连续时间采样。[sample_navigation_waveform()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/studies/issue_03_textbook_correction.py:204)

### 5.4 导频信号

当前没有单独的导频信号实现。`SignalComponentKind.PILOT` 和 `has_pilot_component` 只出现在抽象模型里。[SignalComponentKind](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/models/gnss_signal_tracking_textbook_model.py:57) [SignalStructureModel](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/models/gnss_signal_tracking_textbook_model.py:99)

## 6. 从 WKB 到接收机时间轴

### 6.1 接收机时间轴不是直接照搬 WKB 时间轴

`build_signal_config_from_wkb_time()` 的处理很明确：

- 先读取真实 WKB 时长 `T_real`
- 再按接收机采样率做 `N = round(T_real * fs)`
- 最后把真正使用的接收机时长写成 `T_used = N / fs`

这意味着接收机离散时间轴是“从真实 WKB 时间范围出发，再量化到采样网格”的结果，而不是原始 WKB 时间点的逐点复用。[build_signal_config_from_wkb_time()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:405)

### 6.2 WKB 传播量的来源

`compute_real_wkb_series()` 在中心频率和两侧频偏上各跑一次 WKB，然后得到：

- `A_t`
- `phi_t`
- `hp_t`
- `tau_g_t`

其中 `tau_g_t` 通过相位对角频率的中心差分估计得到。[compute_real_wkb_series()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:465)

### 6.3 重采样到接收机时间轴

`resample_wkb_to_receiver_time()` 用 `np.interp` 把 `A_t`、`phi_t`、`tau_g_t` 重采样到接收机离散时间轴上。[resample_wkb_to_receiver_time()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:558)

这一点很重要，因为后续信号形成并不是直接在原 WKB 样点上完成，而是在接收机采样时间轴上完成。

## 7. 从本地码到接收输入 `rx_block`

### 7.1 发射侧基础工具

`build_transmitter_signal_tools()` 当前只做了一件很核心但也很有限的事：生成 `code_chips = mseq_7()`，并明确打印“当前基础体制仍为 PN/BPSK”。[build_transmitter_signal_tools()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:583)

这里没有：

- 数据位生成
- pilot 分量生成
- 多分量复合信号生成

### 7.2 信道与运动项求值

`evaluate_true_channel_and_motion()` 把两类东西合并起来：

1. 抽象外部输入
- `tau_geom_s`
- `fd_total_hz`

2. 来自 WKB 的传播输入
- `A_t`
- `phi_p_t`
- `tau_g_s`

最后形成：

- `tau_total_s = tau_geom_s + tau_g_s`

见 [evaluate_true_channel_and_motion()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:605)。

这里最需要诚实说明的是：`tau_geom_s` 和 `fd_total_hz` 仍然是线性抽象模型，不是完整轨道和再入体动力学仿真直接推出来的。

### 7.3 legacy 接收输入形成

legacy 路径的 `make_received_block()` 顺序很清楚：

1. 调 `evaluate_true_channel_and_motion()` 得到 `tau_total_s`、`A_t`、`phi_p_t`
2. 用 `t_block_s - tau_total_s` 对 PN 码做延迟采样，得到 `delayed_code`
3. 根据 `doppler_hz_0` 和 `doppler_rate_hz_per_s` 积分得到 `phase_doppler`
4. 与等离子体相位 `phi_p_t` 相加得到 `phase_total`
5. 形成 `rx_clean = A_t * delayed_code * exp(j * phase_total)`
6. 按 `cn0_dbhz` 计算噪声方差并加入复高斯白噪声
7. 返回 `rx_block = rx_clean + noise`

见 [make_received_block()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:648)。

### 7.4 Issue 03 接收输入形成

Issue 03 的 `make_textbook_received_block()` 与 legacy 路径基本一致，但多了一层真实的数据位调制：

- 先得到 `delayed_code`
- 再得到 `delayed_data`
- 然后形成 `rx_clean = A_t * delayed_data * delayed_code * exp(j * phase_total)`

见 [make_textbook_received_block()](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/studies/issue_03_textbook_correction.py:212)。

这说明当前代码库里“数据位真的进入接收信号”的实现，是 Issue 03 这条支线，而不是 legacy 主链默认路径。

## 8. 控制流

只看信号生成到接收输入，这条控制流可以整理为：

1. 外部场与 WKB 结果提供 `wkb_time_s`、`A_t`、`phi_t`、`tau_g_t`
2. `build_signal_config_from_wkb_time()` 把真实时间范围量化成接收机时间配置
3. `build_transmitter_signal_tools()` 生成 `code_chips`
4. `resample_wkb_to_receiver_time()` 把 WKB 传播量重采样到接收机时间轴
5. `evaluate_true_channel_and_motion()` 在当前块时间 `t_block_s` 上计算 `tau_total_s`、`fd_total_hz`、`A_t`、`phi_p_t`
6. `sample_code_waveform()` 生成延迟后的 PN 码波形
7. Issue 03 路径中，`sample_navigation_waveform()` 再生成延迟后的数据位波形
8. `make_received_block()` 或 `make_textbook_received_block()` 形成 `rx_clean`
9. 加入 AWGN，得到接收机输入 `rx_block`

越过这一步之后才进入 acquisition / tracking，这已经超出本文范围。

## 9. 信息流

| 量名 | 来源 | 首次形成位置 | 被谁消费 | 性质 |
| --- | --- | --- | --- | --- |
| `code_chips` | `mseq_7()` | [nb_ka225_rx_from_real_wkb_debug.py:595](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:595) | `sample_code_waveform()`、接收输入形成 | 本地 PN 码 |
| `t_block_s` | 接收机块时间轴 | 调用 `make_received_block()` 时传入 | `evaluate_true_channel_and_motion()`、码/数据位延迟采样 | 接收机本地时间 |
| `A_t` | WKB 结果重采样 | [nb_ka225_rx_from_real_wkb_debug.py:568](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:568) 或 [nb_ka225_rx_from_real_wkb_debug.py:632](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:632) | `rx_clean` 形成 | 传播幅度真值输入 |
| `phi_p_t` | WKB 相位重采样 | [nb_ka225_rx_from_real_wkb_debug.py:633](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:633) | `phase_total` | 传播相位真值输入 |
| `tau_g_s` | WKB 群时延重采样 | [nb_ka225_rx_from_real_wkb_debug.py:634](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:634) | `tau_total_s` | 传播群时延真值输入 |
| `tau_geom_s` | `MotionConfig` 线性模型 | [nb_ka225_rx_from_real_wkb_debug.py:625](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:625) | `tau_total_s` | 抽象外部设定 |
| `tau_total_s` | `tau_geom_s + tau_g_s` | [nb_ka225_rx_from_real_wkb_debug.py:636](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:636) | 延迟后的码和数据位采样 | 真实输入到接收信号形成 |
| `fd_total_hz` | `MotionConfig` 线性模型 | [nb_ka225_rx_from_real_wkb_debug.py:630](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:630) | 当前函数主要作为中间状态返回 | 抽象外部设定 |
| `delayed_code` | `sample_code_waveform(code_chips, t_block_s - tau_total_s)` | [nb_ka225_rx_from_real_wkb_debug.py:680](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:680) | `rx_clean` | 延迟后的码波形 |
| `nav_data_model.symbols` | `build_navigation_data_model()` | [issue_03_textbook_correction.py:195](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/studies/issue_03_textbook_correction.py:195) | `sample_navigation_waveform()` | 数据位序列 |
| `delayed_data` | `sample_navigation_waveform(..., t_block_s - tau_total_s)` | [issue_03_textbook_correction.py:234](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/studies/issue_03_textbook_correction.py:234) | Issue 03 的 `rx_clean` | 延迟后的数据位波形 |
| `phase_total` | 多普勒积分项 + 等离子体相位项 | [nb_ka225_rx_from_real_wkb_debug.py:686](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:686) 和 [issue_03_textbook_correction.py:240](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/studies/issue_03_textbook_correction.py:240) | `exp(j * phase_total)` | 总载波相位 |
| `rx_clean` | 幅度、码、相位，外加 Issue 03 的数据位 | [nb_ka225_rx_from_real_wkb_debug.py:693](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:693) / [issue_03_textbook_correction.py:245](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/studies/issue_03_textbook_correction.py:245) | 噪声叠加 | 无噪复基带信号 |
| `rx_block` | `rx_clean + noise` | [nb_ka225_rx_from_real_wkb_debug.py:705](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py:705) / [issue_03_textbook_correction.py:254](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/studies/issue_03_textbook_correction.py:254) | acquisition / tracking | 接收机输入复基带块 |

## 10. 哪些函数真正生成或修改了信号

只保留直接影响 `rx_block` 的函数：

| 函数 | 作用 | 备注 |
| --- | --- | --- |
| `mseq_7()` | 生成 PN 码序列 | legacy 主链的唯一码生成器 |
| `sample_code_waveform()` | 把 PN 码变成连续时间矩形码波形 | 可作用于任意延迟时间 |
| `build_signal_config_from_wkb_time()` | 确定信号采样时间尺度 | 改变接收机离散时间轴 |
| `compute_real_wkb_series()` | 生成传播幅度 / 相位 / 群时延序列 | 来自真实 WKB |
| `resample_wkb_to_receiver_time()` | 把传播序列映射到接收机时间轴 | 插值重采样 |
| `build_transmitter_signal_tools()` | 组织发射侧基础码资源 | 当前只返回 `code_chips` |
| `evaluate_true_channel_and_motion()` | 形成总时延、传播幅度和相位输入 | 合并抽象运动项和 WKB 项 |
| `build_navigation_data_model()` | 生成导航数据位序列 | 只在 Issue 03 信号路径里有用 |
| `sample_navigation_waveform()` | 生成连续时间数据位波形 | 只在 Issue 03 中参与 |
| `make_received_block()` | 生成 legacy `rx_block` | 无数据位 |
| `make_textbook_received_block()` | 生成 Issue 03 `rx_block` | 有数据位 |

## 11. 差距与风险

### 11.1 “pilot” 术语容易造成误读

代码库里确实存在 `SignalComponentKind.PILOT` 和 `has_pilot_component` 这样的抽象字段，但它们出现在参考模型层，不在可执行信号链里。如果文档或讨论里把这层概念说成“已经实现 pilot”，那会高估当前能力。[gnss_signal_tracking_textbook_model.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/src/nav_ka/models/gnss_signal_tracking_textbook_model.py:57)

### 11.2 legacy 主链和 Issue 03 的信号语义不一致

legacy `make_received_block()` 不注入导航数据位，而 Issue 03 `make_textbook_received_block()` 会注入数据位。这意味着不同实验脚本如果都说自己在处理“接收信号”，它们其实可能不是同一种信号语义。

### 11.3 传播项和运动项的真实性不对称

等离子体传播项来自真实 WKB 结果，这部分相对扎实；但 `tau_geom_s` 和 `fd_total_hz` 仍是线性抽象外部输入。这会让读者误以为整条传播链都同样“物理真实”，其实不是。

### 11.4 当前发射端实现很薄

`build_transmitter_signal_tools()` 现在只有 PN 码，没有把“发射机信号定义”真正拆成码、数据位、分量结构、调制结构等稳定模块。这不影响当前运行，但会让审阅和扩展都继续依赖 legacy 单文件。

## 12. 改进建议

### P0

- 在所有信号相关文档里把“当前无独立 pilot 可执行实现”写明，不再只靠读源码的人自己推断。
- 在接口或注释里明确区分三件事：`PN 码`、`导航数据位`、`导频分量`。
- 在 legacy `make_received_block()` 附近补一句更直接的注释，说明该路径默认不注入导航数据位。

### P1

- 把 `mseq_7()`、`sample_code_waveform()`、`build_navigation_data_model()`、`sample_navigation_waveform()` 抽成单独稳定模块，减少信号定义分散在 legacy 和 study 文件里的问题。
- 把 `evaluate_true_channel_and_motion()` 的抽象几何项和 WKB 项分成更显式的两个对象，避免“都叫 true”但物理真实性不同。

### P2

- 如果后续确实需要“导频信号”论述成立，就必须增加真正的 pilot 分量、明确的数据 / 导频组合结构，以及对应的接收输入形成代码；否则不应继续使用容易让人误解为“已支持 pilot”的说法。
