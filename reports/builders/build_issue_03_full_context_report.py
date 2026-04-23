from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ISSUE01_ROOT = ROOT / "archive" / "research" / "corrections" / "issue_01_truth_dependency"
ISSUE03_ROOT = ROOT / "archive" / "research" / "corrections" / "issue_03_textbook_full_correction"

ISSUE01_COMPARISON_DIR = ISSUE01_ROOT / "comparison"
ISSUE01_CROSS_DIR = ISSUE01_ROOT / "corrected_fullstack" / "cross_frequency"
ISSUE03_COMPARISON_DIR = ISSUE03_ROOT / "comparison"
ISSUE03_CROSS_DIR = ISSUE03_ROOT / "corrected_fullstack" / "cross_frequency"
LEGACY_CROSS_DIR = ROOT / "archive" / "results" / "canonical" / "results_ka_multifreq" / "cross_frequency"

OUTPUT_MD = ISSUE03_ROOT / "weekly_report_issue_03_textbook_full_context.md"
OUTPUT_DOCX = ISSUE03_ROOT / "weekly_report_issue_03_textbook_full_context.docx"

REPRESENTATIVE_FREQUENCIES_HZ = (19.0e9, 22.5e9, 25.0e9, 31.0e9)
KEY_METRICS = [
    "single_tau_rmse_ns",
    "single_fd_rmse_hz",
    "wls_case_b_wls_position_error_3d_m",
    "ekf_pr_doppler_mean_position_error_3d_m",
    "ekf_pr_doppler_mean_velocity_error_3d_mps",
]
METRIC_LABELS = {
    "single_tau_rmse_ns": "单通道码时延均方根误差（纳秒）",
    "single_fd_rmse_hz": "单通道频偏均方根误差（赫兹）",
    "wls_case_b_wls_position_error_3d_m": "困难场景单历元定位三维误差（米）",
    "ekf_pr_doppler_mean_position_error_3d_m": "伪距加距离率联合动态定位平均位置误差（米）",
    "ekf_pr_doppler_mean_velocity_error_3d_mps": "伪距加距离率联合动态定位平均速度误差（米每秒）",
}


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _fmt(value: float, digits: int = 3) -> str:
    if abs(value) >= 1000:
        return f"{value:,.{digits}f}"
    return f"{value:.{digits}f}"


def _freq_label(fc_hz: float) -> str:
    return f"{fc_hz / 1e9:.1f} 吉赫"


def _find_row(rows: list[dict], fc_hz: float) -> dict:
    return next(item for item in rows if abs(float(item["frequency_hz"]) - fc_hz) < 1.0)


def _build_stage_table() -> str:
    lines = [
        "| 阶段 | 核心目标 | 主要动作 | 产出性质 |",
        "| --- | --- | --- | --- |",
        "| 专题一 | 去除运行时真值依赖 | 切断真值辅助对跟踪和导航初始化的直接影响 | 恢复系统独立性 |",
        "| 专题二 | 审查链路是否合法 | 审查各层对象、内部变换和下游接口资格 | 恢复解释资格 |",
        "| 专题三 | 按教材重建分层 | 重建信号层、接收机层、观测形成层和导航层接口 | 恢复教材一致性 |",
    ]
    return "\n".join(lines)


