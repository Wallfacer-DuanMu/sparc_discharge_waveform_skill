# Pipeline 过程状态文件字段规范

本文件定义 `process_state.json` 的推荐结构。它用于记录三阶段放电波形设计中的数据传递关系，保证 `Breakdown`、`Ramp-up`、`Flat-top` 不是彼此独立计算，而是按阶段末态连续推进。

---

## 1. 文件定位

`process_state.json` 是 Pipeline 的过程状态文件。

推荐输出路径：

```text
outputs/<case_name>/process_state.json
```

调试阶段也可以临时写入：

```text
pipeline/process_state.json
```

该文件由 Pipeline 自动生成和更新，不要求用户手动填写。

---

## 2. 顶层结构

```json
{
  "case_name": "sparc_demo_discharge",
  "status": "initialized | running | passed | failed",
  "global_input": {},
  "stage_1_result": {},
  "stage_2_result": {},
  "stage_3_result": {},
  "final_result": {}
}
```

字段说明：

| 字段 | 含义 |
|---|---|
| `case_name` | 案例名称，应与输入配置中的 `case_name` 一致 |
| `status` | Pipeline 当前状态 |
| `global_input` | 用户输入配置的快照 |
| `stage_1_result` | Breakdown 阶段结果 |
| `stage_2_result` | Ramp-up 阶段结果 |
| `stage_3_result` | Flat-top 阶段结果 |
| `final_result` | 三阶段汇总结果 |

---

## 3. global_input

`global_input` 保存输入配置快照，便于复查本次运行使用了哪些目标和约束。

推荐结构：

```json
{
  "case_name": "sparc_demo_discharge",
  "device": {},
  "timeline": {},
  "target": {},
  "coils": {},
  "constraints": {},
  "options": {}
}
```

说明：

- `global_input` 应直接来自 `config/*.yaml`。
- 不建议在这里写入阶段中间结果。
- 阶段中间结果应写入对应的 `stage_*_result`。

---

## 4. stage_1_result

`stage_1_result` 记录 `Breakdown` 阶段输出，并作为 `Ramp-up` 阶段输入。

推荐结构：

```json
{
  "stage_name": "breakdown",
  "time_range_s": {
    "start": 0.0,
    "end": 0.08
  },
  "Ip_at_breakdown_end_MA": 0.15,
  "coil_state_at_breakdown_end": {
    "CS1": 0.0,
    "CS2": 0.0,
    "CS3": 0.0,
    "PF1": 0.0,
    "PF2": 0.0,
    "PF3": 0.0,
    "PF4": 0.0,
    "Div1": 0.0,
    "Div2": 0.0,
    "VS": 0.0
  },
  "cs_flux_used_breakdown_Vs": 1.6,
  "cs_flux_remaining_after_breakdown_Vs": 33.4,
  "waveform_ref": "outputs/<case_name>/stage_1_breakdown_waveform.csv",
  "breakdown_validation": {
    "passed": true,
    "issues": [],
    "warnings": []
  }
}
```

必须字段：

| 字段 | 必须性 | 作用 |
|---|---:|---|
| `Ip_at_breakdown_end_MA` | 必须 | 作为 Ramp-up 初始等离子体电流 |
| `coil_state_at_breakdown_end` | 必须 | 作为 Ramp-up 初始线圈状态 |
| `cs_flux_used_breakdown_Vs` | 必须 | 记录击穿阶段已用伏秒 |
| `cs_flux_remaining_after_breakdown_Vs` | 必须 | 作为 Ramp-up 可用伏秒状态 |
| `breakdown_validation` | 必须 | 判断该阶段是否可交接 |

---

## 5. stage_2_result

`stage_2_result` 记录 `Ramp-up` 阶段输出，并作为 `Flat-top` 阶段输入。

推荐结构：

```json
{
  "stage_name": "rampup",
  "time_range_s": {
    "start": 0.08,
    "end": 1.20
  },
  "Ip_at_rampup_start_MA": 0.15,
  "Ip_at_rampup_end_MA": 8.7,
  "coil_state_at_rampup_start": {},
  "coil_state_at_rampup_end": {
    "CS1": 0.0,
    "CS2": 0.0,
    "CS3": 0.0,
    "PF1": 0.0,
    "PF2": 0.0,
    "PF3": 0.0,
    "PF4": 0.0,
    "Div1": 0.0,
    "Div2": 0.0,
    "VS": 0.0
  },
  "shape_state_at_rampup_end": {
    "R_axis_m": 1.85,
    "minor_radius_m": 0.57,
    "kappa": 1.9,
    "delta": 0.45,
    "x_point": "lower_single_null"
  },
  "cs_flux_used_rampup_Vs": 20.0,
  "cs_flux_remaining_after_rampup_Vs": 13.4,
  "waveform_ref": "outputs/<case_name>/stage_2_rampup_waveform.csv",
  "rampup_validation": {
    "passed": true,
    "issues": [],
    "warnings": []
  }
}
```

