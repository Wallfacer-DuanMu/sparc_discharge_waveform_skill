# Pipeline 总控流程说明

本目录用于定义三阶段放电波形设计的总控流程。它不替代 `stages/` 中的阶段工作包，而是负责把 `Breakdown`、`Ramp-up`、`Flat-top` 串成一条连续的数据链。

---

## 1. 总控目标

Pipeline 的目标是：

1. 读取用户填写的统一输入文件；
2. 检查输入结构、单位和基本约束；
3. 依次执行或推演三个阶段；
4. 将每一阶段的末态写入过程状态文件；
5. 保证下一阶段从上一阶段末态继续，而不是重新从全局初始值开始；
6. 最终合并三阶段波形并生成报告。

---

## 2. 输入入口

Pipeline 默认使用以下输入文件：

```text
config/input_template.yaml
```

实际运行时可复制为案例文件，例如：

```text
config/demo_case.yaml
config/case_high_ip.yaml
config/case_long_flattop.yaml
```

输入文件只描述用户目标和全局约束，不手动填写阶段中间状态。

必须包含的顶层字段：

| 字段 | 作用 |
|---|---|
| `case_name` | 案例名称，用于输出目录命名 |
| `device` | SPARC 简化装置参数 |
| `timeline` | 三阶段时间边界和采样步长 |
| `target` | 目标种子电流、平顶电流和目标位形 |
| `coils` | 各线圈初值、上下限和变化率约束 |
| `constraints` | CS 伏秒、击穿电压、裕度和差分约束 |
| `options` | 波形风格、输出格式和绘图选项 |

---

## 3. 标准数据流

完整数据流如下：

```text
config/*.yaml
  → 读取并校验输入
  → Stage 1 Breakdown
  → 写入 stage_1_result
  → Stage 2 Ramp-up
  → 写入 stage_2_result
  → Stage 3 Flat-top
  → 写入 stage_3_result
  → 合并 final_result
  → 输出 waveforms / reports
```

关键原则：

- Stage 2 必须读取 Stage 1 的末态。
- Stage 3 必须读取 Stage 2 的末态。
- `process_state.json` 是阶段间交接的唯一权威记录。

---

## 4. Pipeline 执行步骤

### Step 1：读取输入配置

读取 YAML 配置，得到：

- 装置背景；
- 三阶段时间边界；
- 目标电流和目标位形；
- 线圈初始电流、限幅、变化率；
- CS 伏秒预算和其他全局约束。

### Step 2：执行全局输入检查

至少检查：

1. `t_start_s < breakdown_end_s < rampup_end_s < flattop_end_s`；
2. `dt_s > 0`；
3. `Ip_seed_MA >= 0`；
4. `Ip_flat_MA > Ip_seed_MA`；
5. 所有线圈 `I_min_MA <= I0_MA <= I_max_MA`；
6. 动态线圈 `dI_dt_max_MA_per_s > 0`；
7. `cs_flux_budget_Vs > 0`；
8. `breakdown_loop_voltage_V > 0`。

若基础输入不合法，Pipeline 应停止，并输出明确的修改建议。

### Step 3：运行 Stage 1 Breakdown

输入：

- `device`；
- `timeline.t_start_s` 到 `timeline.breakdown_end_s`；
- `target.Ip_seed_MA`；
- `coils` 中的全局初始线圈状态；
- `constraints.breakdown_loop_voltage_V`；
- `constraints.cs_flux_budget_Vs`。

输出并写入 `process_state.json`：

- `Ip_at_breakdown_end_MA`；
- `coil_state_at_breakdown_end`；
- `cs_flux_used_breakdown_Vs`；
- `cs_flux_remaining_after_breakdown_Vs`；
- `breakdown_validation`。

### Step 4：运行 Stage 2 Ramp-up

Stage 2 不得重新读取 `coils.*.I0_MA` 作为初态，而必须接收：

- `stage_1_result.Ip_at_breakdown_end_MA`；
- `stage_1_result.coil_state_at_breakdown_end`；
- `stage_1_result.cs_flux_remaining_after_breakdown_Vs`。

同时读取全局目标：

