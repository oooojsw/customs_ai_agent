# Python 脚本编写规范（L4 层）

## 概述

本规范适用于为海关 AI 智能体系统编写 L4 层可执行脚本。脚本将在独立子进程中运行，通过标准输入输出与 Agent 通信。

**适用场景**：
- 复杂数学计算（关税、增值税、汇率换算）
- 数据转换和格式化
- 业务逻辑处理
- 第三方 API 调用

---

## 一、脚本模板

### 标准模板（推荐）

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
脚本名称：[功能名称]
脚本功能：[详细描述脚本功能]
输入参数：通过命令行参数接收 JSON 字符串
输出结果：将结果打印到 stdout（JSON 格式）
"""

import sys
import json

def main():
    # ========== 第一步：参数检查 ==========
    if len(sys.argv) < 2:
        error_result = {
            "error": "缺少参数",
            "message": "请提供 JSON 格式的参数"
        }
        print(json.dumps(error_result, ensure_ascii=False))
        sys.exit(1)

    # ========== 第二步：解析 JSON 参数 ==========
    try:
        args = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        error_result = {
            "error": "参数 JSON 格式无效",
            "details": str(e)
        }
        print(json.dumps(error_result, ensure_ascii=False))
        sys.exit(1)

    # ========== 第三步：提取参数（带默认值） ==========
    param1 = args.get('param1', default_value1)
    param2 = args.get('param2', default_value2)

    # ========== 第四步：参数验证 ==========
    if not isinstance(param1, (int, float)):
        error_result = {
            "error": "参数类型错误",
            "field": "param1",
            "expected": "number"
        }
        print(json.dumps(error_result, ensure_ascii=False))
        sys.exit(1)

    # ========== 第五步：业务逻辑处理 ==========
    try:
        # 这里是你的核心计算逻辑
        result_value = your_calculation_function(param1, param2)
    except Exception as e:
        error_result = {
            "error": "计算失败",
            "details": str(e)
        }
        print(json.dumps(error_result, ensure_ascii=False))
        sys.exit(1)

    # ========== 第六步：输出结果（JSON 格式） ==========
    result = {
        "success": True,
        "result": result_value,
        "field1": value1,
        "field2": value2
    }
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
```

---

## 二、编写规范

### 2.1 文件头规范

每个脚本必须包含标准文件头：

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
脚本名称：关税计算器
脚本功能：根据 CIF 价格和 HS 编码计算关税和增值税
作者：[可选]
创建日期：2026-01-29
版本：1.0
"""
```

### 2.2 参数接收规范

#### 正确示例

```python
# 方式1：通过命令行参数接收（推荐）
if len(sys.argv) < 2:
    print(json.dumps({"error": "缺少参数"}))
    sys.exit(1)

args = json.loads(sys.argv[1])
cif_price = args.get('cif_price', 0)
```

#### 错误示例

```python
# ❌ 不要使用 input()（会阻塞进程）
user_input = input()

# ❌ 不要从环境变量读取（不兼容 Windows）
import os
value = os.getenv('PARAM')

# ❌ 不要读取文件（不符合规范）
with open('params.txt') as f:
    data = f.read()
```

### 2.3 参数验证规范

必须对所有输入参数进行验证：

```python
# 类型检查
if not isinstance(cif_price, (int, float)):
    print(json.dumps({
        "error": "参数类型错误",
        "field": "cif_price",
        "expected": "number",
        "received": type(cif_price).__name__
    }))
    sys.exit(1)

# 范围检查
if cif_price < 0:
    print(json.dumps({
        "error": "参数值超出范围",
        "field": "cif_price",
        "min": 0,
        "received": cif_price
    }))
    sys.exit(1)

# 必填检查
if 'hs_code' not in args:
    print(json.dumps({
        "error": "缺少必填参数",
        "field": "hs_code"
    }))
    sys.exit(1)
```

### 2.4 输出规范

#### 标准 JSON 输出（推荐）

```python
result = {
    "success": True,
    "data": {
        "field1": value1,
        "field2": value2
    },
    "metadata": {
        "timestamp": "2026-01-29T10:00:00",
        "version": "1.0"
    }
}
print(json.dumps(result, ensure_ascii=False))
```

#### 错误输出

```python
error_result = {
    "success": False,
    "error": {
        "code": "INVALID_PARAMETER",
        "message": "参数值无效",
        "field": "cif_price",
        "details": "CIF 价格必须大于 0"
    }
}
print(json.dumps(error_result, ensure_ascii=False))
sys.exit(1)
```

#### 简化输出（可选）

```python
# 对于简单脚本，可以直接输出结果
print(json.dumps({
    "duty": 500.0,
    "vat": 1365.0,
    "total": 1865.0
}, ensure_ascii=False))
```

### 2.5 错误处理规范

#### 必须捕获的异常

```python
try:
    # 业务逻辑
    result = calculate()
