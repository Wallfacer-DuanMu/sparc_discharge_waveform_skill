# Stage 1 Breakdown 工作包说明

本工作包负责完成三阶段放电设计中的第一阶段：`Breakdown`。它的任务不是生成完整平顶位形，而是在固定 TF 背景场下，用 CS 产生击穿所需的环向电压，用 PF3/PF4 建立击穿区低极向场预置，并得到可交给 Ramp-up 阶段继续使用的初始等离子体和线圈末态。

本阶段坚持简化原则：只做学生作业所需的清晰推演，不做完整自由边界平衡求解，也不模拟实时反馈控制。

---

## 1. 阶段目标

Breakdown 阶段需要回答四个问题：

1. 在 `t_start_s` 到 `breakdown_end_s` 之间，能否生成一段连续时间轴；
2. `CS1/CS2/CS3` 能否通过预充磁后的电流变化提供目标击穿电压；
3. `PF3/PF4` 能否给出击穿零场预置，`PF1/PF2` 能否做小幅局部修正；
4. 阶段结束时能否得到接近 `Ip_seed_MA` 的种子电流，并输出下一阶段需要的末态。

本阶段最终应输出：

- `breakdown_waveform`：击穿阶段的 `Ip`、CS、PF、Div、VS、TF 简化波形；
- `Ip_at_breakdown_end_MA`：击穿结束时的种子电流估计；
- `coil_state_at_breakdown_end`：所有线圈组在击穿结束时的电流；
- `cs_flux_used_breakdown_Vs`：本阶段消耗的 CS 伏秒；
- `breakdown_validation`：本阶段约束检查结果。

---

## 2. 输入文件

本阶段默认读取同目录下的 `example.yaml`，也可以由 `generate.py` 接收其他 YAML 配置路径。

输入配置必须包含以下顶层字段：

| 字段 | 作用 |
|---|---|
| `case_name` | 案例名称，用于输出报告标识 |
| `device` | SPARC 简化装置背景参数 |
| `timeline` | 本阶段起止时间与采样步长 |
| `target` | 击穿结束时目标种子电流 |
| `coils` | 线圈初始电流、限幅和变化率 |
| `constraints` | 击穿电压、伏秒预算、零场质量等约束 |
| `options` | 波形风格、输出格式和简化开关 |

---

## 3. 本阶段使用的关键输入

### 3.1 装置背景

| 字段 | 含义 | 默认口径 |
|---|---|---|
| `device.B0_T` | TF 提供的背景环向磁场 | 固定，不生成动态 TF 波形 |
| `device.R0_m` | 大半径参考值 | 用于击穿区位置说明 |
| `device.a_m` | 小半径参考值 | 用于量级判断 |

### 3.2 时间安排

| 字段 | 含义 | 要求 |
|---|---|---|
| `timeline.t_start_s` | 击穿阶段开始时间 | 通常为 `0.0` |
| `timeline.breakdown_end_s` | 击穿阶段结束时间 | 必须大于 `t_start_s` |
| `timeline.dt_s` | 采样步长 | 必须大于 0，且不应大于阶段时长 |

本阶段只生成 `t_start_s <= t <= breakdown_end_s` 的波形。

### 3.3 目标电流

| 字段 | 含义 | 要求 |
|---|---|---|
| `target.Ip_seed_MA` | 击穿结束时的目标种子电流 | `>= 0`，且远小于平顶电流 |

本阶段的 `Ip(t)` 可以用平滑线性函数从 0 过渡到 `Ip_seed_MA`。这里的 `Ip` 是简化估计值，不代表完整等离子体输运模拟结果。

### 3.4 线圈输入

本阶段重点使用：

| 线圈组 | 本阶段职责 |
|---|---|
| `CS1/CS2/CS3` | 从预充磁电流开始变化，产生击穿 loop voltage |
| `PF3/PF4` | 形成击穿区低极向场，即零场预置主力 |
| `PF1/PF2` | 做小幅局部修正，避免初始磁场结构过差 |
| `Div1/Div2` | 击穿阶段不参与主设计，默认保持 0 或初始值 |
| `VS` | 不生成快速反馈波形，只保留基准值和裕度 |
| `TF` | 用 `device.B0_T` 表示固定背景场 |

每个线圈组至少应给出：

- `I0_MA`：阶段初始电流；
- `I_min_MA`：允许最小电流；
- `I_max_MA`：允许最大电流；
- `dI_dt_max_MA_per_s`：最大变化率。

