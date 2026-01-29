这是一个非常专业的改进方向。渐进式读取（Progressive Loading） 的核心目的是解决“上下文爆炸”问题——如果你的技能库有 100 个技能，一次性塞进 Prompt 会让模型变笨且浪费 Token。

为了让 Cursor 实现“像素级”的渐进式读取，我们需要将加载逻辑拆分为 三级缓存模型。请将以下规范提供给 Cursor：

📋 任务指令书：Skill 系统渐进式读取（Progressive Loading）深度增强规范
1. 核心逻辑：三级加载架构

请重新设计并实施 Skill 的加载机制，严格遵守以下三个层级，以节省 Token 并提高检索精度：

L1：索引层（Discovery）：Agent 启动时只读取技能的 name 和 description。这是“技能清单”。

L2：指令层（Execution）：只有当 Agent 调用 use_skill 时，才读取 SKILL.md 的正文内容。

L3：资源层（Resource）：如果技能文件夹内包含其他辅助文件（如 .csv, .json），Agent 只有在阅读完 L2 指令后，认为有必要时才调用 read_skill_resource 工具读取。

2. 文件系统变更规范

请调整 data/skills/ 的内部结构，以支持 L3 级资源读取：

code
Text
download
content_copy
expand_less
data/skills/{skill_name}/
├── SKILL.md            # (L1 & L2) 包含元数据和核心操作步骤
└── resources/          # [新增] 存放该技能专属的庞大数据文件
    ├── data_table.csv  # 例如：HS编码对照表
    └── info.json       # 例如：特定港口的作业代码
3. SkillManager 类接口增强 (Service Layer)

请在 src/services/skill_manager.py 中更新以下接口，以实现物理隔离加载：

3.1 增强型 __init__

初始化时，严禁将全量文件内容读入内存。只解析 YAML 头部的 name 和 description，并记录文件路径。

3.2 新增 list_resources(self, skill_name: str) -> list

返回该技能 resources/ 目录下所有文件的文件名列表。

3.3 新增 get_resource_content(self, skill_name: str, file_name: str) -> str

读取具体的 L3 资源文件。

安全校验：必须验证路径，防止 Agent 通过 ../ 攻击读取系统其他文件。

4. Agent 智能工具链更新 (Agent Tools)

请在 src/services/chat_agent.py 中实现工具的“套娃”调用逻辑：

4.1 更新 use_skill 工具

功能逻辑变更：

加载 SKILL.md 的 L2 正文。

调用 list_resources 检查是否有附加资源。

关键 Prompt 注入：在返回的手册中告诉 Agent：“本技能拥有以下数据资源：[资源列表]。如需查看细节，请调用 read_skill_resource 工具。”

4.2 新增 read_skill_resource 工具

描述："当已激活的技能手册中提到需要查询特定数据文件时使用。输入参数：skill_name, file_name。"

实现：调用 skill_manager.get_resource_content 并返回给模型。

5. 运行流程规范 (Workflow)

请确保 Agent 遵循以下渐进式思考链路：

用户问：“帮我查下这票货的港口附加费。”

Agent 查索引 (L1)：发现 port_fee_query 技能描述匹配。

调用 use_skill (L2)：获取到手册。手册写着：“请查阅 resources 目录下的 fees.json 获取最新费率”。

调用 read_skill_resource (L3)：读取 fees.json 的具体内容。

最终回答：根据读取到的 JSON 数据给出精确结果。

6. 验收技术指标 (Metrics)

Token 占用率：在不调用任何技能时，System Prompt 中关于技能的部分不得超过全量的 5%。

按需加载验证：通过日志观察，确保只有在特定问题下才会触发对应技能目录的文件读取（I/O 延迟应只出现在工具调用阶段）。

资源可见性：Agent 在没调用 use_skill 之前，不应该知道 resources/ 下有哪些具体文件。

请 Cursor 立即开始执行：先调整文件结构，再更新 SkillManager 接口，最后重构 ChatAgent 的工具集。