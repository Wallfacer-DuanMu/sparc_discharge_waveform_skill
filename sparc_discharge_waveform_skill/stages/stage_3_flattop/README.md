# Stage 3：Flat-top 阶段工作包说明

本工作包用于生成 SPARC 放电波形规划中的第三阶段：Flat-top。该阶段从第二阶段 Ramp-up 的末端状态出发，在目标平台电流附近维持等离子体电流、边界形状、X 点和偏滤器构型，并检查 CS 剩余伏秒、PF 平衡裕度、Div 打击点调节能力和 VS 稳定裕度。

## 1. 阶段定位

Flat-top 是三阶段离线波形设计的维持与验收阶段。它不是重新从零寻找一套大幅变化的线圈波形，而是在 Ramp-up 已经完成升流和成形的基础上，继续生成一段平稳、可评审、可与前两阶段拼接的候选波形。

该阶段重点关注：

- 平台等离子体电流 `Ip_flat` 的保持
- `CS1/CS2/CS3` 的慢速维持变化与剩余伏秒检查
- `PF1/PF2/PF3/PF4` 的平顶工作点保持和小幅慢调
- `Div1/Div2` 的打击点设定或小幅扫描
- `VS` 的基准值、可用控制范围和垂直稳定裕度
- 与 Stage 2 输出和最终三阶段总结果之间的数据衔接

## 2. 输入

输入文件通常为 `example.yaml` 或同结构的用户配置文件。推荐包含以下部分：

### 2.1 元信息

- `metadata.case_id`：案例编号
- `metadata.stage`：阶段名称，固定为 `flattop`
- `metadata.description`：案例描述
- `metadata.author`：配置来源或作者
- `metadata.created_at`：创建日期
- `metadata.version`：配置版本

### 2.2 上一阶段交接状态

`handoff_from_stage_2` 描述 Ramp-up 阶段末端状态，作为 Flat-top 初始条件：

- `time_s`：Flat-top 起始时间，通常等于 Ramp-up 结束时间
- `plasma_current_MA`：平顶入口等离子体电流
- `loop_voltage_V`：平顶入口环电压
- `flux_consumed_Wb`：前两阶段累计已消耗磁通
- `flux_remaining_Wb`：进入平顶时剩余 CS 伏秒预算
- `q95`：平顶入口安全因子估计
- `target_shape`：Ramp-up 末端已形成的目标位形
- `coil_currents_kA`：Ramp-up 末端各线圈电流
- `constraint_status`：Stage 2 约束检查状态

### 2.3 Flat-top 目标

`targets` 描述本阶段目标：

- `end_time_s`：Flat-top 结束时间
- `target_plasma_current_MA`：目标平台等离子体电流
- `allowed_current_deviation_MA`：平台电流允许偏差
- `target_loop_voltage_V`：维持电流所需的目标环电压
- `target_q95`：目标边界安全因子
- `target_shape`：目标平顶位形
- `divertor_targets`：偏滤器 X 点和打击点目标
- `min_flux_margin_fraction`：阶段结束时所需最小剩余伏秒比例

### 2.4 波形策略

`waveform_strategy` 描述平顶维持方式：

- `time_grid`：本阶段时间网格
- `plasma_current_hold`：平台电流保持策略
- `loop_voltage_profile`：低环电压维持策略
- `cs_maintenance`：CS 慢速摆动和伏秒消耗策略
- `pf_shape_hold`：PF 形状保持和小幅修正策略
- `divertor_control`：Div 固定设定或打击点扫描策略
- `vs_reserve`：VS 基准值和裕度输出策略

### 2.5 工程限制

`engineering_limits` 描述工程边界：

- 总剩余伏秒、已消耗伏秒和平顶最大允许消耗
- 环电压上下限
- 等离子体电流允许范围与偏差
- 各线圈电流上下限
- 各线圈最大变化率
- CS/PF/Div/VS 电源电压与功率限制

### 2.6 物理与控制约束

`physics_constraints` 与 `control_constraints` 描述平顶可行性和控制要求：

- `q95` 下限和目标值
- 内电感、归一化 beta 与密度范围
- 目标拉长比、三角形变、小半径、磁轴位置容差
- X 点位置和打击点位置容差
- 垂直稳定裕度与 VS 预留比例
- 电流、形状、线圈和打击点跟踪容忍度

## 3. 处理流程

建议实现流程如下：

