# SPARC 放电波形设计 Skill

## 1. Skill 定位

本 Skill 是一个面向托卡马克放电实验前准备的离线波形设计助手。它以 SPARC 简化装置为参考边界，根据用户给定的目标放电需求，组织 `Breakdown`、`Ramp-up`、`Flat-top` 三阶段推演，生成 PF / CS / Div / VS 线圈候选波形、阶段状态、约束检查和修正建议。

当前版本的重点变化是：**三阶段说明已从经验型流程描述升级为“最小真实物理约束流程”**。也就是说，Agent 在使用本 Skill 时，应默认按照三阶段物理链路理解和组织工作，而不是把阶段结果看成纯插值占位： 

```text
用户目标与约束
  → 统一输入文件
  → Breakdown：击穿电路 + PF 零场预置
  → Ramp-up：Ip / Lp / Rp / CS 伏秒 / PF 成形
  → Flat-top：平台维持环电压 / PF 保持 / Div / VS 裕度
  → 三阶段状态传递
  → 波形与验证报告
```

---

## 2. 使用边界

Agent 使用本 Skill 时必须遵守以下边界：

- 本 Skill 只用于实验前离线波形规划，不参与实时控制。
- 不做完整自由边界平衡求解。
- 不模拟 VS 快速反馈细节，只保留稳定裕度。
- 不把 TF 作为动态优化对象，TF 仅作为固定背景环向场。
- 输出结果是初步候选方案，不是可直接工程落地的最终波形。
- 当前 Pipeline 已具备最小闭环能力，三阶段文档已对接最小物理口径，但代码层仍存在占位实现与后续接入空间。

---

## 3. 目录职责

Agent 必须先理解各目录职责，再决定读哪些文件。

| 目录/文件 | 职责 |
|---|---|
| `SKILL.md` | Skill 总入口，规定 Agent 如何使用本包 |
| `docs/` | 项目背景、装置约束、工作流、输入输出规范 |
| `config/input_template.yaml` | 用户填写实验目标和全局约束的统一输入模板 |
| `pipeline/` | 三阶段总控层，负责读取输入、调度阶段、传递状态、写出结果 |
| `pipeline/README.md` | 说明 Pipeline 的总控流程 |
| `pipeline/state_schema.md` | 固定 `process_state.json` 的字段规范 |
| `pipeline/run_pipeline.py` | 当前最小代码闭环入口 |
| `common/` | 公共工具层，提供读写、校验、状态构造等基础能力 |
| `stages/` | 三个阶段的工作包，描述各阶段目标、输入、物理链路和验证项 |
| `outputs/` | Pipeline 或阶段程序输出结果的位置 |

---

## 4. Agent 阅读顺序

### 4.1 初次理解项目时

按以下顺序阅读：

1. `README.md`
2. `docs/01_project_summary.md`
3. `docs/02_facility_and_constraints.md`
4. `docs/03_workflows.md`
5. `pipeline/README.md`
6. `pipeline/state_schema.md`
7. 三个阶段的 `README.md`
8. 如需理解升级后的物理背景，再阅读根目录三个阶段物理说明文档

### 4.2 用户要求“运行完整流程”时

优先阅读：

1. `config/input_template.yaml`
2. `pipeline/README.md`
3. `pipeline/state_schema.md`
4. `pipeline/run_pipeline.py`
5. `common/io.py`
6. `common/validation.py`
7. `common/state.py`

### 4.3 用户要求“改某个阶段物理逻辑”时

优先阅读对应阶段：

- `stages/stage_1_breakdown/README.md`
- `stages/stage_2_rampup/README.md`
- `stages/stage_3_flattop/README.md`

必要时再对照：

- `第一阶段物理过程.md`
- `第二阶段物理过程.md`
- `第三阶段物理过程.md`

然后再检查 `pipeline/run_pipeline.py` 中是否需要把阶段函数接入 Pipeline。

---

## 5. 标准使用流程

当用户给出目标放电需求时，Agent 应按以下流程工作：

1. 将用户需求整理为统一 YAML 输入，优先使用 `config/input_template.yaml` 的结构。
2. 检查输入字段是否完整，包括 `device`、`timeline`、`target`、`coils`、`constraints`、`options`。
3. 检查时间顺序、目标电流、线圈限幅、变化率上限和 CS 伏秒预算。
4. 依据三阶段物理链路理解问题：
   - Breakdown 看击穿环电压、CS swing 和 PF 零场预置；
   - Ramp-up 看 `Ip(t)`、`L_p(t)`、`R_p(t)`、CS 伏秒和 PF 成形；
   - Flat-top 看平台维持环电压、剩余伏秒、PF 保持、Div 打击点和 VS 裕度。
