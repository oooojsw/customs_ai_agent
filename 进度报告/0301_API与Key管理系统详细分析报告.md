# 智慧口岸AI代理 - API与Key管理系统详细分析报告

**报告日期**: 2026-03-01
**分析范围**: API配置管理、Key管理系统、LLM/图像配置加载机制

---

## 一、系统架构概览

该项目采用**双层配置架构**：
- **第一层（基础层）**: .env 环境变量配置
- **第二层（用户层）**: 数据库动态配置（优先级高于.env）

核心特点：
1. 支持多LLM厂商切换（DeepSeek、OpenAI、Qwen、Zhipu、Azure、SiliconFlow等）
2. 图像识别独立配置系统
3. 配置热重载，无需重启服务
4. 完整的连接测试机制

---

## 二、环境变量配置系统

### 2.1 核心文件
**文件位置**: `src/config/loader.py`

### 2.2 支持的API Key类型

| 配置项 | 环境变量 | 说明 |
|--------|----------|------|
| Google API Key | `GOOGLE_API_KEY` | Gemini模型使用 |
| Gemini模型 | `GEMINI_MODEL_NAME` | 默认: gemini-2.0-flash-exp |
| DeepSeek Key | `DEEPSEEK_API_KEY` | 主LLM厂商 |
| DeepSeek Base URL | `DEEPSEEK_BASE_URL` | 默认: https://api.deepseek.com |
| DeepSeek Model | `DEEEPSEEK_MODEL` | 默认: deepseek-chat |
| Azure OpenAI Key | `AZURE_OAI_KEY` | Azure集成 |
| Azure Endpoint | `AZURE_OAI_ENDPOINT` | Azure资源端点 |
| Azure Deployment | `AZURE_OAI_DEPLOYMENT` | 部署名称 |
| Azure API Version | `AZURE_OAI_VERSION` | 默认: 2024-02-01 |
| HTTP代理 | `HTTP_PROXY` / `HTTPS_PROXY` | 网络代理配置 |
| 服务端口 | `API_PORT` / `API_HOST` | 默认: 8000/0.0.0.0 |

### 2.3 核心代码实现

```python
# src/config/loader.py (核心部分)
class ConfigLoader:
    """配置加载器：单例模式，负责将环境变量映射为 Python 属性"""
    
    def __init__(self):
        # 1. 强制寻找项目根目录的 .env 文件
        self.BASE_DIR = Path(__file__).resolve().parent.parent.parent
        self.ENV_PATH = self.BASE_DIR / ".env"
        
        if self.ENV_PATH.exists():
            load_dotenv(dotenv_path=self.ENV_PATH, override=True)
        
        # 加载配置
        self.GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
        self.MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash-exp")
        self.DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
        self.DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.DEEPSEEK_MODEL = os.getenv("DEEEPSEEK_MODEL", "deepseek-chat")
        self.AZURE_OAI_KEY = os.getenv("AZURE_OAI_KEY", "")
        self.AZURE_OAI_ENDPOINT = os.getenv("AZURE_OAI_ENDPOINT", "")
        self.AZURE_OAI_DEPLOYMENT = os.getenv("AZURE_OAI_DEPLOYMENT", "")
        self.AZURE_OAI_VERSION = os.getenv("AZURE_OAI_VERSION", "2024-02-01")
        
        # 网络代理
        self.HTTP_PROXY = os.getenv("HTTP_PROXY")
        self.HTTPS_PROXY = os.getenv("HTTPS_PROXY")

# 全局单例
settings = ConfigLoader()
```

---

## 三、LLM配置动态管理系统

### 3.1 核心文件
- **配置加载器**: `src/config/llm_loader.py`
- **数据模型**: `src/database/models.py` (UserLLMConfig表)
- **数据操作**: `src/database/crud.py` (LLMConfigRepository类)

### 3.2 数据库模型

```python
# src/database/models.py - UserLLMConfig表
class UserLLMConfig(Base):
    __tablename__ = "user_llm_config"
    
    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String(50), nullable=False)  # 服务商名称
    is_enabled = Column(Boolean, default=False)  # 是否启用
    api_key = Column(String(255), nullable=False)
    base_url = Column(String(255), nullable=False)
    model_name = Column(String(100), nullable=False)
    api_version = Column(String(50), nullable=True)  # Azure特有
    temperature = Column(Float, default=0.3)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    last_tested_at = Column(DateTime, nullable=True)
    test_status = Column(String(20), default="never")  # never/success/failed
```

