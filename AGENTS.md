# AGENTS.md - 智慧口岸AI代理开发指南

本文件为操作此代码库的代理性编码工具（如AI编程助手）提供全面的开发规范和操作指南。所有代理在修改代码前必须严格遵循这些准则。

## 开发环境设置

### Python版本要求
- **最低版本**: Python 3.10+
- **推荐版本**: Python 3.11+
- **包管理**: pip + requirements.txt

### 依赖安装
```bash
# 安装所有依赖
pip install -r requirements.txt

# 如果需要开发依赖（当前项目无额外dev依赖）
pip install -r requirements-dev.txt  # 如存在
```

### 环境变量配置
在项目根目录创建 `.env` 文件：
```bash
# DeepSeek API 配置
DEEPSEEK_API_KEY="your-api-key"
DEEPSEEK_BASE_URL="https://api.deepseek.com"
DEEPSEEK_MODEL="deepseek-chat"

# 网络代理（必须配置）
HTTP_PROXY="http://127.0.0.1:7890"
HTTPS_PROXY="http://127.0.0.1:7890"

# 服务配置
API_PORT=8000
API_HOST="127.0.0.1"
```

## 构建和运行命令

### 开发服务器启动
```bash
# 推荐方式：支持热重载
python src/main.py

# 备选方式：使用uvicorn
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload

# Docker方式
docker-compose up -d

# 查看服务状态
docker-compose logs -f
```

### API文档访问
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI Schema**: http://localhost:8000/openapi.json

### 停止服务
```bash
# Docker方式
docker-compose down

# 进程方式（查找进程ID）
netstat -ano | findstr :8000
taskkill /PID <进程ID> /F
```

## 测试命令

### 运行所有测试
```bash
# 当前项目只有一个集成测试文件
python test_vietnamese_fix.py

# 如将来添加pytest框架
pytest
pytest tests/
pytest tests/ -v  # 详细输出
```

### 运行单个测试
```bash
# 直接运行测试文件
python test_vietnamese_fix.py

# 如使用pytest运行特定测试类/方法
pytest tests/test_example.py::TestClass::test_method -v
pytest tests/test_example.py -k "test_keyword" -v
```

### 测试覆盖率
```bash
# 如将来配置coverage
pytest --cov=src --cov-report=html
# 查看报告：open htmlcov/index.html
```

### 性能测试
```bash
# 基础性能测试（当前无专门配置）
python -m timeit -s "import asyncio; from src.services.chat_agent import CustomsChatAgent" "asyncio.run(CustomsChatAgent().chat('Hello'))"
```

## Lint和代码质量检查

### 当前Lint配置
**注意**: 项目当前未配置专门的lint工具。建议添加以下配置：

### 推荐Lint工具配置
创建 `pyproject.toml` 并添加：
```toml
[tool.black]
line-length = 100
target-version = ['py310']

[tool.isort]
profile = "black"
line_length = 100

[tool.mypy]
python_version = "3.10"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
disallow_incomplete_defs = true

[tool.ruff]
line-length = 100
target-version = "py310"
```

### Lint命令（推荐配置后使用）
```bash
# 代码格式化
black src/
isort src/

# 代码检查
ruff check src/
mypy src/

# 安全检查
bandit -r src/

# 修复自动可修复的问题
ruff check src/ --fix
```

## 代码风格指南

### 1. 导入规范

#### 标准库导入顺序
```python
# 1. 标准库
import os
import sys
import asyncio
import json
from pathlib import Path
from typing import Optional, List, Dict

# 2. 第三方库
import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# 3. 本地模块
from src.config.loader import settings
from src.services.chat_agent import CustomsChatAgent
```

#### 导入分组
- 使用空行分隔不同的导入组
- 每组按字母顺序排序
- 避免循环导入

#### 导入别名
```python
# 推荐
from typing import Optional as Opt

# 不推荐
from typing import Optional as O
```

### 2. 格式化规范

#### 行长度
- **最大行长**: 100字符
- **换行规则**: 在操作符后换行，缩进4个空格

#### 示例
```python
# 正确
def process_data(
    data: Dict[str, Any],
    config: Optional[Config] = None
) -> List[Result]:
    return [
        process_item(item, config)
        for item in data.values()
        if is_valid_item(item)
    ]

# 错误（行太长）
def process_data(data: Dict[str, Any], config: Optional[Config] = None) -> List[Result]:
    return [process_item(item, config) for item in data.values() if is_valid_item(item)]
```