必须字段：

| 字段 | 必须性 | 作用 |
|---|---:|---|
| `Ip_at_rampup_end_MA` | 必须 | 作为 Flat-top 初始等离子体电流 |
| `coil_state_at_rampup_end` | 必须 | 作为 Flat-top 初始线圈状态 |
| `shape_state_at_rampup_end` | 必须 | 作为 Flat-top 初始位形状态 |
| `cs_flux_used_rampup_Vs` | 必须 | 记录爬升阶段已用伏秒 |
| `cs_flux_remaining_after_rampup_Vs` | 必须 | 作为 Flat-top 可用伏秒状态 |
| `rampup_validation` | 必须 | 判断该阶段是否可交接 |

---

## 6. stage_3_result

`stage_3_result` 记录 `Flat-top` 阶段输出，是最终结果汇总的主要依据。

推荐结构：

```json
{
  "stage_name": "flattop",
  "time_range_s": {
    "start": 1.20,
    "end": 3.20
  },
  "Ip_at_flattop_start_MA": 8.7,
  "Ip_at_flattop_end_MA": 8.7,
  "coil_state_at_flattop_start": {},
  "coil_state_at_flattop_end": {
    "CS1": 0.0,
    "CS2": 0.0,
    "CS3": 0.0,
    "PF1": 0.0,
    "PF2": 0.0,
    "PF3": 0.0,
    "PF4": 0.0,
    "Div1": 0.0,
    "Div2": 0.0,
    "VS": 0.0
  },
  "shape_state_at_flattop_end": {
    "R_axis_m": 1.85,
    "minor_radius_m": 0.57,
    "kappa": 1.9,
    "delta": 0.45,
    "x_point": "lower_single_null"
  },
  "cs_flux_used_flattop_Vs": 4.0,
  "cs_flux_margin": {
    "remaining_Vs": 9.4,
    "margin_fraction": 0.27,
    "passed": true
  },
  "divertor_setting": {
    "Div1_MA": 0.0,
    "Div2_MA": 0.0,
    "mode": "fixed_or_small_scan"
  },
  "vs_reserved_range": {
    "VS_bias_MA": 0.0,
    "reserved_fraction": 0.7,
    "I_min_MA": -1.0,
    "I_max_MA": 1.0
  },
  "waveform_ref": "outputs/<case_name>/stage_3_flattop_waveform.csv",
  "flattop_validation": {
    "passed": true,
    "issues": [],
    "warnings": []
  }
}
```

必须字段：

| 字段 | 必须性 | 作用 |
|---|---:|---|
| `coil_state_at_flattop_end` | 必须 | 最终线圈工作点 |
| `shape_state_at_flattop_end` | 推荐 | 最终位形状态 |
| `cs_flux_margin` | 必须 | 判断平顶结束后是否仍有伏秒裕度 |
| `divertor_setting` | 推荐 | 记录 Div 平顶设定或扫描方式 |
| `vs_reserved_range` | 必须 | 记录 VS 离线保留裕度 |
| `flattop_validation` | 必须 | 判断平顶阶段是否通过 |

---

## 7. final_result

`final_result` 汇总三阶段结果，面向最终报告和用户阅读。

推荐结构：

```json
{
  "passed": true,
  "failed_stage": null,
  "waveform_file": "outputs/<case_name>/waveforms.csv",
  "process_state_file": "outputs/<case_name>/process_state.json",
  "stage_summary_file": "outputs/<case_name>/stage_summary.md",
  "validation_report_file": "outputs/<case_name>/validation_report.md",
  "revision_suggestions_file": "outputs/<case_name>/revision_suggestions.md",
  "key_metrics": {
    "Ip_seed_MA": 0.15,
    "Ip_flat_MA": 8.7,
    "cs_flux_budget_Vs": 35.0,
    "cs_flux_used_total_Vs": 25.6,
    "cs_flux_remaining_Vs": 9.4,
    "cs_flux_margin_fraction": 0.27
  },
  "major_warnings": [],
  "next_revision_suggestions": []
}
```

