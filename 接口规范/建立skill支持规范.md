没问题。这份文档将作为给 Cursor 的**“绝对执行指令”。它不包含具体的 Python 代码实现（因为 Cursor 会写），但它定义了文件结构、数据协议、类接口、逻辑流程和Prompt规范**，精确到每一个字段和步骤。

你可以将以下内容直接复制给 Cursor，告诉它：“请严格按照这份设计规范实施开发。”

📋 任务指令书：智慧口岸 Agent 技能插件系统 (Skill System) 实施规范
1. 项目目标

在现有的 customs_ai_agent 项目中，新增一套动态技能（Skill）系统。该系统允许通过添加 Markdown 配置文件的方式，动态扩展 Agent 的能力（如 HS 编码归类、税费计算等），而无需修改核心代码。

2. 文件系统变更规范

请在项目根目录下创建以下目录和文件结构：

2.1 新增目录

data/skills/：用于存放所有技能包的根目录。

src/services/skill_manager.py：新增的技能管理服务模块。

2.2 数据文件标准 (Data Protocol)

在 data/skills/ 下，每个子文件夹代表一个技能。必须包含一个核心定义文件 SKILL.md。

SKILL.md 文件格式规范：

Frontmatter (YAML 头)：必须包含 name (技能ID) 和 description (技能用途简述)。

Body (Markdown 正文)：包含具体的执行指令、角色定义、步骤说明。

请创建以下 2 个默认技能作为测试数据：

技能 1：HS 编码归类顾问

路径：data/skills/hs_code_advisor/SKILL.md

YAML：

code
Yaml
download
content_copy
expand_less
name: hs_code_advisor
description: 帮助用户查询商品的HS编码。当用户询问商品归类、税号或编码时使用。

正文内容：定义海关归类专家的角色，要求先提取商品要素（品名、材质、用途），然后基于推理给出建议编码。

技能 2：进口税费计算器

路径：data/skills/tax_calculator/SKILL.md

YAML：

code
Yaml
download
content_copy
expand_less
name: tax_calculator
description: 估算进口商品的关税和增值税。当用户询问“这货要交多少税”时使用。

正文内容：定义计算逻辑（关税=完税价格×关税率，增值税=(完税价格+关税)×增值税率），并要求用户提供 CIF 价格。

3. 后端服务层规范 (Service Layer Specification)

请在 src/services/skill_manager.py 中实现 SkillManager 类。

3.1 依赖项

pathlib, os：用于文件操作。

yaml (PyYAML)：用于解析 Frontmatter。

3.2 类接口定义 (Interface)

__init__(self)：初始化时自动扫描 data/skills 目录。

_discover_skills(self)：

遍历目录。

解析每个 SKILL.md 的 YAML 头。

将合法的技能存储在内存字典中：{name: {description, path}}。

get_skill_registry_text(self) -> str：

返回一个格式化的字符串，用于注入 System Prompt。

格式要求：- {name}: {description} (每行一个)。

load_skill_content(self, skill_name: str) -> str：

接收技能名称。

读取对应的 SKILL.md 文件。

关键处理：移除 YAML 头，只返回 Markdown 正文部分（即操作手册）。

4. Agent 核心改造规范 (Agent Core Modification)

请修改 src/services/chat_agent.py 中的 CustomsChatAgent 类。

4.1 初始化逻辑

在 __init__ 方法中实例化 SkillManager。

调用 skill_manager.get_skill_registry_text() 获取技能清单字符串。

4.2 Prompt 工程规范 (Prompt Engineering)

修改 self.system_prompt_text，在原有的设定之后，追加以下逻辑块：

code
Text
download
content_copy
expand_less
【扩展能力中心】
你现在连接到了外部技能库，拥有以下特殊能力：
{skills_registry_text}

【调度策略】
当用户的意图与上述某个技能的描述高度匹配时，请**优先**激活该技能。
激活方式：调用 `use_skill` 工具，并传入技能名称。
一旦获取到技能的操作手册，请严格按照手册中的步骤执行后续推理。
4.3 工具注册规范 (Tool Registration)

新增一个 LangChain Tool，并添加到 self.tools 列表中。

工具名称：use_skill

工具描述："激活特定技能以获取详细操作指导。输入参数：skill_name（必须精确匹配技能列表中的名称），query（用户的具体问题）。"

实现逻辑：

接收 skill_name。

调用 skill_manager.load_skill_content(skill_name) 获取手册内容。

返回一个 Prompt 字符串，告诉 LLM：“你已激活 [skill_name]。请根据以下手册处理用户问题：\n\n [手册内容]”。

5. 验收标准 (Acceptance Criteria)

启动检查：服务启动时，控制台应打印出“已加载 Skill: hs_code_advisor, tax_calculator”。

归类测试：

用户输入：“我要进口一批棉制男式衬衫，编码是多少？”

日志显示：Agent 调用了 use_skill(skill_name="hs_code_advisor")。

Agent 回复：按照 SKILL.md 中定义的步骤（先问材质用途，再给编码）进行回复。

普通对话测试：

用户输入：“你好”。

Agent 不调用 use_skill，直接回复。

请 Cursor 按照以上规范，分步创建文件并修改代码。