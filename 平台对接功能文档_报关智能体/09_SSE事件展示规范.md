# 09 SSE 事件展示规范

## 功能定位

平台前端要通过 SSE 展示智能体实时执行过程。该文件说明每类事件怎么渲染。

## 必须支持的事件

| event | 展示方式 |
| --- | --- |
| `agent_started` | 任务开始 |
| `status_changed` | 状态提示 |
| `message_delta` | 追加到聊天气泡 |
| `tool_started` | 工具调用开始，显示 loading |
| `tool_finished` | 工具调用结束，关闭 loading |
| `customs_process_updated` | 更新报关流程进度条 |
| `output_created` | 增加文件/结果卡片 |
| `warning` | 显示非阻断警告 |
| `heartbeat` | 可忽略或用于连接状态 |
| `agent_completed` | 完成 |
| `agent_failed` | 失败 |
| `agent_cancelled` | 已取消 |

## 可选支持的事件

| event | 展示方式 |
| --- | --- |
| `subagent_started` | 子智能体开始 |
| `subagent_progress` | 子智能体进度，当前可忽略 |
| `subagent_finished` | 子智能体完成/失败 |
| `tool_progress` | 工具细粒度进度，当前可忽略 |

平台前端必须忽略未知事件。

## tool_started 示例

```json
{
  "tool": "process_customs_review",
  "display_name": "海关综合审单",
  "status": "running",
  "interaction_kind": "customs_authority",
  "auto_expand": true,
  "started_at": "..."
}
```

## tool_finished 示例

```json
{
  "tool": "process_customs_review",
  "display_name": "海关综合审单",
  "status": "success",
  "interaction_kind": "customs_authority",
  "auto_expand": true,
  "summary": "审单通过",
  "customs_reply": "海关模拟回复全文",
  "finished_at": "..."
}
```

## interaction_kind

| 值 | 含义 | 前端建议 |
| --- | --- | --- |
| `agent_tool` | 普通智能体工具 | 默认折叠 |
| `declaration_operation` | 报关业务操作 | 可显示流程动作 |
| `customs_authority` | 海关模拟窗口 | 默认展开 |
| `subagent` | 子智能体 | 可作为高级过程展示 |

## 取消展示

取消时正常事件顺序可能是：

```text
tool_finished(status=error, summary="智能体任务已取消")
agent_cancelled
```

平台收到 `agent_cancelled` 后应：

```text
停止 loading
禁用停止按钮
显示“任务已取消”
保留已产生的文字和 Output
```

## 失败展示

失败时会有：

```text
agent_failed
```

其中包含：

```json
{
  "error": {
    "error_code": "RUN_TIMEOUT",
    "message": "智能体任务执行超时",
    "retryable": true,
    "stage": "run_execution"
  }
}
```

平台可以根据 `retryable` 显示“可重试”。

## 重连

平台断线后可带：

```http
Last-Event-ID: 12
```

服务会从后续 sequence 继续推送。

