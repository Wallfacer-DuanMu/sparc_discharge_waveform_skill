# 03 三阶段工作流

本文件描述 Breakdown、Ramp-up 与 Flat-top 三阶段的数据流转和阶段逻辑。它与 `04_io_and_examples.md` 配合使用：`04` 定义输入输出格式，本文件说明这些输入如何被逐阶段传导，最终生成完整的线圈电流波形和检查报告。

---

## 1. 总体工作流

本 Skill 的核心流程是：先用一份统一配置定义目标放电和装置约束，再把放电拆成三个连续阶段，每个阶段只解决本阶段最关键的问题。

```text
config.yaml
  → 读取 SPARC 简化装置、目标 Ip、目标位形、线圈约束
  → Stage 1: Breakdown
      生成 CS 击穿 swing 与 PF3/PF4 零场预置
  → Stage 2: Ramp-up
      从击穿末态继续，生成 Ip 爬升与 PF 成形波形
  → Stage 3: Flat-top
      从爬升末态继续，生成平顶维持、Div 微调与裕度检查
  → 输出 waveforms.csv、stage_summary.md、validation_report.md
```

三个阶段不是互相独立的三份结果，而是一条连续链路：

| 交接点 | 上一阶段输出 | 下一阶段输入 |
|---|---|---|
| `t = breakdown_end` | `Ip_seed`、CS 末态、PF 零场预置末态 | Ramp-up 初始 `Ip` 和线圈初值 |
| `t = rampup_end` | `Ip_flat`、CS 剩余伏秒、PF 平顶工作点、Div 过渡值 | Flat-top 初始工作点 |
| `t = flattop_end` | 完整波形、剩余裕度、风险提示 | 作为下一轮修正依据 |

---

## 2. 统一数据对象

各阶段共享同一组最小数据对象，避免每个阶段各说各话。

| 数据对象 | 内容 | 主要用途 |
|---|---|---|
| `device` | `B0/R0/a` 等 SPARC 简化参数 | 提供量级和背景约束 |
| `timeline` | 三阶段起止时间与采样步长 | 生成统一时间轴 |
| `target` | `Ip_seed/Ip_flat/R/a/κ/δ/X-point` | 定义阶段目标 |
| `coil_state` | 每个线圈组在某时刻的电流 | 阶段交接 |
| `coil_limits` | 电流上限、变化率上限、PF 差分上限 | 约束检查 |
| `cs_flux_state` | CS 已用伏秒、剩余伏秒、裕度 | 判断能否完成爬升和平顶 |
| `validation` | 各阶段检查结果 | 决定是否需要修正 |

其中 `coil_state` 是阶段传递的关键。每一阶段都从上一阶段末态开始，而不是重新假定线圈初值。

---

## 3. Stage 1：Breakdown 工作流

### 3.1 阶段目标

Breakdown 阶段解决的问题是：在固定 TF 背景场下，利用 CS 产生足够 loop voltage，并用 PF3/PF4 在击穿区附近建立低极向场区域，使气体形成初始等离子体和种子电流。

本阶段不追求最终位形，只要求初始等离子体能够形成并被捕获。

### 3.2 输入

来自 `04_io_and_examples.md` 的配置字段主要包括：

- `device.B0_T`：固定背景环向场；
- `timeline.t_start_s` 与 `timeline.breakdown_end_s`；
- `target.Ip_seed_MA`；
- `constraints.breakdown_loop_voltage_V`；
- `coils.CS1/CS2/CS3` 的初始预充磁电流、限幅和变化率；
- `coils.PF3/PF4` 的击穿零场预置能力；
- `coils.PF1/PF2` 的小修正能力。

### 3.3 计算逻辑

Breakdown 可按下面顺序执行：

1. **建立时间片**：生成 `t_start` 到 `breakdown_end` 的短时间轴。
2. **CS 击穿 swing**：根据目标击穿 loop voltage，估算 CS 需要的电流变化率，并分配到 `CS1/CS2/CS3`。
3. **PF 零场预置**：优先调整 `PF3/PF4`，使击穿区附近的 `B_R/B_Z` 趋于低值。
4. **PF 局部修正**：用 `PF1/PF2` 做小幅修正，避免初始磁场结构过差。
5. **生成种子电流**：把 `Ip` 从 0 平滑过渡到 `Ip_seed`，表示初始等离子体形成。
6. **检查约束**：检查 CS 电流、变化率、已用伏秒、PF 零场质量和波形连续性。

简化数据流为：

```text
Ip_seed + breakdown_loop_voltage
  → CS dI/dt
  → CS1/CS2/CS3 击穿波形

击穿区低 B_R/B_Z
  → PF3/PF4 预置
  → PF1/PF2 小修正
  → PF 零场检查
```

### 3.4 输出

本阶段输出：

