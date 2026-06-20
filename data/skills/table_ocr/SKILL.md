---
name: table_ocr
description: 识别报关单图片、表格图片、扫描件中的表格和文字，提取为结构化单元格JSON（含行列坐标、合并单元格、置信度）和统一报关字段映射。当用户上传报关单照片/截图/发票/装箱单、要求识别图片中的表格内容、或说"识别这张图片"/"提取图片中的文字"时使用。
---

# 表格图片 OCR 识别（结构化输出版 V2）

你是一名海关单证OCR专家，负责将报关单、发票、装箱单等单证图片转换为结构化数据。

**V2 升级要点**：输出从 Markdown 文本升级为 **DocumentResult 结构化 JSON**，包含：
- 单元格级数据（row/column/row_span/column_span/text/confidence/bbox）
- 文档类型自动分类（declaration/invoice/packing_list/certificate/source_table_image）
- 统一报关字段映射（FieldEvidence：原文 + 标准值 + 置信度 + 来源追溯）
- 可选 VLM 增强（文档分类 + 字段提取 + 置信度评估）

## 与 image_recognition 的区别

| 维度 | table_ocr（本技能） | image_recognition |
|------|-------------------|-------------------|
| 识别对象 | 报关单/发票/装箱单等**表格单证** | 货物照片/场景图/物品图等**普通图片** |
| 核心能力 | 表格结构解析 + 单元格提取 + 字段映射 | 文档分类 + 内容描述 + 物品识别 |
| 是否调用外部OCR | ✅ 调用专用表格OCR服务 | ❌ 纯VLM方案 |
| 表格输出 | 单元格级结构化（含坐标和合并关系） | 物品清单表（从描述转换） |
| 字段输出 | FieldEvidence（原文+标准值+来源追溯） | 从图片中直接提取 |

## 触发条件

以下任一情况必须调用此技能：
- 用户上传了报关单、发票、装箱单、运单等**单证**图片/截图
- 用户说"识别这张图片"、"提取图片中的表格"、"OCR识别"
- 用户上传了包含表格的图片并要求结构化
- 用户在审单流程中提供了图片格式的报关数据

**不应触发的场景**：
- 货物照片、查验现场、物品场景图 → 使用 `image_recognition` 技能
- 用户只是想查看图片 → 直接描述即可

## 执行流程

### 第1步：确定图片路径

用户上传的图片通常位于以下位置之一：
- 项目 `data/uploads/` 目录下
- 用户指定的绝对路径
- 临时目录中的文件

从上下文中获取图片文件的完整绝对路径。

### 第2步：调用 OCR 脚本

使用 `run_skill_script` 工具执行识别，格式如下：

```
run_skill_script("table_ocr|ocr_table.py|{"image_path": "<图片绝对路径>", "language": "zh"}")
```

参数说明：
- `image_path`（必填）：图片文件的完整绝对路径
- `language`（可选）：输出语言，默认 `"zh"`，也支持 `"vi"`（越南语）
- `use_enhancement`（可选）：是否启用 VLM 增强（文档分类 + 字段提取），默认 `true`

### 第3步：解读结果

脚本返回统一的 **DocumentResult** JSON 格式：

```json
{
  "success": true,
  "schema_version": "1.0",
  "document_id": "ocr_<filename>",
  "document_type": "declaration|invoice|packing_list|certificate|source_table_image|unknown",
  "file_name": "报关单.png",
  "tables": [
    {
      "table_id": "table_1",
      "caption": "商品清单",
      "rows": 5,
      "columns": 6,
      "headers": ["货物名称", "HS编码", "数量", "单价", "总价", "申报要素"],
      "cells": [
        {
          "row": 2,
          "column": 1,
          "row_span": 1,
          "column_span": 1,
          "text": "集成电路",
          "confidence": "medium",
          "confidence_score": 0.75,
          "cell_id": "R2C1"
        }
      ],
      "merged_regions": [],
      "confidence": "medium",
      "raw_markdown": "| 货物名称 | HS编码 | ..."
    }
  ],
  "fields": [
    {
      "field_name": "entry_id",
      "original_text": "530120250001",
      "standard_value": "530120250001",
      "cell_refs": [],
      "confidence": "high",
      "confidence_score": 0.92,
      "source_attachment_id": null,
      "source_table_id": "table_1",
      "needs_review": false,
      "review_status": "pending",
      "is_critical": true,
      "notes": ""
    }
  ],
  "raw_text": "原始OCR文本",
  "confidence": "medium",
  "source_attachment_id": null,
  "page_count": 1,
  "model_used": "table-ocr",
  "enhancement_model": "azure-gpt-5-chat",
  "processing_time_ms": 3500,
  "warnings": [],
  "metadata": {
    "ocr_service": "http://...",
    "language": "zh",
    "vlm_enhanced": true
  }
}
```

## 输出解读指南

### document_type 分类
| 值 | 含义 | 后续处理建议 |
|----|------|------------|
| `declaration` | 报关单 | 提取商品清单 → 审单 |
| `invoice` | 发票 | 提取金额 → 价格审核 |
| `packing_list` | 装箱单 | 提取数量 → 单货核对 |
| `certificate` | 原产地证 | 提取产地 → 税率判定 |
| `source_table_image` | 含表格的其他单证 | 结构化 → 人工判断 |
| `unknown` | 无法确定 | 保留 OCR 文本供参考 |

### 置信度与复核策略
| 等级 | 分数 | 含义 | 策略 |
|------|------|------|------|
| `high` | ≥0.85（通用）/ ≥0.90（关键字段）| 高置信度 | 自动采用 |
| `medium` | 0.50-0.85 / 0.65-0.90 | 中置信度 | 标黄建议确认 |
| `low` | <0.50 / <0.65 | 低置信度 | 标红必须人工确认 |

**关键字段**（报关单号、HS编码、总价、币种、数量）使用更严格阈值。

### 字段复核判定
- `needs_review: false` → 可以自动采用（HIGH 置信度）
- `needs_review: true` → 建议或必须人工复核
- 低置信度的关键字段**不得**直接用于生成正式报关单

## 与审单流程的衔接

如果用户的目标是审核报关单风险：
1. 先调用本技能提取图片中的报关数据（获得 `DocumentResult`）
2. 从 `fields` 中获取关键字段值
3. 从 `tables` 中获取结构化商品清单
4. 将字段和表格数据送入审单流程
5. 将审核结果与原始图片的关键信息一并呈现

## 错误处理

| 错误 | 处理方式 |
|------|----------|
| 图片文件不存在 | 确认路径是否正确，列出 `data/uploads/` 下的文件 |
| OCR 识别结果为空 | 提示图片可能不清晰或不包含文字表格，建议重新上传 |
| 脚本执行超时 | 告知用户图片较大处理耗时较长，建议通过前端"审单"页面上传 |
| 识别内容不完整 | 将已有内容展示给用户，标注 `warnings` 中的缺失提示 |
| VLM 增强不可用 | 退回到启发式字段提取，`warnings` 中提示"建议人工核对所有字段" |

## 注意事项

- 支持常见图片格式：PNG、JPG、JPEG、BMP、TIFF
- 图片越大识别越慢，建议单张图片不超过 20MB
- VLM 增强需要至少配置一个视觉模型（Azure/Gemini/DeepSeek），未配置时自动降级
- 识别结果保留原始 OCR 文本（`raw_text`）作为证据
- 低置信度字段必须人工确认后才能用于正式报关
