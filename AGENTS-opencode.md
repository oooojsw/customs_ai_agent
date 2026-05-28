# AGENTS.md - 智慧口岸AI代理开发指南

本文件为操作此代码库的代理性编码工具提供开发规范。

## 开发环境
- **Python版本**: 3.10+ (推荐 3.11+)
- **包管理**: pip + requirements.txt

### 依赖安装
```bash
pip install -r requirements.txt
```

### 环境变量配置 (.env)
```bash
DEEPSEEK_API_KEY="your-api-key"
DEEPSEEK_BASE_URL="https://api.deepseek.com"
DEEPSEEK_MODEL="deepseek-chat"
HTTP_PROXY="http://127.0.0.1:7890"
HTTPS_PROXY="http://127.0.0.1:7890"
API_PORT=8000
API_HOST="127.0.0.1"
```

## 构建和运行命令
```bash
# 启动开发服务器
python src/main.py
# 或
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload

# API文档: http://localhost:8000/docs | http://localhost:8000/redoc

# 停止服务
netstat -ano | findstr :8000
taskkill //F //PID <进程ID>
```

## 测试命令
```bash
# 根目录测试
python test_siliconflow.py

# tests/ 目录
pytest tests/
pytest tests/ -v

# 运行单个测试
python tests/test_export.py
pytest tests/test_export.py::test_function_name -v
pytest tests/test_export.py -k "keyword" -v
```

## 代码风格指南

### 1. 导入规范
```python
# 1. 标准库 → 2. 第三方库 → 3. 本地模块（空行分隔，按字母排序）
import os
import asyncio
from typing import Optional, List, Dict
import httpx
from fastapi import FastAPI
from pydantic import BaseModel
from src.config.loader import settings
from src.services.chat_agent import CustomsChatAgent
```

### 2. 格式化规范
- **最大行长**: 100字符
- **换行**: 操作符后换行，缩进4空格
```python
def process_data(
    data: Dict[str, Any],
    config: Optional[Config] = None
) -> List[Result]:
    return [process_item(item, config) for item in data.values()]
```

### 3. 类型注解（强制）
- 所有函数参数和返回值必须有类型注解
- 使用 `Dict`, `List`, `Optional` 而非 `dict`, `list`
```python
def analyze_customs_declaration(raw_data: str, language: str = "zh") -> Dict[str, Any]:
    pass
```

### 4. 命名约定
| 类型 | 规则 | 示例 |
|------|------|------|
| 类 | PascalCase | `CustomsChatAgent` |
| 函数/变量 | snake_case | `analyze_data` |
| 常量 | UPPER_SNAKE_CASE | `MAX_RETRY_COUNT = 3` |
| 私有成员 | `_前缀` | `self._config` |

### 5. 错误处理
- 具体异常优先于通用异常
- 禁止裸 `except:` 和空 `pass`
```python
try:
    result = await process_data(data)
except httpx.TimeoutException:
    logger.error(f"请求超时: {data}")
    raise HTTPException(status_code=504, detail="服务超时")
except Exception as e:
    logger.error(f"未知错误: {e}", exc_info=True)
    raise HTTPException(status_code=500, detail="内部服务器错误")
```

### 6. 异步编程
- 所有I/O操作使用async/await
- 避免在async函数中使用阻塞操作
```python
async def analyze_data(self, data: str) -> Dict[str, Any]:
    tasks = [self._validate(data), self._check_risks(data)]
    results = await asyncio.gather(*tasks)
    return self._combine_results(results)
```

### 7. 文档字符串
遵循Google风格，包含Args/Returns/Raises说明。
```python
def analyze_customs_declaration(raw_data: str) -> Dict[str, Any]:
    """
    分析海关申报数据并识别潜在风险。

    Args:
        raw_data: 原始申报数据文本

    Returns:
        包含风险等级和建议的字典

    Raises:
        ValueError: 当输入数据无效时
    """
    pass
```

## 安全注意事项
- **禁止硬编码API密钥**: 使用 `os.getenv()` 读取
- **日志脱敏**: 避免记录敏感信息

## 项目结构
```
src/
├── main.py              # 应用入口
├── api/routes.py       # API路由 (/api/v1/*)
├── config/             # 配置管理
├── core/               # 核心编排 (审单)
├── services/           # 三大Agent
│   ├── chat_agent.py   # 法规咨询
│   └── report_agent.py # 报告生成
└── database/           # SQLite数据层

web/                    # 前端界面
config/                 # 配置文件
data/knowledge/         # RAG知识库
```

## 关键实现细节
1. **Windows事件循环** (`src/main.py`):
   ```python
   if platform.system() == 'Windows':
       asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
   ```

2. **网络代理穿透**:
   ```python
   async_transport = httpx.AsyncHTTPTransport(proxy=proxy_url, verify=False)
   ```

3. **SSE流式响应**: 使用 `StreamingResponse` + 异步生成器

## 扩展开发指南
- **添加审单规则**: 编辑 `config/risk_rules.json`
- **添加知识库文档**: 放入 `data/knowledge/`，重启自动重建索引
- **添加LLM工具**: 在 `src/services/chat_agent.py` 的 tools 列表添加

---

**详细开发指南见 CLAUDE.md**
