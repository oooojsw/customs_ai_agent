# OpenCode 配置与集成补全

> 版本: 2.2
> 日期: 2026-03-20
> 来源: 深度研究 OpenCode Config.Info + 海关 chat_agent.py + routes.py + main.py

---

## 16. OpenCode 自身 LLM 配置（关键缺失）

### 16.1 问题说明

OpenCode 服务器启动后，它自己也需要 LLM 配置才能工作。这不是海关智能体的 LLM，而是 **OpenCode 内部工具执行时使用的 LLM**（例如 bash 工具需要 LLM 决定执行什么命令）。

### 16.2 Config.Info 完整 Schema

```typescript
// OpenCode Config.Info 类型（来自 config.ts）
Config.Info = {
  $schema?: string,
  model?: string,                    // 格式: "provider/model"，如 "anthropic/claude-sonnet-4-20250514"
  small_model?: string,              // 小模型，用于标题生成等
  provider?: Record<string, Provider>, // 提供商配置
  server?: {                         // 服务器配置
    port?: number,
    hostname?: string,
    mdns?: boolean,
    cors?: string[]
  },
  permission?: Permission,           // 权限配置
  mcp?: Record<string, Mcp>,        // MCP 服务器配置
  agent?: Record<string, Agent>,    // Agent 配置
  // ... 其他字段
}
```

### 16.3 Provider 配置

```typescript
Config.Provider = {
  apiKey?: string,       // API Key
  baseURL?: string,      // API 基础 URL
  enterpriseUrl?: string,// GitHub Enterprise URL（仅 Copilot）
  timeout?: number | false, // 请求超时（毫秒）
  models?: Record<string, Model> // 模型覆盖配置
}
```

### 16.4 支持的提供商（BUNDLED_PROVIDERS）

来自 `provider.ts`，OpenCode 内置支持以下提供商 SDK：

| 提供商            | SDK 包名                      |
| ----------------- | ----------------------------- |
| Anthropic         | `@ai-sdk/anthropic`           |
| OpenAI            | `@ai-sdk/openai`              |
| OpenAI Compatible | `@ai-sdk/openai-compatible`   |
| Google            | `@ai-sdk/google`              |
| Google Vertex     | `@ai-sdk/google-vertex`       |
| Azure             | `@ai-sdk/azure`               |
| Mistral           | `@ai-sdk/mistral`             |
| Groq              | `@ai-sdk/groq`                |
| XAI               | `@ai-sdk/xai`                 |
| Cohere            | `@ai-sdk/cohere`              |
| Cerebras          | `@ai-sdk/cerebras`            |
| DeepInfra         | `@ai-sdk/deepinfra`           |
| Together AI       | `@ai-sdk/togetherai`          |
| Perplexity        | `@ai-sdk/perplexity`          |
| OpenRouter        | `@openrouter/ai-sdk-provider` |
| Amazon Bedrock    | `@ai-sdk/amazon-bedrock`      |
| Vercel AI Gateway | `@ai-sdk/vercel`              |
| GitHub Copilot    | `@ai-sdk/github-copilot`      |

### 16.5 配置文件加载优先级

```
1. Remote well-known config (最低优先级)
2. Global user config (~/.config/opencode/opencode.json)
3. OPENCODE_CONFIG 环境变量指定的文件
4. 项目级 opencode.jsonc / opencode.json（向上查找）
5. OPENCODE_CONFIG_CONTENT 环境变量（最高优先级）
```

### 16.6 推荐配置：使用 DeepSeek（与海关智能体一致）

```json
// opencode.json（放在 OpenCode 源码目录或海关项目目录）
{
  "model": "deepseek/deepseek-chat",
  "provider": {
    "deepseek": {
      "options": {
        "apiKey": "your_deepseek_api_key",
        "baseURL": "https://api.deepseek.com"
      }
    }
  },
  "server": {
    "port": 4096,
    "hostname": "127.0.0.1"
  },
  "permission": {
    "bash": "ask",
    "write": "ask",
    "edit": "ask"
  }
}
```

### 16.7 配置传递方式

方式一：通过 `OPENCODE_CONFIG_CONTENT` 环境变量传递（推荐）

```python
import json

config = {
    "model": "deepseek/deepseek-chat",
    "provider": {
        "deepseek": {
            "options": {
                "apiKey": settings.DEEPSEEK_API_KEY,
                "baseURL": settings.DEEPSEEK_BASE_URL
            }
        }
    }
}

env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
```

方式二：在 OpenCode 源码目录创建 `opencode.json` 文件

---

