# SPARC 简化放电线圈电流波形设计 Skill

本项目是一个面向托卡马克放电实验前准备的离线波形设计 Skill。它以 **SPARC 风格的简化托卡马克装置** 为参考对象，把一次标准放电拆成三个连续阶段：

```text
Breakdown 击穿
  → Ramp-up 电流爬升
  → Flat-top 平顶维持
```

项目目标不是给出真实 SPARC 可直接工程执行的最终波形，而是给出一套**结构清晰、阶段连续、可检查可迭代**的候选波形设计流程：从用户给定的放电目标出发，推导 CS / PF / Div / VS 等线圈组的候选电流波形，并输出约束检查、风险提示和下一轮修正建议。

---

## 0. 三个阶段物理过程详细说明

本仓库已补充三份“物理过程（简化版）接入”说明，建议与主 README 配合阅读：

- [第一阶段物理过程](./sparc_discharge_waveform_skill/stages/stage_1_breakdown/第一阶段物理过程.md)
- [第二阶段物理过程](./sparc_discharge_waveform_skill/stages/stage_2_rampup/第二阶段物理过程.md)
- [第三阶段物理过程](./sparc_discharge_waveform_skill/stages/stage_3_flattop/第三阶段物理过程.md)

这三份文档分别说明了三个阶段目前采用的**最小真实物理约束口径**：

- **Stage 1 / Breakdown**：用等离子体电路方程、CS 互感关系和 PF 击穿零场条件描述种子等离子体建立；
- **Stage 2 / Ramp-up**：用 \(I_p(t)\)、\(L_p(t)\)、\(R_p(t)\)、CS 伏秒预算与 PF 响应矩阵描述升流与成形；
- **Stage 3 / Flat-top**：用平台维持环电压、剩余伏秒、PF 位形保持、Div 打击点与 VS 裕度描述平顶维持。

项目现在从早期的结构验证阶段“经验型阶段插值说明”，升级为：**在简化 SPARC 边界下，按三阶段最小物理链路组织输入、状态传递、波形生成与验证**。

---

## 1. 项目文件结构

```text
Hope02/
├─ README.md
└─ sparc_discharge_waveform_skill/
   ├─ SKILL.md                      # Skill 总入口：Agent 使用规则、阅读顺序、执行边界。
   ├─ 文件目录.md                   # Skill 子目录结构说明。
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
   │  ├─ adapters.py                # 文档输入/输出与结构转换辅助。
   │  ├─ constraints.py             # 公共约束检查预留。
   │  ├─ io.py                      # 公共输入输出工具。
   │  ├─ state.py                   # 公共状态结构。
   │  ├─ utils.py                   # 公共工具预留。
   │  └─ validation.py              # 公共验证辅助。
   │
   ├─ stages/
   │  ├─ stage_1_breakdown/
   │  │  ├─ README.md               # 击穿阶段说明。
   │  │  ├─ example.yaml            # 击穿阶段示例输入。
   │  │  ├─ generate.py             # 击穿阶段生成入口。
   │  │  ├─ models.py               # 击穿阶段数据模型。
   │  │  ├─ physics.py              # 第一阶段物理计算辅助。
   │  │  ├─ validation.py           # 击穿阶段验证。
   │  │  └─ 第一阶段物理过程.md      # 第一阶段详细物理说明。
   │  │
   │  ├─ stage_2_rampup/
   │  │  ├─ README.md               # 电流爬升阶段说明。
   │  │  ├─ example.yaml            # 爬升阶段示例输入。
   │  │  ├─ generate.py             # 爬升阶段生成入口。
   │  │  ├─ models.py               # 爬升阶段数据模型。
   │  │  ├─ validation.py           # 爬升阶段验证。
   │  │  └─ 第二阶段物理过程.md      # 第二阶段详细物理说明。
   │  │
   │  └─ stage_3_flattop/
   │     ├─ README.md               # 平顶阶段说明。
   │     ├─ example.yaml            # 平顶阶段示例输入。
   │     ├─ generate.py             # 平顶阶段生成入口。
   │     ├─ models.py               # 平顶阶段数据模型。
   │     ├─ validation.py           # 平顶阶段验证。
   │     └─ 第三阶段物理过程.md      # 第三阶段详细物理说明。
   │
   └─ outputs/
      ├─ README.md                  # 输出目录说明。
      ├─ sparc_demo_discharge/      # Pipeline 示例输出。
      ├─ stage_1_breakdown/         # Stage 1 单独运行输出。
      ├─ stage_2_rampup/            # Stage 2 单独运行输出。
      └─ stage_3_flattop/           # Stage 3 单独运行输出。
```

推荐从 `sparc_discharge_waveform_skill/SKILL.md`、`sparc_discharge_waveform_skill/docs/02_facility_and_constraints.md`、`sparc_discharge_waveform_skill/docs/03_workflows.md` 和 `sparc_discharge_waveform_skill/pipeline/README.md` 开始阅读。

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

