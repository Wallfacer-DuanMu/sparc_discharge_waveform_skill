# Stage 2：Ramp-up 阶段工作包说明

> 快速跳转：[`第二阶段物理过程.md`](./第二阶段物理过程.md)

本工作包用于生成 SPARC 放电波形规划中的第二阶段：Ramp-up。该阶段从第一阶段 Breakdown 的末端状态出发，构建等离子体电流、线圈电流、PF 控制量与主要工程约束随时间爬升的结构化描述。

当前版本的关键变化是：Ramp-up 已从“经验爬升公式说明”升级为**最小真实物理约束模型说明**。它的主线不再只是给出一条 `Ip` 曲线，而是明确围绕 `Ip(t)`、`L_p(t)`、`R_p(t)`、CS 伏秒消耗与 PF 响应矩阵成形来组织输入、计算和验证。

## 1. 阶段定位

Ramp-up 阶段连接 Breakdown 与后续 Flat-top 阶段，核心目标是在满足电源、线圈、等离子体稳定性与控制约束的前提下，将等离子体电流从击穿后的初始电流水平提升到目标平台电流，并逐步形成平顶所需位形。

该阶段重点关注：

- 等离子体电流 `Ip` 的爬升轨迹
- `L_p(t)`、`R_p(t)`、`V_loop_required(t)` 的物理链路
- 中心螺线管电流演化与伏秒预算
- PF1/2/3/4 的平衡与成形职责
- 安全因子、内电感、等离子体形状等关键物理量
- 工程约束与控制裕度
- 与 Stage 1 输出、Stage 3 输入之间的数据衔接

## 2. 输入

输入文件通常为 `example.yaml` 或同结构的用户配置文件。推荐包含以下部分：

### 2.1 元信息

- `metadata.case_id`：案例编号
- `metadata.stage`：阶段名称，固定为 `rampup`
- `metadata.description`：案例描述
- `metadata.author`：配置来源或作者
- `metadata.created_at`：创建日期

### 2.2 上一阶段交接状态

`handoff_from_stage_1` 描述 Breakdown 阶段末端状态，作为 Ramp-up 初始条件：

- `time_s`：阶段起始时间
- `plasma_current_MA`：初始等离子体电流
- `loop_voltage_V`：交接环电压
- `flux_consumed_Wb`：已消耗磁通
- `plasma_state`：击穿后等离子体状态
- `coil_currents_kA`：上一阶段末端线圈电流

### 2.3 Ramp-up 目标

`targets` 描述本阶段目标：

- `end_time_s`：Ramp-up 结束时间
- `target_plasma_current_MA`：目标等离子体电流
- `target_shape`：目标等离子体形状
- `target_q95`：目标边界安全因子
- `max_flux_consumption_Wb`：本阶段允许磁通消耗上限

### 2.4 波形策略

`waveform_strategy` 描述电流爬升方式：

- `current_ramp.mode`：爬升模式，例如 `piecewise_linear`
- `current_ramp.breakpoints`：分段时间点与目标电流
- `shape_evolution`：形状参数随时间变化策略
- `solver`：PF 解算、权重和正则项策略

### 2.5 线圈与电源约束

`engineering_limits` 描述工程边界：

- 线圈电流上限与下限
- 线圈电流变化率限制
- 电源电压限制
- 最大允许磁通消耗
- 热负载或能量限制

### 2.6 物理与控制约束

`physics_constraints` 与 `control_constraints` 描述物理可行性和控制要求：

- 最小安全因子
- 最大归一化 beta
- 垂直稳定性裕度
- 密度爬升限制
- 控制误差容忍度
- 采样时间或控制更新周期

### 2.7 物理参数

本阶段建议显式提供 `physics` 小节，至少包括：

- `cs_mutual_inductance_H`
- `plasma_resistance`
- `internal_inductance`
- `poloidal_beta`
- `pf_response_matrix`
- `pf_shape_gains`
- `solver.weights` 与 `solver.pf_regularization`

## 3. 处理流程

当前实现建议按如下物理链路组织：

1. 读取并验证 YAML 配置。
2. 检查 Stage 1 交接状态是否完整。
3. 根据 `targets` 和 `waveform_strategy` 构建时间网格。
4. 生成 `Ip(t)` 爬升轨迹和 `shape(t)` 位形轨迹。
5. 计算 `li(t)`、`Te(t)`、`R_p(t)` 和 `L_p(t)`。
6. 用等离子体电路方程计算物理环电压需求：