## 17. chat_agent.py 完整集成代码

### 17.1 修改 CustomsChatAgent.**init**

在 `src/services/chat_agent.py` 的 `__init__` 方法中添加 `opencode_client` 参数：

```python
class CustomsChatAgent:
    def __init__(self, kb=None, llm_config: dict = None, opencode_client=None):
        # ... 现有初始化代码 ...

        # ✅ 新增：OpenCode 客户端
        self.opencode_client = opencode_client
        self.opencode_tools = []

        # ... 现有工具注册 ...

        # ✅ 新增：注册 OpenCode 工具（在 MCP 工具之前）
        if self.opencode_client:
            self._register_opencode_tools()
```

### 17.2 新增 \_register_opencode_tools 方法

```python
def _register_opencode_tools(self):
    """注册 OpenCode 工具到工具列表"""

    async def opencode_create_session(input_str: str) -> str:
        """创建 OpenCode 会话"""
        try:
            parts = input_str.split("|", 1)
            workspace_dir = parts[0].strip()
            title = parts[1].strip() if len(parts) > 1 else None
            result = await self.opencode_client.create_session(
                workspace_dir=workspace_dir, title=title
            )
            return json.dumps({
                "success": True,
                "session_id": result["id"],
                "title": result.get("title", ""),
                "directory": result.get("directory", "")
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

    async def opencode_read_file(path: str) -> str:
        """读取文件内容"""
        try:
            result = await self.opencode_client.read_file(path.strip())
            return result.get("content", "") if isinstance(result, dict) else str(result)
        except Exception as e:
            return f"读取文件失败: {str(e)}"

    async def opencode_search_files(query: str) -> str:
        """搜索文件名"""
        try:
            results = await self.opencode_client.search_files(query.strip())
            return "\n".join(results) if results else "未找到匹配的文件"
        except Exception as e:
            return f"搜索失败: {str(e)}"

    async def opencode_search_text(pattern: str) -> str:
        """搜索文本内容"""
        try:
            results = await self.opencode_client.search_text(pattern.strip())
            if not results:
                return "未找到匹配"
            output = []
            for match in results[:10]:
                data = match.get("data", {})
                fp = data.get("path", {}).get("text", "")
                line = data.get("lines", {}).get("text", "")
                ln = data.get("line_number", "")
                output.append(f"{fp}:{ln}: {line.strip()}")
            return "\n".join(output)
        except Exception as e:
            return f"搜索失败: {str(e)}"

    async def opencode_list_files(path: str) -> str:
        """列出目录内容"""
        try:
            results = await self.opencode_client.list_files(path.strip())
            if not results:
                return "目录为空"
            output = []
            for item in results:
                t = item.get("type", "file")
                n = item.get("name", "")
                output.append(f"{'📁' if t == 'directory' else '📄'} {n}{'/' if t == 'directory' else ''}")
            return "\n".join(output)
        except Exception as e:
            return f"列出目录失败: {str(e)}"

    async def opencode_send_message(input_str: str) -> str:
        """发送消息到 OpenCode 会话"""
        try:
            parts = input_str.split("|", 1)
            if len(parts) != 2:
                return "格式: session_id|message"
            session_id = parts[0].strip()
            message = parts[1].strip()
            result = await self.opencode_client.send_message(
                session_id=session_id,
                parts=[{"type": "text", "text": message}]
            )
            # 提取助手回复
            parts_list = result.get("parts", [])
            text = ""
            for p in parts_list:
                if p.get("type") == "text":
                    text += p.get("text", "")
            return text or "消息已发送"
        except Exception as e:
            return f"发送失败: {str(e)}"

    async def opencode_run_command(input_str: str) -> str:
        """通过 OpenCode 执行命令"""
        try:
            parts = input_str.split("|", 1)
            if len(parts) != 2:
                return "格式: session_id|command"
            session_id = parts[0].strip()
            command = parts[1].strip()

            # 通过 shell 接口执行
            response = await self.opencode_client._client.post(
                f"/session/{session_id}/shell",
                json={"agent": "general", "command": command}
            )
            response.raise_for_status()
            data = response.json()
            parts_list = data.get("parts", [])
            output = ""
            for p in parts_list:
                if p.get("type") == "tool":
                    state = p.get("state", {})
                    if state.get("status") == "completed":
                        output += state.get("output", "")
            return output or "命令执行完成"
        except Exception as e:
            return f"执行失败: {str(e)}"

    # 注册工具
    opencode_tool_defs = [
        ("opencode_create_session", "创建 OpenCode 会话。格式: workspace_dir|title", opencode_create_session),
        ("opencode_read_file", "读取文件内容。参数: 文件路径", opencode_read_file),
        ("opencode_search_files", "按文件名搜索。参数: 搜索关键词", opencode_search_files),
        ("opencode_search_text", "在文件中搜索文本。参数: 正则表达式", opencode_search_text),
        ("opencode_list_files", "列出目录内容。参数: 目录路径", opencode_list_files),
        ("opencode_send_message", "发送消息到 OpenCode 会话。格式: session_id|message", opencode_send_message),
        ("opencode_run_command", "执行 shell 命令。格式: session_id|command", opencode_run_command),
    ]

    for name, desc, func in opencode_tool_defs:
        tool = Tool(
            name=name,
            func=lambda x: "此工具仅支持异步环境运行",
            coroutine=func,
            description=desc
        )
        self.tools.append(tool)
        self.opencode_tools.append(tool)

    print(f"[ChatAgent] ✅ OpenCode 工具已注册: {len(opencode_tool_defs)} 个")
```

