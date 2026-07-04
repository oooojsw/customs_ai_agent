# 07 附件与 OCR 识别

## 功能定位

附件能力用于平台上传图片、表格单证、后续 PDF/Excel 等文件，让智能体进行识别或结构化处理。

当前最小可演示的是图片 OCR。PDF 协议已预留，但 Agent V1 OCR 链路尚未稳定接入 PDF 解析。

## 推荐 intent

```json
{
  "options": {
    "intent": "ocr"
  }
}
```

## 平台输入方式

平台不要传 Base64，也不要传服务器本地路径。正确方式是：

1. 平台先把附件存入自己的文件中心。
2. 平台生成临时 `download_url`。
3. 创建 Run 时把附件元信息放入 `attachments`。

## 图片请求示例

```json
{
  "request_id": "req-ocr-image-001",
  "session": {
    "session_id": "session-ocr-001",
    "user_id": "user-001",
    "tenant_id": "tenant-001"
  },
  "message": {
    "content": "识别这张报关单图片，提取表格字段"
  },
  "attachments": [
    {
      "file_id": "platform-file-001",
      "kind": "image",
      "name": "declaration.png",
      "purpose": "source_table_image",
      "mime_type": "image/png",
      "size": 182340,
      "download_url": "https://platform.example.com/temp/declaration.png",
      "expires_at": "2026-07-03T18:00:00+08:00"
    }
  ],
  "options": {
    "intent": "ocr",
    "output_file_policy": "agent_temporary"
  }
}
```

## 平台必须配置

附件下载域名需要配置到服务端环境变量：

```env
AGENT_V1_ATTACHMENT_ALLOWED_HOSTS=platform.example.com
```

否则会返回：

```text
ATTACHMENT_HOST_NOT_ALLOWED
```

## SSE 展示

```text
tool_started: image_ocr
tool_finished: image_ocr
output_created: 结构化识别 JSON
output_created: 如果识别出表格，可能生成 XLSX
message_delta: 已完成附件识别
```

## 输出

图片识别结果会以 `structured_data` Output 返回：

```json
{
  "kind": "structured_data",
  "format": "json",
  "name": "declaration.png 识别结果",
  "source_tool": "image_ocr",
  "data": {
    "document_type": "table",
    "full_text": "...",
    "tables": [],
    "fields": []
  }
}
```

如果包含表格，可能额外输出：

```json
{
  "kind": "spreadsheet",
  "format": "xlsx",
  "name": "declaration-识别表格.xlsx",
  "source_tool": "table_export"
}
```

## PDF 当前状态

必须明确告诉平台：

```text
PDF 附件协议已预留，但当前 Agent V1 OCR 链路没有稳定接入 PDF 解析。
```

当前代码会下载 PDF，但 OCR Adapter 会把文件转发给外部 `TABLE_OCR_URL`。如果外部 OCR 服务支持 PDF，则可能成功；如果只支持图片，则会失败。

因此演示时建议先使用图片，不要承诺 PDF 稳定识别。

## 多模态负责人后续工作

多模态负责人可以继续增强：

```text
table_ocr Skill
image_recognition Skill
PDF 转图片/文本解析适配
DocumentResult 标准化
低置信度字段复核
图片转 Excel
填写后报关单图片/PDF 预览
```

## 当前边界

- 当前图片 OCR 依赖外部 OCR 服务 `TABLE_OCR_URL`。
- 识别准确率需要通过样例图 + expected JSON 建立评测。
- 低置信度结果不应直接用于正式申报。