except ValueError as e:
    print(json.dumps({
        "error": "值错误",
        "details": str(e)
    }))
    sys.exit(1)
except KeyError as e:
    print(json.dumps({
        "error": "缺少必要字段",
        "field": str(e)
    }))
    sys.exit(1)
except ZeroDivisionError:
    print(json.dumps({
        "error": "除零错误",
        "message": "计算时发生除零"
    }))
    sys.exit(1)
except Exception as e:
    print(json.dumps({
        "error": "未知错误",
        "type": type(e).__name__,
        "details": str(e)
    }))
    sys.exit(1)
```

---

## 三、依赖管理规范

### 3.1 仅使用标准库（推荐）

```python
# ✅ 允许的标准库模块
import json      # JSON 处理
import sys       # 系统参数
import math      # 数学计算
import datetime  # 日期时间
import re        # 正则表达式
import csv       # CSV 文件读取
```

### 3.2 避免使用第三方库

```python
# ❌ 不要使用（除非用户环境已安装）
import numpy as np
import pandas as pd
import requests
```

### 3.3 如需外部依赖

如果确实需要第三方库，必须在 SKILL.md 中说明：

```markdown
## 环境要求

本脚本需要以下依赖：
- requests>=2.28.0
- pandas>=1.5.0

安装命令：
```bash
pip install requests pandas
```
```

---

## 四、安全规范

### 4.1 防止路径遍历

```python
# ❌ 错误：直接使用用户输入的路径
file_path = args.get('file_path')
with open(file_path) as f:
    data = f.read()

# ✅ 正确：验证路径合法性
import os
file_path = args.get('file_name')
allowed_dir = '/path/to/allowed/dir'
full_path = os.path.join(allowed_dir, file_path)

if not os.path.abspath(full_path).startswith(allowed_dir):
    print(json.dumps({"error": "非法路径"}))
    sys.exit(1)
```

### 4.2 防止命令注入

```python
# ❌ 错误：直接拼接命令
import subprocess
cmd = f"ls {user_input}"
subprocess.run(cmd, shell=True)

# ✅ 正确：使用列表形式
subprocess.run(['ls', user_input], shell=False)
```

### 4.3 防止资源耗尽

```python
# ✅ 限制循环次数
MAX_ITERATIONS = 1000
for i in range(MAX_ITERATIONS):
    # 计算逻辑
    pass

# ✅ 限制文件大小
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
file_size = os.path.getsize(file_path)
if file_size > MAX_FILE_SIZE:
    print(json.dumps({"error": "文件过大"}))
    sys.exit(1)
```

---

## 五、性能规范

### 5.1 超时控制

系统会自动在 10 秒后终止脚本，但建议自行控制：

```python
import signal

def timeout_handler(signum, frame):
    raise TimeoutError("脚本执行超时")

signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(8)  # 8秒后超时（留2秒余量）
```

### 5.2 避免死循环

```python
# ❌ 错误：可能死循环
while True:
    if condition:
        break

# ✅ 正确：限制迭代次数
max_iterations = 1000
for i in range(max_iterations):
    if condition:
        break
```

---

## 六、测试规范

### 6.1 单元测试示例

```python
def test_calculation():
    # 测试正常情况
    result = calculate_duty(10000, '85423100')
    assert result['duty'] == 0
    assert result['vat'] == 1300

    # 测试边界情况
    result = calculate_duty(0, '85423100')
    assert result['duty'] == 0

    # 测试错误输入
    try:
        calculate_duty(-1000, '85423100')
        assert False, "应该抛出异常"
    except ValueError:
        pass
```

### 6.2 手动测试方法

```bash
# 测试脚本
python your_script.py '{"param1": 100, "param2": "test"}'

# 预期输出
{"success": true, "result": {...}}
```

---

## 七、实战示例

### 7.1 税费计算脚本

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
关税和增值税计算器
"""
import sys
import json

def main():
    # 参数检查
    if len(sys.argv) < 2:
        print(json.dumps({"error": "缺少参数"}))
        sys.exit(1)

    # 解析参数
    try:
        args = json.loads(sys.argv[1])
        cif_price = float(args.get('cif_price', 0))
        hs_code = args.get('hs_code', '')
    except (json.JSONDecodeError, ValueError) as e:
        print(json.dumps({"error": f"参数解析失败: {str(e)}"}))
        sys.exit(1)

    # 参数验证
    if cif_price < 0:
        print(json.dumps({"error": "CIF 价格不能为负数"}))
        sys.exit(1)

    if not hs_code:
        print(json.dumps({"error": "HS 编码不能为空"}))
        sys.exit(1)

    # 业务逻辑
    duty_rate = 0.0 if hs_code == '85423100' else 0.05
    vat_rate = 0.13

    duty = cif_price * duty_rate
    vat = (cif_price + duty) * vat_rate
    total = duty + vat

    # 输出结果
    result = {
        "duty": round(duty, 2),
        "vat": round(vat, 2),
        "total": round(total, 2),
        "duty_rate": duty_rate,
        "vat_rate": vat_rate,
        "hs_code": hs_code
    }
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
```