### 17.3 修改 initialize_mcp_tools

```python
async def initialize_mcp_tools(self, opencode_client=None) -> None:
    """异步初始化 MCP 工具并构建图智能体"""

    # ✅ 新增：接收 opencode_client
    if opencode_client:
        self.opencode_client = opencode_client
        self._register_opencode_tools()

    # ... 现有 MCP 初始化代码 ...

    # 合并工具
    if self.mcp_tools:
        self.tools.extend(self.mcp_tools)

    # 创建 agent
    self._create_agent()
    self._build_system_prompt()
```

### 17.4 修改 \_build_system_prompt

在系统提示词中添加 OpenCode 工具说明：

```python
def _build_system_prompt(self) -> None:
    # ... 现有代码 ...

    # ✅ 新增：OpenCode 工具提示
    opencode_tool_names = [t.name for t in self.opencode_tools] if self.opencode_tools else []
    opencode_section = ""
    if opencode_tool_names:
        opencode_section = f"""
【OpenCode 文件操作中心】
已加载 {len(opencode_tool_names)} 个 OpenCode 工具:
{', '.join(opencode_tool_names)}

使用流程:
1. 先调用 opencode_create_session 创建会话（格式: "data|会话标题"）
2. 使用其他工具进行文件操作
3. 操作完成后可调用 opencode_delete_session 清理

典型场景:
- 需要读取、搜索、分析文件内容时
- 需要执行 shell 命令时
- 需要进行复杂的文件操作时
"""

    # 拼接到完整 prompt
    self.system_prompt_text = f"""
...原有内容...
{opencode_section}
"""
```

---

## 18. main.py 集成代码

### 18.1 在 lifespan 中启动 OpenCode

在 `src/main.py` 的 `lifespan` 函数中，在初始化 agent 之前添加：