5. 使用 `pipeline/run_pipeline.py` 运行最小闭环，或按 `pipeline/README.md` 手动推演同样的数据流。
6. 读取输出的 `process_state.json`，确认三阶段状态是否连续。
7. 读取 `stage_summary.md`、`validation_report.md`、`revision_suggestions.md`，向用户汇报结果。
8. 如果某阶段不通过，优先建议用户调整输入参数，而不是强行声称通过。

---

## 6. Pipeline 的作用

`pipeline/` 是本 Skill 的总控层。它不负责展开所有阶段内部物理细节，而负责把整个三阶段流程组织起来。

Pipeline 的职责是：

```text
读取 config
  → 调用输入检查
  → 生成或调用 Stage 1
  → 将 Stage 1 末态交给 Stage 2
  → 将 Stage 2 末态交给 Stage 3
  → 汇总 final_result
  → 写出 process_state.json 和报告
```

当前 `pipeline/run_pipeline.py` 已实现最小代码闭环：

- 读取 `config/input_template.yaml`；
- 调用 `common/validation.py` 检查输入；
- 调用 `common/state.py` 中的 `make_stage_1_result`、`make_stage_2_result`、`make_stage_3_result` 构造阶段结果；
- 写出 `process_state.json`、`waveforms.csv`、`stage_summary.md`、`validation_report.md`、`revision_suggestions.md`。

注意：当前 `make_stage_1_result`、`make_stage_2_result`、`make_stage_3_result` 仍是最小闭环阶段占位函数。它们保证数据链路和字段规范正确，但不等价于完整阶段物理实现。Agent 必须同时记住两点：

1. **文档口径已经升级到最小真实物理约束流程**；
2. **代码总控仍可能使用占位阶段结果**。

因此，在说明现状时要区分“文档与设计口径”和“当前代码接入程度”。

---

## 7. common 的作用

`common/` 是公共工具层，为 Pipeline 和未来阶段代码提供共享能力。

当前职责如下：

| 文件 | 作用 |
|---|---|
| `common/io.py` | 读取 YAML，写出 JSON/文本，创建输出目录 |
| `common/validation.py` | 检查统一输入是否合法，包括时间、目标电流、线圈限幅、变化率和伏秒预算 |
| `common/state.py` | 构造 `process_state`、阶段结果、最终结果和最小状态传递结构 |
| `common/constraints.py` | 预留公共约束检查位置，可后续承载电流限幅、变化率、伏秒和残差检查 |
| `common/utils.py` | 预留通用工具位置，可后续承载平滑函数、时间轴、响应矩阵与报告辅助函数 |

Agent 不应把公共逻辑重复写进每个阶段。凡是多个阶段都会用到的能力，应优先放在 `common/`。

---

## 8. 必须保持的数据传递

三阶段必须通过 `process_state.json` 串联，核心传递关系如下：

```text
用户输入 config.yaml
  → Stage 1 Breakdown
  → stage_1_result
  → Stage 2 Ramp-up
  → stage_2_result
  → Stage 3 Flat-top
  → stage_3_result
  → final_result
```

必须保持以下规则：

- `stage_1_result.coil_state_at_breakdown_end` 必须作为 Ramp-up 初始线圈状态。
- `stage_1_result.Ip_at_breakdown_end_MA` 必须作为 Ramp-up 初始等离子体电流。
- `stage_1_result.cs_flux_remaining_after_breakdown_Vs` 必须作为 Ramp-up 可用伏秒状态。
- `stage_2_result.coil_state_at_rampup_end` 必须作为 Flat-top 初始线圈状态。
- `stage_2_result.shape_state_at_rampup_end` 必须作为 Flat-top 初始位形状态。
- `stage_2_result.cs_flux_remaining_after_rampup_Vs` 必须作为 Flat-top 可用伏秒状态。

禁止每个阶段重新从全局初始值开始计算。

---

## 9. 输入文件要求

用户输入应采用统一 YAML 配置，推荐文件为：

```text
config/input_template.yaml
```