1. 读取并验证 YAML 配置。
2. 检查 `handoff_from_stage_2` 是否完整，确认起始时间、电流、位形和线圈状态可用。
3. 根据 `targets` 和 `waveform_strategy.time_grid` 构建 Flat-top 时间网格。
4. 生成近似恒定的 `Ip(t)` 平台轨迹，并检查是否落在允许偏差内。
5. 生成低环电压 `loop_voltage(t)`，累计本阶段 CS 伏秒消耗。
6. 让 `CS1/CS2/CS3` 从 Ramp-up 末态开始慢速变化，维持目标电流并保留伏秒裕度。
7. 让 `PF1/PF2/PF3/PF4` 保持在平顶工作点附近，按目标形状、X 点和主半径做小幅慢调。
8. 让 `Div1/Div2` 给出固定工作点或小幅扫描，用于偏滤器打击点微调。
9. 输出 `VS` 基准电流和可用控制范围，不生成高频反馈细节。
10. 检查工程限制、物理约束和控制裕度。
11. 输出结构化结果，供三阶段总波形拼接和最终报告使用。

## 4. 输出

推荐输出结构包括：

```yaml
stage: flattop
status: valid
summary:
  start_time_s: 3.0
  end_time_s: 8.0
  target_plasma_current_MA: 8.7
  mean_plasma_current_MA: 8.7
  flux_consumed_Wb: 12.5
  flux_margin_fraction: 0.48
waveforms:
  time_s: []
  plasma_current_MA: []
  loop_voltage_V: []
  flux_consumed_Wb: []
  flux_remaining_Wb: []
  flux_margin_fraction: []
  q95: []
  elongation: []
  triangularity: []
  x_point: {}
  strike_points: {}
  coil_currents_kA: {}
auxiliary_settings:
  divertor_setting: {}
  vs_reserved_range_kA: {}
constraints:
  passed: []
  warnings: []
  violations: []
final_state:
  time_s: 8.0
  plasma_current_MA: 8.7
  coil_currents_kA: {}
  flux_remaining_Wb: 0.0
  shape: {}
  divertor_setting: {}
  vs_reserved_range_kA: {}
```

## 5. 验证项

至少应验证以下内容：

- 起始时间与 Stage 2 结束时间一致。
- 起始等离子体电流与 Stage 2 输出一致。
- 起始线圈电流、目标形状和剩余伏秒字段完整。
- Flat-top 结束时间大于起始时间。
- `Ip(t)` 保持在目标平台电流容忍范围内。
- 环电压处于低维持区间，且不超过电源限制。
- 平顶阶段 CS 伏秒消耗不超过预算。
- 阶段结束时剩余伏秒比例不低于 `min_flux_margin_fraction`。
- 各线圈电流不超过上下限。
- 各线圈电流变化率不超过限制。
- PF 波形保持平滑，不出现非物理阶跃。
- 目标拉长比、三角形变、小半径和磁轴位置满足容差。
- X 点位置和打击点位置满足简化容差。
- Div 只承担打击点细调，不参与主升流或大幅平衡修正。
- VS 不生成离线快速反馈波形，但保留足够控制裕度。
- 输出 `final_state` 字段完整，可用于最终三阶段汇总。

## 6. 与其他阶段的数据关系

### 来自 Stage 2

Flat-top 使用 Stage 2 的末端数据作为初始条件，尤其是：

- Ramp-up 结束时间
- 平顶入口等离子体电流
- 平顶入口环电压
- 累计已消耗磁通与剩余伏秒
- 平顶入口线圈电流
- 目标位形状态
- Ramp-up 约束检查状态

### 输出到最终总结果

Flat-top 是三阶段链路的最后一个工作包，应向最终汇总传递：

- 完整平顶阶段波形
- 平顶末端线圈状态
- 平顶期间 CS 伏秒消耗和最终剩余裕度
- PF 位形保持检查结果
- Div 打击点设定或扫描结果
- VS 稳定裕度范围
- 平顶阶段约束检查结果与修正建议

## 7. 文件约定

本目录建议包含：

- `README.md`：阶段说明与数据契约
- `example.yaml`：最小可运行输入案例
- `models.py`：数据模型定义
- `validation.py`：输入与输出校验逻辑
- `generate.py`：波形生成入口

当前 README 主要定义 Stage 3 的输入输出结构和实现边界，后续代码应优先保持与 `example.yaml` 的字段一致。

## 8. 简化建模口径

本阶段采用如下简化口径：

- `TF` 继续作为固定背景环向场，不生成动态波形。
- `CS` 只做慢速维持变化，重点检查剩余伏秒和平顶持续时间。
- `PF1/PF2` 主要维持边界、拉长比和三角形变。
- `PF3/PF4` 主要维持整体平衡、主半径、X 点和偏滤器入口位形。
- `Div1/Div2` 用于平顶打击点细调，可固定工作点或小幅扫描。
- `VS` 只输出基准值和允许控制范围，不做实时反馈求解。

一句话概括：Flat-top 阶段的核心不是“大幅再成形”，而是“接住 Ramp-up 的末态，稳定维持目标平台，并证明仍有伏秒、形状和控制裕度”。
