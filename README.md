# SPARC 简化放电线圈电流波形设计 Skill

本项目是一个面向托卡马克放电实验前准备的离线波形设计 Skill。它以 **SPARC 风格的简化托卡马克装置** 为参考对象，把一次标准放电拆成三个阶段：

```text
Breakdown 击穿
  → Ramp-up 电流爬升
  → Flat-top 平顶维持
```

项目目标不是给出真实 SPARC 可直接工程执行的最终波形，而是完成一个学生作业级别的、结构清晰的波形设计流程：从用户给定的放电目标出发，推导 CS/PF/Div/VS 等线圈组的候选电流波形，并输出约束检查、风险提示和下一轮修正建议。

---

## 1. 项目文件结构

```text
sparc_discharge_waveform_skill/
├─ SKILL.md                      # Skill 总入口：Agent 使用规则、阅读顺序、执行边界。
│
├─ docs/
│  ├─ 01_project_summary.md      # 项目摘要：任务目标、Skill 定位、总体方法。
│  ├─ 02_facility_and_constraints.md
│  │                              # 简化 SPARC 装置结构、线圈职责、硬约束。
│  ├─ 03_workflows.md            # Breakdown / Ramp-up / Flat-top 三阶段工作流。
│  └─ 04_io_and_examples.md      # 输入输出规范与示例。
│
├─ config/
│  └─ input_template.yaml        # 统一输入模板：用户填写目标放电需求和全局约束。
│
├─ pipeline/
│  ├─ README.md                  # Pipeline 总控说明。
│  ├─ run_pipeline.py            # 三阶段总入口：串联 Breakdown → Ramp-up → Flat-top。
│  └─ state_schema.md            # 过程状态、阶段交接、最终状态字段约定。
│
├─ common/
│  ├─ io.py                      # 公共输入输出工具。
│  ├─ state.py                   # 公共状态结构。
│  ├─ validation.py              # 公共验证辅助。
│  ├─ utils.py                   # 公共工具预留。
│  └─ constraints.py             # 公共约束检查预留。
│
├─ stages/
│  ├─ stage_1_breakdown/
│  │  ├─ README.md               # 击穿阶段说明。
│  │  ├─ example.yaml            # 击穿阶段示例输入。
│  │  ├─ generate.py             # 击穿阶段生成入口。
│  │  ├─ models.py               # 击穿简化模型。
│  │  └─ validation.py           # 击穿阶段验证。
│  │
│  ├─ stage_2_rampup/
│  │  ├─ README.md               # 电流爬升阶段说明。
│  │  ├─ example.yaml            # 爬升阶段示例输入。
│  │  ├─ generate.py             # 爬升阶段生成入口。
│  │  ├─ models.py               # 爬升简化模型。
│  │  └─ validation.py           # 爬升阶段验证。
│  │
│  └─ stage_3_flattop/
│     ├─ README.md               # 平顶阶段说明。
│     ├─ example.yaml            # 平顶阶段示例输入。
│     ├─ generate.py             # 平顶阶段生成入口。
│     ├─ models.py               # 平顶简化模型。
│     └─ validation.py           # 平顶阶段验证。
│
└─ outputs/
   ├─ README.md                  # 输出目录说明。
   ├─ sparc_demo_discharge/      # Pipeline 示例输出。
   ├─ stage_1_breakdown/         # Stage 1 单独运行输出。
   ├─ stage_2_rampup/            # Stage 2 单独运行输出。
   └─ stage_3_flattop/           # Stage 3 单独运行输出。
```

推荐从 `SKILL.md`、`docs/02_facility_and_constraints.md` 和 `pipeline/README.md` 开始阅读。

---

## 2. 项目建立在一个简化 SPARC 装置假设上

本项目不是完整 SPARC 工程模型，也不尝试复现实验装置的全部细节。为了让学生作业可以落地，项目先定义了一个“简化 SPARC 参考装置”。后续所有模型、输入、阶段推演和验证逻辑，都建立在这个简化装置边界之上。

对应说明文件是：

```text
sparc_discharge_waveform_skill/docs/02_facility_and_constraints.md
```

### 2.1 简化磁体系统