`VS` 可不设置 `dI_dt_max_MA_per_s`，但必须设置 `reserved_fraction`，表示为实时反馈保留的裕度比例。

### 3.5 约束输入

| 字段 | 含义 |
|---|---|
| `constraints.breakdown_loop_voltage_V` | 击穿阶段目标 loop voltage |
| `constraints.cs_flux_budget_Vs` | 三阶段 CS 总伏秒预算 |
| `constraints.breakdown_zero_field_tolerance_T` | 击穿区简化零场容许误差 |
| `constraints.min_cs_flux_margin_fraction` | 全流程至少保留的 CS 伏秒裕度比例 |
| `constraints.max_pf_asymmetry_fraction` | PF 上下差分上限；本阶段默认不用差分 |

---

## 4. 计算步骤

本阶段代码应按以下顺序执行，避免跳步。

### Step 1：读取并检查输入

读取 YAML 配置，检查：

1. 顶层字段是否完整；
2. 时间是否满足 `t_start_s < breakdown_end_s`；
3. `dt_s > 0`；
4. `Ip_seed_MA >= 0`；
5. 每个线圈的 `I_min_MA <= I0_MA <= I_max_MA`；
6. 每个动态线圈的 `dI_dt_max_MA_per_s > 0`；
7. `breakdown_loop_voltage_V > 0`；
8. `cs_flux_budget_Vs > 0`。

若基础输入不合法，应直接停止并给出明确错误。

### Step 2：生成击穿阶段时间轴

用 `t_start_s`、`breakdown_end_s` 和 `dt_s` 生成时间数组。

要求：

- 包含起点 `t_start_s`；
- 包含或尽量贴近终点 `breakdown_end_s`；
- 时间单调递增；
- 后续所有波形使用同一时间轴。

### Step 3：生成种子电流轨迹

生成 `Ip(t)`：

- 起点为 `0.0 MA`；
- 终点为 `target.Ip_seed_MA`；
- 中间平滑上升，不允许阶跃。

推荐初版采用 `smooth_piecewise_linear`：即线性上升，两端可做简单平滑处理。若暂不实现平滑函数，也必须保证连续。

### Step 4：估算 CS 击穿 swing

根据目标击穿电压估算本阶段所需 CS 伏秒：

```text
cs_flux_used_breakdown_Vs = breakdown_loop_voltage_V * (breakdown_end_s - t_start_s)
```

然后把击穿需求分配给 `CS1/CS2/CS3`。

推荐简化分配规则：

| 线圈 | 分担比例 |
|---|---:|
| `CS1` | 0.30 |
| `CS2` | 0.40 |
| `CS3` | 0.30 |

初版不需要建立真实互感矩阵，可以用“目标 CS 电流变化量”代表产生 loop voltage 的 swing。生成时应满足：

- 三组 CS 从各自 `I0_MA` 连续变化；
- 方向统一，体现预充磁释放；
- 变化率不超过各自 `dI_dt_max_MA_per_s`；
- 电流不超过各自 `I_min_MA/I_max_MA`。

### Step 5：生成 PF 零场预置

本阶段重点使用 `PF3/PF4` 做击穿区零场预置。

推荐简化规则：

- `PF4` 负责主要垂直场抵消，变化幅度最大；
- `PF3` 负责辅助平衡和击穿区位置修正；
- `PF1/PF2` 只做小幅修正，幅度应明显小于 `PF3/PF4`；
- `Div1/Div2` 保持 0 或初始值；
- `VS` 保持基准值，不参与快速控制。

零场质量可以先用一个简化指标表示：

```text
zero_field_error_T = abs(weighted_sum(PF1..PF4) - target_null_field)
```

初版可以不追求真实磁场计算，只要求 `zero_field_error_T <= breakdown_zero_field_tolerance_T`，并在报告中说明这是简化检查。

### Step 6：合并本阶段波形

每个时间点应输出同一套字段：

| 字段 | 含义 |
|---|---|
| `time_s` | 时间 |
| `stage` | 固定为 `breakdown` |
| `Ip_MA` | 种子电流轨迹 |
| `I_CS1_MA` / `I_CS2_MA` / `I_CS3_MA` | CS 击穿 swing |
| `I_PF1_MA` / `I_PF2_MA` / `I_PF3_MA` / `I_PF4_MA` | PF 零场预置与修正 |
| `I_Div1_MA` / `I_Div2_MA` | 默认保持初始值或 0 |
| `I_VS_bias_MA` | VS 离线基准值 |
| `B0_T` | 固定背景环向场 |
| `note` | 起点、击穿中、终点等说明 |