def _build_issue01_delta_table(diff_summary: dict) -> str:
    metrics = diff_summary["metrics"]
    lines = [
        "| 指标 | 平均增量 | 中位增量 | 最小增量 | 最大增量 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name in KEY_METRICS:
        stats = metrics[name]
        lines.append(
            "| "
            + " | ".join(
                [
                    METRIC_LABELS[name],
                    _fmt(float(stats["mean_delta"])),
                    _fmt(float(stats["median_delta"])),
                    _fmt(float(stats["min_delta"])),
                    _fmt(float(stats["max_delta"])),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _build_issue03_delta_table(three_way: dict) -> str:
    metrics = three_way["metrics"]
    lines = [
        "| 指标 | 去真值后相对原始实现 | 教材修正后相对去真值版本 | 教材修正后相对原始实现 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name in KEY_METRICS:
        stats = metrics[name]
        lines.append(
            "| "
            + " | ".join(
                [
                    METRIC_LABELS[name],
                    _fmt(float(stats["mean_delta_issue01_vs_legacy"])),
                    _fmt(float(stats["mean_delta_issue03_vs_issue01"])),
                    _fmt(float(stats["mean_delta_issue03_vs_legacy"])),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _build_representative_single_table(
    legacy_rows: list[dict],
    issue01_rows: list[dict],
    issue03_rows: list[dict],
) -> str:
    lines = [
        "| 频点 | 原始实现码时延误差 | 去真值后码时延误差 | 教材修正后码时延误差 | 原始实现频偏误差 | 去真值后频偏误差 | 教材修正后频偏误差 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for fc_hz in REPRESENTATIVE_FREQUENCIES_HZ:
        legacy_row = _find_row(legacy_rows, fc_hz)
        issue01_row = _find_row(issue01_rows, fc_hz)
        issue03_row = _find_row(issue03_rows, fc_hz)
        lines.append(
            "| "
            + " | ".join(
                [
                    _freq_label(fc_hz),
                    _fmt(float(legacy_row["single_tau_rmse_ns"])),
                    _fmt(float(issue01_row["single_tau_rmse_ns"])),
                    _fmt(float(issue03_row["single_tau_rmse_ns"])),
                    _fmt(float(legacy_row["single_fd_rmse_hz"])),
                    _fmt(float(issue01_row["single_fd_rmse_hz"])),
                    _fmt(float(issue03_row["single_fd_rmse_hz"])),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _build_representative_navigation_table(
    legacy_rows: list[dict],
    issue01_rows: list[dict],
    issue03_rows: list[dict],
) -> str:
    lines = [
        "| 频点 | 原始实现单历元定位误差 | 去真值后单历元定位误差 | 教材修正后单历元定位误差 | 原始实现动态位置误差 | 去真值后动态位置误差 | 教材修正后动态位置误差 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for fc_hz in REPRESENTATIVE_FREQUENCIES_HZ:
        legacy_row = _find_row(legacy_rows, fc_hz)
        issue01_row = _find_row(issue01_rows, fc_hz)
        issue03_row = _find_row(issue03_rows, fc_hz)
        lines.append(
            "| "
            + " | ".join(
                [
                    _freq_label(fc_hz),
                    _fmt(float(legacy_row["wls_case_b_wls_position_error_3d_m"])),
                    _fmt(float(issue01_row["wls_case_b_wls_position_error_3d_m"])),
                    _fmt(float(issue03_row["wls_case_b_wls_position_error_3d_m"])),
                    _fmt(float(legacy_row["ekf_pr_doppler_mean_position_error_3d_m"])),
                    _fmt(float(issue01_row["ekf_pr_doppler_mean_position_error_3d_m"])),
                    _fmt(float(issue03_row["ekf_pr_doppler_mean_position_error_3d_m"])),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _build_representative_delta_table(
    issue01_rows: list[dict],
    issue03_rows: list[dict],
) -> str:
    lines = [
        "| 频点 | 码时延误差增量 | 频偏误差增量 | 单历元定位误差增量 | 动态位置误差增量 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for fc_hz in REPRESENTATIVE_FREQUENCIES_HZ:
        issue01_row = _find_row(issue01_rows, fc_hz)
        issue03_row = _find_row(issue03_rows, fc_hz)
        lines.append(
            "| "
            + " | ".join(
                [
                    _freq_label(fc_hz),
                    _fmt(float(issue03_row["single_tau_rmse_ns"]) - float(issue01_row["single_tau_rmse_ns"])),
                    _fmt(float(issue03_row["single_fd_rmse_hz"]) - float(issue01_row["single_fd_rmse_hz"])),
                    _fmt(
                        float(issue03_row["wls_case_b_wls_position_error_3d_m"])
                        - float(issue01_row["wls_case_b_wls_position_error_3d_m"])
                    ),
                    _fmt(
                        float(issue03_row["ekf_pr_doppler_mean_position_error_3d_m"])
                        - float(issue01_row["ekf_pr_doppler_mean_position_error_3d_m"])
                    ),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _build_problem_impact_table(three_way: dict) -> str:
    metrics = three_way["metrics"]
    tau_i01 = metrics["single_tau_rmse_ns"]["mean_delta_issue01_vs_legacy"]
    wls_i01 = metrics["wls_case_b_wls_position_error_3d_m"]["mean_delta_issue01_vs_legacy"]
    tau_i03 = metrics["single_tau_rmse_ns"]["mean_delta_issue03_vs_issue01"]
    fd_i03 = metrics["single_fd_rmse_hz"]["mean_delta_issue03_vs_issue01"]
    wls_i03 = metrics["wls_case_b_wls_position_error_3d_m"]["mean_delta_issue03_vs_issue01"]
    ekf_pos_i03 = metrics["ekf_pr_doppler_mean_position_error_3d_m"]["mean_delta_issue03_vs_issue01"]
    ekf_vel_i03 = metrics["ekf_pr_doppler_mean_velocity_error_3d_mps"]["mean_delta_issue03_vs_issue01"]
    lines = [
        "| 问题项 | 教材要求 | 发生修正的阶段 | 关键指标变化 | 直接影响 |",
        "| --- | --- | --- | --- | --- |",
        (
            "| 运行时真值注入 | 环路只能由观测和内部状态驱动 | 专题一 | "
            f"码时延平均增量 = {_fmt(tau_i01)}，单历元定位平均增量 = {_fmt(wls_i01)} | "
            "去掉真值稳定以后，低频脆弱区被真实暴露出来。 |"
        ),
        (
            "| 信号层没有真实包含导航数据 | 含数据的信号必须真的带有数据调制 | 专题三 | "
            f"码时延平均增量 = {_fmt(tau_i03)}，频偏平均增量 = {_fmt(fd_i03)} | "
            "加入真实数据调制后，前端开始面对真正的数据符号干扰。 |"
        ),
        (
            "| 自然测量量与标准观测量混层 | 标准观测量必须经过独立观测形成层 | 专题三 | "
            f"单历元定位平均增量 = {_fmt(wls_i03)}，动态位置平均增量 = {_fmt(ekf_pos_i03)} | "
            "导航层只消费标准观测量以后，接口资格恢复，误差传播也更诚实。 |"
        ),
        (
            "| 环路结构只有整体控制律 | 判别器、滤波器和数控振荡器应分开建模 | 专题三 | "
            f"频偏平均增量 = {_fmt(fd_i03)}，动态速度平均增量 = {_fmt(ekf_vel_i03)} | "
            "结构化以后，前端和动态层之间的耦合关系可以被单独解释。 |"
        ),
    ]
    return "\n".join(lines)


def build_report_markdown() -> str:
    issue01_diff_summary = _load_json(ISSUE01_COMPARISON_DIR / "issue_01_diff_summary.json")
    issue03_three_way = _load_json(ISSUE03_COMPARISON_DIR / "legacy_vs_issue01_vs_issue03.json")
    legacy_rows = _load_json(LEGACY_CROSS_DIR / "combined_metrics.json")
    issue01_rows = _load_json(ISSUE01_CROSS_DIR / "combined_metrics.json")
    issue03_rows = _load_json(ISSUE03_CROSS_DIR / "combined_metrics.json")

    generated_at = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    total_frequencies = len(issue03_rows)
    stage_table = _build_stage_table()
    issue01_table = _build_issue01_delta_table(issue01_diff_summary)
    issue03_table = _build_issue03_delta_table(issue03_three_way)
    single_table = _build_representative_single_table(legacy_rows, issue01_rows, issue03_rows)
    navigation_table = _build_representative_navigation_table(legacy_rows, issue01_rows, issue03_rows)
    delta_table = _build_representative_delta_table(issue01_rows, issue03_rows)
    impact_table = _build_problem_impact_table(issue03_three_way)

    sections = [
        f"""# 周报：教材金标准下的链路修正与结果汇总

生成时间：{generated_at}""",
        f"""## 一、汇报范围

本报告把最近三步工作合并成一条连续叙事：

1. 专题一：去除运行时真值依赖，恢复系统独立性。
2. 专题二：以教材为金标准，审查各层对象和内部变换是否合法。
3. 专题三：按教材分层重建信号层、接收机层、观测形成层和导航层接口，并重跑全频全链路。

当前结果覆盖 {total_frequencies} 个频点，频率范围为 19.0 吉赫到 31.0 吉赫。本报告重点回答三件事：

- 原始实现为什么不合法或不标准。
- 修正以后每一类问题具体造成了什么影响。
- 哪些变化是教材约束恢复以后暴露出的真实性能。""",
        f"""## 二、问题背景与三步演进

### 2.1 原始实现中的核心问题

原始实现并不是完全错误，而是存在几类会破坏解释资格的问题：

1. 运行时真值直接进入环路和导航初始化，改变了系统行为。
2. 导航数据开关停留在配置层，没有真实进入信号对象。
3. 接收机内部状态过早被命名成标准观测量。
4. 环路更新主要以整体控制律表达，缺少教材意义上的分层结构。

这些问题共同造成一个结果：程序虽然可以运行，但很难清楚回答“这一层为什么可以这样算”，也很难明确某个量究竟属于自然测量量、标准观测量，还是已经带有导航层含义。

### 2.2 三步工作的角色分工

{stage_table}""",
        """## 三、教材金标准下的对象边界

### 3.1 全链路对象图

```
发射信号
  -> 传播印记
  -> 接收复信号块
  -> 捕获初值
  -> 跟踪环路
  -> 自然测量量
  -> 标准观测量
  -> 导航解算
```

这条链是合法性审查和教材修正的共同基础。最关键的边界有三条：

1. 接收机层的终点是自然测量量。
2. 观测形成层才第一次产出标准观测量。
3. 导航解算层只能消费标准观测量，不能越层直接消费环路内部状态。""",
        r"""### 3.2 信号层与接收机层为什么要这样分开

在教材口径下，接收信号可以简化写成：

$$
r(t)=A(t)\,d_k\,c(t-\tau_g)\exp\{j[2\pi(f_c+f_D)t+\phi_p(t)]\}+n(t)
$$

式中各项的物理意义如下：

| 组成 | 含义 |
| --- | --- |
| 幅度项 | 传播过程带来的强度变化 |
| 数据符号项 | 导航数据调制引入的符号变化 |
| 扩频码项 | 延迟后的码信号 |
| 相位项 | 载波频率、频偏和传播相位共同作用 |
| 噪声项 | 接收端噪声与扰动 |

接收机随后不是直接“算伪距”，而是先做同步控制与状态恢复：

$$
\Lambda(\tau,f)=\left|\sum r(t)\,c(t-\tau)\,\exp(-j2\pi f t)\right|^2
$$

$$
D_1=\frac{|E|-|L|}{|E|+|L|}, \qquad
D_2=\operatorname{atan2}(Q_P,\ |I_P|)
$$

因此，接收机层的合法输出首先应当是下面这些中文对象，而不是一开始就命名成标准伪距或标准多普勒：

| 中文对象 | 含义 | 所属层 |
| --- | --- | --- |
| 码时延估计 | 接收机恢复出的复制码时间状态 | 接收机层 |
| 载波相位累计量 | 接收机恢复出的复制载波相位状态 | 接收机层 |
| 载波频率估计 | 接收机恢复出的复制载波频率状态 | 接收机层 |
| 锁定质量指标 | 用于描述当前锁定状态的辅助指标 | 接收机层 |

这里的第一判别量对应码环误差，第二判别量对应载波环误差。""",
        r"""### 3.3 为什么必须有独立的观测形成层

标准观测方程应当保持为：

$$
\rho = \|r_s-r\| + c(\delta t_r-\delta t_s) + d_1 + d_2 + d_3 + \varepsilon_\rho
$$

$$ 
\dot{\rho} = u^T(v_s-v_r) + c(\dot{\delta t}_r-\dot{\delta t}_s) + \varepsilon_{\dot{\rho}}
$$

其中：

| 项 | 含义 |
| --- | --- |
| 第一项 | 几何距离 |
| 第二项 | 接收机与卫星钟差项 |
| 第三至第五项 | 传播、色散和硬件等非几何项 |
| 最后一项 | 观测噪声 |

从接收机内部状态过渡到标准观测量时，需要经过下面这道明确的转换：

```
自然测量量
  -> 时间标记解释
  -> 波长换算
  -> 符号约定统一
  -> 标准观测量
```

只要这道转换被省略，导航层就会把“内部复制状态”和“正式观测量”混在一起，后续方程即使看起来标准，也缺少对象语义上的解释资格。""",
        f"""## 四、专题一：去除运行时真值依赖

专题一的目标很明确：不再让真值直接参与系统运行机制。具体去掉的内容包括：

1. 单通道跟踪中的码环真值辅助速率。
2. 单通道跟踪中的载波环真值辅助速率。
3. 单历元定位中由真值位置和钟差派生的默认初值。
4. 动态滤波上游逐历元初始化中的真值热启动。

真值仍然保留在两个位置：

1. 仿真观测生成。
2. 解后误差评估和结果对比。

### 4.1 去真值后的差分摘要

{issue01_table}

### 4.2 这一步的真正意义

专题一不是为了让数字更好看，而是为了恢复系统独立性。去掉真值稳定以后，低频段的前端脆弱区立即暴露出来，说明原始实现并不是完全依靠模型和观测自行工作，而是曾经被真值动态稳定过。

![专题一：去真值后的差分图](archive/research/corrections/issue_01_truth_dependency/comparison/issue_01_diff_plots.png)""",
        """## 五、专题二：合法性审查结论

专题二不改代码，而是回答三个更基础的问题：

1. 这一层接收什么对象。
2. 这一层内部为什么可以这样变换。
3. 这一层产出的对象为什么有资格进入下一层。

审查结果可以压缩成下表：""",
        """| 层 | 审查结论 | 原始状态 | 教材修正方向 |
| --- | --- | --- | --- |
| 信号层 | 必须区分发射信号、传播后接收信号、本地复制信号和相关器输入块 | 导航数据只停留在配置层，没有真实进入信号 | 让数据调制真实进入接收信号对象 |
| 接收机层 | 捕获、相关、码环、载波环都属于同步控制与内部状态恢复 | 前半段结构基本成立，但自然测量量和标准观测量越层混用 | 接收机层只输出自然测量量 |
| 观测形成层 | 必须独立把自然测量量组织成标准观测量 | 伪距和距离率命名过早，接口资格不清楚 | 新增独立的标准观测形成层 |
| 导航层 | 单历元定位和动态滤波的合法性取决于上游观测语义是否成立 | 方程形式基本标准，但消费对象语义混杂 | 只消费标准观测量接口 |""",
        """专题二最重要的结论不是“哪里写得不好看”，而是：当前问题不是简单命名问题，而是对象边界、变换合法性和下游资格的问题。""",
        """## 六、专题三：教材分层修正

专题三在无真值依赖的边界上，正式落地了教材分层：

1. 信号对象真实包含导航数据调制。
2. 接收机层只输出自然测量量。
3. 观测形成层独立生成标准伪距、载波相位和距离率。
4. 单历元定位和动态滤波只消费标准观测量。

### 6.1 修正内容落点

- 前端信号与跟踪修正模块：负责真实信号对象和环路结构化表达。
- 单历元定位修正模块：负责只消费标准观测量的定位求解。
- 动态滤波修正模块：负责只消费标准观测量的动态状态估计。
- 周报生成模块：负责汇总三步工作的前因后果和对比结果。

### 6.2 结果链条中的关键图

![专题三：单通道跨频概览图](archive/research/corrections/issue_03_textbook_full_correction/corrected_fullstack/single_channel/wkb_multifreq_overview.png)

![专题三：22.5 吉赫单历元定位观测形成图](archive/research/corrections/issue_03_textbook_full_correction/corrected_fullstack/wls/22p5GHz/pseudorange_formation.png)

![专题三：22.5 吉赫动态滤波观测形成概览图](archive/research/corrections/issue_03_textbook_full_correction/corrected_fullstack/ekf/22p5GHz/observation_formation_overview.png)""",
        f"""## 七、三方结果对比

专题三以后，结果比较必须采用三方口径：

1. 从原始实现到去真值版本：看去真值依赖本身的影响。
2. 从去真值版本到教材修正版：看教材分层修正本身的影响。
3. 从原始实现到教材修正版：看总的变化幅度。

### 7.1 三方均值增量

{issue03_table}

这张表说明了三件事：

1. 去真值以后，低频脆弱区已经暴露。
2. 在此基础上继续恢复教材边界，许多原来被混层掩盖的问题会进一步放大。
3. 这种变差不能简单理解为“系统被做坏了”，而应理解为“教材约束恢复以后，真实性能被更诚实地暴露出来了”。

![三方结果对比图](archive/research/corrections/issue_03_textbook_full_correction/comparison/plots.png)""",
        f"""### 7.2 代表频点的前端对比

{single_table}

### 7.3 代表频点的导航层对比

{navigation_table}

### 7.4 教材修正后相对去真值版本的代表频点增量

{delta_table}

这些表格说明了两个特别重要的现象：

1. 在 19.0 吉赫上，教材修正版在前端误差和单历元定位上相对去真值版本有局部改善，但动态位置误差仍显著放大，说明下游动态链条会继续放大前端残余问题。
2. 在 25.0 吉赫和 31.0 吉赫上，去真值版本曾经表现较好，但教材修正版加入真实数据调制、正式观测形成和结构化环路以后，前端难度显著上升，原先看似稳定的区间也暴露出明显不足。""",
        f"""## 八、每一类不合法项的具体影响

本节把“问题项、教材要求、修正阶段、指标变化、直接影响”统一放在一张矩阵里：

{impact_table}

这张矩阵的意义在于：不再只说“指标变差了”，而是把每一类不合法项原来具体掩盖了什么问题说清楚。""",
        """## 九、综合结论

三步工作合起来以后，结论已经比较清楚：

1. 专题一证明，原始实现的一部分稳定性来自运行时真值依赖，而不是系统独立能力。
2. 专题二证明，问题不只是参数没调好，而是对象边界、变换合法性和接口资格本身存在混层。
3. 专题三把教材金标准真正落到代码路径以后，单通道、观测形成和导航层的困难都变得更可解释，但也更严苛。

因此，当前教材修正版虽然在不少指标上明显劣于原始实现，结论口径仍然应当是：

教材修正版不是把系统做坏了，而是第一次把系统放回了教材允许解释、允许继续严肃优化的对象框架里。""",
        """## 十、下一步

后续工作不应再回到原始实现的混层接口，而应围绕当前教材修正版继续做两类事情：

1. 在教材边界内继续优化环路设计，特别是含导航数据信号条件下的载波环和码环参数、切换策略与稳定域。
2. 强化标准观测量进入单历元定位和动态滤波之后的鲁棒处理，避免前端误差被下游动态模型过度放大。""",
        """## 十一、相关产物说明

本次周报已经同步更新了：

1. 中文化主稿。
2. 中文化的可编辑周报文档。
3. 对比图、观测形成图和跨频概览图的汇报引用。""",
    ]
    return "\n\n".join(sections) + "\n"


def ensure_pandoc() -> None:
    if shutil.which("pandoc") is not None:
        return
    raise SystemExit("pandoc 未安装。请先执行: brew install pandoc")


def write_markdown() -> None:
    OUTPUT_MD.write_text(build_report_markdown(), encoding="utf-8")


def render_docx() -> None:
    ensure_pandoc()
    subprocess.run(
        [
            "pandoc",
            str(OUTPUT_MD),
            "-o",
            str(OUTPUT_DOCX),
            "--from=markdown+tex_math_dollars",
            "--resource-path",
            f"{ROOT}{os.pathsep}{ISSUE03_ROOT}",
            "--toc",
        ],
        cwd=ROOT,
        check=True,
    )


def main() -> None:
    write_markdown()
    render_docx()
    print(f"markdown: {OUTPUT_MD}")
    print(f"docx: {OUTPUT_DOCX}")


if __name__ == "__main__":
    main()
