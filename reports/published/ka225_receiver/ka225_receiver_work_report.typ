#set page(
  paper: "a4",
  margin: (x: 16mm, y: 14mm),
)

#set text(
  lang: "zh",
  size: 10.2pt,
  font: ("DengXian", "DejaVu Serif", "DejaVu Sans"),
)
#set par(justify: true, leading: 0.72em)
#set heading(numbering: "1.")
#show raw: set text(font: ("DejaVu Sans Mono", "DengXian"))
#show figure.caption: set text(size: 8.8pt, fill: rgb("#444444"))

#let data = json("assets/ka225_receiver/summary.json")

#let pct(x) = str(calc.round(x * 10000) / 100) + "%"
#let f1(x) = str(calc.round(x * 10) / 10)
#let f2(x) = str(calc.round(x * 100) / 100)
#let f3(x) = str(calc.round(x * 1000) / 1000)

#let blue = rgb("#e6efff")
#let green = rgb("#e7f4e7")
#let amber = rgb("#fff1da")
#let red = rgb("#f9e4e1")
#let gray = rgb("#f4f5f7")
#let line = rgb("#8e949c")

#show heading.where(level: 1): it => block(
  above: 1.1em,
  below: 0.45em,
  text(font: ("DengXian", "DejaVu Serif"), weight: "bold", size: 16pt, it),
)
#show heading.where(level: 2): it => block(
  above: 0.9em,
  below: 0.3em,
  text(font: ("DengXian", "DejaVu Serif"), weight: "bold", size: 12.8pt, it),
)
#show heading.where(level: 3): it => block(
  above: 0.75em,
  below: 0.2em,
  text(font: ("DengXian", "DejaVu Serif"), weight: "bold", size: 11.3pt, it),
)

#let node(title, body, fill: gray) = box(
  width: 100%,
  inset: 8pt,
  radius: 6pt,
  stroke: 0.7pt + line,
  fill: fill,
  [
    #text(weight: "bold", title)
    #v(3pt)
    #body
  ],
)

#let card(title, body, fill: gray) = box(
  width: 100%,
  inset: 9pt,
  radius: 6pt,
  stroke: 0.6pt + line,
  fill: fill,
  [
    #text(weight: "bold", title)
    #v(4pt)
    #body
  ],
)

#let arrow(dir: "→") = align(center + horizon, text(size: 18pt, fill: rgb("#555555"), dir))
#let eq(body) = block(above: 5pt, below: 5pt, align(center, body))

