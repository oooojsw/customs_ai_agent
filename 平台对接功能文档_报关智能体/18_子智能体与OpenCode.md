# 18 子智能体与 OpenCode

## 功能定位

OpenCode 子智能体用于处理复杂本地代码、文件、脚本或工程任务。它是主智能体内部的受控子执行器，不是平台用户直接操作的独立智能体。

## 平台是否需要单独接入

不需要。

平台仍然只接 Agent V1：

```text
POST /api/agent/v1/runs
GET /api/agent/v1/runs/{run_id}/events
```

## SSE 事件

当主智能体调用 OpenCode 子智能体时，平台可能看到：

```text
subagent_started
subagent_finished
output_created
warning
```

示例：

```json
{
  "event": "subagent_started",
  "data": {
    "subagent": "opencode",
    "tool": "delegate_to_opencode",
    "display_name": "OpenCode 子智能体",
    "interaction_kind": "subagent",
    "auto_expand": true
  }
}
```

完成时：

```json
{
  "event": "subagent_finished",
  "data": {
    "subagent": "opencode",
    "tool": "delegate_to_opencode",
    "task_id": "subtask-xxx",
    "status": "completed",
    "ok": true,
    "summary": "..."
  }
}
```

如果子智能体生成文件，会统一走：

```text
output_created
```

## 平台展示建议

最低实现：

```text
可以忽略 subagent_* 事件
```

较好实现：

```text
显示“正在调用子智能体”
显示子智能体完成/失败原因
如果有 output_created，展示文件卡片
```

## 当前边界

- OpenCode 主要用于内部工程任务，不是报关业务必演示功能。
- 平台不要向用户暴露任意 shell/文件操作入口。
- 子智能体失败时会通过 warning 或 subagent_finished 返回原因。

