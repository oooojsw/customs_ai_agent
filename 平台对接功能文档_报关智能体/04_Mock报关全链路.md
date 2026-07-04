# 04 Mock 报关全链路

## 功能定位

Mock 报关全链路用于演示一次完整的一般贸易进口申报流程，包括创建案件、加载单证、预审、提交海关、海关受理、审单、退单/补件/查验/征税、放行、结关。

这是当前最能展示“报关业务流程”的能力。

## 推荐 intent

```json
{
  "options": {
    "intent": "mock_import_declaration"
  }
}
```

## 当前三个固定演示案例

| mock_case_id | 含义 | 适合展示 |
| --- | --- | --- |
| `normal_release` | 资料完整，正常审单、缴税、放行、结关 | 稳定完整流程 |
| `returned_then_release` | 初始申报缺少型号/用途，海关退单，系统改单后重新申报 | 退单重报 |
| `high_risk_inspection` | 价格偏低，触发风险布控和查验后放行 | 风险、查验、海关回复 |

这些案例文件位于：

```text
data/mock_customs_cases/
```

## 请求示例：高风险查验

```json
{
  "request_id": "req-mock-import-001",
  "session": {
    "session_id": "session-mock-001",
    "user_id": "user-001",
    "tenant_id": "tenant-001"
  },
  "message": {
    "content": "演示一票高风险进口报关全流程"
  },
  "business_context": {
    "mock_case_id": "high_risk_inspection",
    "step_delay_ms": 800
  },
  "options": {
    "intent": "mock_import_declaration",
    "response_mode": "stream",
    "include_tool_trace": true,
    "include_structured_result": true,
    "output_file_policy": "agent_temporary",
    "timeout_seconds": 600
  }
}
```

## 流程进度事件

平台应重点渲染：

```text
customs_process_updated
```

核心字段：

```json
{
  "business_case_id": "MOCK-CASE-xxx",
  "customs_case_id": "MOCK-CASE-xxx",
  "stage": "UNDER_REVIEW",
  "stage_label": "海关审单",
  "stage_order": 8,
  "total_stages": 18,
  "progress_percent": 44,
  "is_terminal": false,
  "summary": "海关模拟审单岗位开始审核",
  "receipt_summary": "海关模拟审单岗位开始审核",
  "allowed_actions": ["PROCESS_REVIEW"],
  "receipt": {},
  "risk_items": [],
  "mock": true
}
```

## 工具事件展示

海关模拟窗口工具会带：

```json
{
  "interaction_kind": "customs_authority",
  "auto_expand": true,
  "customs_reply": "海关模拟回复全文"
}
```

平台前端建议默认展开这类工具调用，让观看者看到“海关侧回复”。

## 演示建议

推荐视频演示顺序：

1. 选择 `high_risk_inspection`。
2. 展示流程进度条从创建案件到结关。
3. 展示工具调用列表。
4. 展示海关模拟回复默认展开。
5. 展示风险项和查验结果。
6. 展示最后 `agent_completed`。

## 当前边界

- 这是 Mock 流程，不接真实海关系统。
- 流程由状态机保证稳定，不建议平台让前端直接操作内部阶段。
- 新增演示案例可以增加 `data/mock_customs_cases/*.json`，但这只能改变数据和分支开关，不能自由定义跨能力工作流。