#let compare-table() = table(
  columns: 4,
  stroke: 0.4pt + rgb("#bbbbbb"),
  inset: 6pt,
  [指标], [修复前], [修复后], [改善幅度],
  [码时延 RMSE (ns)],
  [#f3(data.at("baseline").at("tau_rmse_ns"))],
  [#f3(data.at("current").at("tau_rmse_ns"))],
  [#f2(data.at("baseline").at("tau_rmse_ns") / data.at("current").at("tau_rmse_ns")) #sym.times],
  [频偏 RMSE (Hz)],
  [#f3(data.at("baseline").at("fd_rmse_hz"))],
  [#f3(data.at("current").at("fd_rmse_hz"))],
  [#f2(data.at("baseline").at("fd_rmse_hz") / data.at("current").at("fd_rmse_hz")) #sym.times],
  [最终载波频率估计 (kHz)],
  [#f3(data.at("baseline").at("final_fd_est_khz"))],
  [#f3(data.at("current").at("final_fd_est_khz"))],
  [真值为 #f3(data.at("current").at("final_fd_true_khz"))],
  [最终码时延估计 (us)],
  [#f3(data.at("baseline").at("final_tau_est_us"))],
  [#f3(data.at("current").at("final_tau_est_us"))],
  [真值为 #f3(data.at("current").at("final_tau_true_us"))],
)

#let diag-table() = table(
  columns: 2,
  stroke: 0.4pt + rgb("#bbbbbb"),
  inset: 6pt,
  [诊断项], [当前值],
  [预测输入 C/N0 范围 (dB-Hz)], [#f3(data.at("tracking_diagnostics").at("predicted_cn0_dbhz_min")) ~ #f3(data.at("tracking_diagnostics").at("predicted_cn0_dbhz_max"))],
  [后相关 Prompt SNR 范围 (dB)], [#f3(data.at("tracking_diagnostics").at("post_corr_snr_db_min")) ~ #f3(data.at("tracking_diagnostics").at("post_corr_snr_db_max"))],
  [PLL 超线性区占比], [#pct(data.at("tracking_diagnostics").at("pll_out_of_linear_frac"))],
  [DLL 超线性区占比], [#pct(data.at("tracking_diagnostics").at("dll_out_of_linear_frac"))],
  [弱 Prompt SNR 占比], [#pct(data.at("tracking_diagnostics").at("weak_prompt_frac"))],
  [弱载波锁定占比], [#pct(data.at("tracking_diagnostics").at("carrier_lock_weak_frac"))],
  [FLL 辅助占比], [#pct(data.at("tracking_diagnostics").at("fll_active_frac"))],
  [DLL 冻结占比], [#pct(data.at("tracking_diagnostics").at("dll_frozen_frac"))],
  [PLL 冻结占比], [#pct(data.at("tracking_diagnostics").at("pll_frozen_frac"))],
  [PLL 积分器夹限次数], [#data.at("tracking_diagnostics").at("pll_integrator_clamped_count")],
  [PLL 频率命令夹限次数], [#data.at("tracking_diagnostics").at("pll_freq_clamped_count")],
)

#let segment-table() = table(
  columns: 6,
  stroke: 0.4pt + rgb("#bbbbbb"),
  inset: 5pt,
  [阶段], [tau RMSE (ns)], [fd RMSE (Hz)], [Prompt SNR 中位数 (dB)], [PLL RMS (rad)], [Loss 占比],
  [#data.at("tracking_diagnostics").at("segment_names").at(0)],
  [#f3(data.at("tracking_diagnostics").at("segment_tau_rmse_ns").at(0))],
  [#f3(data.at("tracking_diagnostics").at("segment_fd_rmse_hz").at(0))],
  [#f3(data.at("tracking_diagnostics").at("segment_prompt_snr_db").at(0))],
  [#f3(data.at("tracking_diagnostics").at("segment_pll_rms").at(0))],
  [#pct(data.at("tracking_diagnostics").at("segment_loss_frac").at(0))],
  [#data.at("tracking_diagnostics").at("segment_names").at(1)],
  [#f3(data.at("tracking_diagnostics").at("segment_tau_rmse_ns").at(1))],
  [#f3(data.at("tracking_diagnostics").at("segment_fd_rmse_hz").at(1))],
  [#f3(data.at("tracking_diagnostics").at("segment_prompt_snr_db").at(1))],
  [#f3(data.at("tracking_diagnostics").at("segment_pll_rms").at(1))],
  [#pct(data.at("tracking_diagnostics").at("segment_loss_frac").at(1))],
  [#data.at("tracking_diagnostics").at("segment_names").at(2)],
  [#f3(data.at("tracking_diagnostics").at("segment_tau_rmse_ns").at(2))],
  [#f3(data.at("tracking_diagnostics").at("segment_fd_rmse_hz").at(2))],
  [#f3(data.at("tracking_diagnostics").at("segment_prompt_snr_db").at(2))],
  [#f3(data.at("tracking_diagnostics").at("segment_pll_rms").at(2))],
  [#pct(data.at("tracking_diagnostics").at("segment_loss_frac").at(2))],
)

#align(center)[
  #text(size: 20pt, weight: "bold", data.at("title"))
]

#v(6pt)

#align(center)[
  #text(size: 9.2pt, fill: rgb("#555555"), "脚本: " + data.at("generation").at("script"))
  #linebreak()
  #text(size: 9.2pt, fill: rgb("#555555"), "报告资源目录: " + data.at("generation").at("asset_dir"))
]

#v(10pt)

#grid(
  columns: (1fr, 1fr),
  gutter: 8pt,
  card("文档目的", [
    本文档给出 `src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py` 的接收机侧技术重构说明。内容覆盖脚本内部组织、运行流程、信号模型、捕获与跟踪方程、调试出口、图像资产与最终性能。
  ], fill: blue),
  card("交付边界", [
    代码修改限定在目标脚本；报告产物由 `reports/generate_ka225_receiver_report_assets.py`、Typst 文档和构建脚本组成，输出 `pdf` 与 `docx` 两种格式。
  ], fill: green),
)

= 任务范围

当前版本完成的工作包括：

- 在接收机侧补充捕获、跟踪、失锁与门控的真实诊断量，不以提示文本代替指标。
- 将接收机编排整理为适度对象化结构，保留数学工具和信号工具的函数式实现。
- 为接收机内部波形、频谱、相关器、环路和快照提供可选绘图出口。
- 生成覆盖结构、公式、图像证据和结果对比的汇报文档，并输出 `pdf` 与 `docx`。

文档组织顺序采用“结构与流程优先，指标结果后置”的方式。程序形态、状态流和公式先于性能对比给出，便于后续协作直接定位实现与接口。

= 脚本结构

== 文件内部分区

#figure(
  grid(
    columns: (1fr, auto, 1fr, auto, 1fr, auto, 1fr, auto, 1fr),
    gutter: 6pt,
    node("配置与状态", [
      - `SignalConfig`
      - `MotionConfig`
      - `AcquisitionConfig`
      - `TrackingConfig`
      - `ReceiverState`
    ], fill: blue),
    arrow(),
    node("信号与传播", [
      - `mseq_7`
      - `sample_code_waveform`
      - `evaluate_true_channel_and_motion`
      - `make_received_block`
    ], fill: green),
    arrow(),
    node("捕获链", [
      - `run_acquisition`
      - `diagnose_acquisition_physics`
      - 粗搜索与局部细化
    ], fill: amber),
    arrow(),
    node("跟踪链", [
      - `correlate_block`
      - `run_tracking`
      - `diagnose_tracking_physics`
      - `build_tracking_snapshot`
    ], fill: red),
    arrow(),
    node("图像与报告资产", [
      - `plot_receiver_results`
      - `summary.json`
      - `png`
      - Typst 文档与构建脚本
    ], fill: gray),
  ),
  caption: [目标脚本与报告资产的静态分区。数据和控制流自左向右推进。],
)

分区原则如下：

- 配置与共享状态进入数据类，便于在捕获、跟踪和报告资产之间复用。
- 数学与信号处理函数保持独立函数形态，便于替换公式、门限和局部实验逻辑。
- OOP 仅用于封装共享上下文和执行顺序，不把判别器、相关器、频谱等基础计算封进层层方法。

== 对象边界与协作关系

#figure(
  grid(
    columns: (1fr, auto, 1fr, auto, 1fr),
    gutter: 8pt,
    node("ReceiverRuntimeContext", [
      - 配置集合
      - 码序列
      - `plasma_rx`
      - 接收机时间轴
      - `make_received_block`
    ], fill: blue),
    arrow(),
    node("KaBpskReceiver", [
      - 固定执行顺序
      - 捕获后再跟踪
      - 汇总诊断输出
    ], fill: amber),
    arrow(),
    node("ReceiverRunArtifacts", [
      - `acq_result`
      - `acq_diag`
      - `trk_result`
      - `trk_diag`
    ], fill: green),
  ),
  caption: [对象级协作边界。`KaBpskReceiver` 只负责编排，算法细节仍在函数级实现中。],
)

#figure(
  grid(
    columns: (1fr, auto, 1fr, auto, 1fr),
    gutter: 8pt,
    node("AcquisitionEngine", [
      - 读取 `ReceiverRuntimeContext`
      - 调用 `run_acquisition`
      - 调用 `diagnose_acquisition_physics`
    ], fill: amber),
    arrow(),
    node("共享状态", [
      - 初始码时延
      - 初始频偏
      - 捕获热图与局部切片
    ], fill: gray),
    arrow(),
    node("TrackingEngine", [
      - 调用 `run_tracking`
      - 调用 `diagnose_tracking_physics`
      - 记录块级快照与门控状态
    ], fill: red),
  ),
  caption: [捕获与跟踪的接口位置。共享对象位于上下文与结果对象之间，不额外复制整条接收机链。],
)

== 接口清单

#table(
  columns: 4,
  stroke: 0.4pt + rgb("#bbbbbb"),
  inset: 5pt,
  [分区], [主要实现], [输入], [输出],
  [配置], [`SignalConfig`, `MotionConfig`, `AcquisitionConfig`, `TrackingConfig`], [WKB 时间轴、采样率、环路参数], [统一配置对象],
  [共享上下文], [`ReceiverRuntimeContext`], [配置、码序列、重采样信道、时间轴], [块级信号生成入口],
  [捕获], [`run_acquisition`, `diagnose_acquisition_physics`], [上下文、捕获配置], [粗峰、细峰、热图、次峰比、初始化误差],
  [跟踪], [`run_tracking`, `diagnose_tracking_physics`], [捕获结果、跟踪配置、上下文], [时延与频率估计、判别器、锁定指标、失锁判据],
  [可视化], [`plot_receiver_results`], [捕获与跟踪全部结果], [四类诊断图],
  [报告资产], [`generate_ka225_receiver_report_assets.py`], [运行结果与图像], [`summary.json`, `png`, Typst 输入],
)

= 运行流程

== 主流程

#figure(
  grid(
    columns: 1,
    gutter: 5pt,
    node("1. 传播结果离散化", [
      由场与 WKB 结果得到接收机时间轴上的幅度、群时延和附加相位序列。
    ], fill: gray),
    arrow(dir: "↓"),
    node("2. 接收机配置构造", [
      建立 PN/BPSK 信号参数、积分时间、码率、采样率、动态先验和环路参数。
    ], fill: blue),
    arrow(dir: "↓"),
    node("3. 运行时上下文组装", [
      将配置、码序列、重采样传播结果和统一时间轴整理为 `ReceiverRuntimeContext`。
    ], fill: green),
    arrow(dir: "↓"),
    node("4. 捕获", [
      二维粗搜索确定峰值邻域；随后在邻域内做局部细化，形成更准确的初值。
    ], fill: amber),
    arrow(dir: "↓"),
    node("5. 跟踪", [
      逐个 1 ms 积分块执行本地载波生成、去载波、Early/Prompt/Late 相关、DLL/PLL/FLL 更新、门控和失锁记录。
    ], fill: red),
    arrow(dir: "↓"),
    node("6. 诊断与报告资产", [
      生成分段指标、锁定状态、快照图和 `summary.json`，再由 Typst 编译为 `pdf` 和 `docx`。
    ], fill: gray),
  ),
  caption: [`main()` 的主要执行链。],
)

== 单积分块内部流程

#figure(
  grid(
    columns: (1fr, auto, 1fr, auto, 1fr, auto, 1fr),
    gutter: 6pt,
    node("真实来波", [
      `r_k[n]`
      #linebreak()
      幅度衰落、群时延、多普勒、噪声
    ], fill: blue),
    arrow(),
    node("本地副本生成", [
      `c_E[n]`
      #linebreak()
      `c_P[n]`
      #linebreak()
      `c_L[n]`
      #linebreak()
      `exp(-j phi_k[n])`
    ], fill: green),
    arrow(),
    node("相关器", [
      `E_k`
      #linebreak()
      `P_k = I_(P,k) + j Q_(P,k)`
      #linebreak()
      `L_k`
    ], fill: amber),
    arrow(),
    node("环路更新", [
      DLL
      #linebreak()
      Costas PLL
      #linebreak()
      FLL 辅助
      #linebreak()
      门控与失锁判据
    ], fill: red),
  ),
  caption: [每个 1 ms 积分块的接收机内部信号路径。],
)

== 报告产物链

#figure(
  grid(
    columns: (1fr, auto, 1fr, auto, 1fr, auto, 1fr),
    gutter: 6pt,
    node("接收机脚本", [
      `nb_ka225_rx_from_real_wkb_debug.py`
    ], fill: blue),
    arrow(),
    node("图像与摘要数据", [
      `receiver_overview.png`
      #linebreak()
      `receiver_acquisition_internal.png`
      #linebreak()
      `receiver_tracking_internal.png`
      #linebreak()
      `receiver_tracking_snapshots.png`
      #linebreak()
      `summary.json`
    ], fill: green),
    arrow(),
    node("Typst 版式层", [
      `ka225_receiver_work_report.typ`
    ], fill: amber),
    arrow(),
    node("发布产物", [
      `ka225_receiver_work_report.pdf`
      #linebreak()
      `ka225_receiver_work_report.docx`
    ], fill: red),
  ),
  caption: [报告构建链。`docx` 由已渲染页面图像封装，以保持公式和图形版式一致。],
)

= 信号模型与程序逻辑

== 接收信号模型

脚本中的接收信号可以写成：

#eq($
  r(t) = A(t) c(t - tau(t)) exp(j phi(t)) + w(t)
$)

其中总时延与总相位分别由几何项和传播项组成：

#eq($
  tau(t) = tau_("geom")(t) + tau_g(t)
$)

#eq($
  phi(t) = 2 pi (f_(D,0) t + 1/2 f_(D,1) t^2) + phi_p(t)
$)

式中 `A(t)` 表示衰落包络，`tau_g(t)` 表示传播引入的群时延，`phi_p(t)` 表示传播附加相位，`f_(D,0)` 与 `f_(D,1)` 对应脚本中显式注入的载波动态。

== 捕获目标函数

捕获阶段先在离散频偏与码相位网格上计算相关能量：

#eq($
  Z(tau, f) = sum_(n=0)^(N-1) r_n c_(n, tau) exp(-j 2 pi f t_n)
$)

粗捕获峰值由 `abs(Z(tau, f))^2` 的最大点给出。当前脚本在粗峰邻域继续进行细化搜索，减少平顶峰对初始条件的影响。这个细化步骤直接降低了 DLL 初始残差和 PLL 早期过渡阶段的动态压力。

== 相关器与判别器

每个积分块生成三路本地码副本与一路本地载波副本，相关输出记为：

#eq($
  E_k = sum_(n=0)^(N-1) r_k[n] c_(E,k)[n] exp(-j hat(phi)_k[n])
$)

#eq($
  P_k = sum_(n=0)^(N-1) r_k[n] c_(P,k)[n] exp(-j hat(phi)_k[n])
$)

#eq($
  L_k = sum_(n=0)^(N-1) r_k[n] c_(L,k)[n] exp(-j hat(phi)_k[n])
$)

Prompt 支路分解为：

#eq($
  P_k = I_(P,k) + j Q_(P,k)
$)

DLL 采用非相干早迟判别器：

#eq($
  e_(D,k) = (abs(E_k) - abs(L_k)) / (abs(E_k) + abs(L_k))
$)

载波环采用 Costas 判别器，并在早期由 FLL 提供辅助频率误差：

#eq($
  e_(P,k) = "atan2"(Q_(P,k), abs(I_(P,k)))
$)

#eq($
  e_(F,k) = "angle"(P_k overline(P_(k-1))) / (2 pi T_c)
$)

== 预测器与环路更新

当前版本在码 NCO 和载波 NCO 中加入线性预测项：

#eq($
  tau_k^- = hat(tau)_(k-1) + dot(tau)_a T_c
$)

#eq($
  f_k^- = hat(f)_(k-1) + dot(f)_a T_c
$)

DLL 和载波环的更新形式为：

#eq($
  hat(tau)_k = tau_k^- - K_D e_(D,k) T_"ch"
$)

#eq($
  hat(f)_k = f_k^- + f_(I,k) + K_P e_(P,k) + K_F e_(F,k)
$)

#eq($
  f_(I,k) = "clip"(f_(I,k-1) + K_I e_(P,k), -f_M, f_M)
$)

其中 `dot(tau)_a` 和 `dot(f)_a` 来自接收机动态先验，`"clip"` 对应脚本中的积分器保护与频率命令保护。

== 门控与失锁判据

门控变量记为：

#eq($
  g_(D,k), g_(P,k) in {0, 1}
$)

其物理含义为“允许更新”或“冻结更新”。当后相关 SNR 低于阈值，或载波锁定指标低于阈值时，对应环路暂不吸收新误差，只依靠预测器与现有状态维持。

持续失锁判据采用三项得分累加：

#eq($
  J_k = I_(S,k) + I_(P,k) + I_(D,k)
$)

其中：

- `I_(S,k)` 表示 Prompt 后相关 SNR 低于弱锁定阈值。
- `I_(P,k)` 表示 PLL 超出线性区，且同时出现弱载波锁定或正交分量占优。
- `I_(D,k)` 表示 DLL 超出线性区。

当 `J_k >= 2` 且连续维持超过设定块数时，记为持续失锁。该判据避免将单个离群块误判成真正的环路失锁。

= 调试出口与可视化

脚本提供四类可选图像资产，均可保存为 `png`：

- 总览图：信道幅度、群时延、真值/预测/估计轨迹、Prompt 星座和相关器幅度。
- 捕获内部图：捕获块原始信号、频谱、粗热图、细热图、码延迟切片和最优假设副本。
- 跟踪内部图：DLL/PLL/FLL 误差、锁定指标、门控、NCO 命令和误差轨迹。
- 首中末块快照：原始块、去载波后基带、局部码副本、频谱与 Prompt 输出。

这些图像的作用不是仅做展示，而是将以下诊断点外显：

- 码与载波初值误差是否已在捕获阶段被压低。
- 跟踪后段是否仍出现非线性区占比抬升。
- FLL 是否只在需要时介入，而不是长期主导载波环。
- 本地副本与接收信号在首、中、末阶段的匹配程度是否一致。

= 结果与指标

== 修复前后对比

#compare-table()

当前版本的改进不是单点调参，而是初始化、预测器、FLL 辅助和门控策略共同作用后的结果。关键变化是粗捕获误差不再直接传入跟踪环，且跟踪环在低质量相关输出下不会继续吸收错误判别器输出。

== 当前接收机诊断量

#diag-table()

上表给出的值说明当前问题位置已经从“硬失锁或硬饱和”转移到“后段相关质量和线性区占比下降”。`PLL` 和 `DLL` 没有出现命令夹限，但后段仍能观察到锁定质量下降，因此调试重点应放在弱信号阶段的模型匹配与门限细化，而不是简单放宽控制范围。

== 分段表现

#segment-table()

三个时间分段的结果表明：

- 前段捕获后进入跟踪的过渡已经稳定，`tau` 和 `fd` 误差明显低于旧版本。
- 中段为当前版本的最佳工作区，Prompt SNR 与 PLL RMS 最平稳。
- 后段仍存在退化，但没有触发持续失锁，说明预测器与门控已阻断原有的发散路径。

= 图像证据

== 总览图

#figure(
  image("assets/ka225_receiver/receiver_overview.png", width: 100%),
  caption: [总览图。包含信道幅度、群时延、真值/预测/估计轨迹、后相关 SNR、`|E|/|P|/|L|` 和 Prompt 星座。],
)

该图用于检查整体运行状态是否一致：预测器与估计器是否围绕真值工作，后相关 SNR 是否维持在可跟踪区间，以及 Prompt 星座是否在全时域内保持集中。

#pagebreak()

== 捕获内部图

#figure(
  image("assets/ka225_receiver/receiver_acquisition_internal.png", width: 100%),
  caption: [捕获内部图。包含原始捕获块、频谱、粗捕获热图、细化热图、码延迟切片和最佳假设。],
)

当前主峰与次峰的幅度比为 #strong[#f3(data.at("current").at("peak_to_second_ratio"))]，折合 #strong[#f3(data.at("current").at("peak_to_second_db")) dB]。主峰附近地形较平，因此细化搜索属于必要步骤，而不是附加优化。

#pagebreak()

== 跟踪内部图

#figure(
  image("assets/ka225_receiver/receiver_tracking_internal.png", width: 100%),
  caption: [跟踪内部图。包含 DLL/PLL/FLL 误差、锁定指标、门控状态、NCO 命令和码频误差轨迹。],
)

该图给出环路内部状态在时间轴上的展开结果，可直接判断：

- 判别器是否大范围进入非线性区。
- FLL 介入时段是否与弱锁定时段一致。
- DLL/PLL 冻结是否发生在低 SNR 或低锁定指标阶段。
- 积分器与频率命令是否逼近保护边界。

#pagebreak()

== 首中末块快照

#figure(
  image("assets/ka225_receiver/receiver_tracking_snapshots.png", width: 100%),
  caption: [首、中、末积分块快照。包含原始信号、去载波后基带、本地码副本与频谱。],
)

块级快照适合检查“每一步的样子”是否合理，包括原始样值的复平面分布、去载波后能量是否集中、Early/Prompt/Late 本地码是否匹配，以及首段与末段之间的波形和频谱差异。

= 修改条目与交付物

== 代码与报告修改条目

#for item in data.at("fixes") [
- #item
]

此外，报告构建链补充了 `docx` 输出，将渲染后的页面图像封装为 Word 文档，以保证公式、图形和分页在两种发布格式中保持一致。

== 交付物

- 目标脚本：`src/nav_ka/legacy/nb_ka225_rx_from_real_wkb_debug.py`
- 资产生成脚本：`reports/generate_ka225_receiver_report_assets.py`
- Typst 报告源：`reports/ka225_receiver_work_report.typ`
- 构建脚本：`reports/builders/build_ka225_receiver_report.sh`
- 报告输出：`reports/ka225_receiver_work_report.pdf`
- 报告输出：`reports/ka225_receiver_work_report.docx`