本项目现在采用的不是纯经验插值口径，而是**三阶段最小真实物理约束流程**：

```text
用户目标放电需求
  → 统一输入文件
  → Breakdown：击穿电路与零场预置
  → Ramp-up：Ip / Lp / Rp / CS 伏秒 / PF 成形
  → Flat-top：平台维持环电压 / PF 保持 / Div / VS 裕度
  → 阶段间状态交接
  → 合并三阶段波形
  → 输出验证报告和修正建议
```

### 3.1 用户输入的不是线圈电流，而是放电目标

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

### 3.2 三阶段物理过程

#### Stage 1：Breakdown 击穿

目标：形成初始等离子体并建立种子电流。

核心口径：

- 用目标 `Ip_seed` 构造简化 `Ip(t)`；
- 用 \(V_{loop}=L_0\,dI_p/dt + R_p I_p\) 检查击穿所需环电压；
- 用 \(V_{loop,CS}=-M_{CS}\,dI_{CS}/dt\) 反推 CS swing；
- 用 PF 场系数矩阵约束击穿点零场预置；
- 输出 `handoff_to_stage_2`。

#### Stage 2：Ramp-up 电流爬升

目标：把 `Ip` 从种子电流升到平顶目标，同时逐步形成目标位形。

核心口径：

- 给定 `Ip(t)`、`shape(t)`；
- 计算 \(L_p(t)\)、\(R_p(t)\)、\(V_{loop,req}(t)\)；
- 用 CS 互感方程反推 `CS1/CS2/CS3`；
- 用 Shafranov 型垂直场需求与 PF 响应矩阵求解 `PF1-4`；
- 统计 Ramp-up 伏秒消耗与剩余裕度；
- 输出 `handoff_to_stage_3`。

#### Stage 3：Flat-top 平顶维持

目标：维持目标平顶电流、位形、X 点与偏滤器构型。

核心口径：

- 以平台保持为主，`dIp/dt` 接近 0；
- 用 \(V_{loop,req}=d(L_p I_p)/dt + R_p I_p\) 计算低环电压维持需求；
- 用 CS 互感关系估算平台伏秒消耗；
- 用 PF 响应矩阵维持位形和 X 点；
- 用 Div 维持或微扫打击点；
- 用 VS 只输出基准值和稳定裕度；
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

```text
装置假设文档
  → 统一输入模板
  → Pipeline 总控
  → 三个阶段工作包
  → 公共状态与验证结构
  → 输出报告
```

Agent 不需要凭空设计完整波形，而应按固定步骤读取文件、理解阶段边界、检查交接状态、运行 Pipeline、读取输出并给出修改建议。

### 5.2 Agent 看到本 Skill 后应该怎么工作

推荐工作流如下：

1. 先阅读 `SKILL.md`、`README.md`、`docs/02_facility_and_constraints.md`；
2. 再阅读 `docs/03_workflows.md`、`pipeline/README.md`、`pipeline/state_schema.md`；
3. 明确三阶段已升级为“最小真实物理约束流程”，不是纯经验阶段插值；
4. 读取 `config/input_template.yaml` 识别用户目标与装置约束；
5. 运行 `pipeline/run_pipeline.py` 或按同一数据流做人工推演；
6. 检查 `outputs/<case_name>/` 下的过程状态、报告和建议；
7. 优先建议调整输入目标、阶段时长、伏秒预算和成形目标，而不是跳过物理约束直接声称通过。

### 5.3 各目录在 Skill 中的角色

| 目录 | 在 Skill 中的作用 |
|---|---|
| `docs/` | 提供物理背景、装置假设、阶段工作流和 I/O 规则。 |
| `config/` | 提供统一输入入口。 |
| `pipeline/` | 把三阶段组织成完整流程，是运行总入口。 |
| `stages/` | 提供各阶段的目标、输入、物理链路、验证与交接约定。 |
| `common/` | 放置公共状态、读写和验证工具。 |
| `outputs/` | 保存波形、状态、报告和修正建议。 |

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

判断项目是否完成的重点不是“波形是否最优”，而是：

- 装置假设是否清楚；
- 三阶段拆解是否合理；
- 物理链路是否自洽；
- 阶段间状态是否连续；
- 约束检查是否覆盖主要风险；
- Agent 是否能根据 Skill 文档稳定复现流程。

---

## 7. 一句话总结

本项目将“托卡马克放电线圈电流波形设计”封装成一个可运行、可复查、可由 Agent 执行的 Skill：在简化 SPARC 装置边界下，以三阶段最小真实物理约束模型组织 Breakdown、Ramp-up、Flat-top，生成 CS / PF / Div / VS 候选波形，并输出验证报告与修正建议。