### 3.3 配置优先级机制

```
用户数据库配置 (is_enabled=True)  >  .env 环境变量
```

**关键代码** (`src/config/llm_loader.py`):
```python
class LLMConfigLoader:
    """LLM 配置加载器 (单例)"""
    
    async def load_config(self, db_session) -> Dict:
        # 1. 尝试从数据库加载用户配置
        user_config = await repo.get_active_config()
        
        if user_config and user_config.is_enabled:
            return {
                'api_key': user_config.api_key,
                'base_url': user_config.base_url,
                'model': user_config.model_name,
                'temperature': user_config.temperature,
                'source': 'user'  # 标记来源
            }
        
        # 2. 回退到 .env 配置
        return {
            'api_key': settings.DEEPSEEK_API_KEY,
            'base_url': settings.DEEPSEEK_BASE_URL,
            'model': settings.DEEPSEEK_MODEL,
            'temperature': 0.3,
            'source': 'env'
        }
```

### 3.4 支持的LLM厂商

| 厂商 | provider值 | 默认Base URL | 认证方式 |
|------|------------|--------------|----------|
| DeepSeek | deepseek | https://api.deepseek.com/v1 | Bearer Token |
| OpenAI | openai | https://api.openai.com/v1 | Bearer Token |
| 阿里Qwen | qwen | https://dashscope.aliyuncs.com/compatible-mode/v1 | Bearer Token |
| 智谱GLM | zhipu | https://open.bigmodel.cn/api/paas/v4 | Bearer Token |
| 硅基流动 | siliconflow | https://api.siliconflow.cn/v1 | Bearer Token |
| Azure OpenAI | azure | 自定义endpoint | api-key header |
| 自定义 | custom | 用户自定义 | Bearer Token |

---

## 四、图像识别配置系统

### 4.1 核心文件
- **配置加载器**: `src/config/image_loader.py`
- **数据模型**: `src/database/models.py` (ImageModelConfig表)
- **数据操作**: `src/database/image_config_crud.py`

### 4.2 数据库模型

```python
# src/database/models.py - ImageModelConfig表
class ImageModelConfig(Base):
    __tablename__ = "image_model_config"
    
    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String(50), nullable=False)  # azure/gemini/custom
    is_enabled = Column(Boolean, default=False)
    api_key = Column(String(255), nullable=False)
    base_url = Column(String(255), nullable=True)
    model_name = Column(String(100), nullable=False)
    api_version = Column(String(50), nullable=True)
    endpoint = Column(String(255), nullable=True)  # Azure endpoint
    temperature = Column(Float, default=0.1)
    max_tokens = Column(Integer, default=16384)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    last_tested_at = Column(DateTime, nullable=True)
    test_status = Column(String(20), default="never")
    description = Column(String(255), nullable=True)
```

### 4.3 配置加载逻辑

```python
# src/config/image_loader.py
class ImageConfigLoader:
    """图像识别配置加载器（单例）"""
    
    def load_from_env(self) -> Dict[str, Any]:
        provider = os.getenv("IMAGE_PROVIDER", "gemini")
        
        return {
            "provider": provider,
            "api_key": os.getenv("AZURE_OAI_KEY", os.getenv("GOOGLE_API_KEY", "")),
            "endpoint": os.getenv("AZURE_OAI_ENDPOINT", ""),
            "base_url": os.getenv("AZURE_OAI_ENDPOINT", ""),
            "model_name": default_model,
            "api_version": os.getenv("AZURE_API_VERSION", "2024-02-01"),
            "temperature": float(os.getenv("IMAGE_TEMPERATURE", "0.1")),
            "max_tokens": int(os.getenv("IMAGE_MAX_TOKENS", "16384")),
            "is_enabled": False  # .env 配置默认不启用
        }
    
    def load_from_database(self, db_config: Dict) -> Dict:
        """从数据库加载配置"""
        return {
            "provider": db_config.get("provider", "azure"),
            "api_key": db_config.get("api_key", ""),
            "model_name": db_config.get("model_name", "gpt-4-vision"),
            "is_enabled": db_config.get("is_enabled", False),
            "source": "database"
        }
```

---

## 五、API接口层

### 5.1 核心文件
**文件位置**: `src/api/routes.py`

### 5.2 LLM配置管理接口

