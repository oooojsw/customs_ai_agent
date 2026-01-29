完美！我已经获取到了每刻报销的详细API文档。现在给你具体的调用示例：

## 📋 每刻报销汇率API - 完整调用示例

### 1️⃣ **基础信息**

```
接口地址: https://openapi-ng.maycur.com/api/openapi/currency/sys-exchange-rate
请求方式: POST
Content-Type: application/json
```

### 2️⃣ **JavaScript/Node.js 调用示例**

```javascript
// ========== 基础调用 ==========
async function fetchExchangeRate(from, to, effectiveDate) {
  const url = 'https://openapi-ng.maycur.com/api/openapi/currency/sys-exchange-rate';
  
  const payload = {
    data: {
      from: from,           // 基准货币，如 "USD", "EUR"
      to: to,              // 兑换货币，如 "CNY"
      effectiveDate: effectiveDate  // 毫秒级时间戳
    }
  };

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    const result = await response.json();
    
    if (result.success) {
      return {
        status: 'success',
        data: result.data
      };
    } else {
      return {
        status: 'error',
        message: result.message
      };
    }
  } catch (error) {
    return {
      status: 'error',
      message: error.message
    };
  }
}

// ========== 使用示例 ==========
// 查询今天 EUR -> CNY 的汇率
const today = new Date();
today.setHours(0, 0, 0, 0);
const timestamp = today.getTime();

const result = await fetchExchangeRate('EUR', 'CNY', timestamp);
console.log(result);
```

### 3️⃣ **Python 调用示例**

```python
import requests
import json
from datetime import datetime

def fetch_exchange_rate(from_currency, to_currency, effective_date_ms):
    """
    查询汇率
    :param from_currency: 基准货币 (e.g., 'USD', 'EUR')
    :param to_currency: 兑换货币 (e.g., 'CNY')
    :param effective_date_ms: 生效时间（毫秒级时间戳）
    :return: 汇率信息
    """
    url = 'https://openapi-ng.maycur.com/api/openapi/currency/sys-exchange-rate'
    
    payload = {
        'data': {
            'from': from_currency,
            'to': to_currency,
            'effectiveDate': effective_date_ms
        }
    }
    
    headers = {
        'Content-Type': 'application/json'
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        result = response.json()
        
        if result.get('success'):
            return {
                'status': 'success',
                'data': result.get('data', [])
            }
        else:
            return {
                'status': 'error',
                'message': result.get('message', 'Unknown error')
            }
    except Exception as e:
        return {
            'status': 'error',
            'message': str(e)
        }


# ========== 使用示例 ==========
import time

# 获取当前时间的毫秒级时间戳
current_timestamp_ms = int(time.time() * 1000)

# 查询 USD -> CNY
result = fetch_exchange_rate('USD', 'CNY', current_timestamp_ms)
print(json.dumps(result, indent=2, ensure_ascii=False))

# 输出结果示例：
# {
#   "status": "success",
#   "data": [
#     {
#       "fromCurrency": "USD",
#       "toCurrency": "CNY",
#       "exchangeRate": 7.0850,
#       "rateType": "SYSTEM",  # SYSTEM=中行 CUSTOM=自定义
#       "startedAt": 1689782414000,
#       "endAt": 0
#     }
#   ]
# }
```

### 4️⃣ **cURL 调用示例**

```bash
curl -X POST https://openapi-ng.maycur.com/api/openapi/currency/sys-exchange-rate \
  -H "Content-Type: application/json" \
  -d '{
    "data": {
      "from": "USD",
      "to": "CNY",
      "effectiveDate": 1689830100000
    }
  }'
```

### 5️⃣ **完整实际调用案例**

