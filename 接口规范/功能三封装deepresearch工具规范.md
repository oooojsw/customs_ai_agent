这是最终整合了三级加载架构、隐式状态流转（数据隧道）以及LLM按需感知机制的像素级实施规范。这份文档直接面向 Cursor，确保其能够构建出生产级的智能体流水线。

📑 任务指令书：Agent 全栈技能系统与隐式数据流转 (LangGraph v1.0)
1. 核心设计哲学

数据隧道机制：大文本（如几千字的报告）存储在 AgentState 的隐藏字段中。生产者工具写入，消费者工具读取，LLM 仅通过“摘要”感知。

按需感知：LLM 默认不读取全文以节省 Token 和保持界面整洁，仅在用户追问细节时通过特定工具调阅。

零杂文输出：自动化任务链执行过程中，严禁在聊天窗口展示中间过程的冗长文本。

2. 状态管理 (State Schema)

请在 src/types/state.py 或 src/services/chat_agent.py 中定义：

code
Python
download
content_copy
expand_less
from typing import TypedDict, Annotated, List, Optional
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage

class AgentState(TypedDict):
    # 1. 消息历史：标准对话流
    messages: Annotated[List[BaseMessage], add_messages]
    
    # 2. 报告缓冲区：存放生成的 Markdown 全文（数据隧道）
    # 对 LLM 隐藏，除非调用 read_report_buffer
    report_buffer: str 
    
    # 3. 元数据状态：记录当前生成的报告主题、字数、核心结论摘要
    report_metadata: dict
3. 基础设施层规范
3.1 静态目录挂载 (src/main.py)
code
Python
download
content_copy
expand_less
# 必须挂载以支持文件下载链接
os.makedirs("data/exports", exist_ok=True)
app.mount("/downloads", StaticFiles(directory="data/exports"), name="downloads")
3.2 脚本执行器 (src/services/script_executor.py)

使用 subprocess 运行隔离进程：

输入：脚本路径 + JSON 字符串参数。

输出：解析 stdout 为 JSON。

安全：强制 20秒 超时，捕获 stderr 错误。

4. 核心技能工具链 (Tools Implementation)
4.1 生产者：合规报告引擎 (compliance_reporter)

工具名：generate_compliance_report

逻辑：调用现有 ComplianceReporter 逻辑生成全文。

关键实现：

将 全文 写入 report_buffer 状态。

构造 简短摘要（主题、结论、各章标题）。

通过 Command(update={...}) 返回摘要。

LLM 感知：此时 LLM 知道报告已生成及其大概内容，但 Context 中不含全文。

4.2 消费者：文档导出专家 (document_exporter)

工具名：export_document_file

参数注入：使用 Annotated[str, InjectedState("report_buffer")]。

逻辑：

检查 report_buffer 是否有内容。

调用 L4 脚本 export_engine.py。

返回极简下载链接：✅ 转换成功：[文件名.pdf](/downloads/xxx.pdf)。

4.3 显微镜：缓冲区调阅工具 (read_report_buffer)

工具名：read_report_buffer

描述："当用户询问报告中某个具体章节的理由、法律依据或细节时使用。"

逻辑：从 report_buffer 中提取相关文本返回给消息流。

5. L4 执行脚本规范 (data/skills/document_exporter/scripts/export_engine.py)

PDF 引擎：使用 weasyprint 或 pdfkit。必须配置 UTF-8 编码和支持中文字体的 CSS（如 font-family: "Source Han Sans CN"）。

Word 引擎：使用 python-docx。将 Markdown 的 # 映射为一级标题，## 映射为二级标题。

清理逻辑：脚本内需自动剔除 Markdown 中的 YAML 头部或可能的调试标签。

6. Prompt Engineering 指令 (System Prompt)

请在 Agent 的系统提示词中硬编码以下工作流守则：

code
Text
download
content_copy
expand_less
【内部状态感知规则】
1. 你拥有一个名为 `report_buffer` 的系统缓冲区。
2. 当调用 `generate_compliance_report` 后，全文将存入缓冲区。你仅会收到一份“内容摘要”。
3. 如果用户要求下载或转成文件，请直接调用 `export_document_file`，无需复述正文。

【全自动任务链逻辑】
- 若用户指令为“写份报告并下载 PDF”：
  第一步：调用 `generate_compliance_report`。
  第二步：识别摘要中的生成状态。
  第三步：静默调用 `export_document_file`。
  第四步：仅回复用户下载链接和核心结论，严禁展示报告原文。

【细节查阅规则】
- 若用户针对已生成的报告提问（如“理由是什么？”），请调用 `read_report_buffer` 工具查看细节后再回答。
7. 验收测试用例 (Test Cases)
场景 A：全自动链路测试

输入：帮我写一份关于“二手挖掘机进口”的合规建议书，直接给我 Word 版。

预期动作：

工具 generate_compliance_report 运行。

工具 export_document_file 运行。

预期结果：输出中不包含报告正文，仅包含一个 Word 下载链接。

场景 B：按需感知测试

前提：已完成场景 A。

输入：报告中提到的第二项风险，具体的法律依据是哪一条？

预期动作：Agent 调用 read_report_buffer 查阅缓冲区。

预期结果：Agent 给出具体的法律条款（如《海关法》第XX条）。

8. 给 Cursor 的技术提醒

** InjectedState 必须准确**：确保 InjectedState("report_buffer") 中的 Key 与 AgentState 定义的 Key 完全一致。

异步兼容性：generate_compliance_report 涉及长时间 I/O，必须使用 async def 定义。

Command 返回：在 LangGraph 中，修改非消息字段（如 report_buffer）必须通过返回 Command(update={...}) 实现。

请 Cursor 开始执行：先定义 State，再实现逻辑层，最后在 chat_agent.py 中编排工具。