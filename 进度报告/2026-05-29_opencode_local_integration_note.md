# opencode 本机安装版接入说明

## 当前状态
- 已新增 `data/mcp_servers.json` 的 `opencode_local` 条目。
- 默认 `enabled=false`，避免在非 MCP 协议输出时阻塞启动。
- 当前有效 MCP 仍为 `filesystem`。

## 为什么默认禁用
- 现有桥接器 `src/services/mcp_bridge.py` 期望子进程讲 MCP stdio 协议。
- `opencode run` 输出为任务事件流（JSON），不是 MCP 协议握手流。
- 直接启用会导致 `initialize()/list_tools()` 失败。

## 你要启用本机 opencode 的两条路
1. MCP 路线：把 `command/args` 指向一个真正的 opencode MCP server 可执行项，再把 `enabled` 改为 `true`。
2. 子智能体路线（推荐）：主系统通过本机 `opencode run` 委托任务，结果回流到当前会话。

## 本次变更
- 修复并标准化了 `data/mcp_servers.json`（无 BOM UTF-8，JSON 可解析）。
- 新增 `opencode_local` 预留条目（默认禁用）。
