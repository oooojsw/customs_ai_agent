# Agent V1 平台演示联调最小调用说明

## 目标

平台侧先只需要调通一个统一智能体入口，不接图片识别，不依赖平台文件中心。

## 推荐环境变量

```env
AGENT_V1_ENABLED=true
AGENT_V1_DEMO_MODE=true
AGENT_V1_RUN_STORE=sqlite
AGENT_V1_AUTH_ENABLED=false
AGENT_V1_USE_PLATFORM_FILES=false
```

## 创建 Run

```http
POST /api/agent/v1/runs
Content-Type: application/json
```

```json
{
  "request_id": "req-demo-001",
  "session": {
    "session_id": "platform-session-001",
    "user_id": "platform-user-001",
    "tenant_id": "tenant-001"
  },
  "message": {
    "content": ""
  },
  "business_context": {
    "entry_id": "530120250001",
    "mock_mode": true
  },
  "options": {
    "intent": "full_review",
    "response_mode": "stream",
    "include_tool_trace": true,
    "include_structured_result": true,
    "output_file_policy": "agent_temporary",
    "timeout_seconds": 600
  }
}
```

返回：

```json
{
  "run_id": "run-xxx",
  "request_id": "req-demo-001",
  "status": "queued",
  "events_url": "/api/agent/v1/runs/run-xxx/events",
  "status_url": "/api/agent/v1/runs/run-xxx"
}
```

## 消费过程事件

```http
GET /api/agent/v1/runs/{run_id}/events
Accept: text/event-stream
```

平台需要识别：

- `agent_started`
- `tool_started`
- `tool_finished`
- `customs_process_updated`
- `output_created`
- `message_delta`
- `warning`
- `heartbeat`
- `agent_completed`
- `agent_failed`
- `agent_cancelled`

工具事件可直接用于平台展示：

- `status`: `running`、`success` 或 `error`
- `interaction_kind`: 普通工具为 `agent_tool`，报关操作为 `declaration_operation`，海关模拟窗口为 `customs_authority`
- `auto_expand`: 海关模拟窗口回复为 `true`，其他工具默认 `false`
- `customs_reply`: 海关模拟窗口的完整回复文本

`customs_process_updated` 可直接用于绘制流程条，重点读取：

- `stage`、`stage_label`
- `stage_order`、`total_stages`、`progress_percent`
- `is_terminal`
- `receipt`、`allowed_actions`、`risk_items`

## 查询最终结果

```http
GET /api/agent/v1/runs/{run_id}
```

成功时重点读取：

- `status`
- `final_answer`
- `structured_result.process.state`
- `outputs`

## 下载生成文件

如果 Output 返回：

```json
{
  "kind": "document",
  "format": "docx",
  "agent_output_url": "/api/agent/v1/outputs/out-xxx/content"
}
```

平台直接请求 `agent_output_url` 即可下载演示 DOCX。

`output_created.data.output` 统一包含 `output_id`、`kind`、`format`、`name`、`source_tool`、`download_url`、`agent_output_url`、`platform_file_id` 和 `metadata`。图片、Excel、结构化表格和归档也使用同一事件。

## 取消任务

```http
POST /api/agent/v1/runs/{run_id}/cancel
```

取消成功后 SSE 会以 `agent_cancelled` 收尾。正在执行的工具也会收到 `tool_finished` 且 `status=error`，平台不应继续显示“正在调用”。

## 超时建议

- 普通对话、审单：默认 600 秒
- Mock 全链路申报：默认 300 秒
- 报告生成：默认 1200 秒
- 平台没有特殊要求时可不传 `timeout_seconds`，由服务端按 intent 选择默认值

## 当前边界

- 图片识别和多模态能力暂不进入本次联调。
- 平台文件中心暂不强依赖，默认使用智能体临时下载地址。
- 真实平台鉴权后续再开启 `AGENT_V1_AUTH_ENABLED=true`。
- 当前重点是平台能创建 Run、消费 SSE、查询结果、下载文件。