### 7.2 汇率换算脚本

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
多币种汇率换算器（简化版）
"""
import sys
import json

# 汇率表（示例）
EXCHANGE_RATES = {
    "USD": 1.0,
    "CNY": 6.5,
    "EUR": 0.85,
    "JPY": 110.0
}

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "缺少参数"}))
        sys.exit(1)

    try:
        args = json.loads(sys.argv[1])
        amount = float(args.get('amount', 0))
        from_currency = args.get('from', 'USD').upper()
        to_currency = args.get('to', 'CNY').upper()
    except (json.JSONDecodeError, ValueError) as e:
        print(json.dumps({"error": f"参数解析失败: {str(e)}"}))
        sys.exit(1)

    # 验证货币代码
    if from_currency not in EXCHANGE_RATES:
        print(json.dumps({"error": f"不支持的源货币: {from_currency}"}))
        sys.exit(1)

    if to_currency not in EXCHANGE_RATES:
        print(json.dumps({"error": f"不支持的目标货币: {to_currency}"}))
        sys.exit(1)

    # 计算汇率
    usd_amount = amount / EXCHANGE_RATES[from_currency]
    result_amount = usd_amount * EXCHANGE_RATES[to_currency]

    result = {
        "amount": round(result_amount, 2),
        "from": from_currency,
        "to": to_currency,
        "rate": EXCHANGE_RATES[to_currency] / EXCHANGE_RATES[from_currency]
    }
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
```

---

## 八、调试技巧

### 8.1 添加调试日志

```python
import sys

# 调试输出会显示在 Agent 日志中
def debug_log(message):
    print(f"[DEBUG] {message}", file=sys.stderr)

# 使用
debug_log(f"开始计算，参数: {args}")
```

### 8.2 验证 JSON 格式

```python
# 测试你的 JSON 输出是否正确
import json
result = {"key": "value"}
json_str = json.dumps(result, ensure_ascii=False)
print(json_str)

# 验证是否可以解析回来
parsed = json.loads(json_str)
assert parsed == result
```

### 8.3 本地测试脚本

创建 `test_script.py`：

```python
import subprocess
import json

def test_script(script_path, args):
    result = subprocess.run(
        ['python', script_path, json.dumps(args)],
        capture_output=True,
        text=True
    )

    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
    print("Return Code:", result.returncode)

    if result.returncode == 0:
        print("Result:", json.loads(result.stdout))

# 测试
test_script(
    'scripts/calculate_duty.py',
    {'cif_price': 10000, 'hs_code': '85423100'}
)
```

---

## 九、常见问题

### Q1: 脚本执行超时怎么办？

**A**: 确保脚本在 10 秒内完成：
- 避免死循环
- 减少不必要的计算
- 使用缓存

### Q2: 如何处理浮点数精度？

**A**: 使用 `round()` 函数：

```python
result = 0.1 + 0.2  # 0.30000000000000004
rounded = round(result, 2)  # 0.3
```

### Q3: 如何返回复杂结构？

**A**: 使用嵌套的 JSON：

```python
result = {
    "items": [
        {"name": "item1", "value": 100},
        {"name": "item2", "value": 200}
    ],
    "summary": {
        "total": 300,
        "count": 2
    }
}
print(json.dumps(result, ensure_ascii=False))
```

### Q4: 如何调用外部 API？

**A**: 使用标准库 `urllib`：

```python
from urllib import request
import json

url = "https://api.example.com/rate"
data = request.urlopen(url).read()
result = json.loads(data)
```

---

## 十、最佳实践清单

- [ ] 使用标准模板
- [ ] 所有参数都进行验证
- [ ] 输出标准 JSON 格式
- [ ] 捕获所有异常
- [ ] 添加详细注释
- [ ] 使用类型提示（可选）
- [ ] 编写单元测试
- [ ] 本地测试通过
- [ ] 更新 SKILL.md 文档
- [ ] 性能测试（< 10 秒）

---

**文档版本**: v1.0
**最后更新**: 2026-01-29
**维护者**: Claude Code Sonnet 4.5