| 输出 | 内容 |
|---|---|
| `breakdown_waveform` | `t_start` 到 `breakdown_end` 的 CS/PF/Ip 波形 |
| `Ip_seed_result` | 击穿结束时的估计种子电流 |
| `coil_state_at_breakdown_end` | 所有线圈组在击穿末端的电流 |
| `cs_flux_used_breakdown` | 击穿阶段已消耗伏秒 |
| `breakdown_validation` | loop voltage、零场、限幅、变化率、平滑性检查 |

如果检查不通过，优先修正顺序为：提高或重新分配 CS swing、延长击穿时间、调整 PF3/PF4 预置、减小不必要的 PF1/PF2 修正。

---

## 4. Stage 2：Ramp-up 工作流

### 4.1 阶段目标

Ramp-up 阶段解决的问题是：从 `Ip_seed` 平滑爬升到 `Ip_flat`，同时让等离子体从初始简单截面逐步过渡到目标平顶位形。

这一阶段采用两条弱耦合主线：

1. CS 电流驱动线：负责 `Ip` 上升和伏秒管理；
2. PF 位形控制线：负责主半径、边界、拉长比、三角形变和 X 点趋势。

### 4.2 输入

Ramp-up 的输入不是从零开始，而是接收 Breakdown 的末态：

- `Ip_at_breakdown_end`；
- `coil_state_at_breakdown_end`；
- `cs_flux_budget` 扣除击穿消耗后的剩余伏秒；
- `timeline.breakdown_end_s` 到 `timeline.rampup_end_s`；
- `target.Ip_flat_MA`；
- `target.shape` 中的 `R_axis_m/minor_radius_m/kappa_flat/delta_flat/x_point`；
- PF1-4 的限幅、变化率和允许差分约束。

### 4.3 计算逻辑

Ramp-up 可按下面顺序执行：

1. **生成 Ip 目标轨迹**：从 `Ip_seed` 平滑上升到 `Ip_flat`，避免阶跃。
2. **估算 loop voltage 需求**：根据 `Ip(t)` 的斜率估算所需感应电压。
3. **生成 CS 波形**：把 loop voltage 需求分配到 `CS1/CS2/CS3`，并更新伏秒消耗。
4. **生成位形目标轨迹**：令 `R/a/κ/δ/X-point` 从初始状态逐步接近平顶目标。
5. **生成 PF 波形**：
   - `PF4` 主要随 `Ip` 增大调整整体平衡和主半径；
   - `PF3` 参与径向/垂直平衡、X 点趋势和后段上下修正；
   - `PF1/PF2` 负责边界、拉长比、三角形变和 X 点形成；
   - `Div1/Div2` 只在 ramp-up 后段缓慢接近平顶设定。
6. **检查约束**：检查 CS 伏秒、电流限幅、变化率、PF 平滑性、位形演化趋势和 VS 裕度。

简化数据流为：

```text
Ip_seed → Ip_flat
  → Ip(t)
  → loop voltage(t)
  → CS1/CS2/CS3(t)
  → CS 伏秒检查

初始截面 → 目标 R/a/κ/δ/X-point
  → shape(t)
  → PF1/PF2/PF3/PF4(t)
  → 位形趋势与限幅检查
```

### 4.4 输出

本阶段输出：

| 输出 | 内容 |
|---|---|
| `rampup_waveform` | `breakdown_end` 到 `rampup_end` 的 Ip、CS、PF、Div 波形 |
| `Ip_flat_result` | 爬升结束时的等离子体电流 |
| `coil_state_at_rampup_end` | 平顶入口处各线圈工作点 |
| `cs_flux_used_rampup` | 爬升阶段伏秒消耗 |
| `shape_state_at_rampup_end` | 平顶入口位形目标状态 |
| `rampup_validation` | Ip 跟踪、伏秒余量、电流限幅、变化率和位形趋势检查 |

如果检查不通过，优先修正顺序为：延长 ramp-up 时间、降低 `Ip` 爬升斜率、重新分配 CS swing、降低 PF 成形速度、推迟 Div 进入工作点。

---

## 5. Stage 3：Flat-top 工作流

### 5.1 阶段目标

Flat-top 阶段解决的问题是：在 `Ip_flat` 已经达到的前提下，尽量平稳地维持等离子体电流、目标边界、X 点和偏滤器构型，并确认 CS 伏秒和 VS 稳定裕度没有被耗尽。

本阶段不再大幅重塑等离子体，而是维持和微调。

### 5.2 输入

Flat-top 接收 Ramp-up 的末态：

- `Ip_at_rampup_end`；
- `coil_state_at_rampup_end`；
- `shape_state_at_rampup_end`；
- 剩余 `cs_flux_state`；
- `timeline.rampup_end_s` 到 `timeline.flattop_end_s`；
- 平顶目标 `Ip_flat`、`κ/δ/X-point`；
- `Div1/Div2` 平顶设定或小幅扫描要求；
- `VS` 基准值和预留裕度。

### 5.3 计算逻辑

Flat-top 可按下面顺序执行：