```text
托卡马克磁体系统（本项目简化版）
├── TF 环向场线圈
│   └── 提供主环向磁场 B_t；作为固定背景场，不设计动态波形
│
└── 极向场与感应驱动系统
    ├── CS 中心螺线管
    │   ├── CS1_U / CS1_L
    │   ├── CS2_U / CS2_L
    │   └── CS3_U / CS3_L
    │       └── 通过电流变化产生环向电压，驱动 Ip 启动、爬升和维持
    │
    ├── PF 主极向场线圈
    │   ├── PF1_U / PF1_L：边界与局部形状控制
    │   ├── PF2_U / PF2_L：拉长、三角形变与 X 点趋势控制
    │   ├── PF3_U / PF3_L：径向/垂直平衡、X 点和上下位形调节
    │   └── PF4_U / PF4_L：击穿零场、整体垂直场和主半径平衡
    │
    └── 辅助线圈
        ├── Div1 / Div2：偏滤器打击点与边缘磁场细调
        └── VS：垂直稳定快速反馈；本项目只保留裕度
```

### 2.2 各类线圈在本项目中的角色

| 线圈组 | 本项目中的处理方式 |
|---|---|
| `TF` | 固定背景环向场，只用 `B0` 表示，不生成动态波形。 |
| `CS1/CS2/CS3` | 主波形对象，负责产生环向电压、驱动 `Ip` 启动、爬升和平顶维持。 |
| `PF1/PF2` | 主波形对象，负责边界、拉长比、三角形变和局部形状控制。 |
| `PF3/PF4` | 主波形对象，负责击穿零场、主半径、径向/垂直平衡、X 点和偏滤器入口位形。 |
| `Div1/Div2` | 辅助对象，主要在平顶阶段做打击点细调或小幅扫描。 |
| `VS` | 实时反馈对象，本项目不模拟高频反馈，只输出基准值和控制裕度。 |

### 2.3 关键建模假设

本项目采用以下简化假设：

1. **只做离线候选波形设计**，不参与实时控制。
2. **不做完整自由边界平衡求解**，只做工程量级、趋势一致性和约束可行性检查。
3. **TF 固定**，不作为动态优化变量。
4. **VS 不做反馈波形**，只保留裕度。
5. **Div 不承担主升流任务**，只在 ramp-up 后段和平顶阶段参与偏滤器细调。
6. **CS 与 PF 先弱耦合处理**：CS 负责电流驱动，PF 负责位形控制。
7. **上下线圈先按等效组处理**，必要时只做小差分修正。

因此，本项目的输出应被理解为：

> 一套用于展示设计思路、数据流和约束检查的候选波形方案，而不是可直接用于真实 SPARC 实验的工程波形。

---

## 3. 物理过程：输入如何一步步变成结果

真实托卡马克放电控制非常复杂。本项目将它简化成一条可复查的数据链：

```text
用户目标放电需求
  → 统一输入文件
  → 三阶段目标拆解
  → 每阶段生成线圈候选波形
  → 阶段间状态交接
  → 合并三阶段波形
  → 输出验证报告和修正建议
```

### 3.1 用户输入的不是线圈电流，而是放电目标

实验设计中，用户通常不会直接指定 `CS1`、`PF2` 等线圈在每个时刻的电流。更合理的输入是目标等离子体状态和装置约束。

统一输入文件是：

```text
sparc_discharge_waveform_skill/config/input_template.yaml
```

用户主要关心的基础目标包括：

| 输入类别 | 示例字段 | 含义 |
|---|---|---|
| 案例名称 | `case_name` | 本次放电设计任务名称。 |
| 时间安排 | `timeline.breakdown_end_s`、`timeline.rampup_end_s`、`timeline.flattop_end_s` | 三阶段时间边界。 |
| 目标电流 | `target.Ip_seed_MA`、`target.Ip_flat_MA` | 击穿后的种子电流和平顶等离子体电流。 |
| 目标位形 | `target.shape.R_axis_m`、`minor_radius_m`、`kappa_flat`、`delta_flat`、`x_point` | 平顶目标位置、大小、拉长比、三角形变和 X 点构型。 |
| 装置参数 | `device.B0_T`、`R0_m`、`a_m` | 简化 SPARC 参考边界。 |
| 工程约束 | `coils.*.I_min_MA`、`I_max_MA`、`dI_dt_max_MA_per_s` | 线圈电流和变化率限制。 |
| 伏秒约束 | `constraints.cs_flux_budget_Vs`、`min_cs_flux_margin_fraction` | CS 可用磁通和剩余裕度。 |

其中，真正随实验目标经常变化的是：