```python
# ==================== OpenCode 服务器启动 ====================
opencode_process = None
opencode_client = None

# 加载 OpenCode 配置
try:
    import json
    from pathlib import Path

    opencode_config_path = project_root / "data" / "opencode_config.json"
    if opencode_config_path.exists():
        with open(opencode_config_path, "r", encoding="utf-8") as f:
            opencode_config = json.load(f)
    else:
        opencode_config = {"enabled": False}
        print("⚠️ [OpenCode] 配置文件不存在，跳过启动")

    if opencode_config.get("enabled", False):
        opencode_source_dir = opencode_config.get("opencode_source_dir", "")
        if not opencode_source_dir or not Path(opencode_source_dir).exists():
            print(f"❌ [OpenCode] 源码目录不存在: {opencode_source_dir}")
        else:
            # 构建启动命令
            cmd = [
                "bun", "run", "dev", "serve",
                "--port", str(opencode_config.get("port", 4096)),
                "--hostname", opencode_config.get("hostname", "127.0.0.1")
            ]

            # 设置环境变量
            opencode_env = os.environ.copy()
            if opencode_config.get("server_password"):
                opencode_env["OPENCODE_SERVER_PASSWORD"] = opencode_config["server_password"]

            # 传递 LLM 配置给 OpenCode
            opencode_llm_config = {
                "model": opencode_config.get("model", "deepseek/deepseek-chat"),
                "provider": {
                    opencode_config.get("llm_provider", "deepseek"): {
                        "options": {
                            "apiKey": opencode_config.get("llm_api_key", settings.DEEPSEEK_API_KEY),
                            "baseURL": opencode_config.get("llm_base_url", settings.DEEPSEEK_BASE_URL)
                        }
                    }
                }
            }
            opencode_env["OPENCODE_CONFIG_CONTENT"] = json.dumps(opencode_llm_config)

            # 清除代理
            for key in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
                opencode_env.pop(key, None)

            # 启动进程
            import subprocess
            opencode_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=opencode_env,
                cwd=str(Path(opencode_source_dir))
            )

            # 等待启动
            await asyncio.sleep(5)
            print(f"✅ [OpenCode] 服务器已启动 (PID: {opencode_process.pid})")

            # 创建客户端
            from src.services.opencode_client import OpenCodeClient
            base_url = f"http://{opencode_config.get('hostname', '127.0.0.1')}:{opencode_config.get('port', 4096)}"
            opencode_client = OpenCodeClient(
                base_url=base_url,
                username=opencode_config.get("server_username", "opencode"),
                password=opencode_config.get("server_password"),
                timeout=opencode_config.get("timeout", 30)
            )

            # 健康检查
            health = await opencode_client.health_check()
            print(f"✅ [OpenCode] 客户端连接成功: {health}")

except Exception as e:
    print(f"❌ [OpenCode] 启动失败: {e}")
    opencode_process = None
    opencode_client = None

# ==================== 现有 Agent 初始化 ====================
# 修改 agent 初始化，传入 opencode_client
try:
    agent = CustomsChatAgent(
        kb=app.state.kb,
        llm_config=llm_config,
        opencode_client=opencode_client  # ✅ 新增参数
    )
    await agent.initialize_mcp_tools()  # 内部会同时初始化 OpenCode 工具
    app.state.agent = agent
    app.state.opencode_client = opencode_client  # ✅ 保存到 app.state
    app.state.opencode_process = opencode_process  # ✅ 保存进程引用
except Exception as e:
    print(f"❌ [System] 对话引擎初始化失败: {e}")
    app.state.agent = None
```

### 18.2 在 shutdown 中关闭 OpenCode

```python
# 在 yield 之后（优雅停机阶段）
if getattr(app.state, 'opencode_client', None):
    try:
        await app.state.opencode_client.close()
        print("✅ [OpenCode] 客户端已关闭")
    except Exception as e:
        print(f"⚠️ [OpenCode] 客户端关闭失败: {e}")

if getattr(app.state, 'opencode_process', None):
    try:
        app.state.opencode_process.terminate()
        await asyncio.wait_for(
            asyncio.create_task(asyncio.to_thread(app.state.opencode_process.wait)),
            timeout=5
        )
        print("✅ [OpenCode] 服务器已停止")
    except Exception as e:
        print(f"⚠️ [OpenCode] 服务器关闭失败: {e}")
```

---

## 19. routes.py 集成代码

### 19.1 修改 chat 端点

在 `src/api/routes.py` 的 `/chat` 端点中传入 opencode_client：

```python
@router.post("/chat")
async def chat_with_agent(body: ChatRequest, request: Request):
    llm_config = await get_current_llm_config(request)
    kb = getattr(request.app.state, "kb", None)

    # ✅ 获取 opencode_client（如果已初始化）
    opencode_client = getattr(request.app.state, "opencode_client", None)

    from src.services.chat_agent import CustomsChatAgent
    agent = CustomsChatAgent(
        kb=kb,
        llm_config=llm_config,
        opencode_client=opencode_client  # ✅ 传入
    )

    return StreamingResponse(
        agent.chat_stream(body.message, body.session_id, language=body.language),
        media_type="text/event-stream"
    )
```

---

## 20. Bun 运行时检查

### 20.1 启动前检查代码

```python
def check_bun_runtime() -> bool:
    """检查 Bun 运行时是否已安装"""
    import shutil
    bun_path = shutil.which("bun")
    if bun_path:
        print(f"✅ [OpenCode] Bun 运行时已安装: {bun_path}")
        return True
    else:
        print("❌ [OpenCode] Bun 运行时未安装！")
        print("   请访问 https://bun.sh 安装 Bun")
        print("   Windows: powershell -c \"irm bun.sh/install.ps1 | iex\"")
        return False
```

### 20.2 端口检查代码

```python
def check_port_available(port: int) -> bool:
    """检查端口是否可用"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except socket.error:
            return False

def find_available_port(start_port: int = 4096, max_attempts: int = 10) -> int:
    """查找可用端口"""
    for port in range(start_port, start_port + max_attempts):
        if check_port_available(port):
            return port
    raise RuntimeError(f"无法找到可用端口（{start_port}-{start_port + max_attempts}）")
```
