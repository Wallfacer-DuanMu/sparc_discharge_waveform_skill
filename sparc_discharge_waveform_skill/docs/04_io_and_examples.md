# 04 输入输出规范与案例

本文件定义本 Skill 的最小输入、阶段输出和示例任务。目标不是建立复杂工程数据库，而是让 `03_workflows.md` 中的三阶段工作流有统一的数据口径：同一份配置可以被拆分为 Breakdown、Ramp-up、Flat-top 三个工作包，每个工作包输出的末态又作为下一阶段的初态。

---

## 1. 输入输出总览

```text
输入配置 config.yaml
  ├─ device: SPARC 简化装置参数
  ├─ timeline: 三阶段时间边界
  ├─ target: 目标 Ip 与目标位形
  ├─ coils: 线圈电流、变化率、伏秒约束
  └─ options: 平滑、采样、输出控制

阶段计算
  ├─ stage_1_breakdown
  ├─ stage_2_rampup
  └─ stage_3_flattop

输出结果 outputs/
  ├─ waveforms.csv / waveforms.json
  ├─ stage_summary.md
  ├─ validation_report.md
  └─ revision_suggestions.md
```

本项目默认输出等效线圈组波形：`CS1/CS2/CS3`、`PF1/PF2/PF3/PF4`、`Div1/Div2`、`VS`、`TF`。其中 `VS` 只输出基准和裕度，`TF` 只输出背景磁场说明。

---

## 2. 输入配置结构

### 2.1 顶层结构

```yaml
case_name: sparc_demo_discharge

device:
  name: SPARC_simplified
  B0_T: 12.2
  R0_m: 1.85
  a_m: 0.57

timeline:
  t_start_s: 0.0
  breakdown_end_s: 0.08
  rampup_end_s: 1.20
  flattop_end_s: 3.20
  dt_s: 0.02

target:
  Ip_seed_MA: 0.15
  Ip_flat_MA: 8.7
  shape:
    R_axis_m: 1.85
    minor_radius_m: 0.57
    kappa_flat: 1.9
    delta_flat: 0.45
    x_point: lower_single_null

coils:
  CS1: {I0_MA: 5.0, I_min_MA: -8.0, I_max_MA: 8.0, dI_dt_max_MA_per_s: 12.0}
  CS2: {I0_MA: 6.0, I_min_MA: -9.0, I_max_MA: 9.0, dI_dt_max_MA_per_s: 14.0}
  CS3: {I0_MA: 5.0, I_min_MA: -8.0, I_max_MA: 8.0, dI_dt_max_MA_per_s: 12.0}
  PF1: {I0_MA: 0.2, I_min_MA: -5.0, I_max_MA: 5.0, dI_dt_max_MA_per_s: 6.0}
  PF2: {I0_MA: 0.3, I_min_MA: -5.0, I_max_MA: 5.0, dI_dt_max_MA_per_s: 6.0}
  PF3: {I0_MA: -0.4, I_min_MA: -6.0, I_max_MA: 6.0, dI_dt_max_MA_per_s: 7.0}
  PF4: {I0_MA: -0.6, I_min_MA: -7.0, I_max_MA: 7.0, dI_dt_max_MA_per_s: 8.0}
  Div1: {I0_MA: 0.0, I_min_MA: -1.5, I_max_MA: 1.5, dI_dt_max_MA_per_s: 2.0}
  Div2: {I0_MA: 0.0, I_min_MA: -1.5, I_max_MA: 1.5, dI_dt_max_MA_per_s: 2.0}
  VS: {I0_MA: 0.0, I_min_MA: -1.0, I_max_MA: 1.0, reserved_fraction: 0.7}

constraints:
  cs_flux_budget_Vs: 35.0
  breakdown_loop_voltage_V: 20.0
  min_cs_flux_margin_fraction: 0.15
  max_pf_asymmetry_fraction: 0.10

options:
  waveform_style: smooth_piecewise_linear
  output_format: [csv, json, markdown]
  make_plots: true
```

### 2.2 字段含义

