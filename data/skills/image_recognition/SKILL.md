---
name: image_recognition
description: 调用多模态大模型对图片进行文档分类和内容识别，输出统一的DocumentResult结构化JSON。自动判断图片是报关单证还是普通货物照片，并采用对应的提取策略。当用户上传货物照片/场景图片/物品图片、要求"分析这张图片"/"图片里有什么"/"识别图片中的物品"、或需要从非单证图片中提取物品信息时使用。注意：报关单/发票/装箱单等表格单证图片优先使用 table_ocr 技能。
---

# 图片内容识别（多模态大模型 V2）

你是一名海关货物查验专家，负责调用多模态视觉大模型对图片进行两阶段分析：
1. **文档分类** — 自动判断图片是否为报关单证，若是则提取结构化字段
2. **内容描述** — 对普通货物照片输出物品清单和自然语言描述

输出格式已对齐统一 **DocumentResult** 数据模型，包含文档类型、字段证据（含置信度）、物品清单表。

## 与 table_ocr 的区别

| 维度 | table_ocr | image_recognition（本技能） |
|------|-----------|---------------------------|
| 识别对象 | 报关单/发票/装箱单等**表格单证** | 货物照片/场景图/物品图等**普通图片** |
| 核心能力 | 表格结构解析 + 单元格提取 + 字段映射 | 文档分类 + 内容描述 + 物品识别 |
| 表格来源 | 专用表格OCR服务解析 | VLM 从图片直接理解（无OCR中间层） |
| 字段提取 | OCR文本 → 模式匹配/VLM增强 | VLM 直接从图片提取 |
| 适用场景 | 有明确表格结构的单证 | 无表格的货物照片/场景/物品 |

**选择规则**：
- 图片是报关单/发票/装箱单等 → **优先 `table_ocr`**（有OCR服务，表格结构更精确）
- 图片是货物照片/查验现场/物品 → **使用 `image_recognition`**（无表格可提取，需要视觉理解）
- 不确定类型 → **使用 `image_recognition`**（自动分类后再决定后续处理）

## 触发条件

以下任一情况必须调用此技能：
- 用户上传了货物照片、查验现场图片、物品场景图等**非单证**图片
- 用户说"分析这张图片"、"图片里有什么"、"识别图片中的物品"
- 用户需要从图片中提取物品清单（名称、类别、数量、特征）
- 海关查验场景中需要描述货物外观、包装、状态
- 用户上传了不确定类型的图片（本技能会自动分类）

**不应触发的场景**：
- 明确是报关单、发票、装箱单等表格单证 → 使用 `table_ocr` 技能
- 用户只是想查看图片 → 直接描述即可，无需调用脚本

## 执行流程

### 第1步：确定图片路径

用户上传的图片通常位于以下位置之一：
- 项目 `data/uploads/` 目录下
- 用户指定的绝对路径
- 临时目录中的文件

从上下文中获取图片文件的完整绝对路径。

### 第2步：调用识别脚本

使用 `run_skill_script` 工具执行识别，格式如下：

```
run_skill_script("image_recognition|analyze_image.py|{"image_path": "<图片绝对路径>", "language": "zh"}")
```

参数说明：
- `image_path`（必填）：图片文件的完整绝对路径
- `language`（可选）：输出语言，默认 `"zh"`（简体中文），也支持 `"en"`（英语）、`"vi"`（越南语）
- `detail_level`（可选）：识别详细程度，`"brief"`（简要）/ `"standard"`（标准，默认）/ `"detailed"`（详细）

### 第3步：解读结果

脚本返回统一的 **DocumentResult** JSON 格式：

```json
{
  "success": true,
  "schema_version": "1.0",
  "document_id": "img_<filename>",
  "document_type": "declaration|invoice|packing_list|certificate|general_image|unknown",
  "file_name": "货物照片.jpg",
  "tables": [
    {
      "table_id": "items_table",
      "caption": "图片整体描述",
      "rows": 4,
      "columns": 6,
      "headers": ["序号", "物品名称", "类别", "数量", "特征", "置信度"],
      "cells": [
        {
          "row": 2,
          "column": 2,
          "text": "电子元器件",
          "confidence": "high",
          "confidence_score": 0.90,
          "cell_id": "R2C2"
        }
      ],
      "confidence": "high"
    }
  ],
  "fields": [
    {
      "field_name": "entry_id",
      "original_text": "530120250001",
      "standard_value": "530120250001",
      "confidence": "high",
      "confidence_score": 0.92,
      "needs_review": false,
      "review_status": "pending",
      "is_critical": true,
      "notes": ""
    }
  ],
  "raw_text": "图片自然语言描述文本",
  "confidence": "high",
  "source_attachment_id": null,
  "page_count": 1,
  "model_used": "azure-gpt-5-chat",
  "processing_time_ms": 2500,
  "warnings": [],
  "metadata": {
    "category": "货物照片",
    "tags": ["电子产品", "芯片", "集成电路"],
    "customs_relevance": "high",
    "language": "zh",
    "detail_level": "standard",
    "notes": "补充说明"
  }
}
```