输入文件至少包含：

- `case_name`
- `device`
- `timeline`
- `target`
- `coils`
- `constraints`
- `options`

所有时间单位使用 `s`，电流单位使用 `MA`，磁场单位使用 `T`，伏秒单位使用 `Vs`。

Agent 如果发现用户只给了自然语言目标，应先转写为上述结构，再继续执行。

---

## 10. 输出要求

完整流程至少应输出：

- `waveforms.csv`：三阶段连续波形表。
- `process_state.json`：阶段间过程状态和数据传递记录。
- `stage_summary.md`：三阶段关键结果摘要。
- `validation_report.md`：约束检查结果。
- `revision_suggestions.md`：风险提示和下一轮修正建议。

推荐输出路径：

```text
outputs/<case_name>/
```

Agent 向用户汇报时，应优先说明：

1. Pipeline 是否跑通；
2. 三阶段状态是否完成传递；
3. 当前结果是占位输出还是真实阶段输出；
4. 主要风险和下一步建议。

---

## 11. 简化物理口径

本 Skill 统一采用以下简化口径：

- `TF` 固定为 `device.B0_T`，只作为背景环向场。
- `CS1/CS2/CS3` 负责击穿、电流爬升和平顶维持所需的感应驱动。
- `PF3/PF4` 负责击穿零场、整体平衡和位置控制。
- `PF1/PF2` 负责边界成形、拉长和三角形变。
- `Div1/Div2` 不参与击穿和主升流，只在 ramp-up 后段和平顶阶段做偏滤器细调。
- `VS` 不生成高频反馈波形，只输出基准值和保留裕度。
- 初版按上下对称线圈组处理，必要时再加入 PF 小差分修正。

在这个统一口径下，三阶段应分别理解为：

- **Breakdown**：击穿电路方程 + CS 互感 + PF 击穿零场；
- **Ramp-up**：`I_p(t)`、`L_p(t)`、`R_p(t)`、CS 伏秒预算 + PF 响应矩阵成形；
- **Flat-top**：平台维持环电压 + PF 保持 + Div 打击点 + VS 裕度。

---

## 12. 当前实现状态

当前 Skill 已完成：

- 文档层：`docs/`、`pipeline/README.md` 和三个阶段 `README.md` 已同步到新的三阶段物理工作流程；
- 输入层：`config/input_template.yaml` 已提供统一输入模板；
- 总控层：`pipeline/README.md` 和 `pipeline/state_schema.md` 已定义流程和状态字段；
- 最小代码闭环：`pipeline/run_pipeline.py`、`common/io.py`、`common/validation.py`、`common/state.py` 已搭建。

当前仍属于简化实现的是：

- 阶段内部代码未必全部按最新物理说明完整接入；
- `stages/stage_*/generate.py` 与 Pipeline 总控之间仍可能存在占位适配；
- `waveforms.csv` 当前输出能力可能仍偏向最小闭环而非完整高分辨率物理时间序列。

Agent 必须如实说明当前实现状态，不得把最小闭环说成完整物理仿真。

---

## 13. 后续增强路线

如果用户要求继续增强，应按以下顺序推进：

1. 让 `stage_1_breakdown/generate.py` 与击穿物理链路完整对齐，并替换 `make_stage_1_result`。
2. 让 `stage_2_rampup/generate.py` 与 `Ip/Lp/Rp/CS/PF` 物理链路完整对齐，并替换 `make_stage_2_result`。
3. 让 `stage_3_flattop/generate.py` 与平台维持、Div、VS 裕度链路完整对齐，并替换 `make_stage_3_result`。
4. 将完整时间序列波形写入 `waveforms.csv`。
5. 将更细的电流限幅、变化率、伏秒、PF 残差、位形与打击点检查下沉到 `common/constraints.py`。
6. 完善报告和修正建议生成逻辑。

---

## 14. Agent 输出风格

Agent 给用户的结果应保持工程化、可追踪、可检查：

- 明确说明使用了哪些输入参数。
- 明确说明执行了 Pipeline 还是仅做文档推演。
- 明确说明每个阶段的输入、输出和末态。
- 明确说明哪些约束通过、哪些存在风险。
- 明确说明当前结果是否仍包含占位逻辑。
- 明确给出下一轮可调整的参数或可替换的阶段模块。
- 不应过度宣称精度，不应把简化推演表述为完整物理仿真。