字段说明：

| 字段 | 含义 |
|---|---|
| `passed` | 三阶段总体是否通过 |
| `failed_stage` | 若失败，记录失败阶段 |
| `waveform_file` | 最终连续波形文件路径 |
| `key_metrics` | 关键数值摘要 |
| `major_warnings` | 主要风险提示 |
| `next_revision_suggestions` | 下一轮调整建议 |

---

## 8. 阶段交接规则

Pipeline 必须强制执行以下交接规则。

### 8.1 Breakdown → Ramp-up

Ramp-up 初态必须来自：

```text
stage_1_result.Ip_at_breakdown_end_MA
stage_1_result.coil_state_at_breakdown_end
stage_1_result.cs_flux_remaining_after_breakdown_Vs
```

不得重新使用 `global_input.coils.*.I0_MA` 作为 Ramp-up 初态。

### 8.2 Ramp-up → Flat-top

Flat-top 初态必须来自：

```text
stage_2_result.Ip_at_rampup_end_MA
stage_2_result.coil_state_at_rampup_end
stage_2_result.shape_state_at_rampup_end
stage_2_result.cs_flux_remaining_after_rampup_Vs
```

不得重新假设平顶初始位形或线圈状态。

### 8.3 Flat-top → Final

最终结果必须来自：

```text
stage_1_result
stage_2_result
stage_3_result
```

不得只根据输入目标直接生成最终通过结论。

---

## 9. validation 结构

三个阶段的验证字段建议统一为：

```json
{
  "passed": true,
  "issues": [],
  "warnings": [],
  "checks": {
    "time_axis": true,
    "current_limits": true,
    "dI_dt_limits": true,
    "cs_flux_budget": true,
    "waveform_continuity": true
  }
}
```

其中：

- `issues` 表示导致阶段不通过的问题；
- `warnings` 表示可接受但需要报告的风险；
- `checks` 保存具体检查项布尔结果。

不同阶段可以增加专属检查项：

| 阶段 | 可增加检查项 |
|---|---|
| Breakdown | `zero_field_quality`、`seed_current_reached` |
| Ramp-up | `Ip_tracking`、`shape_transition`、`flux_margin_after_rampup` |
| Flat-top | `Ip_hold`、`divertor_setting_valid`、`vs_margin_reserved` |

---

## 10. 命名和单位规范

必须保持以下命名和单位：

| 类型 | 命名后缀 | 单位 |
|---|---|---|
| 时间 | `_s` | 秒 |
| 电流 | `_MA` | 兆安 |
| 磁场 | `_T` | 特斯拉 |
| 伏秒 | `_Vs` | 伏秒 |
| 比例 | `_fraction` | 无量纲 |

线圈名称统一使用：

```text
CS1, CS2, CS3, PF1, PF2, PF3, PF4, Div1, Div2, VS
```

波形表中对应列名建议为：

```text
I_CS1_MA, I_CS2_MA, I_CS3_MA,
I_PF1_MA, I_PF2_MA, I_PF3_MA, I_PF4_MA,
I_Div1_MA, I_Div2_MA, I_VS_bias_MA
```

---

## 11. 最小合格状态文件

如果暂时不实现完整字段，`process_state.json` 至少必须包含：

```json
{
  "case_name": "sparc_demo_discharge",
  "global_input": {},
  "stage_1_result": {
    "Ip_at_breakdown_end_MA": 0.15,
    "coil_state_at_breakdown_end": {},
    "cs_flux_remaining_after_breakdown_Vs": 33.4,
    "breakdown_validation": {"passed": true}
  },
  "stage_2_result": {
    "Ip_at_rampup_end_MA": 8.7,
    "coil_state_at_rampup_end": {},
    "shape_state_at_rampup_end": {},
    "cs_flux_remaining_after_rampup_Vs": 13.4,
    "rampup_validation": {"passed": true}
  },
  "stage_3_result": {
    "coil_state_at_flattop_end": {},
    "cs_flux_margin": {},
    "vs_reserved_range": {},
    "flattop_validation": {"passed": true}
  },
  "final_result": {
    "passed": true,
    "waveform_file": "outputs/<case_name>/waveforms.csv"
  }
}
```

这个最小结构已经足以支撑三阶段连续推演和最终报告生成。
