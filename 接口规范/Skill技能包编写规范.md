# Skill 技能包编写规范（四级加载架构）

## 概述

本规范详细说明如何为海关 AI 智能体系统编写技能包（Skill）。技能包采用**四级渐进式加载架构**，确保高效、安全、可扩展。

---

## 一、四级加载架构总览

```
┌─────────────────────────────────────────────┐
│  L1 层（索引层）- 启动时加载                  │
│  内容：技能名称 + 描述（~25 tokens）         │
│  文件：SKILL.md 的 YAML frontmatter          │
└─────────────────────────────────────────────┘
                    ↓ 用户触发
┌─────────────────────────────────────────────┐
│  L2 层（指令层）- 调用 use_skill 时加载       │
│  内容：完整技能手册（~200 tokens）           │
│  文件：SKILL.md 正文部分                     │
└─────────────────────────────────────────────┘
                    ↓ 需要数据时
┌─────────────────────────────────────────────┐
│  L3 层（资源层）- 调用 read_skill_resource   │
│  内容：数据文件（CSV/JSON/TXT）              │
│  文件：resources/ 目录下的文件               │
└─────────────────────────────────────────────┘
                    ↓ 需要计算时
┌─────────────────────────────────────────────┐
│  L4 层（执行层）- 调用 run_skill_script      │
│  内容：Python 可执行脚本                     │
│  文件：scripts/ 目录下的 .py 文件            │
└─────────────────────────────────────────────┘
```

---

## 二、文件系统结构

### 2.1 标准目录结构

```
data/skills/{skill_name}/
├── SKILL.md              # L1 + L2 层（必需）
├── resources/            # L3 层（可选）
│   ├── data.csv
│   ├── config.json
│   └── reference.txt
└── scripts/              # L4 层（可选）
    ├── calculator.py
    └── processor.py
```

### 2.2 文件命名规范

```
✅ 正确命名：
- hs_code_advisor/       # 下划线分隔
- tax_calculator/        # 全小写
- exchange_rate_tool/    # 描述性名称

❌ 错误命名：
- HS-Code-Advisor/       # 不要使用连字符和大写
- Tax Calculator/        # 不要使用空格
- taxCalculator/         # 不要使用驼峰命名
```

---

## 三、L1 层：索引层（YAML Frontmatter）

### 3.1 标准格式

每个 SKILL.md 文件必须以 YAML frontmatter 开头：

```markdown
---
name: skill_name
description: 技能的简短描述，当用户询问...时使用。
version: 1.0
author: 作者名称（可选）
tags:
  - 标签1
  - 标签2
resources:
  - data.csv
  - config.json
---
```

### 3.2 必填字段

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `name` | string | 技能名称（唯一标识符） | `tax_calculator` |
| `description` | string | 技能描述（触发条件） | `估算进口商品的关税和增值税。当用户询问"这货要交多少税"时使用。` |

### 3.3 可选字段

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `version` | string | 版本号 | `1.0` |
| `author` | string | 作者 | `张三` |
| `tags` | array | 标签列表 | `["税务", "计算"]` |
| `resources` | array | 资源文件列表 | `["tax_rates.csv", "ftas.json"]` |

### 3.4 编写要点

#### ✅ 正确示例

```yaml
---
name: tax_calculator
description: 估算进口商品的关税和增值税。当用户询问"这货要交多少税"、"要交多少关税"、"税费是多少"时使用。
resources:
  - tax_rates.csv
  - ftas.json
---
```

#### ❌ 错误示例

```yaml
---
name: TaxCalculator        # ❌ 不要使用驼峰命名
description: 这是个技能      # ❌ 描述太模糊，缺少触发条件
resources:
  - /path/to/file.csv      # ❌ 不要使用绝对路径
  - ../data.csv            # ❌ 不要使用相对路径
---
```

### 3.5 描述编写技巧

**描述 = 功能 + 触发条件**

```yaml
# 好的描述
description: 帮助用户查询商品的HS编码。当用户询问商品归类、税号、编码、HS编码时使用。

# 不好的描述
description: HS编码查询工具  # ❌ 太简短，缺少触发条件
```