- `target.Ip_flat_MA`；
- `target.shape`；
- `timeline.breakdown_end_s` 到 `timeline.rampup_end_s`。

输出并写入 `process_state.json`：

- `Ip_at_rampup_end_MA`；
- `coil_state_at_rampup_end`；
- `shape_state_at_rampup_end`；
- `cs_flux_used_rampup_Vs`；
- `cs_flux_remaining_after_rampup_Vs`；
- `rampup_validation`。

### Step 5：运行 Stage 3 Flat-top

Stage 3 必须接收：

- `stage_2_result.Ip_at_rampup_end_MA`；
- `stage_2_result.coil_state_at_rampup_end`；
- `stage_2_result.shape_state_at_rampup_end`；
- `stage_2_result.cs_flux_remaining_after_rampup_Vs`。

同时读取全局目标：

- `target.Ip_flat_MA`；
- `target.shape`；
- `timeline.rampup_end_s` 到 `timeline.flattop_end_s`；
- `Div1/Div2` 和 `VS` 约束。

输出并写入 `process_state.json`：

- `coil_state_at_flattop_end`；
- `cs_flux_margin`；
- `divertor_setting`；
- `vs_reserved_range`；
- `flattop_validation`。

### Step 6：合并最终结果

Pipeline 最后应合并三阶段结果，生成：

- 连续的 `Ip(t)`；
- 连续的 `CS1/CS2/CS3` 波形；
- 连续的 `PF1/PF2/PF3/PF4` 波形；
- `Div1/Div2` 平顶或后段过渡设定；
- `VS` 基准和裕度；
- `TF` 背景场说明。

---

## 5. 过程状态文件

Pipeline 应维护一个过程状态文件：

```text
outputs/<case_name>/process_state.json
```

推荐也可在调试阶段临时写入：

```text
pipeline/process_state.json
```

该文件记录三阶段交接状态，是后续复查和调试的依据。

顶层结构建议：

```json
{
  "case_name": "sparc_demo_discharge",
  "global_input": {},
  "stage_1_result": {},
  "stage_2_result": {},
  "stage_3_result": {},
  "final_result": {}
}
```

具体字段应由 `pipeline/state_schema.md` 进一步固定。

---

## 6. 输出目录

推荐输出到：

```text
outputs/<case_name>/
```

至少包含：

| 文件 | 内容 |
|---|---|
| `waveforms.csv` | 三阶段连续波形表 |
| `waveforms.json` | 结构化波形数据，可选 |
| `process_state.json` | 阶段间过程状态 |
| `stage_summary.md` | 阶段摘要 |
| `validation_report.md` | 约束检查报告 |
| `revision_suggestions.md` | 下一轮修正建议 |

---

## 7. 与 stages/ 的关系

`pipeline/` 只负责调度和数据传递。

`stages/` 负责阶段内部计算：

```text
stages/stage_1_breakdown/  → 生成击穿波形和击穿末态
stages/stage_2_rampup/     → 生成爬升波形和爬升末态
stages/stage_3_flattop/    → 生成平顶维持波形和最终检查
```

如果阶段内部代码暂未完全实现，Agent 也应按照各阶段 `README.md` 中的规则进行结构化推演，并保持同样的数据字段。

---

## 8. Agent 使用要求

Agent 使用 Pipeline 时必须遵守：

1. 先确认用户输入是否能整理为 `config/*.yaml`；
2. 不允许跳过 Stage 1 直接生成平顶波形；
3. 不允许每个阶段独立重置线圈初态；
4. 必须记录 `coil_state`、`Ip`、`cs_flux` 的阶段传递；
5. 必须输出验证结果和修正建议；
6. 若某阶段不通过，应优先指出需要调整的输入参数，而不是强行给出通过结论。

---

## 9. 最小可运行闭环

在代码尚未完全实现时，Pipeline 的最小闭环可以先做到：

```text
读取 config
  → 生成 stage_1_result 字典
  → 生成 stage_2_result 字典
  → 生成 stage_3_result 字典
  → 写出 process_state.json
  → 合并已有阶段输出或生成占位 waveforms
  → 写出 summary / validation / suggestions
```

这个闭环的重点是数据链路正确，而不是模型精度完整。
