# 环路设计图说明

旧的三栏拼图已经退役，当前正式插图改成 6 张独立教材图，统一由 `Graphviz` 从结构化 `.dot` 文件自动生成，输出位置在 [figures](./figures)。

## 1. 图集组成

### 1.1 教材标准总接收机链路图

- [textbook_receiver_chain.svg](./figures/textbook_receiver_chain.svg)
- [textbook_receiver_chain.png](./figures/textbook_receiver_chain.png)

这张图只表达教材标准对象关系：

接收复信号  
→ 捕获  
→ 相关器  
→ 判别器  
→ 环路滤波器  
→ 数控振荡器  
→ 自然测量量  
→ 观测形成  
→ 标准观测量

### 1.2 原始实现总链路图

- [legacy_receiver_chain.svg](./figures/legacy_receiver_chain.svg)
- [legacy_receiver_chain.png](./figures/legacy_receiver_chain.png)

这张图只画原始实现真实存在的链路，并显式标出两类问题：

- 运行时真值注入
- 接收机内部状态直接改名成观测

### 1.3 教材修正版总链路图

- [corrected_receiver_chain.svg](./figures/corrected_receiver_chain.svg)
- [corrected_receiver_chain.png](./figures/corrected_receiver_chain.png)

这张图对应 `Issue 03` 的 corrected 路径，重点是三点：

- 信号对象含真实导航数据
- 码环与载波环显式拆开
- 自然测量量与标准观测量显式分层

### 1.4 教材标准码环图

- [textbook_dll_loop.svg](./figures/textbook_dll_loop.svg)
- [textbook_dll_loop.png](./figures/textbook_dll_loop.png)

只表达 DLL 这一条控制闭环：

接收复基带  
→ 早 / 准 / 晚相关器  
→ DLL 判别器  
→ 码环滤波器  
→ 码 NCO  
→ 本地码发生器  
→ 回到相关器

### 1.5 教材标准载波环图

- [textbook_carrier_loop.svg](./figures/textbook_carrier_loop.svg)
- [textbook_carrier_loop.png](./figures/textbook_carrier_loop.png)

这张图对应当前 corrected 路径采用的 `FLL` 辅助 `Costas PLL`：

准时相关输出  
→ Costas 判别器  
→ 环路组合与滤波  
→ 载波 NCO  
→ 本地载波  
→ 回到准时相关输出

并额外画出 `FLL` 的辅助分支。

### 1.6 观测形成层图

- [observable_formation_chain.svg](./figures/observable_formation_chain.svg)
- [observable_formation_chain.png](./figures/observable_formation_chain.png)

这张图专门解释为什么接收机层输出还不能直接叫标准观测：

自然测量量  
→ 接收时标解释 / 发射时刻恢复  
→ 波长换算 / 符号约定  
→ 统一观测方程  
→ 标准观测量

## 2. 与代码实现的对应关系

### 原始实现

- 相关器：`notebooks/nb_ka225_rx_from_real_wkb_debug.py:958`
- 码环判别器：`notebooks/nb_ka225_rx_from_real_wkb_debug.py:1007`
- 载波判别器：`notebooks/nb_ka225_rx_from_real_wkb_debug.py:1017`
- 主跟踪循环：`notebooks/nb_ka225_rx_from_real_wkb_debug.py:1090`

原始实现的问题不是“没有环路”，而是：

- 环路更新中混入真值辅助
- 内部更新律没有拆成正式块图
- 内部状态被提前叫成观测量

### 教材修正版

- 相关器：`src/issue_03_textbook_correction.py:364`
- 码环更新：`src/issue_03_textbook_correction.py:403`
- 载波环更新：`src/issue_03_textbook_correction.py:415`
- 跟踪主循环：`src/issue_03_textbook_correction.py:477`
- 观测形成：`src/issue_03_textbook_correction.py:454`

教材修正版不是换了一套陌生算法，而是把原有结构按教材对象边界拆干净。

## 3. 当前图集的用途

- `textbook_receiver_chain` 用来表示教材金标准
- `legacy_receiver_chain` 用来说明原始实现具体偏离在哪里
- `corrected_receiver_chain` 用来说明当前修正到底改到了什么位置
- `textbook_dll_loop` 和 `textbook_carrier_loop` 用来单独解释前端控制环
- `observable_formation_chain` 用来单独解释自然测量量到标准观测的合法过渡

这套图现在可以直接用于周报、汇报或后续 Issue 04 的接口讨论，不再依赖那张三栏拼图。