---

## 四、L2 层：指令层（SKILL.md 正文）

### 4.1 标准模板

```markdown
# 技能标题

## 功能说明

简要描述技能的功能和用途。

## 使用场景

当用户询问以下问题时，请使用本技能：
- 场景1
- 场景2
- 场景3

## 工作流程

1. 第一步：...
2. 第二步：...
3. 第三步：...

## 计算公式（如适用）

\`\`\`
公式1 = ...
公式2 = ...
\`\`\`

## 输出格式

\`\`\`
【标题】
字段1: 值1
字段2: 值2
\`\`\`

## 注意事项

- 注意事项1
- 注意事项2

## L4 脚本调用（如适用）

对于简单的计算，可以直接调用 Python 脚本：

\`\`\`
run_skill_script("skill_name", "script_name.py", '{"param": value}')
\`\`\`

**输入**：参数说明
**输出**：结果说明
```

### 4.2 编写规范

#### 使用场景

明确列出何时使用该技能：

```markdown
## 使用场景

当用户询问以下问题时，请使用本技能：
- "这批货要交多少税？"
- "帮我算一下关税"
- "进口芯片要交多少税费"
- "HS编码8501的税率是多少"
```

#### 工作流程

提供清晰的步骤指引：

```markdown
## 工作流程

1. 确认用户提供的信息：
   - CIF价格（完税价格）
   - 商品HS编码
   - 原产国/地区

2. 如果缺少信息，向用户询问

3. 调用脚本进行计算：
   run_skill_script("tax_calculator", "calculate_duty.py", '{"cif_price": ..., "hs_code": ...}')

4. 解读计算结果并回复用户
```

#### L4 脚本说明

如果技能包含可执行脚本，必须说明：

```markdown
## L4 脚本调用（快速计算）

对于简单的税费计算，可以直接调用 Python 脚本进行自动计算：

\`\`\`
run_skill_script("tax_calculator", "calculate_duty.py", '{"cif_price": <CIF价格>, "hs_code": "<HS编码>"}')
\`\`\`

**脚本特性**：
- HS编码 `85423100`（芯片）：关税 0%，增值税 13%
- 其他HS编码：关税 5%，增值税 13%
- 自动计算并返回 JSON 格式结果

**示例**：
- 输入：`{"cif_price": 10000, "hs_code": "85423100"}`
- 输出：`{"duty": 0, "vat": 1300, "total": 1300, "duty_rate": 0.0, "vat_rate": 0.13}`
```

---

## 五、L3 层：资源层（resources/ 目录）

### 5.1 目录结构

```
resources/
├── tax_rates.csv          # CSV 格式数据
├── ftas.json              # JSON 格式配置
├── regulations.txt        # TXT 格式参考文档
└── reference.md           # Markdown 格式手册
```

### 5.2 支持的文件格式

| 格式 | 扩展名 | 用途 | 读取方式 |
|------|--------|------|----------|
| CSV | `.csv` | 表格数据 | `read_skill_resource` |
| JSON | `.json` | 配置数据 | `read_skill_resource` |
| TXT | `.txt` | 纯文本 | `read_skill_resource` |
| Markdown | `.md` | 文档 | `read_skill_resource` |

### 5.3 CSV 文件示例

**文件**: `resources/tax_rates.csv`

```csv
hs_code,description,duty_rate,vat_rate
8501.51.0000,电动机，输出功率≤37.5W,0.10,0.13
8542.31.0000,处理器及控制器,0.00,0.13
8471.30.0000,便携式自动数据处理设备,0.00,0.13
```

**在 SKILL.md 中引用**：

```markdown
## 参考数据

如需查询具体税率，请调用：
\`\`\`
read_skill_resource("tax_calculator", "tax_rates.csv")
\`\`\`

这将返回完整的税率表（CSV格式）。
```

### 5.4 JSON 文件示例

**文件**: `resources/ftas.json`

