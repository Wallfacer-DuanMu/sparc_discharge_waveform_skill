阅读以下文件：

任务要求：@00任务要求.md 
方案大致方向：@01方案方向.md 
方案具体规划：@05线圈行为准则.md 
方案文件目录：@sparc_discharge_waveform_skill/文件目录.md 
本方案简化的实验设施与约束条件：@sparc_discharge_waveform_skill/docs/02_facility_and_constraints.md 
项目摘要：@sparc_discharge_waveform_skill/docs/01_project_summary.md 
简化版本的数据流向讲解@12数据流逻辑.md 
------

本阶段任务目标是，完成第三阶段的搭建，它包括下面文件：

│  └─ stage_3_flattop/
│     ├─ README.md               # 第三阶段工作包说明：目标、输入、计算步骤、输出、验证项。
│     ├─ example.yaml            # 第三阶段输入案例。
│     ├─ generate.py             # 第三阶段主入口：生成 Flat-top 候选波形。
│     ├─ models.py               # 第三阶段简化模型：稳态维持、Div 微调、VS 裕度等。
│     └─ validation.py           # 第三阶段验证：边界、X 点、打击点、剩余伏秒等检查。




注意，我们这个是学生作业，不追求复杂的极致工程性，而是追求整体思路的流畅完整性，简洁干练是我们的宗旨，一定要避免复杂冗余。

