# 报关智能体平台对接功能文档

本文档包用于帮助平台侧理解“报关智能体”当前能提供哪些能力、如何调用、如何在平台前端展示、如何录制演示视频。

当前集成方式是统一 Agent V1 接口。平台不需要分别调用审单、法规检索、报告、Mock 报关、OCR 等内部接口，只需要创建 Run、消费 SSE 事件、展示 Output。

## 平台先做哪几个页面/组件

平台侧最小只需要做 5 个组件：

1. 智能体输入框：用户输入文本，选择演示类型。
2. 流式回答区：展示 `message_delta`。
3. 工具调用区：展示 `tool_started` / `tool_finished`。
4. 报关流程区：展示 `customs_process_updated`，用于 Mock 报关全链路。
5. 文件结果区：展示 `output_created`，提供下载或预览。

接口只需要先接 4 个：

```text
POST /api/agent/v1/runs
GET  /api/agent/v1/runs/{run_id}/events
GET  /api/agent/v1/runs/{run_id}
POST /api/agent/v1/runs/{run_id}/cancel
```

文件下载再接：

```text
GET /api/agent/v1/outputs/{output_id}/content
```

## 文件清单

| 文件 | 说明 |
| --- | --- |
| `00_统一接入协议.md` | 平台必须先实现的统一入口、SSE、取消、查询、下载协议 |
| `01_通用智能体对话.md` | 通用报关智能体聊天、工具编排、子智能体事件 |
| `02_智能审单.md` | 报关数据风险检查、字段校验、风险提示展示 |
| `03_综合审查演示链路.md` | 查询/输入报关数据、审单、法规依据、报告生成的组合演示 |
| `04_Mock报关全链路.md` | 正常放行、退单重报、高风险查验三类报关流程演示 |
| `05_法规检索.md` | 法规依据检索、引用集合 Output 展示 |
| `06_合规报告生成.md` | 合规建议书/审单报告生成与文件下载 |
| `07_附件与OCR识别.md` | 图片附件输入、当前 OCR 能力、PDF 边界、多模态后续扩展 |
| `08_输出文件与下载.md` | output_created、agent_output_url、平台文件中心对接 |
| `09_SSE事件展示规范.md` | 前端如何渲染文字流、工具、流程条、错误、取消 |
| `10_演示视频候选场景.md` | 建议平台侧选择的 5 个演示点 |
| `11_可插拔演示流程设计.md` | 后续如何用 manifest + prompt 做可增删的演示流程插件 |
| `12_功能模块总览表.md` | 所有模块、intent、输入输出、演示状态一览 |
| `13_请求示例合集.md` | 平台后端可直接复制的典型请求 JSON |
| `14_报关单查询.md` | 根据 entry_id 查询报关数据 |
| `15_批量审单.md` | Excel/CSV 批量审单任务创建，当前为降级能力 |
| `16_Skill能力说明.md` | HS 编码、税费估算、图像识别、表格 OCR 等内部 Skill |
| `17_汇率查询与辅助工具.md` | 通用智能体内部汇率查询等辅助工具 |
| `18_子智能体与OpenCode.md` | OpenCode 子智能体事件、文件产物和平台展示方式 |
| `19_健康检查与能力发现.md` | capabilities、health 接口说明 |
| `20_能力覆盖核查清单.md` | 按源码倒查后的能力覆盖与边界确认 |

## 当前最小可演示能力

平台侧最小实现以下内容即可演示：

1. `POST /api/agent/v1/runs` 创建智能体任务。
2. 使用返回的 `events_url` 消费 SSE。
3. 渲染 `message_delta`、`tool_started`、`tool_finished`、`customs_process_updated`、`output_created`、`agent_completed`、`agent_failed`、`agent_cancelled`。
4. 用户点击停止时调用 `POST /api/agent/v1/runs/{run_id}/cancel`。
5. 对 `output_created.data.output.agent_output_url` 提供下载或预览入口。

## 当前边界

- 当前是演示级平台集成，不接真实海关生产系统。
- Mock 报关全链路是模拟流程，结果只用于演示。
- 图片 OCR 已有接口和 Skill 方向，但表格识别准确率仍需要多模态负责人继续优化。
- PDF 附件协议已预留，但 Agent V1 OCR 链路尚未稳定接入 PDF 解析。
- 平台前端必须忽略未知 SSE 事件，保证后续新增能力时不崩溃。