#### 5.2.1 获取当前LLM配置
```
GET /api/v1/config/llm
```
返回: 当前启用的provider、model、base_url、temperature等

#### 5.2.2 保存LLM配置
```
POST /api/v1/config/llm
```
请求体:
```json
{
    "provider": "deepseek",
    "api_key": "sk-xxx",
    "base_url": "https://api.deepseek.com/v1",
    "model_name": "deepseek-chat",
    "temperature": 0.3,
    "is_enabled": true
}
```

#### 5.2.3 测试LLM连接
```
POST /api/v1/config/llm/test
```
使用实际API调用测试连接，返回success/error状态

#### 5.2.4 热重载配置
```
POST /api/v1/config/llm/reload
```
重新加载数据库配置，更新app.state中的llm_config

#### 5.2.5 获取所有配置
```
GET /api/v1/config/llm/all
```
返回所有已保存的厂商配置（隐藏API Key）

#### 5.2.6 切换激活厂商
```
POST /api/v1/config/llm/activate/{provider}
```
激活指定厂商配置，自动禁用其他厂商

#### 5.2.7 获取模型列表
```
GET /api/v1/config/llm/models?provider=xxx&api_key=xxx&base_url=xxx
```
动态获取指定厂商的可用模型列表

### 5.3 图像配置管理接口

| 接口 | 方法 | 功能 |
|------|------|------|
| `/api/v1/config/image` | GET | 获取当前图像配置 |
| `/api/v1/config/image` | POST | 保存图像配置 |
| `/api/v1/config/image/test` | POST | 测试图像API连接 |
| `/api/v1/config/image/reset` | POST | 重置为.env配置 |
| `/api/v1/config/image/reload` | POST | 热重载图像配置 |
| `/api/v1/config/image/models` | GET | 获取图像模型列表 |

---

## 六、核心配置流程

### 6.1 服务启动流程

```
main.py:lifespan
    │
    ├─→ init_database() 初始化数据库
    │
    ├─→ LLMConfigLoader.load_config()
    │       │
    │       ├─→ 查询DB中 is_enabled=True 的配置
    │       │
    │       └─→ 如无，回退到 .env 配置
    │
    ├─→ ImageConfigRepository.get_active_config()
    │       │
    │       ├─→ 查询DB中启用的图像配置
    │       │
    │       └─→ 如无，使用 .env 配置
    │
    └─→ 初始化各Agent（传入配置）
```

### 6.2 动态配置获取流程

```
API请求 (/analyze, /chat, /generate_report)
    │
    └─→ get_current_llm_config(req)
            │
            ├─→ 每次都查询DB的 is_enabled 状态
            │
            └─→ 返回最新配置给Agent
```

### 6.3 配置更新流程

```
前端保存配置 → POST /config/llm
    │
    └─→ LLMConfigRepository.save_config()
            │
            ├─→ 如果 is_enabled=True，禁用其他所有配置
            │
            ├─→ 智能更新API Key（空值不覆盖）
            │
            └─→ 更新 updated_at 时间戳

→ 前端调用 reload → POST /config/llm/reload
    │
    └─→ 重新加载配置到 app.state
            │
            └─→ 更新所有Agent实例
```

---

## 七、安全机制

### 7.1 API Key保护

1. **调试日志脱敏**:
```python
# 只显示前4位
masked_key = self.GOOGLE_API_KEY[:4] + "****"
```

2. **API返回脱敏**:
```python
# 列表接口隐藏完整Key
"api_key_preview": config.api_key[:8] + "..."
```

3. **智能更新防覆盖**:
```python
# 只有填新Key时才更新
if new_api_key:
    existing.api_key = new_api_key
# 空值保留原Key
```

### 7.2 配置状态互斥

```python
# 保存时确保唯一激活
if is_enable_action:
    await self.disable_all_configs()  # 先禁用所有
    # 再启用当前
```

---

## 八、总结

该项目的API和Key管理系统具有以下特点：

1. **双层配置架构**: 数据库用户配置优先级高于.env环境变量
2. **多厂商支持**: 兼容7+家主流LLM服务商
3. **热重载能力**: 修改配置无需重启服务
4. **完整测试机制**: 每个配置都经过真实API调用测试
5. **安全保护**: API Key脱敏显示，智能防覆盖
6. **独立图像系统**: 图像识别配置与LLM配置分离

整个系统设计合理，扩展性强，安全性良好。
