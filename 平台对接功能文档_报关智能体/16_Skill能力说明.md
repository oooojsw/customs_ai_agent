# 16 Skill 能力说明

## 功能定位

Skill 是智能体内部能力包。平台不需要直接调用 Skill 文件，也不需要知道脚本路径；平台只通过 Agent V1 发送用户请求，智能体在内部按需调用 Skill。

当前仓库中的 Skill：

```text
data/skills/hs_code_advisor
data/skills/tax_calculator
data/skills/image_recognition
data/skills/table_ocr
```

## hs_code_advisor

### 功能

辅助用户查询商品 HS 编码，说明归类依据和风险。

### 触发方式

用户在 `auto/chat` 中询问：

```text
全自动贴片机应该归到哪个 HS 编码？
```

### 平台展示

平台只看到普通工具调用和智能体回答，不需要展示 Skill 内部文件。

## tax_calculator

### 功能

估算进口环节税费，包括关税、增值税、总税额。

### 输入要素

```text
CIF 价格
HS 编码
原产国/地区
税率或优惠政策
```

### 触发方式

用户在 `auto/chat` 中询问：

```text
CIF 10000 美元，HS 85423100，帮我估算进口税费。
```

### 注意

审单场景不应自动计算税费，除非用户明确要求估税。

## image_recognition

### 功能

用于普通货物图片、查验现场图片、物品图片的视觉理解。

### 当前状态

多模态负责人后续可继续增强。

### 输出目标

```text
DocumentResult JSON
图片描述
物品清单
置信度
```

## table_ocr

### 功能

用于报关单、发票、装箱单等表格图片 OCR，目标是输出结构化单元格、字段、置信度。

### 当前重点

这是多模态负责人最应该优先做准的模块。

### 建议验收

```text
关键字段准确率
表格单元格召回率
字段来源 cell_ref
低置信度 needs_review 标记
expected JSON 对比
```

## 平台是否需要直接接 Skill

不需要。

平台只接：

```text
POST /api/agent/v1/runs
GET /api/agent/v1/runs/{run_id}/events
```

智能体内部通过 `invoke_skill` 调用 Skill。

## 当前边界

- Skill 是内部扩展机制，不是平台正式外部 API。
- 平台不应传脚本路径、服务器本地路径或 Skill 内部文件名。
- 如果要做可插拔演示流程，建议通过 `data/demo_flows` 引用 Skill，而不是平台直接调用 Skill。