| 字段 | 含义 | 使用阶段 |
|---|---|---|
| `device.B0_T` | 固定环向背景场 | 全阶段，只作为背景 |
| `timeline.breakdown_end_s` | 击穿结束时间 | Breakdown 终点，Ramp-up 初点 |
| `timeline.rampup_end_s` | 爬升结束时间 | Ramp-up 终点，Flat-top 初点 |
| `timeline.flattop_end_s` | 平顶结束时间 | Flat-top 终点 |
| `target.Ip_seed_MA` | 击穿后种子电流 | Breakdown 输出目标，Ramp-up 初值 |
| `target.Ip_flat_MA` | 平顶目标电流 | Ramp-up 终点和平顶目标 |
| `target.shape` | 目标位形参数 | Ramp-up 演化，Flat-top 维持 |
| `coils.*.I0_MA` | 阶段起始或全局初始电流 | 各阶段初始条件 |
| `coils.*.I_min/I_max` | 电流限幅 | 全阶段约束检查 |
| `coils.*.dI_dt_max` | 变化率限幅 | 全阶段约束检查 |
| `constraints.cs_flux_budget_Vs` | CS 可用伏秒预算 | 全阶段 CS 检查 |
| `constraints.max_pf_asymmetry_fraction` | PF 上下差分上限 | Ramp-up 后段与 Flat-top |

---

## 3. 阶段输入与输出

### 3.1 Breakdown 输入输出

输入重点：

- `device.B0_T`；
- `target.Ip_seed_MA`；
- `constraints.breakdown_loop_voltage_V`；
- `CS1/CS2/CS3` 初始预充磁电流与变化率上限；
- `PF3/PF4` 击穿零场预置，`PF1/PF2` 小修正。

输出重点：

| 输出 | 说明 |
|---|---|
| `Ip_at_breakdown_end_MA` | 击穿结束时的种子电流估计 |
| `CS_current_at_breakdown_end` | 三组 CS 的阶段末态 |
| `PF_null_preset` | PF1-4 的击穿预置电流 |
| `breakdown_checks` | loop voltage、零场、限幅和变化率检查 |

Breakdown 的输出末态必须成为 Ramp-up 的输入初态。

### 3.2 Ramp-up 输入输出

输入重点：

- Breakdown 输出的 `Ip_seed` 与各线圈末态；
- `target.Ip_flat_MA`；
- `target.shape` 中的 `R/a/κ/δ/X-point`；
- CS 伏秒预算剩余量；
- PF1-4 电流和变化率限制。

输出重点：

| 输出 | 说明 |
|---|---|
| `Ip_at_rampup_end_MA` | 爬升结束时的平顶电流 |
| `CS_current_at_rampup_end` | CS 进入平顶前的电流状态 |
| `PF_shape_currents` | PF1-4 对应目标位形的工作点 |
| `Div_transition` | Div1/Div2 是否已缓慢接近平顶值 |
| `rampup_checks` | Ip 跟踪、PF 平滑、限幅、伏秒余量检查 |

Ramp-up 的输出末态必须成为 Flat-top 的输入初态。

### 3.3 Flat-top 输入输出

输入重点：

- Ramp-up 输出的 `Ip_flat` 与各线圈末态；
- 目标平顶持续时间；
- 目标边界、X 点和偏滤器构型；
- CS 剩余伏秒；
- VS 预留裕度。

输出重点：

| 输出 | 说明 |
|---|---|
| `flat_top_hold` | 平顶阶段 `Ip` 和 PF 工作点保持结果 |
| `CS_flux_margin` | 平顶结束时剩余伏秒比例 |
| `Div_strike_point_setting` | Div 平顶设定值或小幅扫描说明 |
| `VS_reserved_range` | VS 反馈可用范围 |
| `flattop_checks` | 平顶维持、X 点、打击点、剩余伏秒和裕度检查 |

---

## 4. 统一波形输出格式

### 4.1 表格输出

推荐输出 `waveforms.csv`，每一行对应一个采样时刻：

