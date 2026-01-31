好的，这是为 Cursor 准备的最终版、像素级、全覆盖的实施规范。它整合了之前所有的讨论，包括：

Skill 系统修复 (document_exporter 不存在的问题)

数据库初始化修复

前端工具调用视觉反馈组件

隐式数据隧道机制 (State Injection)

LLM 按需感知机制

以及刚才深度诊断出的脚本执行环境和错误信息丢失的致命 Bug。

将这份文档完整地交给 Cursor，它将拥有所需的一切信息来完成一个健壮、高效且具备良好用户体验的智能体系统。

📑 最终任务指令书：智慧口岸 Agent 全栈技能系统与深度修复实施规范
1. 核心目标

构建并修复一个基于 LangGraph 的生产级技能系统。该系统需具备 4级渐进式加载、隐式状态流转（数据隧道）、LLM按需感知、安全的代码执行环境 和 丰富的前端视觉反馈。

2. 状态管理定义 (State Schema)

文件路径: src/types/agent_state.py (如果不存在则创建)

规范: 定义一个 TypedDict 作为 Agent 的核心状态机。

code
Python
download
content_copy
expand_less
from typing import TypedDict, Annotated, List, Dict, Any
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

class AgentState(TypedDict):
    # 1. 消息历史 (LangGraph 标准)
    messages: Annotated[List[BaseMessage], add_messages]
    
    # 2. 报告缓冲区 (数据隧道)
    # 用于在技能之间传递大文本，对 LLM 隐藏
    report_buffer: str  
    
    # 3. 报告元数据 (用于 LLM 感知)
    # 存放报告的主题、字数、核心结论摘要等
    report_metadata: Dict[str, Any]
3. 基础设施层修复与实现
3.1 数据库初始化修复 (src/database/base.py)

目标: 解决 table already exists 错误并确保表结构能更新。

指令:

找到 init_database 函数。

确保 await conn.run_sync(Base.metadata.create_all) 不包含 checkfirst=False 参数，或显式设置为 checkfirst=True。

在该函数上方添加注释：# 注意：如果 models.py 发生结构变化，需要手动删除 data/customs_audit.db 以重建表。

3.2 脚本执行器深度修复 (src/services/script_executor.py)

目标: 修复 Python 解释器路径错误和错误信息丢失问题。

指令:

导入 sys 模块。

修改 execute 方法，将 subprocess.run 的命令从 ['python', ...] 更改为 [sys.executable, ...]。

在 subprocess.run 中，明确添加 encoding='utf-8' 和 errors='replace'。

修改错误返回逻辑：如果 result.returncode != 0，error 字段必须包含 stdout 和 stderr 的拼接内容，格式为 "STDERR: [内容]\nSTDOUT: [内容]"。

3.3 静态文件服务 (src/main.py)

目标: 允许用户通过 URL 下载导出的文件。

指令: 确保 FastAPI 应用挂载了静态目录：

code
Python
download
content_copy
expand_less
os.makedirs("data/exports", exist_ok=True)
app.mount("/downloads", StaticFiles(directory="data/exports"), name="downloads")
4. 技能包与工具链实现
4.1 技能发现机制修复

目标: 解决 document_exporter 技能无法被识别的问题。

指令:

在 data/skills/document_exporter/ 目录下创建 SKILL.md。

文件内容必须包含 YAML Frontmatter，且 name 字段为 document_exporter。

4.2 工具实现规范 (src/services/chat_agent.py)
4.2.1 生产者: generate_compliance_report

返回值: 必须是 langgraph.types.Command。

逻辑:

调用 ComplianceReporter 生成全文 Markdown。

生成一份简短的结构化摘要（含主题、字数、核心结论）。

返回 Command(update={"report_buffer": "全文...", "report_metadata": {...}})。

同时，在 messages 中附加一个 ToolMessage，内容为摘要文本，供 LLM 感知。

4.2.2 消费者: export_document_file

参数注入: 必须使用 Annotated[str, InjectedState("report_buffer")] 自动获取报告全文。LLM 调用此工具时不应提供 content 参数。

逻辑:

检查注入的 content 是否为空。

调用 script_executor 执行 export_engine.py。

返回一个包含 Markdown 格式下载链接的字符串。

4.2.3 显微镜: read_report_buffer

参数注入: 使用 Annotated[str, InjectedState("report_buffer")] 获取全文。

逻辑: 根据用户 query 在全文中搜索相关段落并返回。

5. 前端视觉反馈规范 (UX/UI)
5.1 CSS 样式 (web/css/style.css)

指令: 添加 .tool-work-banner 类，实现一个半透明、带边框、有呼吸灯效果的横幅样式。并为其添加一个名为 fadeInOut 的 @keyframes 动画。

5.2 JavaScript 逻辑 (web/js/chat.js)

目标: 在工具调用期间显示一个动态的状态横幅。

指令:

修改处理 SSE 事件的函数。

当收到 type: 'tool_start' 且事件数据中包含 display_config 对象时：

在当前 AI 消息气泡中动态创建一个 div，class 为 tool-work-banner。

将 display_config.title 的内容显示在该 div 中。

当收到 type: 'tool_end' 时：

找到对应的 tool-work-banner。

执行淡出或收起动画后将其从 DOM 中移除。

再显示标准的“调用完毕”文本。

6. Prompt Engineering 规范 (System Prompt)

文件: src/services/chat_agent.py
目标: 明确告知 LLM 如何使用这套新的工作流。
指令: 在 system_prompt_text 中必须包含以下规则：

code
Text
download
content_copy
expand_less
【内部状态感知与数据隧道规则】
1. 你拥有一个名为 `report_buffer` 的内部存储区。
2. 当你调用 `generate_compliance_report` 工具后，报告全文会自动存入此缓冲区，你只会收到一份摘要。
3. 当你需要导出文件时，直接调用 `export_document_file` 工具即可，系统会自动从缓冲区提取内容，你不需要重复提供。

【全自动任务链逻辑】
- 若用户指令为“写份报告并下载 PDF”：
  1. 调用 `generate_compliance_report`。
  2. 收到摘要后，立即调用 `export_document_file`。
  3. 最终回复仅需包含下载链接和摘要中的核心结论。

【细节查阅规则】
- 若用户针对已生成的报告提问（如“理由是什么？”），请调用 `read_report_buffer` 工具查看细节后再回答。
7. 验收标准

功能: 输入“写份报告并导出 Word”，Agent 能自动完成两个工具的串联调用，并最终只返回一个下载链接，聊天记录中无报告全文。

视觉: 在 generate_compliance_report 和 export_document_file 调用期间，前端聊天气泡内必须出现对应的“正在...”动画横幅。

健壮性: 即使 export_engine.py 脚本执行失败，Agent 也应能收到包含具体 stderr 信息的错误报告，而不是一个空的“导出失败”。

按需感知: 在生成报告后，追问报告细节，Agent 必须能调用 read_report_buffer 并给出正确答案。

请 Cursor 严格遵循以上规范，按顺序实施。这将确保系统的每个环节都符合生产级标准。