1. **保持 Ip 平顶**：令 `Ip(t)` 维持在 `Ip_flat` 附近。
2. **生成 CS 慢变波形**：CS 只提供维持电流所需的慢速变化，并持续更新剩余伏秒。
3. **保持 PF 工作点**：`PF1-4` 接近 ramp-up 末态，只允许小幅慢调以维持边界、主半径和 X 点。
4. **设置 Div 微调**：`Div1/Div2` 给出固定工作点或小幅扫描，用于打击点位置修正。
5. **保留 VS 裕度**：`VS` 不生成快速反馈波形，只报告可用电流范围和保留比例。
6. **检查平顶可维持性**：检查剩余伏秒、PF 平滑性、X 点/偏滤器构型、Div 范围和 VS 裕度。

简化数据流为：

```text
Ip_flat + flattop_duration
  → CS 慢变需求
  → 剩余伏秒检查

目标边界 + X-point + Div strike point
  → PF1-4 平顶工作点
  → Div1/Div2 微调
  → 平顶位形与裕度检查
```

### 5.4 输出

本阶段输出：

| 输出 | 内容 |
|---|---|
| `flattop_waveform` | `rampup_end` 到 `flattop_end` 的 Ip、CS、PF、Div、VS 基准波形 |
| `coil_state_at_flattop_end` | 平顶结束时各线圈状态 |
| `cs_flux_margin` | 平顶结束时剩余伏秒比例 |
| `divertor_setting` | Div 工作点或小幅扫描说明 |
| `vs_reserved_range` | VS 实时反馈预留范围 |
| `flattop_validation` | 平顶电流、边界、X 点、打击点、伏秒和裕度检查 |

如果检查不通过，优先修正顺序为：缩短平顶时间、增加 CS 伏秒裕度、降低平顶维持电压需求、减小 Div 扫描幅度、放宽或调整目标位形。

---

## 6. 三阶段合并与最终检查

三阶段分别生成后，需要合并成一条连续波形。

### 6.1 合并规则

1. 时间轴必须单调递增；
2. 阶段交接点的 `Ip` 和各线圈电流必须连续；
3. 同一列变量在三个阶段中使用同一单位和命名；
4. `TF` 始终作为 `B0_T` 背景量输出，不参与动态优化；
5. `VS` 只输出离线基准和裕度，不伪装成实时反馈结果。

### 6.2 最终检查项

| 检查项 | 通过标准 |
|---|---|
| 电流限幅 | 所有线圈电流位于 `I_min/I_max` 内 |
| 变化率 | 相邻采样点变化率不超过 `dI_dt_max` |
| CS 伏秒 | 击穿、爬升、平顶后仍有最低裕度 |
| 波形连续性 | 阶段交接处无非物理阶跃 |
| Breakdown 零场 | 击穿区 `B_R/B_Z` 处于可接受低值趋势 |
| Ramp-up 位形 | `R/a/κ/δ/X-point` 平滑接近目标 |
| Flat-top 维持 | `Ip`、PF 工作点和 Div 设定保持稳定 |
| VS 裕度 | VS 保留足够实时反馈范围 |

---

## 7. 基于示例输入的传导脉络

以 `04_io_and_examples.md` 中的示例为例，传导过程如下：

1. `t = 0.00 s`：TF 已等效提供 `B0 = 12.2 T`；CS 处于预充磁状态；PF3/PF4 给出击穿零场预置；Div 和 VS 为 0 或待命。
2. `t = 0.08 s`：CS swing 产生 loop voltage，`Ip` 达到约 `0.15 MA`；PF 零场配置完成；该时刻的 CS/PF 电流作为 Ramp-up 初值。
3. `t = 0.08-1.20 s`：`Ip` 从 `0.15 MA` 平滑升到 `8.7 MA`；CS 持续消耗伏秒；PF4/PF3 随 `Ip` 调整整体平衡；PF1/PF2 逐步建立拉长、三角形变和 X 点趋势；Div 后段缓慢进入工作点。
4. `t = 1.20 s`：进入平顶，`Ip = 8.7 MA`，PF1-4 达到目标位形附近工作点，CS 仍保留伏秒裕度。
5. `t = 1.20-3.20 s`：CS 慢变维持电流；PF1-4 小幅慢调或近似保持；Div 微调打击点；VS 保留快速反馈裕度。
6. `t = 3.20 s`：输出完整波形表和检查报告。如果伏秒不足或变化率超限，则回到配置中调整时间、目标斜率或线圈分配。

---

## 8. 简化原则

本工作流刻意保持简洁：

- 不做完整自由边界平衡求解，只做趋势一致性和约束检查；
- 不把每个上下线圈都独立展开，先使用等效线圈组；
- 不设计 VS 高频反馈，只说明基准和裕度；
- 不让 Div 参与击穿和主升流，只在后段和平顶微调；
- 不追求最优波形，只追求阶段逻辑清楚、数据传递连续、约束检查自洽。

因此，本 Skill 的最小可用结果是一条清楚的推演链：

```text
目标放电参数
  → Breakdown 形成种子电流
  → Ramp-up 达到目标 Ip 与目标位形
  → Flat-top 维持目标状态
  → 输出波形、检查报告和修正建议
```