$$
V_{loop,req}(t)=\frac{d}{dt}\left[L_p(t)I_p(t)\right]+R_p(t)I_p(t)
$$

7. 用 CS 互感方程反推 `CS1/CS2/CS3` 电流：

$$
V_{loop,CS}(t)=-\sum_i M_{CS_i}\frac{dI_{CS_i}}{dt}
$$

8. 统计 Ramp-up 阶段伏秒消耗，并检查末端剩余裕度。
9. 用 Shafranov 型近似计算平衡垂直场需求，并通过 PF 响应矩阵求解 `PF1-4`：

$$
I_{PF}=\arg\min_I \|W(C_{PF}I-y_{target})\|_2^2+\lambda\|I-I_{prev}\|_2^2
$$

10. Div 只在后段缓慢进入偏滤器预偏置，VS 只保留基准与裕度。
11. 检查工程限制，包括电流、电压、变化率与磁通预算。
12. 检查物理限制，包括 `q95`、内电感、PF 残差、稳定性与形状演化约束。
13. 输出结构化结果，用于 Stage 3 继续消费。

## 4. 输出

推荐输出结构包括：

```yaml
stage: rampup
status: valid
summary:
  start_time_s: 0.08
  end_time_s: 3.0
  start_plasma_current_MA: 0.15
  end_plasma_current_MA: 8.7
  flux_consumed_Wb: 42.0
waveforms:
  time_s: []
  plasma_current_MA: []
  loop_voltage_V: []
  coil_currents_kA: {}
constraints:
  passed: []
  warnings: []
  violations: []
handoff_to_stage_3:
  time_s: 3.0
  plasma_current_MA: 8.7
  shape: {}
  coil_currents_kA: {}
  flux_remaining_Wb: 0.0
```

建议在当前字段基础上，补充至少以下诊断量：

- `plasma_inductance_H`
- `plasma_resistance_ohm`
- `loop_voltage_required_V`
- `loop_voltage_cs_V`
- `loop_voltage_inductive_V`
- `loop_voltage_resistive_V`
- `cs_flux_used_stage_Wb`
- `cs_flux_remaining_Wb`
- `poloidal_beta`
- `pf_balance_residual`
- `vertical_stability_margin`

## 5. 验证项

至少应验证以下内容：

- 起始时间与 Stage 1 结束时间一致。
- 起始等离子体电流与 Stage 1 输出一致。
- 目标电流大于起始电流。
- Ramp-up 结束时间大于起始时间。
- 电流爬升率不超过配置上限。
- 物理环电压需求不超过电源限制。
- `loop_voltage_cs_V` 与 `loop_voltage_required_V` 的跟踪误差在容差内。
- 线圈电流不超过上下限。
- 线圈电流变化率不超过限制。
- 磁通消耗不超过预算，且末端保留最低伏秒裕度。
- `plasma_inductance_H` 为正且数量级合理。
- `plasma_resistance_ohm` 非负。
- PF 响应矩阵残差 `pf_balance_residual` 不超过容差。
- `q95`、内电感、稳定性裕度和形状参数满足约束。
- 输出的 `handoff_to_stage_3` 字段完整，并包含 Ramp-up 物理诊断字段。

## 6. 与其他阶段的数据关系

### 来自 Stage 1

Ramp-up 使用 Stage 1 的末端数据作为初始条件，尤其是：

- 击穿完成时间
- 初始等离子体电流
- 已消耗磁通
- 初始线圈电流
- 初始环电压

### 传递给 Stage 3

Ramp-up 应向下一阶段传递：

- 平台前目标等离子体电流
- Ramp-up 结束时刻
- 线圈电流状态
- 剩余磁通预算
- 形状与稳定性相关参数
- 约束检查结果

## 7. 文件约定

本目录建议包含：

- `README.md`：阶段说明与数据契约
- `example.yaml`：最小可运行输入案例
- `models.py`：数据模型定义
- `validation.py`：输入与输出校验逻辑
- `generate.py`：波形生成入口

当前 README 的职责，是把 Stage 2 说明成一条清楚的物理链路：**输入 `Ip/shape` 目标，计算 `L_p/R_p/V_loop`，再反推 CS 和 PF，并用伏秒、稳定性与响应残差验证可行性。**