#### 字符串格式化
```python
# 推荐：f-string（Python 3.6+）
name = "World"
message = f"Hello, {name}!"

# 复杂格式化
result = f"处理了 {len(items):,} 个项目，总耗时 {elapsed:.2f} 秒"

# 多行字符串
query = """
SELECT id, name, status
FROM customs_declarations
WHERE created_at >= ?
ORDER BY created_at DESC
""".strip()
```

### 3. 类型注解

#### 强制要求
- 所有函数参数必须有类型注解
- 所有函数返回值必须有类型注解
- 类属性应有类型注解

#### 示例
```python
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

class AnalysisRequest(BaseModel):
    raw_data: str
    language: str = "zh"
    timeout: Optional[float] = None

def analyze_customs_declaration(
    raw_data: str,
    language: str = "zh",
    timeout: Optional[float] = None
) -> Dict[str, Any]:
    """分析海关申报数据"""
    pass

async def process_batch(
    items: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """批量处理项目"""
    pass
```

#### 泛型类型
```python
from typing import TypeVar, Generic

T = TypeVar('T')

class Result(Generic[T]):
    def __init__(self, data: T, success: bool):
        self.data: T = data
        self.success: bool = success
```

### 4. 命名约定

#### 类命名
- 使用PascalCase（大驼峰）
- 描述性强，避免缩写

```python
# 正确
class CustomsChatAgent:
class RiskAnalysisOrchestrator:
class ComplianceReporter:

# 错误
class customsChatAgent:
class RiskAnalyzer:  # 缩写不清晰
```

#### 函数和变量命名
- 使用snake_case（小写下划线）
- 函数名应是动词或动词短语
- 变量名应描述性

```python
# 正确
def analyze_customs_declaration(raw_data: str) -> Dict:
    processed_items = []
    total_count = len(raw_data.split())

# 错误
def analyze(raw_data: str) -> Dict:  # 太泛化
def AnalyzeCustomsDeclaration(raw_data: str) -> Dict:  # PascalCase
```

#### 常量命名
- 使用UPPER_SNAKE_CASE
- 在模块级别定义

```python
# 正确
MAX_RETRY_COUNT = 3
DEFAULT_TIMEOUT = 30.0
API_BASE_URL = "https://api.deepseek.com"

# 错误
maxRetryCount = 3
default_timeout = 30.0
```

#### 私有成员
- 使用单下划线前缀表示模块私有
- 使用双下划线前缀表示类私有（name mangling）

```python
class Agent:
    def __init__(self):
        self._config = {}  # 模块私有
        self.__secret = None  # 类私有
```

### 5. 错误处理

#### 异常处理原则
- 具体异常优先于通用异常
- 总是记录异常信息
- 不要吞没异常

```python
# 正确
try:
    result = await process_data(data)
except httpx.TimeoutException:
    logger.error(f"请求超时: {data}")
    raise HTTPException(status_code=504, detail="服务超时")
except httpx.HTTPStatusError as e:
    logger.error(f"HTTP错误 {e.response.status_code}: {e.response.text}")
    raise HTTPException(status_code=502, detail="外部服务错误")
except Exception as e:
    logger.error(f"未知错误: {e}", exc_info=True)
    raise HTTPException(status_code=500, detail="内部服务器错误")

# 错误
try:
    result = await process_data(data)
except:  # 不要裸except
    pass  # 不要吞没异常
```

#### 自定义异常
```python
class CustomsAgentError(Exception):
    """海关代理基础异常"""
    pass

class ValidationError(CustomsAgentError):
    """数据验证错误"""
    pass

class ExternalServiceError(CustomsAgentError):
    """外部服务错误"""
    pass
```

### 6. 异步编程

#### Async/Await使用
- 所有I/O操作使用async
- 正确使用await
- 避免在async函数中阻塞操作

```python
# 正确
async def analyze_data(self, data: str) -> Dict[str, Any]:
    """异步分析数据"""
    # 并发执行多个任务
    tasks = [
        self._validate_data(data),
        self._check_risks(data),
        self._generate_report(data)
    ]
    results = await asyncio.gather(*tasks)
    return self._combine_results(results)

# 错误：阻塞操作在async函数中
async def bad_example(self, data: str):
    time.sleep(1)  # 阻塞！
    return data.upper()
```

