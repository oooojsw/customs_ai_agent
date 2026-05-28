# 测试记录

## 2026-03-23 下午

### 问题1：MCP Bridge ClosedResourceError
- 现象：list_tools() 失败，anyio.ClosedResourceError，14个MCP工具全部加载失败
- 根因：pip show指向了AppData/Roaming/Python环境的旧版本，实际运行的是miniconda3的mcp 1.26.0
- 修复：重启服务后自动恢复
- 端口：无清理需求（服务正常）

### 问题2：recursion_limit错误
- 现象：Agent达到25轮上限崩溃
- 第一次错误修复：在create_react_agent()参数中传入recursion_limit=100 → 报错Agent创建失败
- 第二次正确修复：在config字典中传入recursion_limit=100 → 成功
- 涉及文件：src/services/chat_agent.py
- 涉及行：第1121行
- 端口：无清理需求（服务正常）

### 问题3：torch缺失
- 现象：sentence_transformers加载失败
- 修复：pip install torch --index-url https://download.pytorch.org/whl/cpu
- 端口：无清理需求

### 最终状态
- 服务运行：PID 31944，端口 8000
- 工具加载：23个（9个内置Skill + 14个MCP）
- 所有模块：就绪
