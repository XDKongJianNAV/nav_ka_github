# 00 审查方法

## 1. 审查标准

本轮以教材为金标准，先于代码建立对象定义，再审查代码中的内部变换是否合法。

基准材料：

- `src/gnss_signal_tracking_textbook_model.py`
- `docs/gnss_book_ai/`
- `corrections/issue_01_truth_dependency/` 下的修正版结果与周报

本轮不采用“结果看起来像对的”作为主要标准，而采用下面三问：

1. 这一层接收什么对象。
2. 这一层内部为什么可以这样变换。
3. 这一层产出的对象为什么有资格进入下一层。

## 2. 总链与对象分层

```text
signal source
  -> propagation-imprinted received signal
  -> acquisition/tracking receiver internals
  -> natural measurements
  -> standard navigation observables
  -> navigation estimators
```

对应到本仓库，重点文件是：

- `notebooks/nb_ka225_rx_from_real_wkb_debug.py`
- `notebooks/exp_multisat_wls_pvt_report.py`
- `notebooks/exp_dynamic_multisat_ekf_report.py`
- `src/issue_01_truth_dependency.py`

## 3. 变换类别

本轮把中间处理强制分到以下类别之一：

| 类别 | 含义 | 典型例子 |
| --- | --- | --- |
| 估计 | 由观测推断未知状态 | 捕获给出 `tau_hat_0`、`fd_hat_0` |
| 控制 | 用误差驱动内部状态收敛 | DLL/PLL/FLL 的 NCO 更新 |
| 补偿 | 显式去除已知影响 | 载波 wipeoff、钟差修正 |
| 同步 | 建立码、载波、时间对齐 | acquisition、tracking lock |
| 观测形成 | 将内部状态组织成标准导航观测 | `tau_est -> pseudorange` |

如果某一步混合了多种角色，也要明确指出“主角色是什么，副角色是什么”。

## 4. 合法性标签

| 标签 | 含义 |
| --- | --- |
| 合法 | 对象定义清楚，变换对应教材正式结构，输出资格明确 |
| 条件合法 | 结构本身合理，但依赖额外条件，例如已锁定、已统一符号约定、已明确时标 |
| 启发式近似 | 工程上可用，但不是教材中正式定义的完整形式 |
| 语义越层 | 这一层提前产出了下一层对象，或把内部状态直接改名为下游观测 |

## 5. Issue 01 结果如何进入本轮审查

`Issue 01` 不是本轮标准，而是本轮证据。

使用方式：

1. 先在教材和对象定义层判断某一步是否应当独立存在。
2. 再看 `Issue 01` 去真值依赖后，这一步的缺口是否在结果上暴露。
3. 用结果说明“这个问题不是文字游戏，而是会改变系统行为”。

## 6. 固定模板

后续每一层笔记都使用同一模板：

1. 本层对象定义
2. 本层合法变换
3. 当前代码映射
4. 合法性判断
5. 与 Issue 01 结果的联系
6. 对下游的接口资格

## 7. 本轮边界

- 本轮主产物是审查笔记，不是实现重构。
- 本轮允许引用当前工程里的工程化近似，但必须标明它只是近似。
- 本轮必须延伸到导航层，因为如果前端输出对象不清楚，WLS/EKF 的解释资格也会一起受损。