```json
{
  "china_asean": {
    "name": "中国-东盟自贸协定",
    "countries": ["越南", "泰国", "新加坡"],
    "benefits": "零关税"
  },
  "rcep": {
    "name": "区域全面经济伙伴关系协定",
    "countries": ["日本", "韩国", "澳大利亚"],
    "benefits": "逐步降税"
  }
}
```

**在 SKILL.md 中引用**：

```markdown
## 自贸协定优惠

如需查询自贸协定信息，请调用：
\`\`\`
read_skill_resource("tax_calculator", "ftas.json")
\`\`\`
```

### 5.5 大文件处理

如果文件较大（>100行），系统会自动截断并提示：

```
... (文件过大，仅显示前100行)
```

建议：
- 将大文件拆分为多个小文件
- 或在 SKILL.md 中说明文件结构，让 Agent 有针对性查询

---

## 六、L4 层：执行层（scripts/ 目录）

### 6.1 脚本规范

详见《Python脚本编写规范.md》，简要要求：

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import json

def main():
    # 1. 参数检查
    if len(sys.argv) < 2:
        print(json.dumps({"error": "缺少参数"}))
        sys.exit(1)

    # 2. 解析参数
    args = json.loads(sys.argv[1])

    # 3. 业务逻辑
    result = your_function(args)

    # 4. 输出结果
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
```

### 6.2 在 SKILL.md 中声明

```markdown
## L4 脚本调用

本技能包含以下可执行脚本：

### 1. calculate_duty.py
**功能**：计算关税和增值税
**参数**：
\`\`\`json
{
  "cif_price": 10000,
  "hs_code": "85423100"
}
\`\`\`
**返回**：
\`\`\`json
{
  "duty": 0.0,
  "vat": 1300.0,
  "total": 1300.0
}
\`\`\`

**调用方式**：
\`\`\`
run_skill_script("tax_calculator", "calculate_duty.py", '{"cif_price": 10000, "hs_code": "85423100"}')
\`\`\`
```

---

## 七、完整示例

### 7.1 示例：关税计算器

**目录结构**：
```
data/skills/tax_calculator/
├── SKILL.md
├── resources/
│   ├── tax_rates.csv
│   └── ftas.json
└── scripts/
    └── calculate_duty.py
```

**SKILL.md**：
```markdown
---
name: tax_calculator
description: 估算进口商品的关税和增值税。当用户询问"这货要交多少税"时使用。
resources:
  - tax_rates.csv
  - ftas.json
---

# 进口税费计算器

## 功能说明

本技能提供进口货物关税和增值税的估算功能。

## 使用场景

当用户询问以下问题时使用：
- "这批货要交多少税？"
- "帮我算一下关税"
- "HS编码8501的税率是多少"

## 工作流程

1. 向用户确认必要信息：
   - CIF价格（完税价格）
   - 商品HS编码
   - 原产国（可选）

2. 调用计算脚本：
   run_skill_script("tax_calculator", "calculate_duty.py", '{"cif_price": ..., "hs_code": ...}')

3. 解读结果并回复用户

## 计算公式

关税 = CIF价格 × 关税率
增值税 = (CIF价格 + 关税) × 13%

## 参考数据

详细税率表：
read_skill_resource("tax_calculator", "tax_rates.csv")

自贸协定信息：
read_skill_resource("tax_calculator", "ftas.json")

## L4 脚本调用

**脚本**：calculate_duty.py
**输入**：{"cif_price": 10000, "hs_code": "85423100"}
**输出**：{"duty": 0, "vat": 1300, "total": 1300}
```

---

## 八、开发工作流

### 8.1 创建新技能步骤

#### 第一步：规划技能

```
1. 确定技能名称（英文，下划线分隔）
2. 编写技能描述（包含触发条件）
3. 列出所需的资源文件
4. 确定是否需要可执行脚本
```

#### 第二步：创建目录结构

```bash
mkdir -p data/skills/your_skill_name
mkdir -p data/skills/your_skill_name/resources
mkdir -p data/skills/your_skill_name/scripts
```

#### 第三步：编写 SKILL.md

```bash
touch data/skills/your_skill_name/SKILL.md
```

按照 L1 + L2 层规范编写内容。