### Step 7：提取阶段末态

在最后一个时间点提取：

- `Ip_at_breakdown_end_MA`；
- `coil_state_at_breakdown_end`；
- `cs_flux_used_breakdown_Vs`；
- `cs_flux_remaining_after_breakdown_Vs`。

其中 `coil_state_at_breakdown_end` 必须包含 `CS1/CS2/CS3/PF1/PF2/PF3/PF4/Div1/Div2/VS`，因为 Ramp-up 阶段要直接接收它作为初态。

### Step 8：执行验证

验证通过后，才认为本阶段结果可交给 Ramp-up。

---

## 5. 验证项

本阶段至少检查以下内容。

| 检查项 | 通过条件 | 不通过时优先建议 |
|---|---|---|
| 时间轴 | 起止时间正确，时间单调，`dt_s > 0` | 修正 `timeline` |
| 输入初值 | 所有 `I0_MA` 在上下限内 | 调整线圈初始电流或限幅 |
| CS 电流限幅 | `I_min_MA <= I_CS <= I_max_MA` | 减小 CS swing 或调整预充磁 |
| CS 变化率 | `abs(dI/dt) <= dI_dt_max` | 延长击穿时间或重新分配 CS 比例 |
| CS 伏秒消耗 | 本阶段消耗小于总预算，且保留后续裕度 | 降低目标击穿电压或延长整体方案 |
| PF 电流限幅 | PF1-4 均在限幅内 | 降低零场预置幅度或重新分配 PF3/PF4 |
| PF 变化率 | PF1-4 变化率不超限 | 延长预置时间或减小修正幅度 |
| 零场质量 | `zero_field_error_T <= tolerance` | 优先调整 PF4，再调整 PF3，最后微调 PF1/PF2 |
| 种子电流 | 终点接近 `Ip_seed_MA` | 提高 loop voltage 或延长 breakdown |
| 波形连续性 | 不出现非物理阶跃 | 使用平滑函数或增加过渡点 |

---

## 6. 输出文件建议

本阶段建议输出到 `outputs/stage_1_breakdown/`，至少包括：

| 文件 | 内容 |
|---|---|
| `breakdown_waveform.csv` | 本阶段逐时刻波形表 |
| `breakdown_waveform.json` | 同样内容的结构化结果，可选 |
| `breakdown_summary.md` | 阶段目标、末态和关键数值摘要 |
| `breakdown_validation.md` | 约束检查结果和修正建议 |

若项目暂时只实现最小版本，可以先返回 Python 字典或打印摘要，但字段命名应与本文件一致，方便后续阶段衔接。

---

## 7. 与 Ramp-up 的交接

Ramp-up 阶段不得重新从全局初始值开始，而必须接收本阶段末态。

交接数据结构建议如下：

```yaml
stage_1_result:
  Ip_at_breakdown_end_MA: 0.15
  coil_state_at_breakdown_end:
    CS1: <stage_end_current>
    CS2: <stage_end_current>
    CS3: <stage_end_current>
    PF1: <stage_end_current>
    PF2: <stage_end_current>
    PF3: <stage_end_current>
    PF4: <stage_end_current>
    Div1: <stage_end_current>
    Div2: <stage_end_current>
    VS: <stage_end_current>
  cs_flux_used_breakdown_Vs: <used_flux>
  cs_flux_remaining_after_breakdown_Vs: <remaining_flux>
  breakdown_validation:
    passed: true
    issues: []
```

只要这个交接结构清楚，第二阶段就可以在第一阶段结果上继续计算，而不是重新假设线圈状态。

---

## 8. 简化口径

本阶段采用以下简化口径，后续代码和报告应保持一致：

1. `TF` 固定为 `device.B0_T`，不生成动态电流波形；
2. `VS` 不参与击穿主计算，只保留基准和裕度；
3. `Div1/Div2` 击穿阶段不参与主设计；
4. `PF3/PF4` 是击穿零场预置主力；
5. `PF1/PF2` 只做小幅修正；
6. `CS1/CS2/CS3` 共同承担击穿 loop voltage；
7. 初版不做完整磁场平衡求解，只做量级、趋势和约束检查。
