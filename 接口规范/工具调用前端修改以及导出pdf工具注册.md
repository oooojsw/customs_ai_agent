这是一个非常棒的交互优化建议。通过在工具调用时增加**“视觉反馈层”**，可以消除用户等待时的焦虑感，让智能体看起来真的在“思考”和“工作”。

为了让 Cursor 能够精准实现 “修复 document_exporter 报错” 以及 “通用的前端工具调用展示协议”，我为你编写了这份像素级实施规范。

📑 任务指令书：Skill 系统修复与通用工具展示组件实施规范
1. 核心修复：解决 document_exporter 不存在问题
1.1 技能包注册补全

问题根源：SkillManager 严格依赖 SKILL.md 文件的 YAML 头进行识别。目前 data/skills/document_exporter/ 目录下缺少该文件。
操作规范：

新建文件：data/skills/document_exporter/SKILL.md。

必须包含的 Frontmatter (YAML)：

code
Markdown
download
content_copy
expand_less
---
name: document_exporter
description: 导出缓冲区内容为 Word/PDF 文件。
resources: []
---
# 文档导出专家
使用本技能将系统缓冲区中的 Markdown 内容转换为物理文档。
1.2 基础设施：数据库初始化异常修复

问题根源：checkfirst=False 导致重复创建表报错，可能阻塞后续服务加载。
操作规范：

修改 src/database/base.py 中的 init_database。

指令：将 await conn.run_sync(Base.metadata.create_all, checkfirst=False) 改为 checkfirst=True 或移除该参数。

2. 前端展示协议：通用工具状态组件 (UI Component)

我们将为工具调用增加一套 “展示元数据 (Display Metadata)” 协议，支持大标题淡入淡出和进度显示。

2.1 后端：协议扩展 (SSE Protocol Extension)

在 src/services/chat_agent.py 的 chat_stream 中，修改 on_tool_start 事件。
规范要求：

新增 display_config 字段，允许工具定义其在前端的视觉效果。

示例数据结构：

code
JSON
download
content_copy
expand_less
{
  "type": "tool_start",
  "tool_name": "generate_compliance_report",
  "display_config": {
    "title": "正在开启深度研判流水线",
    "animation": "fade",
    "show_progress": true,
    "status_color": "cyan"
  }
}
2.2 前端：ToolOverlay 组件实现

修改 web/js/chat.js 和 web/css/style.css。

CSS 规范 (像素级样式)：

.tool-overlay：绝对定位在聊天气泡上方的半透明蒙层。

.fade-in-out：使用 @keyframes 实现 2 秒周期的透明度呼吸效果。

.progress-bar-mini：在工具卡片底部增加一个无限循环的进度条动画。

JavaScript 逻辑规范：

在处理 on_tool_start 时，检查是否存在 display_config。

如果存在 title，则在当前 AI 气泡中创建一个特殊的 “状态看板 (Status Banner)” 元素。

动画切换：当收到 on_tool_end 时，看板元素执行一个 slide-up 动画消失，并替换为“调用完毕”的绿色钩子。

3. 深度研究工具链：数据流转与按需感知 (Data Tunneling)
3.1 生产者：generate_compliance_report 规范

任务：调用 ComplianceReporter 生成全文。

状态写入：通过 Command(update={"report_buffer": full_text}) 将几千字写入 AgentState。

前端联动：在工具开始时，通过 display_config 输出：“正在检索法规库，预计撰写 5000 字...”。

3.2 消费者：export_document_file 规范

参数注入：使用 InjectedState("report_buffer") 自动抓取内容。

前端联动：

on_tool_start 输出：“正在进行公文排版与 PDF 渲染...”。

on_tool_end 返回下载链接。

3.3 显微镜：read_report_buffer 规范

任务：当用户问细节时，从 report_buffer 提取片段。

前端联动：输出：“正在从内部缓冲区调阅相关章节...”。

4. 验收标准 (Acceptance Criteria)
4.1 功能验收

不再报错：输入“转 Word”时，不再提示 document_exporter 不存在。

数据流转：点击生成的链接下载的 Word 文档，必须包含上一步生成的 8000+ 字完整报告内容。

4.2 视觉验收 (UX)

淡入淡出：工具执行时，聊天气泡内应出现一个带有 display_config.title 的蓝色通知条，带有呼吸灯动画。

自动消失：工具执行完毕后，通知条应优雅地收缩，转为一行小的“调用完毕”记录。

零杂文：除了最后一行下载链接，聊天历史中严禁出现 8000 字的原始 Markdown 文本。

5. 给 Cursor 的特别技术提示（针对 1.0 版本）

State 声明：请在 src/types/agent_state.py 中显式添加 report_buffer: str 字段。

Tool 定义：使用 from langchain_core.tools import tool。

注入语法：

code
Python
download
content_copy
expand_less
@tool
def my_tool(arg1: str, content: Annotated[str, InjectedState("report_buffer")]):
    # 这里的 content 会被自动填充，AI 无法感知该参数

前端事件处理：在 web/js/chat.js 的 lines.forEach 循环中，确保 tool_start 逻辑能够读取并渲染 display_config。

请 Cursor 立即执行：第一步修复文件缺失和数据库错误，第二步实现前端通用状态展示组件，第三步打通报表生成与导出的数据隧道。