- 平顶目标电流 `Ip_flat_MA`；
- 三阶段时间安排；
- 目标位形，例如 `R_axis_m`、`minor_radius_m`、`kappa_flat`、`delta_flat`、`x_point`；
- 平顶持续时间和伏秒裕度要求。

线圈上下限、变化率、背景磁场等更多是装置约束，不是每次实验都手动设计的目标。

### 3.2 三阶段物理过程

完整流程按三个阶段执行。

#### Stage 1：Breakdown 击穿

目标：从真空和预充气状态形成初始等离子体。

主要逻辑：

```text
目标击穿条件
  → CS 提供环向电压
  → PF3/PF4 形成击穿零场区
  → 得到种子 Ip 和击穿末态
```

本阶段重点：

- `CS1/CS2/CS3` 从预充磁状态开始变化，产生击穿所需 loop voltage；
- `PF3/PF4` 负责在击穿区形成低极向场；
- `PF1/PF2` 只做辅助修正；
- `Div/VS` 不参与主设计；
- 输出 `handoff_to_stage_2`。

#### Stage 2：Ramp-up 电流爬升

目标：将等离子体电流从种子电流升到平顶目标电流，同时逐步形成目标位形。

主要逻辑：

```text
Stage 1 末态
  → Ip(t) 爬升目标
  → loop voltage 需求
  → CS 波形
  → 目标 R/a/κ/δ/X-point 演化
  → PF1/PF2/PF3/PF4 波形
  → Ramp-up 末态
```

本阶段重点：

- `CS` 负责持续驱动 `Ip` 上升并管理伏秒消耗；
- `PF4/PF3` 负责主半径、径向/垂直平衡和 X 点形成；
- `PF1/PF2` 负责拉长比、三角形变和边界成形；
- `Div` 在后段缓慢接近平顶设定；
- `VS` 只检查裕度；
- 输出 `handoff_to_stage_3`。

#### Stage 3：Flat-top 平顶维持

目标：维持目标平顶电流、目标位形、X 点和偏滤器构型。

主要逻辑：

```text
Stage 2 末态
  → Ip_flat 保持
  → CS 低环电压慢速维持
  → PF 保持形状和平衡
  → Div 微调打击点
  → VS 输出裕度
  → final_state
```

本阶段重点：

- `CS1/CS2/CS3` 缓慢变化，维持电流并检查剩余伏秒；
- `PF1/PF2` 维持边界、拉长比和三角形变；
- `PF3/PF4` 维持主半径、整体平衡、X 点和偏滤器入口位形；
- `Div1/Div2` 做打击点固定设定或小幅扫描；
- `VS` 输出基准值和可用控制范围；
- 输出 `final_state`。

### 3.3 最终输出

Pipeline 运行后，默认输出到：

```text
sparc_discharge_waveform_skill/outputs/<case_name>/
```

主要结果包括：

| 输出文件 | 内容 |
|---|---|
| `process_state.json` | 三阶段过程状态、阶段交接和最终状态。 |
| `waveforms.csv` | 三阶段合并后的候选线圈波形表。 |
| `stage_summary.md` | Breakdown / Ramp-up / Flat-top 阶段摘要。 |
| `validation_report.md` | 电流限幅、变化率、伏秒、位形等约束检查。 |
| `revision_suggestions.md` | 下一轮修改建议。 |

---

## 4. 如何运行

在项目根目录运行：

```bash
python sparc_discharge_waveform_skill/pipeline/run_pipeline.py
```

如果需要指定输入文件，可使用：

```bash
python sparc_discharge_waveform_skill/pipeline/run_pipeline.py sparc_discharge_waveform_skill/config/input_template.yaml
```

单独运行某个阶段也可以，例如：

```bash
python sparc_discharge_waveform_skill/stages/stage_1_breakdown/generate.py
python sparc_discharge_waveform_skill/stages/stage_2_rampup/generate.py
python sparc_discharge_waveform_skill/stages/stage_3_flattop/generate.py
```

但推荐优先运行 `pipeline/run_pipeline.py`，因为它会保证阶段之间的状态连续传递。

---

## 5. Skill 化思路：如何把复杂物理过程交给 Agent 执行

本项目不仅是一组脚本，也是一套面向 Agent 的 Skill。它将复杂的物理工程任务拆成可读、可执行、可验证的文件结构。

### 5.1 Skill 化的核心思想

原始问题是：

> 给定目标托卡马克放电，如何规划 CS/PF 等线圈的三阶段电流波形？