#### 第四步：准备资源文件（如需要）

```bash
# 创建 CSV 数据
touch data/skills/your_skill_name/resources/data.csv

# 创建 JSON 配置
touch data/skills/your_skill_name/resources/config.json
```

#### 第五步：编写脚本（如需要）

```bash
touch data/skills/your_skill_name/scripts/processor.py
```

按照《Python脚本编写规范.md》编写脚本。

#### 第六步：测试技能

```python
# 1. 重启服务器（自动加载新技能）
python src/main.py

# 2. 在功能二（智能体）中测试
用户输入：[触发技能描述的问题]

# 3. 验证 L1 层加载
服务器日志应显示：
[SkillManager] [OK] L1加载: your_skill_name - ...

# 4. 验证 L2 层加载
Agent 应调用 use_skill 工具

# 5. 验证 L3 层（如有）
Agent 应调用 read_skill_resource 工具

# 6. 验证 L4 层（如有）
Agent 应调用 run_skill_script 工具
```

### 8.2 调试技巧

#### 查看 L1 层是否加载

```bash
# 服务器启动日志
[SkillManager] [OK] L1加载: tax_calculator - 估算进口商品的关税和增值税...
```

#### 查看 SKILL.md 解析是否正确

```python
# 在 Python 中测试
from src.services.skill_manager import SkillManager

manager = SkillManager()
content = manager.load_skill_content('tax_calculator')
print(content)
```

#### 测试资源文件读取

```python
# 测试 L3 层
result = manager.get_resource_content('tax_calculator', 'tax_rates.csv')
print(result)
```

#### 测试脚本执行

```bash
# 测试 L4 层
python data/skills/tax_calculator/scripts/calculate_duty.py '{"cif_price": 10000, "hs_code": "85423100"}'
```

---

## 九、高级技巧

### 9.1 技能组合调用

一个技能可以调用另一个技能的资源：

```markdown
## 相关技能

如需查询 HS 编码，请先使用 hs_code_advisor 技能：
use_skill("hs_code_advisor", "商品名称")

获得 HS 编码后，再使用本技能计算税费。
```

### 9.2 条件化资源加载

根据用户输入决定是否加载资源：

```markdown
## 资源加载策略

1. 如果用户询问具体商品税率：
   → 调用 read_skill_resource("tax_calculator", "tax_rates.csv")

2. 如果用户询问自贸协定：
   → 调用 read_skill_resource("tax_calculator", "ftas.json")

3. 如果只需要快速估算：
   → 直接调用 run_skill_script("tax_calculator", "calculate_duty.py", ...)
```

### 9.3 多脚本协作

一个技能可以包含多个脚本，各司其职：

```markdown
## L4 脚本列表

### 1. calculate_duty.py
计算基本关税和增值税

### 2. calculate_consumption_tax.py
计算消费税（如适用）

### 3. format_result.py
格式化输出结果
```

---

## 十、最佳实践

### 10.1 L1 层（索引层）

- [ ] 技能名称简短、描述性、全小写
- [ ] 描述包含明确的触发条件
- [ ] 描述不超过 100 字符
- [ ] 正确列出 resources 字段

### 10.2 L2 层（指令层）

- [ ] 使用 Markdown 格式化
- [ ] 结构清晰（功能、场景、流程、输出）
- [ ] 提供具体示例
- [ ] 说明 L4 脚本调用方式
- [ ] 提示 L3 资源文件可用

### 10.3 L3 层（资源层）

- [ ] 文件命名清晰（data.csv, config.json）
- [ ] CSV/JSON 格式标准
- [ ] 文件大小合理（< 1MB）
- [ ] 在 SKILL.md 中说明用途

### 10.4 L4 层（执行层）

- [ ] 脚本文件名描述性（calculate_duty.py）
- [ ] 遵循 Python 脚本编写规范
- [ ] 参数验证完善
- [ ] 错误处理健全
- [ ] 输出标准 JSON 格式

### 10.5 测试清单