## 输出解读指南

### document_type 分类
| 值 | 含义 | 后续处理建议 |
|----|------|------------|
| `declaration` | 图片是报关单 | 标记为单证，提取字段值 |
| `invoice` | 图片是发票 | 提取金额相关字段 |
| `packing_list` | 图片是装箱单 | 提取数量相关字段 |
| `certificate` | 图片是原产地证 | 提取产地信息 |
| `general_image` | 普通图片（非单证） | 查看物品清单和描述 |
| `unknown` | 无法确定 | 保留描述文本供参考 |

### 输出结构说明
- **document_type 为文档类型时**：`fields` 包含结构化报关字段，`tables` 可能为空
- **document_type 为 general_image 时**：`fields` 为空，`tables` 包含物品清单表，`raw_text` 包含自然语言描述
- **document_type 为 unknown 时**：查看 `raw_text` 和 `metadata.notes`

### 置信度与复核策略
| 等级 | 分数 | 含义 | 策略 |
|------|------|------|------|
| `high` | ≥0.85（通用）/ ≥0.90（关键字段）| 高置信度 | 自动采用 |
| `medium` | 0.50-0.85 / 0.65-0.90 | 中置信度 | 标黄建议确认 |
| `low` | <0.50 / <0.65 | 低置信度 | 标红必须人工确认 |

**关键字段**（报关单号、HS编码、总价、币种、数量）使用更严格阈值。

## 输出展示格式

建议按以下格式呈现给用户：

### 文档类型图片（单证）
```
【单证识别结果】
📋 文档类型：报关单 (declaration)
🔧 识别模型：azure-gpt-5-chat

📝 提取字段：
| 字段名 | 原文 | 标准值 | 置信度 | 需复核 |
|--------|------|--------|--------|--------|
| 报关单号 | 530120250001 | 530120250001 | high ✅ | 否 |
| HS编码 | 8542.31.0000 | 8542.31.0000 | medium ⚠️ | 是 |

⚠️ 需复核字段：HS编码（置信度不足）
```

### 普通图片（货物照片）
```
【图片分析结果】
📷 图片分类：货物照片
📝 内容描述：[自然语言描述]

📦 识别物品清单：
| 序号 | 物品名称 | 类别 | 数量 | 特征 | 置信度 |
|------|---------|------|------|------|--------|
| 1 | 芯片托盘 | 电子产品 | 约50片 | 黑色IC芯片 | high ✅ |
| 2 | 防静电包装 | 包装材料 | 1个 | 银色铝箔袋 | high ✅ |

🏷️ 标签：电子产品, 芯片, 集成电路
📊 海关相关度：high
```

## 与审单流程的衔接

如果用户的目标是审核货物风险：
1. 先调用本技能提取图片信息（获得 `DocumentResult`）
2. 如果 `document_type` 是文档类型 → 使用 `fields` 中的关键字段进行审单
3. 如果 `document_type` 是 `general_image` → 从 `tables[0].cells` 中提取物品名称
4. 根据物品名称进一步查询 HS 编码（使用 `hs_code_advisor`）
5. 结合 `metadata.customs_relevance` 判断是否需要深度审单

## 模型选择

脚本自动选择可用模型，优先级为：
1. Azure OpenAI GPT-4o / GPT-5（视觉能力强，适合海关场景）
2. Gemini Flash（速度快，适合快速筛查）
3. OpenAI 兼容接口（DeepSeek-VL / Qwen-VL 等）

可通过环境变量覆盖：
- `VLM_PROVIDER`：指定模型提供商（azure/gemini/deepseek/qwen）
- `VLM_MODEL`：指定模型名称

## 错误处理

| 错误 | 处理方式 |
|------|----------|
| 图片文件不存在 | 确认路径是否正确，列出 `data/uploads/` 下的文件 |
| 识别结果为空 | 提示图片可能不清晰或不包含可识别物品，建议重新拍摄 |
| 脚本执行超时 | 告知用户图片较大处理耗时较长，可尝试压缩图片后重试 |
| 所有 VLM 不可用 | 提示用户检查 API Key 配置，建议通过前端配置页切换可用模型 |
| 不支持的图片格式 | 列出支持的格式（PNG/JPG/JPEG/BMP/TIFF/WEBP），建议转换后重试 |
| 文档类型为 unknown | 展示 `raw_text` 描述文本，建议人工判断图片性质 |

## 注意事项

- 支持常见图片格式：PNG、JPG、JPEG、BMP、TIFF、WEBP
- 建议单张图片不超过 20MB
- 识别结果为 AI 生成，仅供辅助参考，重要决策需人工确认
- 对于海关监管货物，识别结果不能替代专业查验
- 如 `needs_review: true` 的字段较多，建议人工复核后再用于正式流程
- 如果 `document_type` 被识别为文档类型但实际需要精确表格结构，建议补充调用 `table_ocr` 技能
