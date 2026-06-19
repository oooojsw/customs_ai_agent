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
    "output_file_policy": "agent_temporary",
    "timeout_seconds": 30
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
- `output_created`
- `message_delta`
- `agent_completed`
- `agent_failed`

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

## 当前边界

- 图片识别和多模态能力暂不进入本次联调。
- 平台文件中心暂不强依赖，默认使用智能体临时下载地址。
- 真实平台鉴权后续再开启 `AGENT_V1_AUTH_ENABLED=true`。
- 当前重点是平台能创建 Run、消费 SSE、查询结果、下载文件。