| column | meaning |
|---|---|
| `time_s` | 时间 |
| `stage` | `breakdown` / `rampup` / `flattop` |
| `Ip_MA` | 目标或估计等离子体电流 |
| `I_CS1_MA` / `I_CS2_MA` / `I_CS3_MA` | CS 等效线圈组电流 |
| `I_PF1_MA` / `I_PF2_MA` / `I_PF3_MA` / `I_PF4_MA` | PF 等效线圈组电流 |
| `I_Div1_MA` / `I_Div2_MA` | Div 简化电流 |
| `I_VS_bias_MA` | VS 离线基准值 |
| `B0_T` | TF 提供的背景环向磁场 |
| `note` | 关键事件说明 |

### 4.2 报告输出

推荐输出三个 Markdown 报告：

1. `stage_summary.md`：三阶段关键状态、阶段交接点和主要波形趋势；
2. `validation_report.md`：电流限幅、变化率、伏秒、零场、位形趋势、VS 裕度检查；
3. `revision_suggestions.md`：若不满足约束，给出降低爬升斜率、延长 ramp-up、调整 PF 预置等建议。

---

## 5. 示例任务：从一个假定输入走完整三阶段

### 5.1 示例目标

假定目标为：

- `B0 = 12.2 T` 固定；
- `Ip` 在击穿后达到 `0.15 MA` 种子电流；
- `Ip` 在 `1.20 s` 前爬升到 `8.7 MA`；
- `1.20-3.20 s` 维持平顶；
- 平顶位形为 `R0 = 1.85 m`、`a = 0.57 m`、`κ = 1.9`、`δ = 0.45`、下单零位形。

### 5.2 示例数据传递

```text
配置输入
  → Breakdown 使用 CS 预充磁 + PF3/PF4 零场预置
  → 输出 Ip_seed = 0.15 MA 和 t = 0.08 s 的线圈状态
  → Ramp-up 从该状态继续，CS 按 Ip 斜率消耗伏秒，PF1-4 逐步成形
  → 输出 Ip_flat = 8.7 MA 和 t = 1.20 s 的平顶工作点
  → Flat-top 从该工作点继续，CS 慢变，PF 近似保持，Div 微调打击点，VS 留裕度
  → 输出完整 waveforms.csv 与 validation_report.md
```

### 5.3 示例输出片段

数值仅表示格式和趋势，不代表最终工程定型。

| time_s | stage | Ip_MA | I_CS1_MA | I_CS2_MA | I_CS3_MA | I_PF1_MA | I_PF2_MA | I_PF3_MA | I_PF4_MA | I_Div1_MA | I_Div2_MA | note |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 0.00 | breakdown | 0.00 | 5.00 | 6.00 | 5.00 | 0.20 | 0.30 | -0.40 | -0.60 | 0.00 | 0.00 | pre-magnetized |
| 0.08 | breakdown | 0.15 | 4.20 | 5.05 | 4.20 | 0.25 | 0.35 | -0.55 | -0.85 | 0.00 | 0.00 | seed plasma formed |
| 0.60 | rampup | 4.20 | 0.80 | 1.10 | 0.80 | 1.20 | 1.55 | -2.10 | -3.00 | 0.10 | 0.10 | current and shape ramp |
| 1.20 | rampup | 8.70 | -2.20 | -2.80 | -2.20 | 2.10 | 2.70 | -3.80 | -4.60 | 0.35 | 0.35 | flat-top entry |
| 3.20 | flattop | 8.70 | -2.60 | -3.20 | -2.60 | 2.15 | 2.75 | -3.85 | -4.65 | 0.40 | 0.30 | hold with margin |

---

## 6. 最小验收标准

一次完整运行至少应给出：

1. 一份输入配置；
2. 一个覆盖三阶段的 `waveforms.csv` 或等价表格；
3. 三个阶段的交接状态：`t_breakdown_end`、`t_rampup_end`、`t_flattop_end`；
4. CS 伏秒、电流限幅、变化率、PF 位形趋势、Div/VS 简化处理说明；
5. 当检查不通过时，给出可执行修正建议。

只要以上内容自洽，即可满足本学生作业的目标：完整展示“目标放电结果 → 三阶段拆解 → 线圈波形 → 约束检查 → 修正建议”的推演链路。
