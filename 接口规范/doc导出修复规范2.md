你分析得非常准！AI 确实遇到了参数传递的“物理极限”，而且目前的调用方式在处理长文本时存在一个隐藏的“自杀式”缺陷。

通过看你的日志：报告字数 9523 字。
在 Windows 系统下，通过 subprocess 传递参数有一个硬性限制：命令行字符串最大长度约为 8191 个字符。

🔍 深度病理分析：为什么 AI 尽力了但还是失败？

命令行“爆仓” (Windows CLI Limit)：
当 AI 调用 export_document_file 时，系统尝试执行：
python export_engine.py "{\"content\": \"...这里是9500字...\"}"
由于这串字符远远超过了 8191 字符的限制，操作系统会直接截断这行命令。脚本收到的是半截 JSON，解析时报错退出，所以你看到了 ❌ 导出失败：（后面是空的，因为错误发生在解析阶段）。

AI 的“路径强迫症”：
日志显示：content="错误：技能 'document_exporter|我想导出...' 不存在"。
AI 试图把整个需求塞进 skill_name 字段。这是因为工具的 description 引导不够强，导致 AI 在复杂任务链中产生了**“参数幻觉”**。

脚本名称校验过严：
日志显示：content='错误：非法的脚本文件名（禁止路径遍历）'。
AI 习惯性地写了 scripts/export_engine.py，但你的 SkillManager 逻辑只允许写 export_engine.py。

🛠️ 最终版像素级修复规范：引入“磁盘交换”与“语义加固”

为了彻底修好，必须让 Cursor 实施以下 “文件中转”方案，这是业界处理超长参数的唯一标准做法。

📑 最终任务指令书：解决长文本崩溃与 AI 调用歧义
1. 核心修复：从“命令行传参”改为“文件传参”

文件：src/services/script_executor.py
目标：绕过 Windows 8KB 命令行限制。
指令：

逻辑重构：修改 execute 方法。

创建临时文件：不再把 args 序列化为字符串直接传给命令行，而是：

将 args 字典写入一个临时的 JSON 文件（存放在 data/exports/temp_args.json）。

命令行改为：[sys.executable, script_path, temp_args_file_path]。

自动清理：脚本执行完后，必须删除该临时 JSON 文件。

2. 脚本端适配规范

文件：data/skills/document_exporter/scripts/export_engine.py
指令：

读取方式变更：修改脚本入口。不再直接 json.loads(sys.argv[1])。

增加判断逻辑：

检查 sys.argv[1] 是否是一个存在的文件路径。

如果是文件，读取文件内容并解析 JSON；如果不是，再尝试按原始字符串解析。

3. 工具描述加固 (Anti-Hallucination)

文件：src/services/chat_agent.py
目标：强制 AI 正确传参，不产生杂质。
指令：

run_skill_script 工具描述更新：

"执行脚本。参数1:skill_name(仅限名称), 参数2:script_name(仅限文件名,严禁包含路径), 参数3:args(纯JSON字典)。"

export_document_file 工具逻辑加固：

在工具内部自动补全文件名 export_engine.py。

AI 仅需传 format。

4. 前端通用工具状态看板 (Visual Feedback)

文件：web/js/chat.js
目标：实现你要求的“标题淡入淡出”和属性扩展。
指令：

新增 UIHelper.showToolStatus(title) 方法：

在当前消息框顶部创建一个 div.tool-status-banner。

设置 CSS：opacity: 0; transition: opacity 0.5s;。

使用 requestAnimationFrame 触发 opacity: 1 实现淡入。

属性化设计：在 tool_start 的 JSON 中增加 meta 属性，前端根据 meta.status_text 动态更新看板文字。

5. 缓冲区查阅逻辑修复

目标：解决 read_report_buffer 查不到内容的问题。
原因：目前的匹配是大小写敏感的，且只支持单行匹配。
指令：

修改 read_report_buffer_tool：

将 query 和 buffer 统一转为小写再进行 in 判断。

保底机制：如果 query 为空或匹配不到，默认返回前 50 行，而不是返回“未找到”。

🚀 给 Cursor 的一句话操作摘要：

“由于 Windows 命令行长度限制，请将 ScriptExecutor 改造为通过临时 JSON 文件传递参数给 L4 脚本，并同步更新 export_engine.py 以读取该文件。同时，为前端添加通用的 tool-status-banner 动画组件，并优化 read_report_buffer 的匹配容错率。”

这份文档直接指出了“命令行长度”这个物理层面的 Bug，这通常是初级 AI 编程助手最容易忽略的地方。现在让 Cursor 动手吧！