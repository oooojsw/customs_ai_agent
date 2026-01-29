这是一个决定性的功能升级。赋予 Agent 代码执行能力 (Code Execution) 意味着它不再仅仅是“检索者”，而变成了真正的“计算者”和“行动者”。

为了确保实现的安全性和稳定性，我们将采用 独立的子进程 (Subprocess) + 标准输入输出 (StdIO) 模式。这种方式比 exec() 更安全，且容易调试。

请将以下 《Python 脚本执行引擎实施规范》 发送给 Cursor。

📋 任务指令书：Skill 系统 Python 脚本执行引擎 (Script Execution Engine) 实施规范
1. 项目目标

在现有的 Skill 系统基础上，增加本地 Python 脚本执行能力。
Agent 可以调用存储在技能包中的 .py 脚本，将参数传入脚本，并获取脚本的运行结果（stdout）作为推理依据。

2. 文件系统变更规范

请调整 data/skills/ 的内部结构，增加 scripts 目录：

code
Text
download
content_copy
expand_less
data/skills/{skill_name}/
├── SKILL.md            # L1 & L2 定义
├── resources/          # L3 静态资源 (csv/json)
└── scripts/            # [新增] L4 动态脚本
    └── main.py         # 可执行的 Python 脚本
2.1 创建测试数据

请在 data/skills/tax_calculator/ 下创建 scripts/calculate_duty.py，用于测试：

功能：接收 JSON 字符串参数，计算关税和增值税。

输入参数：{"cif_price": float, "hs_code": str}

逻辑：

如果是 HS "85423100" (芯片)，关税 0%，增值税 13%。

其他，假设关税 5%，增值税 13%。

计算公式：

关税 = CIF * 关税率

增值税 = (CIF + 关税) * 增值税率

输出：打印标准 JSON 字符串到 stdout。

3. 后端服务层规范 (Service Layer)

请创建新文件 src/services/script_executor.py 并更新 SkillManager。

3.1 新增 ScriptExecutor 类

这是一个独立的执行器，负责沙箱化运行代码。

__init__(self, timeout=10)：设置默认超时时间（防止死循环）。

execute(self, script_path: str, args: dict) -> dict：

输入：脚本绝对路径，参数字典。

执行机制：使用 subprocess.run。

参数传递：将 args 字典序列化为 JSON 字符串，作为命令行参数传递给脚本（python script.py '{"k":"v"}'）。

捕获输出：捕获 stdout 和 stderr。

异常处理：

处理 TimeoutExpired。

检查 returncode，非 0 则抛出异常并返回 stderr 内容。

尝试将 stdout 解析为 JSON，解析失败则返回原始文本。

3.2 SkillManager 接口增强

在 src/services/skill_manager.py 中增加：

get_script_path(self, skill_name: str, script_name: str) -> str：

验证路径是否存在。

安全检查：防止 .. 路径遍历攻击。

返回脚本的绝对路径。

4. Agent 核心改造规范 (Agent Layer)

请在 src/services/chat_agent.py 中注册新的执行工具。

4.1 初始化

在 CustomsChatAgent.__init__ 中实例化 self.script_executor = ScriptExecutor()。

4.2 新增 run_skill_script 工具

工具名称：run_skill_script

工具描述："执行技能包中的Python脚本进行复杂计算或处理。输入：skill_name, script_name, args (字典格式的参数)。"

实现逻辑：

调用 skill_manager.get_script_path 获取路径。

调用 script_executor.execute 运行脚本。

返回执行结果（JSON 或 错误信息）。

4.3 Prompt 增强

更新 System Prompt 中的【调度策略】部分：

code
Text
download
content_copy
expand_less
...
【L4 高级能力】
如果技能手册 (SKILL.md) 中指明需要“运行脚本”或“计算”，请使用 `run_skill_script` 工具。
你不需要自己进行复杂的数学计算，将参数提取出来交给脚本即可。
5. 验收测试规范 (Perfect Testing)

请创建一个独立的测试脚本 tests/test_skill_execution.py，包含以下测试用例：

测试 1：基础计算验证

场景：模拟用户输入“进口芯片，货值10000美元，算一下税。”

操作：直接调用 run_skill_script 工具。

skill_name: "tax_calculator"

script_name: "calculate_duty.py"

args: {"cif_price": 10000, "hs_code": "85423100"}

预期：返回 JSON 包含 duty: 0, vat: 1300。

测试 2：错误处理验证 (Robustness)

场景：脚本语法错误或运行时崩溃。

操作：创建一个 broken.py (包含 1/0) 并调用。

预期：工具返回包含 stderr 的错误信息，而不是导致 Agent 崩溃。

测试 3：参数传递验证

场景：参数包含特殊字符（如空格、引号）。

预期：subprocess 参数传递正确，脚本能正确解析 JSON。

6. Python 脚本编写规范 (针对 data/skills 中的脚本)

为了确保脚本能被 Agent 正确调用，所有新增脚本必须遵守：

入口：使用 if __name__ == "__main__":。

输入：通过 sys.argv[1] 接收 JSON 字符串参数。

输出：结果必须打印到 print() (stdout)，推荐使用 JSON 格式。

依赖：仅使用标准库 (json, sys, math 等)，避免引入额外的 pip 依赖以免环境配置复杂化。

请 Cursor 严格按照以上步骤执行：先创建基础设施（Executor），再完善 SkillManager，最后集成到 Agent 并生成测试脚本。