- [ ] 目录结构正确
- [ ] SKILL.md 格式正确
- [ ] L1 层加载成功
- [ ] L2 层内容可读
- [ ] L3 资源文件可访问
- [ ] L4 脚本可执行
- [ ] Agent 能正确调用
- [ ] 返回结果符合预期

---

## 十一、常见问题

### Q1: 技能名称可以重复吗？

**A**: 不可以。技能名称（`name` 字段）必须唯一，否则后加载的会覆盖先加载的。

### Q2: 如何更新技能？

**A**:
1. 修改 SKILL.md 或资源文件
2. 重启服务器（或等待下次启动）
3. 技能会自动重新加载

### Q3: resources 字段是必需的吗？

**A**: 不是。如果技能不需要 L3 层资源，可以省略 `resources` 字段或设为空数组：
```yaml
resources: []
```

### Q4: 一个技能可以有多个脚本吗？

**A**: 可以。在 `scripts/` 目录下放置多个 `.py` 文件，在 SKILL.md 中分别说明。

### Q5: 如何调试技能加载失败？

**A**: 查看服务器日志：
```
[SkillManager] [ERROR] L1加载失败: skill_name - 错误详情
```

常见原因：
- YAML frontmatter 格式错误
- `name` 字段缺失
- 描述字段为空

### Q6: 技能可以调用外部 API 吗？

**A**: 可以，但在 L4 脚本中调用。注意：
- 使用 `urllib` 标准库（避免依赖 requests）
- 添加超时控制
- 完善错误处理

### Q7: 如何实现技能之间的协作？

**A**: 在 SKILL.md 中说明：
```markdown
## 协作流程

1. 先使用 skill_a 获取基础数据
2. 再使用本技能进行计算
```

Agent 会根据说明自动调用多个技能。

---

## 十二、版本管理

### 12.1 版本号规范

使用语义化版本号（Semantic Versioning）：

```
主版本.次版本.修订版本

示例：
1.0.0 - 初始版本
1.1.0 - 新增功能（L4 脚本）
1.1.1 - Bug 修复
2.0.0 - 重大变更（L3 资源文件格式变更）
```

### 12.2 变更日志

在 SKILL.md 中维护变更日志：

```markdown
## 变更日志

### v1.1.0 (2026-01-29)
- 新增：L4 脚本 calculate_duty.py
- 优化：改进税费计算公式

### v1.0.0 (2026-01-20)
- 初始版本
- 支持 L3 资源文件
```

---

## 十三、参考示例

### 13.1 完整技能示例

**技能名称**: `exchange_rate_tool`

**目录结构**:
```
data/skills/exchange_rate_tool/
├── SKILL.md
├── resources/
│   └── currency_codes.json
└── scripts/
    └── convert.py
```

**SKILL.md**:
```markdown
---
name: exchange_rate_tool
description: 查询和换算货币汇率。当用户询问汇率、货币换算、美元兑人民币时使用。
version: 1.0.0
resources:
  - currency_codes.json
---

# 汇率查询工具

## 功能说明

提供多币种汇率查询和换算功能。

## 使用场景

- "美元兑人民币的汇率是多少？"
- "100美元能换多少人民币？"
- "欧元汇率"
- "帮我把日元换成人民币"

## 工作流程

1. 识别用户提到的货币（USD/CNY/EUR/JPY等）
2. 调用换算脚本进行计算
3. 返回结果并给出建议

## L4 脚本调用

**脚本**: convert.py
**参数**: {"amount": 100, "from": "USD", "to": "CNY"}
**返回**: {"result": 650, "rate": 6.5}

**调用方式**:
\`\`\`
run_skill_script("exchange_rate_tool", "convert.py", '{"amount": 100, "from": "USD", "to": "CNY"}')
\`\`\`

## 参考数据

支持的货币代码：
read_skill_resource("exchange_rate_tool", "currency_codes.json")
```

---

**文档版本**: v1.0
**最后更新**: 2026-01-29
**维护者**: Claude Code Sonnet 4.5

**相关文档**:
- 《Python脚本编写规范.md》
- 《python沙箱规范.md》
- 《渐进式读取skill规范.md》