```javascript
// ========== EUR -> CNY 的实时查询 ==========
async function getRealTimeExchangeRate() {
  const now = new Date();
  const timestamp = now.getTime();  // 当前时间的毫秒级戳
  
  const response = await fetch(
    'https://openapi-ng.maycur.com/api/openapi/currency/sys-exchange-rate',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        data: {
          from: 'EUR',
          to: 'CNY',
          effectiveDate: timestamp
        }
      })
    }
  );
  
  const result = await response.json();
  
  if (result.success && result.data.length > 0) {
    const rate = result.data[0];
    
    console.log(`\n💱 汇率查询结果`);
    console.log(`─────────────────────`);
    console.log(`货币对: ${rate.fromCurrency} → ${rate.toCurrency}`);
    console.log(`汇率: ${rate.exchangeRate}`);
    console.log(`来源: ${rate.rateType === 'SYSTEM' ? '✅ 中国银行' : '📝 自定义'}`);
    console.log(`生效时间: ${new Date(rate.startedAt).toLocaleString()}`);
    console.log(`失效时间: ${rate.endAt === 0 ? '永久有效' : new Date(rate.endAt).toLocaleString()}`);
    
    // 进行货币转换计算
    const amount = 100;  // 要转换的金额
    const convertedAmount = amount * rate.exchangeRate;
    console.log(`\n${amount} ${rate.fromCurrency} = ${convertedAmount.toFixed(2)} ${rate.toCurrency}`);
  }
}

getRealTimeExchangeRate();
```

***

## 📊 **响应参数说明**

| 参数 | 含义 | 示例 |
|------|------|------|
| **fromCurrency** | 基准货币 | USD, EUR, GBP |
| **toCurrency** | 兑换货币 | CNY |
| **exchangeRate** | 汇率值 | 7.0850 |
| **rateType** | 汇率类型 | `SYSTEM`(中行) / `CUSTOM`(自定义) |
| **startedAt** | 生效时间（毫秒戳） | 1689782414000 |
| **endAt** | 失效时间（0 = 永不失效） | 0 或具体时间戳 |

***

## ⚠️ **重要注意事项**

1. **effectiveDate 是毫秒级时间戳**
   - JavaScript: `Date.now()` 或 `new Date().getTime()`
   - Python: `int(time.time() * 1000)`
   - Unix时间戳要 × 1000

2. **会返回多条汇率**（优先级顺序）
   - 自定义汇率（CUSTOM）
   - 中国银行汇率（SYSTEM）
   - 可能有多个生效期间的数据

3. **货币代码使用标准 ISO 4217**
   - USD (美元)、EUR (欧元)、GBP (英镑)、JPY (日元)、CNY (人民币) 等

4. **无需认证密钥**（根据文档）
   - 但建议确认是否需要在请求头中添加授权信息

***

想要我帮你封装成一个**完整的 Tool 工具函数**供 AI 使用吗？


完美！现在我已经整理好了完整的调用指南。关键修正如下：

## 📌 **核心问题解决**

### ❌ 之前错误的原因
- 提供的是**相对路径**：`/api/openapi/currency/sys-exchange-rate`
- 缺少**基础域名**

### ✅ 正确的完整 API 地址

```
https://openapi-ng.maycur.com/api/openapi/currency/sys-exchange-rate
```

***

## 🔑 **必须要做的 4 件事**

### 1. **完整的 URL**
```javascript
const url = 'https://openapi-ng.maycur.com/api/openapi/currency/sys-exchange-rate';
```

### 2. **请求头认证**
```javascript
headers: {
  'Content-Type': 'application/json',
  'tokenId': '你的tokenId',    // ⚠️ 需要向每刻申请
  'entCode': '你的entCode'     // ⚠️ 需要向每刻申请
}
```

### 3. **毫秒级时间戳**
```javascript
// ✅ 正确
const timestamp = Date.now();                    // 1706505600000 (毫秒)

// ❌ 错误
const timestamp = Math.floor(Date.now() / 1000); // 1706505600 (秒) - 不对！
```

### 4. **完整的请求体**
```json
{
  "data": {
    "from": "USD",
    "to": "CNY",
    "effectiveDate": 1706505600000
  }
}
```

***

## 🧪 **快速测试代码**

```javascript
async function testMaycurAPI() {
  const response = await fetch(
    'https://openapi-ng.maycur.com/api/openapi/currency/sys-exchange-rate',
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'tokenId': '你的tokenId',
        'entCode': '你的entCode'
      },
      body: JSON.stringify({
        data: {
          from: 'USD',
          to: 'CNY',
          effectiveDate: Date.now()
        }
      })
    }
  );
  
  const result = await response.json();
  console.log(result);
}
```

***

我已经生成了完整的 **API 调用指南文档**（maycur_exchange_rate_api.md），包含：
- ✅ 完整的 API 地址和参数
- ✅ JavaScript、Python、cURL 示例代码
- ✅ 时间戳转换速查表
- ✅ 常见错误排查表
- ✅ 关键要点总结

**重点：一定要向每刻申请 tokenId 和 entCode，才能成功调用！** 🔑