#### 异步上下文管理器
```python
async def process_with_client(self, data: str):
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post("/api/analyze", json={"data": data})
        return response.json()
```

### 7. 文档和注释

#### 文档字符串
- 使用三引号
- 包含参数和返回值描述
- 遵循Google风格

```python
def analyze_customs_declaration(
    raw_data: str,
    language: str = "zh"
) -> Dict[str, Any]:
    """
    分析海关申报数据并识别潜在风险。

    Args:
        raw_data: 原始申报数据文本
        language: 分析语言，默认为中文

    Returns:
        包含分析结果的字典，包含风险等级、建议等信息

    Raises:
        ValueError: 当输入数据无效时
        HTTPException: 当外部服务调用失败时

    Example:
        >>> result = analyze_customs_declaration("货物：电子产品")
        >>> print(result['risk_level'])
        LOW
    """
    pass
```

#### 注释规范
- 注释应解释为什么，而不是做什么
- 使用中文注释描述业务逻辑
- 英文注释用于技术细节

```python
# 正确
# 使用代理避免国内网络限制
async_transport = httpx.AsyncHTTPTransport(proxy=proxy_url)

# 错误
# 创建传输对象
transport = httpx.AsyncHTTPTransport()
```

### 8. 安全和性能注意事项

#### API密钥管理
- 永远不要硬编码API密钥
- 使用环境变量或密钥管理服务
- 验证输入数据

```python
# 正确
api_key = os.getenv("DEEPSEEK_API_KEY")
if not api_key:
    raise ValueError("DEEPSEEK_API_KEY environment variable not set")

# 错误
api_key = "sk-xxxxxxxxxxxx"  # 硬编码！
```

#### 日志记录
- 使用适当的日志级别
- 记录关键操作和错误
- 避免记录敏感信息

```python
import logging

logger = logging.getLogger(__name__)

def process_sensitive_data(self, data: Dict):
    logger.info(f"开始处理申报数据，项目数量: {len(data)}")
    try:
        result = await self._analyze(data)
        logger.info("数据分析完成")
        return result
    except Exception as e:
        logger.error(f"数据分析失败: {e}", exc_info=True)
        raise
```

#### 性能优化
- 使用连接池复用
- 缓存频繁访问的数据
- 避免不必要的对象创建

```python
class CustomsChatAgent:
    def __init__(self):
        # 连接池复用
        self._client = httpx.AsyncClient(
            timeout=120.0,
            limits=httpx.Limits(max_keepalive_connections=10)
        )

    async def chat(self, message: str) -> str:
        # 使用缓存的客户端
        response = await self._client.post("/chat", json={"message": message})
        return response.json()["response"]
```

---

## 工具和编辑器配置

### VS Code推荐扩展
```
- Python (Microsoft)
- Pylance
- Black Formatter
- isort
- Ruff
- Python Docstring Generator
```

### Cursor规则（如果存在）
当前项目未配置Cursor特定规则。如有需要，在 `.cursorrules` 中添加：
```
- 强制使用类型注解
- 运行测试前检查代码
- 使用中文注释业务逻辑
```

### Git提交规范
```bash
# 提交消息格式
<type>(<scope>): <subject>

# 类型
feat: 新功能
fix: 修复bug
docs: 文档更新
style: 代码格式调整
refactor: 代码重构
test: 测试相关
chore: 构建过程或工具配置
```

---

## 常见模式和最佳实践

### 服务层架构
```
src/
├── api/          # API路由层
├── services/     # 业务逻辑层
├── core/         # 核心编排逻辑
├── database/     # 数据访问层
└── config/       # 配置管理
```

### 依赖注入
```python
from fastapi import Depends

async def analyze_endpoint(
    request: AnalysisRequest,
    agent: CustomsChatAgent = Depends(get_agent_instance)
):
    return await agent.analyze(request.raw_data)
```

### 配置管理
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    deepseek_api_key: str
    http_proxy: Optional[str] = None

    class Config:
        env_file = ".env"
        case_sensitive = False

settings = Settings()
```

遵循这些指南将确保代码的一致性、可维护性和高质量。所有代理在进行代码修改时必须严格遵守这些规范。