这个问题很复杂，涉及击穿、升流、平衡、成形、偏滤器、伏秒、线圈限幅和稳定性。项目将其 Skill 化为：

```text
装置假设文档
  → 统一输入模板
  → Pipeline 总控
  → 三个阶段工作包
  → 公共状态与验证结构
  → 输出报告
```

这样 Agent 不需要一次性“凭空设计完整波形”，而是可以按固定步骤读取文件、运行阶段、检查结果和提出修改建议。

### 5.2 Agent 看到本 Skill 后应该怎么工作

Agent 的推荐工作流程如下。

#### 第一步：理解项目边界

先阅读：

```text
SKILL.md
README.md
docs/01_project_summary.md
docs/02_facility_and_constraints.md
```

目的：明确这不是完整 SPARC 仿真，而是基于简化装置的离线候选波形设计。

#### 第二步：理解三阶段数据流

继续阅读：

```text
docs/03_workflows.md
pipeline/README.md
pipeline/state_schema.md
```

目的：明确 Stage 1、Stage 2、Stage 3 如何传递 `Ip`、线圈电流、位形和 CS 伏秒状态。

#### 第三步：读取用户输入

读取：

```text
config/input_template.yaml
```

Agent 应识别：

- 哪些是用户目标；
- 哪些是装置固定约束；
- 哪些是工程限幅；
- 哪些字段不应该手动作为阶段中间状态填写。

#### 第四步：运行 Pipeline

运行：

```text
pipeline/run_pipeline.py
```

Pipeline 负责：

1. 读取统一输入；
2. 校验全局字段；
3. 生成 Stage 1 结果；
4. 将 Stage 1 末态交给 Stage 2；
5. 将 Stage 2 末态交给 Stage 3；
6. 合并最终波形；
7. 写出报告。

#### 第五步：检查输出并反馈

Agent 应读取：

```text
outputs/<case_name>/process_state.json
outputs/<case_name>/stage_summary.md
outputs/<case_name>/validation_report.md
outputs/<case_name>/revision_suggestions.md
```

然后回答：

- 波形是否生成成功；
- 三阶段是否连续；
- 哪些约束通过；
- 哪些约束存在风险；
- 下一轮应该调哪些输入目标或约束。

### 5.3 各目录在 Skill 中的角色

| 目录 | 在 Skill 中的作用 |
|---|---|
| `docs/` | 给 Agent 提供物理背景、装置假设、阶段工作流和 I/O 规则。 |
| `config/` | 给用户和 Agent 一个统一输入入口。 |
| `pipeline/` | 把三阶段组织成完整流程，是运行总入口。 |
| `stages/` | 具体阶段工作包，每个阶段独立说明目标、模型、验证和输出。 |
| `common/` | 放置公共状态、读写和验证工具，避免 Pipeline 层重复造结构。 |
| `outputs/` | 保存波形、状态、报告和修正建议，供复查和迭代。 |

### 5.4 为什么这样设计适合学生作业

这个项目有意避免过度工程化和过度物理复杂化：

- 不做完整 MHD / 自由边界平衡求解；
- 不追求最优波形；
- 不模拟实时控制系统；
- 不要求真实 SPARC 工程参数完全准确；
- 重点展示问题拆解、阶段数据流、约束检查和迭代思路。

它适合用来展示：

1. 如何把复杂聚变工程问题拆成阶段；
2. 如何把物理目标转化为可计算输入；
3. 如何把候选线圈波形与约束检查串起来；
4. 如何把 AI Agent 的工作流程封装成 Skill。

---

## 6. 项目输出的正确理解

本项目输出的是：

```text
候选线圈电流波形 + 约束检查 + 风险提示 + 修改建议
```

而不是：

```text
真实 SPARC 实验可直接执行的最终控制波形
```

因此，判断项目是否完成的重点不是“波形是否最优”，而是：

- 装置假设是否清楚；
- 三阶段拆解是否合理；
- 输入输出是否自洽；
- 阶段间状态是否连续；
- 约束检查是否覆盖主要风险；
- Agent 是否能根据 Skill 文档稳定复现流程。

---

## 7. 一句话总结

本项目将“托卡马克放电线圈电流波形设计”简化为一个可运行、可复查、可由 Agent 执行的 Skill：在简化 SPARC 装置假设下，用户输入目标放电需求，Pipeline 串联 Breakdown、Ramp-up、Flat-top 三阶段，生成 CS/PF/Div/VS 候选波形，并输出验证报告与修正建议。
