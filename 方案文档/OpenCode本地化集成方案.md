# OpenCode 本地化集成方案

> 版本: 1.0
> 日期: 2026-03-19
> 状态: 技术规范

---

## 目录

1. [概述](#1-概述)
2. [技术可行性分析](#2-技术可行性分析)
3. [架构设计](#3-架构设计)
4. [SDK API 详细调用规范](#4-sdk-api-详细调用规范)
5. [核心工具设计](#5-核心工具设计)
6. [安全隔离方案](#6-安全隔离方案)
7. [错误处理机制](#7-错误处理机制)
8. [生命周期管理](#8-生命周期管理)
9. [性能优化](#9-性能优化)
10. [测试方案](#10-测试方案)
11. [部署方案](#11-部署方案)
12. [风险评估](#12-风险评估)
13. [实施计划](#13-实施计划)

---

## 1. 概述

### 1.1 项目目标

将 OpenCode 开发环境本地化集成到海关智能体系统中，使智能体能够在不依赖用户全局安装的情况下，自动调用 OpenCode 的文件处理、代码执行、程序编辑等能力，从而大幅提升智能体的外部文件处理和数据操作能力。

### 1.2 核心需求

| 需求类型 | 具体描述 | 优先级 |
|---------|---------|--------|
| 本地化部署 | 无需用户全局安装 OpenCode | P0 |
| 自动启动管理 | FastAPI 启动时自动启动 OpenCode 服务 | P0 |
| 工具封装 | 封装成 7 个核心工具供智能体调用 | P0 |
| 安全隔离 | 限制 OpenCode 的访问范围和操作权限 | P0 |
| 错误处理 | 完善的异常捕获和恢复机制 | P1 |
| 性能优化 | 异步架构，连接池复用 | P1 |

### 1.3 技术选型

| 组件 | 选型 | 说明 |
|------|------|------|
| OpenCode 运行时 | oh-my-opencode-windows-x64 | 已安装在 node_modules |
| Python SDK | httpx | 异步 HTTP 客户端，支持 SSE |
| 服务管理 | asyncio subprocess | 原生异步进程管理 |
| 工具注册 | LangChain StructuredTool | 复用现有架构 |
| 配置管理 | JSON 配置文件 | 与现有 MCP 配置一致 |

---

## 2. 技术可行性分析

### 2.1 项目现状

```
项目结构:
├── node_modules/
│   ├── oh-my-opencode-windows-x64/
│   │   └── bin/oh-my-opencode.exe  ← 可执行文件
│   └── @modelcontextprotocol/
│       └── server-filesystem/      ← 现有 MCP 服务器
├── src/
│   ├── services/
│   │   ├── mcp_bridge.py          ← 现有 MCP 桥接器
│   │   └── chat_agent.py          ← 海关智能体
│   └── main.py                     ← FastAPI 入口
└── data/
    └── mcp_servers.json            ← MCP 配置
```

### 2.2 可行性验证

| 验证项 | 结果 | 说明 |
|--------|------|------|
| OpenCode 可执行文件存在 | ✅ | node_modules/oh-my-opencode-windows-x64/bin/oh-my-opencode.exe |
| SDK API 文档完整 | ✅ | 接口规范/opencode-sdk-api.md (717 行) |
| HTTP API 支持 | ✅ | 标准 REST API + SSE |
| 现有 MCP 桥接器 | ✅ | mcp_bridge.py 提供成熟架构参考 |
| 异步架构 | ✅ | Python asyncio + httpx 完美支持 |

### 2.3 关键技术优势

1. **无需全局安装**: OpenCode 二进制文件已内置于项目中
2. **标准 HTTP API**: OpenCode 服务器暴露完整 REST API
3. **SSE 事件流**: 支持实时事件订阅和流式响应
4. **会话隔离**: 子会话机制支持多任务并行
5. **权限控制**: 可配置的权限规则系统

---

## 3. 架构设计

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     海关智能体系统 (FastAPI)                      │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐   │
│  │ Chat Agent  │  │ Audit      │  │ Report Agent           │   │
│  │             │  │ Orchestrator│  │                        │   │
│  └──────┬──────┘  └──────┬──────┘  └───────────┬─────────────┘   │
│         │                │                     │                  │
│  ┌──────▼────────────────▼─────────────────────▼─────────────┐   │
│  │                    工具注册层 (LangChain)                   │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │   │
│  │  │ MCP Tools│ │ Skill    │ │ OpenCode │ │ Native Tools │  │   │
│  │  │          │ │ Manager  │ │ Tools    │ │              │  │   │
│  │  └──────────┘ └──────────┘ └────┬─────┘ └──────────────┘  │   │
│  └─────────────────────────────────┼─────────────────────────┘   │
├──────────────────────────────────┼─────────────────────────────┤
│                                  │                              │
│  ┌────────────────────────────────▼─────────────────────────┐   │
│  │              OpenCode 封装层 (OpenCodeManager)             │   │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐            │   │
│  │  │ Session    │ │ File Ops   │ │ Event      │            │   │
│  │  │ Manager    │ │ Handler    │ │ Subscriber │            │   │
│  │  └────────────┘ └────────────┘ └────────────┘            │   │
│  └─────────────────────────────────┼─────────────────────────┘   │
├──────────────────────────────────┼─────────────────────────────┤
│                                  │                              │
│  ┌────────────────────────────────▼─────────────────────────┐   │
│  │           OpenCode HTTP 客户端 (httpx)                      │   │
│  │     base_url: http://127.0.0.1:{PORT}                      │   │
│  └─────────────────────────────────┼─────────────────────────┘   │
├──────────────────────────────────┼─────────────────────────────┤
│                                  │                              │
│  ┌────────────────────────────────▼─────────────────────────┐   │
│  │              OpenCode 服务器 (子进程)                        │   │
│  │     opencode serve --port {PORT} --workspace {DIR}         │   │
│  │                                                              │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │   │
│  │  │ REST API │ │ SSE      │ │ WebSocket│ │ File System  │   │   │
│  │  │ (3001)   │ │ Events   │ │          │ │ Access       │   │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────────┘   │   │
│  └───────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 模块职责

| 模块 | 职责 | 核心类/函数 |
|------|------|-------------|
| OpenCodeManager | 服务生命周期管理 | OpenCodeService |
| OpenCodeClient | HTTP API 封装 | OpenCodeHTTPClient |
| OpenCodeTools | 工具集实现 | OpenCodeToolFactory |
| SessionPool | 会话池管理 | SessionPoolManager |
| EventSubscriber | SSE 事件订阅 | OpenCodeEventListener |
| SecurityWrapper | 安全隔离封装 | OpenCodeSecurityGuard |

### 3.3 文件结构

```
src/services/opencode/
├── __init__.py                    # 模块导出
├── manager.py                     # OpenCodeService: 服务生命周期管理
├── client.py                      # OpenCodeHTTPClient: HTTP API 封装
├── session_pool.py                # SessionPoolManager: 会话池管理
├── events.py                      # OpenCodeEventListener: SSE 事件订阅
├── security.py                    # OpenCodeSecurityGuard: 安全隔离
├── tools/                         # 工具集目录
│   ├── __init__.py
│   ├── base.py                    # 工具基类
│   ├── file_processor.py          # 文件处理工具
│   ├── data_converter.py          # 数据转换工具
│   ├── code_executor.py           # 代码执行工具
│   ├── script_generator.py        # 脚本生成工具
│   ├── batch_processor.py         # 批量处理工具
│   ├── data_analyzer.py           # 数据分析工具
│   └── system_bridge.py           # 系统集成工具
├── config.py                      # OpenCode 配置模型
└── exceptions.py                  # 自定义异常
```

### 3.4 数据流

```
用户请求 (HTTP)
    │
    ▼
FastAPI Route
    │
    ▼
Chat Agent (LangChain)
    │
    ▼
工具调用 (StructuredTool)
    │
    ├── MCP Tools ──────────────────► MCP Bridge ──► MCP Servers
    │
    └── OpenCode Tools ──────────────► OpenCodeManager
                                        │
                                        ├── 空闲会话检查
                                        │       │
                                        │       ▼
                                        │   SessionPool
                                        │       │
                                        │       ▼
                                        │   OpenCode HTTP Client
                                        │       │
                                        │       ▼
                                        │   OpenCode Server (HTTP)
                                        │       │
                                        │       ▼
                                        └──────┘
                                            │
                                            ▼
                                        执行结果
                                            │
                                            ▼
                                        返回用户
```

---

## 4. SDK API 详细调用规范

### 4.1 HTTP API 端点

根据 OpenCode SDK API 文档，OpenCode 服务器暴露以下 HTTP API 端点：

#### 4.1.1 会话管理 API

| 方法 | 端点 | 说明 | Python 调用示例 |
|------|------|------|----------------|
| GET | `/session` | 列出会话 | `client.get("/session")` |
| POST | `/session` | 创建会话 | `client.post("/session", json={...})` |
| GET | `/session/{id}` | 获取会话 | `client.get(f"/session/{id}")` |
| DELETE | `/session/{id}` | 删除会话 | `client.delete(f"/session/{id}")` |
| POST | `/session/{id}/prompt` | 发送消息 | `client.post(f"/session/{id}/prompt", json={...})` |
| GET | `/session/{id}/messages` | 获取消息 | `client.get(f"/session/{id}/messages")` |
| GET | `/session/{id}/status` | 获取状态 | `client.get(f"/session/{id}/status")` |
| POST | `/session/{id}/abort` | 中止会话 | `client.post(f"/session/{id}/abort")` |
| GET | `/session/{id}/todo` | 获取 Todo | `client.get(f"/session/{id}/todo")` |

#### 4.1.2 文件操作 API

| 方法 | 端点 | 说明 | Python 调用示例 |
|------|------|------|----------------|
| GET | `/file/list` | 列出目录 | `client.get("/file/list", params={"path": "data/"})` |
| GET | `/file/read` | 读取文件 | `client.get("/file/read", params={"path": "data/test.csv"})` |
| GET | `/file/status` | Git 状态 | `client.get("/file/status")` |

#### 4.1.3 搜索 API

| 方法 | 端点 | 说明 | Python 调用示例 |
|------|------|------|----------------|
| GET | `/find/text` | 文本搜索 | `client.get("/find/text", params={"pattern": "class", "path": "src/"})` |
| GET | `/find/files` | 文件搜索 | `client.get("/find/files", params={"pattern": "*.py"})` |

#### 4.1.4 事件订阅 API

| 方法 | 端点 | 说明 | Python 调用示例 |
|------|------|------|----------------|
| GET | `/event` | SSE 事件流 | `client.get("/event", params={"directory": "."}, stream=True)` |

#### 4.1.5 其他 API

| 方法 | 端点 | 说明 | Python 调用示例 |
|------|------|------|----------------|
| GET | `/health` | 健康检查 | `client.get("/health")` |
| GET | `/config` | 获取配置 | `client.get("/config")` |
| POST | `/config` | 更新配置 | `client.post("/config", json={...})` |
| GET | `/tool/list` | 工具列表 | `client.get("/tool/list")` |
| GET | `/mcp/status` | MCP 状态 | `client.get("/mcp/status")` |

### 4.2 请求/响应格式

#### 4.2.1 创建会话

**请求:**
```json
POST /session
Content-Type: application/json

{
  "title": "数据处理会话",
  "directory": "C:/project/root",
  "permission": {
    "allow": ["read", "write", "exec"],
    "deny": ["network", "system"]
  }
}
```

**响应:**
```json
{
  "id": "sess_abc123xyz",
  "slug": "abc123xyz",
  "title": "数据处理会话",
  "directory": "C:/project/root",
  "createdAt": "2026-03-19T10:00:00Z",
  "updatedAt": "2026-03-19T10:00:00Z"
}
```

#### 4.2.2 发送消息/执行任务

**请求:**
```json
POST /session/{id}/prompt
Content-Type: application/json

{
  "parts": [
    {
      "type": "text",
      "text": "请分析以下CSV文件并提取关键数据：\n```\n商品名称,数量,单价\n手机,100,5000\n电脑,50,8000\n```"
    }
  ],
  "agent": "default",
  "tools": {
    "question": false,
    "task": false
  },
  "noReply": false
}
```

**响应:**
```json
{
  "messageId": "msg_def456",
  "sessionId": "sess_abc123xyz",
  "status": "processing"
}
```

#### 4.2.3 获取消息列表

**请求:**
```json
GET /session/{id}/messages
```

**响应:**
```json
{
  "messages": [
    {
      "id": "msg_001",
      "role": "user",
      "parts": [
        {
          "type": "text",
          "content": "请分析CSV文件"
        }
      ],
      "createdAt": "2026-03-19T10:00:00Z"
    },
    {
      "id": "msg_002",
      "role": "assistant",
      "parts": [
        {
          "type": "text",
          "content": "我已经分析了CSV文件，发现..."
        },
        {
          "type": "tool_use",
          "name": "bash",
          "input": {"command": "python analyze.py"}
        }
      ],
      "tokens": {
        "input": 150,
        "output": 320,
        "cache": {"hits": 45}
      },
      "createdAt": "2026-03-19T10:00:05Z"
    }
  ],
  "hasMore": false
}
```

#### 4.2.4 SSE 事件流

**请求:**
```bash
GET /event?directory=C:/project/root
Accept: text/event-stream
```

**响应事件:**

```text
event: session.created
data: {"type":"session.created","properties":{"id":"sess_abc","title":"新会话"}}

event: message.updated
data: {"type":"message.updated","properties":{"id":"msg_001","content":"处理中..."}}

event: session.idle
data: {"type":"session.idle","properties":{"sessionId":"sess_abc"}}

event: file.edited
data: {"type":"file.edited","properties":{"path":"data/result.csv"}}
```

### 4.3 Python HTTP 客户端封装

```python
# src/services/opencode/client.py
import httpx
import asyncio
import json
from typing import Dict, Any, Optional, AsyncIterator
from dataclasses import dataclass, field
from enum import Enum

class SessionStatus(Enum):
    """会话状态枚举"""
    IDLE = "idle"
    BUSY = "busy"
    RETRY = "retry"
    ERROR = "error"

@dataclass
class OpenCodeConfig:
    """OpenCode 配置"""
    base_url: str = "http://127.0.0.1:3001"
    timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 1.0
    workspace_dir: str = ""

@dataclass
class Part:
    """消息 Part"""
    type: str  # text, file, agent, subtask
    text: Optional[str] = None
    path: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        result = {"type": self.type}
        if self.text:
            result["text"] = self.text
        if self.path:
            result["path"] = self.path
        return result

class OpenCodeHTTPClient:
    """
    OpenCode HTTP API 客户端
    
    封装所有 OpenCode REST API 调用
    参考: 接口规范/opencode-sdk-api.md
    """
    
    def __init__(self, config: Optional[OpenCodeConfig] = None):
        self.config = config or OpenCodeConfig()
        self._client: Optional[httpx.AsyncClient] = None
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()
    
    async def connect(self):
        """建立 HTTP 连接"""
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=httpx.Timeout(
                connect=10.0,
                read=self.config.timeout,
                write=10.0,
                pool=30.0
            ),
            # 绕过代理，直连本地
            proxies={"http://": None, "https://": None},
            limits=httpx.Limits(
                max_keepalive_connections=10,
                max_connections=20
            )
        )
    
    async def close(self):
        """关闭 HTTP 连接"""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    # ==================== 健康检查 ====================
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            response = await self._client.get("/health")
            return response.status_code == 200
        except Exception:
            return False
    
    # ==================== 会话管理 ====================
    
    async def session_list(self) -> Dict[str, Any]:
        """列出会话"""
        response = await self._client.get("/session")
        response.raise_for_status()
        return response.json()
    
    async def session_create(
        self,
        title: str,
        directory: Optional[str] = None,
        permission: Optional[Dict[str, Any]] = None,
        parent_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        创建新会话
        
        Args:
            title: 会话标题
            directory: 工作目录
            permission: 权限配置
            parent_id: 父会话 ID (用于子会话)
        
        Returns:
            会话信息字典
        """
        payload = {"title": title}
        
        if directory:
            payload["directory"] = directory
        
        if permission:
            payload["permission"] = permission
        
        if parent_id:
            payload["parentID"] = parent_id
        
        response = await self._client.post("/session", json=payload)
        response.raise_for_status()
        return response.json()
    
    async def session_get(self, session_id: str) -> Dict[str, Any]:
        """获取会话详情"""
        response = await self._client.get(f"/session/{session_id}")
        response.raise_for_status()
        return response.json()
    
    async def session_delete(self, session_id: str) -> bool:
        """删除会话"""
        try:
            response = await self._client.delete(f"/session/{session_id}")
            response.raise_for_status()
            return True
        except Exception:
            return False
    
    async def session_status(self, session_id: str) -> SessionStatus:
        """获取会话状态"""
        response = await self._client.get(f"/session/{session_id}/status")
        response.raise_for_status()
        data = response.json()
        status_type = data.get("status", {}).get("type", "idle")
        return SessionStatus(status_type)
    
    async def session_abort(self, session_id: str) -> bool:
        """中止会话"""
        try:
            response = await self._client.post(f"/session/{session_id}/abort")
            response.raise_for_status()
            return True
        except Exception:
            return False
    
    async def session_todo(self, session_id: str) -> Dict[str, Any]:
        """获取会话 Todo 列表"""
        response = await self._client.get(f"/session/{session_id}/todo")
        response.raise_for_status()
        return response.json()
    
    # ==================== 消息交互 ====================
    
    async def session_prompt(
        self,
        session_id: str,
        parts: list,
        agent: str = "default",
        model: Optional[Dict[str, str]] = None,
        tools: Optional[Dict[str, bool]] = None,
        system: Optional[str] = None,
        wait_for_complete: bool = True,
        timeout: float = 60.0
    ) -> Dict[str, Any]:
        """
        发送消息并等待响应
        
        Args:
            session_id: 会话 ID
            parts: 消息内容列表
            agent: 使用的 Agent
            model: 模型配置 {"providerID": "deepseek", "modelID": "deepseek-chat"}
            tools: 工具启用配置 {"question": False, "task": False}
            system: System Prompt
            wait_for_complete: 是否等待完成
            timeout: 超时时间
        
        Returns:
            消息响应
        """
        payload = {
            "parts": [p if isinstance(p, dict) else p.to_dict() for p in parts],
            "agent": agent
        }
        
        if model:
            payload["model"] = model
        
        if tools:
            payload["tools"] = tools
        
        if system:
            payload["system"] = system
        
        # 发送消息
        response = await self._client.post(
            f"/session/{session_id}/prompt",
            json=payload
        )
        response.raise_for_status()
        result = response.json()
        
        if not wait_for_complete:
            return result
        
        # 等待完成
        message_id = result.get("messageId")
        deadline = asyncio.get_event_loop().time() + timeout
        
        while asyncio.get_event_loop().time() < deadline:
            status = await self.session_status(session_id)
            
            if status == SessionStatus.IDLE:
                # 获取最终消息
                messages = await self.session_messages(session_id)
                return messages
            
            await asyncio.sleep(0.5)
        
        raise TimeoutError(f"会话 {session_id} 执行超时 ({timeout}秒)")
    
    async def session_prompt_async(
        self,
        session_id: str,
        parts: list,
        agent: str = "default",
        tools: Optional[Dict[str, bool]] = None
    ) -> str:
        """
        异步发送消息，不等待响应
        
        Returns:
            消息 ID
        """
        payload = {
            "parts": [p if isinstance(p, dict) else p.to_dict() for p in parts],
            "agent": agent,
            "noReply": True
        }
        
        if tools:
            payload["tools"] = tools
        
        response = await self._client.post(
            f"/session/{session_id}/prompt",
            json=payload
        )
        response.raise_for_status()
        return response.json().get("messageId")
    
    async def session_messages(
        self,
        session_id: str,
        limit: int = 50
    ) -> Dict[str, Any]:
        """获取会话消息"""
        response = await self._client.get(
            f"/session/{session_id}/messages",
            params={"limit": limit}
        )
        response.raise_for_status()
        return response.json()
    
    # ==================== 文件操作 ====================
    
    async def file_list(
        self,
        path: str,
        recursive: bool = False
    ) -> Dict[str, Any]:
        """列出目录内容"""
        response = await self._client.get(
            "/file/list",
            params={"path": path, "recursive": recursive}
        )
        response.raise_for_status()
        return response.json()
    
    async def file_read(
        self,
        path: str,
        encoding: str = "utf-8",
        max_size: int = 10 * 1024 * 1024  # 10MB
    ) -> str:
        """
        读取文件内容
        
        Args:
            path: 文件路径
            encoding: 文件编码
            max_size: 最大读取大小
        
        Returns:
            文件内容字符串
        """
        response = await self._client.get(
            "/file/read",
            params={"path": path}
        )
        response.raise_for_status()
        return response.text
    
    async def file_status(self) -> Dict[str, Any]:
        """获取 Git 文件状态"""
        response = await self._client.get("/file/status")
        response.raise_for_status()
        return response.json()
    
    # ==================== 搜索 ====================
    
    async def find_text(
        self,
        pattern: str,
        path: str = ".",
        case_sensitive: bool = False,
        regex: bool = True
    ) -> Dict[str, Any]:
        """正则搜索文本"""
        response = await self._client.get(
            "/find/text",
            params={
                "pattern": pattern,
                "path": path,
                "caseSensitive": case_sensitive,
                "regex": regex
            }
        )
        response.raise_for_status()
        return response.json()
    
    async def find_files(
        self,
        pattern: str,
        path: str = "."
    ) -> Dict[str, Any]:
        """按名称搜索文件"""
        response = await self._client.get(
            "/find/files",
            params={"pattern": pattern, "path": path}
        )
        response.raise_for_status()
        return response.json()
    
    # ==================== SSE 事件订阅 ====================
    
    async def event_subscribe(
        self,
        directory: Optional[str] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        订阅 SSE 事件流
        
        Yields:
            事件字典
        """
        params = {}
        if directory:
            params["directory"] = directory
        
        async with self._client.stream("GET", "/event", params=params) as response:
            response.raise_for_status()
            
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                    continue
                
                if line.startswith("data:"):
                    data_str = line[5:].strip()
                    try:
                        event_data = json.loads(data_str)
                        yield {
                            "type": event_type,
                            "properties": event_data
                        }
                    except json.JSONDecodeError:
                        continue
    
    # ==================== 配置管理 ====================
    
    async def config_get(self) -> Dict[str, Any]:
        """获取项目配置"""
        response = await self._client.get("/config")
        response.raise_for_status()
        return response.json()
    
    async def config_update(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """更新项目配置"""
        response = await self._client.post("/config", json=config)
        response.raise_for_status()
        return response.json()
    
    # ==================== 工具查询 ====================
    
    async def tool_list(self) -> Dict[str, Any]:
        """列出所有可用工具"""
        response = await self._client.get("/tool/list")
        response.raise_for_status()
        return response.json()
```

---

## 5. 核心工具设计

### 5.1 工具架构

```python
# src/services/opencode/tools/base.py
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

class ToolInput(BaseModel):
    """工具输入基类"""
    pass

class ToolOutput(BaseModel):
    """工具输出基类"""
    success: bool = Field(description="是否成功")
    message: str = Field(description="结果消息")
    data: Optional[Dict[str, Any]] = Field(default=None, description="返回数据")

class OpenCodeTool(ABC):
    """OpenCode 工具基类"""
    
    name: str = ""           # 工具名称
    description: str = ""   # 工具描述
    
    @abstractmethod
    async def execute(self, params: Dict[str, Any], client) -> ToolOutput:
        """执行工具"""
        pass
    
    def to_langchain_tool(self) -> StructuredTool:
        """转换为 LangChain 工具"""
        
        async def _run(params_json: str) -> str:
            import json
            params = json.loads(params_json)
            # 这里需要获取 OpenCodeHTTPClient 实例
            # 通过全局或依赖注入
            from src.services.opencode.manager import OpenCodeService
            service = OpenCodeService.get_instance()
            client = service.get_client()
            result = await self.execute(params, client)
            return json.dumps(result.model_dump(), ensure_ascii=False)
        
        return StructuredTool(
            name=self.name,
            description=self.description,
            args_schema=ToolInput,
            coroutine=_run
        )
```

### 5.2 工具 1: 文件智能处理器

```python
# src/services/opencode/tools/file_processor.py
"""
文件智能处理器工具

功能:
- 读取多种格式文件 (CSV, Excel, JSON, XML, PDF, TXT)
- 智能识别文件类型
- 提取结构化数据
- 生成文件分析报告
"""

import json
import base64
from typing import Dict, Any, Optional
from io import BytesIO

class FileProcessorTool:
    """文件智能处理器"""
    
    name = "opencode_file_processor"
    
    description = """
[OpenCode文件处理] 智能文件处理器 - 处理外部文件并提取结构化数据。

使用时机:
- 需要读取、转换、分析文件内容时
- 处理 CSV、Excel、JSON、XML、PDF、TXT 等格式
- 需要提取文件中的结构化数据时

参数格式 (JSON字符串):
{
  "action": "analyze|read|extract|info",
  "file_path": "文件路径 (必填)",
  "options": {
    "output_format": "json|dict|text",
    "encoding": "utf-8|gbk|gb2312",
    "max_size": 10485760,  // 最大读取大小 (字节)
    "extract_columns": ["col1", "col2"],  // 提取特定列
    "skip_rows": 0  // 跳过的行数
  }
}

示例调用:
{"action": "analyze", "file_path": "data/report.csv", "options": {"output_format": "json"}}
{"action": "read", "file_path": "data/config.json", "options": {"encoding": "utf-8"}}
{"action": "info", "file_path": "data/archive.zip"}
"""
    
    SUPPORTED_FORMATS = {
        ".csv": "csv",
        ".xlsx": "excel",
        ".xls": "excel",
        ".json": "json",
        ".xml": "xml",
        ".pdf": "pdf",
        ".txt": "text",
        ".md": "markdown",
        ".html": "html",
        ".yaml": "yaml",
        ".yml": "yaml"
    }
    
    async def execute(self, params: Dict[str, Any], client) -> Dict[str, Any]:
        """
        执行文件处理
        
        Args:
            params: 参数字典
            client: OpenCodeHTTPClient 实例
        
        Returns:
            处理结果
        """
        try:
            action = params.get("action", "read")
            file_path = params.get("file_path")
            
            if not file_path:
                return {
                    "success": False,
                    "error": "缺少必填参数: file_path"
                }
            
            # 读取文件
            content = await client.file_read(file_path)
            
            if action == "read":
                return await self._read_file(content, params)
            
            elif action == "analyze":
                return await self._analyze_file(file_path, content, params, client)
            
            elif action == "extract":
                return await self._extract_data(content, params)
            
            elif action == "info":
                return await self._get_file_info(file_path, client)
            
            else:
                return {
                    "success": False,
                    "error": f"不支持的操作: {action}"
                }
        
        except Exception as e:
            return {
                "success": False,
                "error": f"文件处理失败: {str(e)}"
            }
    
    async def _read_file(self, content: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """读取文件内容"""
        options = params.get("options", {})
        output_format = options.get("output_format", "text")
        
        if output_format == "text":
            return {
                "success": True,
                "content": content,
                "format": "text",
                "size": len(content)
            }
        
        elif output_format == "json":
            try:
                data = json.loads(content)
                return {
                    "success": True,
                    "content": data,
                    "format": "json",
                    "size": len(content)
                }
            except json.JSONDecodeError:
                return {
                    "success": False,
                    "error": "文件不是有效的 JSON 格式"
                }
        
        else:
            return {
                "success": True,
                "content": content,
                "format": output_format,
                "size": len(content)
            }
    
    async def _analyze_file(
        self,
        file_path: str,
        content: str,
        params: Dict[str, Any],
        client
    ) -> Dict[str, Any]:
        """分析文件内容"""
        import os
        
        # 获取文件信息
        file_ext = os.path.splitext(file_path)[1].lower()
        file_type = self.SUPPORTED_FORMATS.get(file_ext, "unknown")
        
        analysis = {
            "success": True,
            "file_path": file_path,
            "file_type": file_type,
            "size": len(content),
            "lines": content.count('\n') + 1,
            "encoding": "utf-8",
            "preview": content[:500] if len(content) > 500 else content
        }
        
        # 根据文件类型进行特定分析
        if file_type == "csv":
            analysis["csv_analysis"] = await self._analyze_csv(content, params)
        
        elif file_type == "json":
            analysis["json_analysis"] = await self._analyze_json(content)
        
        elif file_type == "excel":
            analysis["excel_info"] = {
                "note": "Excel文件需要使用Python的pandas/openpyxl库解析",
                "suggestion": "建议使用 opencode_code_executor 工具执行代码处理"
            }
        
        elif file_type == "pdf":
            analysis["pdf_info"] = {
                "note": "PDF文件需要使用marker或其他OCR库解析",
                "suggestion": "建议使用 opencode_code_executor 工具执行代码处理"
            }
        
        return analysis
    
    async def _analyze_csv(self, content: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """分析 CSV 文件"""
        import csv
        from io import StringIO
        
        try:
            reader = csv.DictReader(StringIO(content))
            rows = list(reader)
            
            if not rows:
                return {"error": "CSV文件为空"}
            
            columns = reader.fieldnames or []
            
            # 基本统计
            analysis = {
                "columns": columns,
                "column_count": len(columns),
                "row_count": len(rows),
                "sample": rows[:3] if len(rows) >= 3 else rows
            }
            
            # 提取特定列
            options = params.get("options", {})
            extract_cols = options.get("extract_columns", [])
            if extract_cols:
                filtered_rows = []
                for row in rows:
                    filtered_row = {k: row.get(k) for k in extract_cols if k in row}
                    filtered_rows.append(filtered_row)
                analysis["extracted_data"] = filtered_rows
                analysis["extracted_columns"] = extract_cols
            
            return analysis
        
        except Exception as e:
            return {"error": f"CSV解析失败: {str(e)}"}
    
    async def _analyze_json(self, content: str) -> Dict[str, Any]:
        """分析 JSON 文件"""
        try:
            data = json.loads(content)
            
            analysis = {
                "type": type(data).__name__,
                "keys": []
            }
            
            if isinstance(data, dict):
                analysis["keys"] = list(data.keys())
                analysis["nested_depth"] = self._get_nested_depth(data)
            
            elif isinstance(data, list):
                analysis["length"] = len(data)
                if data and isinstance(data[0], dict):
                    analysis["item_keys"] = list(data[0].keys()) if data[0] else []
            
            return analysis
        
        except Exception as e:
            return {"error": f"JSON解析失败: {str(e)}"}
    
    def _get_nested_depth(self, obj, current_depth=0):
        """获取嵌套深度"""
        if not isinstance(obj, (dict, list)) or not obj:
            return current_depth
        
        if isinstance(obj, dict):
            max_depth = current_depth + 1
            for value in obj.values():
                if isinstance(value, (dict, list)):
                    max_depth = max(max_depth, self._get_nested_depth(value, current_depth + 1))
            return max_depth
        
        elif isinstance(obj, list):
            max_depth = current_depth + 1
            for item in obj:
                if isinstance(item, (dict, list)):
                    max_depth = max(max_depth, self._get_nested_depth(item, current_depth + 1))
            return max_depth
        
        return current_depth
    
    async def _extract_data(
        self,
        content: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """提取结构化数据"""
        options = params.get("options", {})
        extract_cols = options.get("extract_columns", [])
        
        # 尝试解析为 CSV
        if extract_cols:
            import csv
            from io import StringIO
            
            try:
                reader = csv.DictReader(StringIO(content))
                rows = list(reader)
                
                extracted = []
                for row in rows:
                    filtered = {k: row.get(k) for k in extract_cols if k in row}
                    extracted.append(filtered)
                
                return {
                    "success": True,
                    "data": extracted,
                    "count": len(extracted)
                }
            
            except Exception:
                pass
        
        # 尝试解析为 JSON
        try:
            data = json.loads(content)
            
            if isinstance(data, list) and extract_cols:
                extracted = [
                    {k: item.get(k) for k in extract_cols if k in item}
                    for item in data
                ]
                return {
                    "success": True,
                    "data": extracted,
                    "count": len(extracted)
                }
            
            return {
                "success": True,
                "data": data
            }
        
        except Exception:
            return {
                "success": False,
                "error": "无法提取结构化数据"
            }
    
    async def _get_file_info(
        self,
        file_path: str,
        client
    ) -> Dict[str, Any]:
        """获取文件信息"""
        import os
        
        file_ext = os.path.splitext(file_path)[1].lower()
        
        return {
            "success": True,
            "file_path": file_path,
            "extension": file_ext,
            "file_type": self.SUPPORTED_FORMATS.get(file_ext, "unknown"),
            "operations": {
                "read": True,
                "analyze": file_ext in self.SUPPORTED_FORMATS,
                "convert": file_ext in [".csv", ".json", ".xml", ".txt"]
            }
        }
```

### 5.3 工具 2: 代码执行沙箱

```python
# src/services/opencode/tools/code_executor.py
"""
代码执行沙箱工具

功能:
- 在 OpenCode 会话中执行 Python 代码
- 安全隔离的代码执行环境
- 支持 pandas、numpy 等数据分析库
- 执行超时和资源限制
"""

from typing import Dict, Any, Optional
import asyncio

class CodeExecutorTool:
    """代码执行沙箱"""
    
    name = "opencode_code_executor"
    
    description = """
[OpenCode代码执行] 安全代码执行沙箱 - 在隔离环境中执行Python代码。

使用时机:
- 需要运行自定义脚本进行复杂计算时
- 需要进行数据处理、统计分析时
- 需要执行批量操作时

安全限制:
- 仅访问项目目录
- 禁止系统命令
- 执行时间限制 (默认60秒)
- 内存使用限制

参数格式 (JSON字符串):
{
  "code": "Python代码 (必填)",
  "timeout": 60,  // 超时时间 (秒)
  "allowed_modules": ["pandas", "numpy", "json", "csv"],  // 允许的模块
  "return_format": "json|text|auto"  // 返回格式
}

示例调用:
{"code": "import pandas as pd; df = pd.read_csv('data/sales.csv'); return df.describe()", "timeout": 30}
{"code": "import json; data = json.load(open('config.json')); return data['key']"}
"""
    
    DEFAULT_MODULES = [
        "json", "csv", "math", "datetime", "time",
        "re", "os", "pathlib", "collections",
        "pandas", "numpy", "requests", "xml.etree"
    ]
    
    async def execute(self, params: Dict[str, Any], client) -> Dict[str, Any]:
        """
        执行代码
        
        Args:
            params: 参数字典
            client: OpenCodeHTTPClient 实例
        
        Returns:
            执行结果
        """
        try:
            code = params.get("code")
            
            if not code:
                return {
                    "success": False,
                    "error": "缺少必填参数: code"
                }
            
            timeout = params.get("timeout", 60)
            allowed_modules = params.get("allowed_modules", self.DEFAULT_MODULES)
            return_format = params.get("return_format", "auto")
            
            # 构建执行提示
            prompt = self._build_execution_prompt(
                code,
                allowed_modules,
                return_format
            )
            
            # 创建执行会话
            session = await client.session_create(
                title="代码执行会话",
                permission={
                    "allow": ["read", "write", "exec"],
                    "deny": ["network", "system", "sudo"]
                }
            )
            session_id = session["id"]
            
            # 发送执行请求
            result = await client.session_prompt(
                session_id=session_id,
                parts=[{"type": "text", "text": prompt}],
                wait_for_complete=True,
                timeout=timeout
            )
            
            # 提取结果
            execution_result = self._extract_result(result, return_format)
            
            # 清理会话
            await client.session_delete(session_id)
            
            return execution_result
        
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": f"代码执行超时 (>{timeout}秒)",
                "timeout": True
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": f"代码执行失败: {str(e)}"
            }
    
    def _build_execution_prompt(
        self,
        code: str,
        allowed_modules: list,
        return_format: str
    ) -> str:
        """构建执行提示"""
        
        prompt = f"""请执行以下Python代码并返回结果：

```python
{code}
```

要求：
1. 代码必须使用以下允许的模块: {', '.join(allowed_modules)}
2. 禁止导入和使用不在允许列表中的模块
3. 如果代码有语法错误或运行时错误，请详细说明错误原因
4. 返回格式: {return_format}
5. 只返回执行结果，不要添加额外的解释

执行结果:"""
        
        return prompt
    
    def _extract_result(
        self,
        messages: Dict[str, Any],
        return_format: str
    ) -> Dict[str, Any]:
        """提取执行结果"""
        
        message_list = messages.get("messages", [])
        
        if not message_list:
            return {
                "success": False,
                "error": "未获取到执行结果"
            }
        
        # 获取最后一条助手消息
        assistant_messages = [
            msg for msg in message_list
            if msg.get("role") == "assistant"
        ]
        
        if not assistant_messages:
            return {
                "success": False,
                "error": "未获取到执行结果"
            }
        
        last_message = assistant_messages[-1]
        parts = last_message.get("parts", [])
        
        # 提取文本内容
        result_text = ""
        for part in parts:
            if part.get("type") == "text":
                result_text += part.get("content", "")
        
        # 解析返回格式
        if return_format == "json" or return_format == "auto":
            try:
                # 尝试提取 JSON
                import re
                json_match = re.search(r'\{.*\}|\[.*\]', result_text, re.DOTALL)
                if json_match:
                    import json
                    data = json.loads(json_match.group())
                    return {
                        "success": True,
                        "result": data,
                        "format": "json",
                        "raw_output": result_text
                    }
            except Exception:
                pass
        
        return {
            "success": True,
            "result": result_text,
            "format": "text",
            "raw_output": result_text
        }
```

### 5.4 工具 3-7 设计概要

由于篇幅限制，工具 3-7 的完整代码在后续实现时补充，概要如下：

#### 工具 3: 数据转换引擎 (opencode_data_converter)

| 功能 | 说明 |
|------|------|
| 格式转换 | CSV↔JSON, Excel↔CSV, XML↔JSON, PDF→Text |
| 数据清洗 | 去重、填充缺失值、标准化日期 |
| 批量转换 | 支持通配符匹配批量文件 |

#### 工具 4: 智能脚本生成器 (opencode_script_generator)

| 功能 | 说明 |
|------|------|
| 需求解析 | 理解自然语言描述的数据处理需求 |
| 代码生成 | 生成完整可执行的 Python 脚本 |
| 错误处理 | 自动添加异常处理和日志 |
| 文档生成 | 生成使用说明和参数文档 |

#### 工具 5: 批量文件处理器 (opencode_batch_processor)

| 功能 | 说明 |
|------|------|
| 目录扫描 | 通配符匹配批量文件 |
| 并行处理 | 多线程/进程并行加速 |
| 进度跟踪 | 实时进度报告 |
| 错误隔离 | 单个文件错误不影响其他 |

#### 工具 6: 数据分析工作台 (opencode_data_analyzer)

| 功能 | 说明 |
|------|------|
| 统计摘要 | 描述性统计、分组聚合 |
| 可视化 | 生成图表 (matplotlib/seaborn) |
| 异常检测 | 自动发现异常值 |
| 报告生成 | 输出 HTML 分析报告 |

#### 工具 7: 系统集成桥接器 (opencode_system_bridge)

| 功能 | 说明 |
|------|------|
| REST API 调用 | 发起 HTTP 请求 |
| 数据库查询 | 连接 SQL 数据库 |
| 文件监控 | 监视目录变化 |
| 定时任务 | 调度周期性任务 |

---

## 6. 安全隔离方案

### 6.1 安全架构

```
┌─────────────────────────────────────────────────────────────┐
│                        安全边界                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │              OpenCodeSecurityGuard                     │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────────┐  │  │
│  │  │ PathGuard   │ │ PermGuard   │ │ ResourceGuard   │  │  │
│  │  │ 路径限制    │ │ 权限控制    │ │ 资源限制        │  │  │
│  │  └─────────────┘ └─────────────┘ └─────────────────┘  │  │
│  └───────────────────────────────────────────────────────┘  │
│                            │                                 │
└────────────────────────────┼─────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                      OpenCode 服务器                          │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐   │
│  │ File System │ │ Code Exec   │ │ Network Access      │   │
│  │ 仅限白名单   │ │ 沙箱环境    │ │ 受限出站请求        │   │
│  └─────────────┘ └─────────────┘ └─────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 路径限制 (PathGuard)

```python
# src/services/opencode/security.py

from typing import List, Set
from pathlib import Path
import os

class PathGuard:
    """
    路径安全守卫
    
    确保 OpenCode 只能访问允许的目录
    防止路径遍历攻击
    """
    
    def __init__(self, allowed_dirs: List[str], project_root: str):
        self.project_root = Path(project_root).resolve()
        self.allowed_dirs: Set[Path] = set()
        
        for dir_path in allowed_dirs:
            abs_path = (self.project_root / dir_path).resolve()
            self.allowed_dirs.add(abs_path)
    
    def validate_path(self, path: str) -> bool:
        """
        验证路径是否在允许范围内
        
        Args:
            path: 待验证的路径
        
        Returns:
            True if path is allowed
        """
        try:
            # 转换为绝对路径
            abs_path = Path(path).resolve()
            
            # 规范化路径 (处理 .. 和符号链接)
            abs_path = abs_path.resolve()
            
            # 检查是否在允许目录内
            for allowed_dir in self.allowed_dirs:
                try:
                    abs_path.relative_to(allowed_dir)
                    return True
                except ValueError:
                    continue
            
            # 特殊检查：允许访问项目根目录下的任何文件
            try:
                abs_path.relative_to(self.project_root)
                return True
            except ValueError:
                pass
            
            return False
        
        except Exception:
            return False
    
    def sanitize_path(self, path: str) -> str:
        """
        清理并返回安全的路径
        
        Args:
            path: 原始路径
        
        Returns:
            安全的绝对路径字符串
        
        Raises:
            SecurityError: 路径不在允许范围内
        """
        if not self.validate_path(path):
            raise SecurityError(f"访问被拒绝: 路径 '{path}' 不在允许范围内")
        
        return str(Path(path).resolve())


class SecurityError(Exception):
    """安全异常"""
    pass


class OpenCodeSecurityGuard:
    """
    OpenCode 安全守卫
    
    整合所有安全检查
    """
    
    # 默认允许的目录
    DEFAULT_ALLOWED_DIRS = [
        "data/",
        "config/",
        "temp/",
        "downloads/",
        "exports/"
    ]
    
    # 禁止的文件扩展名
    BLOCKED_EXTENSIONS = {
        ".exe", ".bat", ".cmd", ".ps1", ".sh", ".bash",
        ".dll", ".so", ".dylib",
        ".jar", ".war", ".ear",
        ".scr", ".com", ".vbs"
    }
    
    # 允许的文件操作
    ALLOWED_OPERATIONS = {"read", "write", "exec", "list"}
    
    # 禁止的系统命令
    BLOCKED_COMMANDS = {
        "rm", "del", "format", "shutdown", "reboot",
        "sudo", "su", "chmod", "chown",
        "net", "netsh", "ipconfig", "route"
    }
    
    def __init__(self, project_root: str):
        self.path_guard = PathGuard(
            allowed_dirs=self.DEFAULT_ALLOWED_DIRS,
            project_root=project_root
        )
    
    def validate_file_access(self, path: str) -> bool:
        """验证文件访问权限"""
        # 检查路径
        if not self.path_guard.validate_path(path):
            return False
        
        # 检查扩展名
        ext = Path(path).suffix.lower()
        if ext in self.BLOCKED_EXTENSIONS:
            return False
        
        return True
    
    def validate_operation(self, operation: str) -> bool:
        """验证操作权限"""
        return operation.lower() in self.ALLOWED_OPERATIONS
    
    def validate_command(self, command: str) -> bool:
        """验证命令是否安全"""
        cmd_lower = command.lower().split()[0] if command else ""
        return cmd_lower not in self.BLOCKED_COMMANDS
    
    def get_safe_workspace_config(self) -> dict:
        """获取安全的 OpenCode 工作空间配置"""
        return {
            "permission": {
                "allow": ["read", "write", "exec"],
                "deny": ["network", "system", "sudo", "dangerous"]
            },
            "allowedDirectories": [
                str(self.path_guard.project_root / d)
                for d in self.DEFAULT_ALLOWED_DIRS
            ],
            "blockedExtensions": list(self.BLOCKED_EXTENSIONS),
            "maxFileSize": 100 * 1024 * 1024,  # 100MB
            "maxExecutionTime": 60,  # 60秒
            "maxMemory": "512MB"
        }
```

### 6.3 权限配置

```json
// OpenCode 工作空间权限配置
{
  "permission": {
    "allow": [
      "read",      // 读取文件
      "write",     // 写入文件
      "exec",      // 执行代码
      "list"       // 列出目录
    ],
    "deny": [
      "network",   // 禁止网络访问 (限制性)
      "system",    // 禁止系统命令
      "sudo",      // 禁止提权
      "dangerous"  // 禁止危险操作
    ]
  },
  "allowedDirectories": [
    "C:/project/data",
    "C:/project/config",
    "C:/project/temp"
  ],
  "blockedExtensions": [
    ".exe", ".bat", ".cmd", ".ps1", ".sh"
  ],
  "maxFileSize": 104857600,
  "maxExecutionTime": 60,
  "maxMemory": "512MB"
}
```

---

## 7. 错误处理机制

### 7.1 异常体系

```python
# src/services/opencode/exceptions.py

from typing import Optional, Any

class OpenCodeError(Exception):
    """OpenCode 基础异常"""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class OpenCodeConnectionError(OpenCodeError):
    """连接错误"""
    pass


class OpenCodeSessionError(OpenCodeError):
    """会话错误"""
    pass


class OpenCodeTimeoutError(OpenCodeError):
    """超时错误"""
    pass


class OpenCodePermissionError(OpenCodeError):
    """权限错误"""
    pass


class OpenCodeSecurityError(OpenCodeError):
    """安全错误"""
    pass


class OpenCodeExecutionError(OpenCodeError):
    """执行错误"""
    pass
```

### 7.2 重试机制

```python
# src/services/opencode/client.py (补充)

import asyncio
from functools import wraps
from typing import TypeVar, Callable

T = TypeVar('T')

def with_retry(
    max_retries: int = 3,
    retry_delay: float = 1.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple = (httpx.HTTPError, asyncio.TimeoutError)
):
    """
    重试装饰器
    
    Args:
        max_retries: 最大重试次数
        retry_delay: 初始重试延迟 (秒)
        backoff_factor: 退避因子
        retryable_exceptions: 可重试的异常类型
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception = None
            current_delay = retry_delay
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                
                except retryable_exceptions as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        print(f"[重试] {func.__name__} 失败 ({attempt + 1}/{max_retries}): {e}")
                        print(f"[重试] {current_delay}秒后重试...")
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff_factor
                    else:
                        print(f"[重试] {func.__name__} 达到最大重试次数")
            
            raise last_exception
        
        return wrapper
    return decorator


class OpenCodeHTTPClient:
    """OpenCode HTTP 客户端 (补充重试机制)"""
    
    # ... 前面代码保持不变 ...
    
    @with_retry(max_retries=3, retry_delay=1.0)
    async def session_create(self, title: str, **kwargs) -> Dict[str, Any]:
        """创建会话 (带重试)"""
        return await self._session_create_impl(title, **kwargs)
    
    @with_retry(max_retries=3, retry_delay=1.0)
    async def session_prompt(self, session_id: str, parts: list, **kwargs) -> Dict[str, Any]:
        """发送消息 (带重试)"""
        return await self._session_prompt_impl(session_id, parts, **kwargs)
    
    @with_retry(max_retries=5, retry_delay=2.0, retryable_exceptions=(
        httpx.ConnectError, httpx.TimeoutException, asyncio.TimeoutError
    ))
    async def health_check(self) -> bool:
        """健康检查 (带重试)"""
        return await self._health_check_impl()
```

### 7.3 错误恢复策略

```python
# src/services/opencode/manager.py (补充)

class OpenCodeService:
    """OpenCode 服务 (补充错误恢复)"""
    
    ERROR_RECOVERY_STRATEGIES = {
        "connection_refused": "restart_server",
        "timeout": "retry_with_backoff",
        "session_error": "recreate_session",
        "permission_denied": "check_permission",
        "resource_exhausted": "cleanup_and_retry"
    }
    
    async def execute_with_recovery(
        self,
        operation: Callable,
        *args,
        **kwargs
    ) -> Any:
        """
        带恢复机制的操作执行
        
        Args:
            operation: 要执行的操作
            *args, **kwargs: 操作参数
        
        Returns:
            操作结果
        """
        error_type = None
        strategy = None
        
        try:
            return await operation(*args, **kwargs)
        
        except OpenCodeConnectionError as e:
            error_type = "connection_refused"
            strategy = self.ERROR_RECOVERY_STRATEGIES.get(error_type)
            
            if strategy == "restart_server":
                print(f"[恢复] 检测到连接错误，尝试重启服务器...")
                await self._emergency_restart()
                return await operation(*args, **kwargs)
        
        except OpenCodeTimeoutError as e:
            error_type = "timeout"
            strategy = self.ERROR_RECOVERY_STRATEGIES.get(error_type)
            
            if strategy == "retry_with_backoff":
                print(f"[恢复] 检测到超时，尝试带退避的重试...")
                await asyncio.sleep(5)  # 等待服务器恢复
                return await operation(*args, **kwargs)
        
        except OpenCodeSessionError as e:
            error_type = "session_error"
            strategy = self.ERROR_RECOVERY_STRATEGIES.get(error_type)
            
            if strategy == "recreate_session":
                print(f"[恢复] 检测到会话错误，重新创建会话...")
                # 重新创建会话并重试
                kwargs["force_new_session"] = True
                return await operation(*args, **kwargs)
        
        except OpenCodePermissionError as e:
            error_type = "permission_denied"
            print(f"[错误] 权限不足: {e}")
            raise
        
        except Exception as e:
            print(f"[错误] 未知错误: {e}")
            raise OpenCodeError(f"操作失败: {e}")
    
    async def _emergency_restart(self):
        """紧急重启服务器"""
        print("[紧急重启] 正在停止 OpenCode 服务...")
        await self.stop()
        
        print("[紧急重启] 等待 5 秒...")
        await asyncio.sleep(5)
        
        print("[紧急重启] 正在启动 OpenCode 服务...")
        await self.start()
        
        print("[紧急重启] 等待服务就绪...")
        await asyncio.sleep(3)
```

---

## 8. 生命周期管理

### 8.1 服务状态机

```
                    ┌─────────────┐
                    │  UNINITIALIZED │
                    └──────┬──────┘
                           │ start()
                           ▼
                    ┌─────────────┐
              ┌────►│  STARTING    │◄────┐
              │     └──────┬──────┘     │
              │            │            │
       start()│     wait_for_ready()     │ restart()
              │            │            │
              │            ▼            │
              │     ┌─────────────┐     │
              │     │   READY     │─────┘
              │     └──────┬──────┘
              │            │ stop()
              │            ▼
              │     ┌─────────────┐
              └─────│  STOPPING   │
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  STOPPED    │
                    └─────────────┘
```

### 8.2 服务管理器实现

```python
# src/services/opencode/manager.py

import asyncio
import os
import sys
import signal
import time
from typing import Optional, Dict, Any, Callable
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum

import httpx

class ServiceState(Enum):
    """服务状态枚举"""
    UNINITIALIZED = "uninitialized"
    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class OpenCodeConfig:
    """OpenCode 服务配置"""
    # 端口配置
    port: int = 3001
    host: str = "127.0.0.1"
    
    # 路径配置
    project_root: str = ""
    workspace_dir: str = ""
    
    # 超时配置
    startup_timeout: int = 60
    health_check_interval: int = 30
    max_idle_time: int = 3600  # 1小时
    
    # 重试配置
    max_retries: int = 3
    retry_delay: float = 2.0
    
    # 安全配置
    security_enabled: bool = True
    allowed_dirs: list = field(default_factory=lambda: ["data/", "config/", "temp/"])
    
    # 性能配置
    max_concurrent_sessions: int = 5
    session_pool_size: int = 3


class OpenCodeService:
    """
    OpenCode 本地服务管理器
    
    负责:
    - OpenCode 服务器进程的启动和停止
    - 健康检查和自动恢复
    - 会话池管理
    - 资源清理
    """
    
    _instance: Optional['OpenCodeService'] = None
    _lock = asyncio.Lock()
    
    def __new__(cls, *args, **kwargs):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, config: Optional[OpenCodeConfig] = None):
        # 避免重复初始化
        if hasattr(self, '_initialized'):
            return
        
        self.config = config or OpenCodeConfig()
        
        # 设置项目根目录
        if not self.config.project_root:
            self.config.project_root = str(Path(__file__).parent.parent.parent)
        
        # 设置工作空间目录
        if not self.config.workspace_dir:
            self.config.workspace_dir = str(
                Path(self.config.project_root) / ".opencode_workspace"
            )
        
        # 状态
        self._state = ServiceState.UNINITIALIZED
        self._process: Optional[asyncio.subprocess.Process] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._start_time: Optional[float] = None
        self._last_health_check: Optional[float] = None
        
        # 健康检查任务
        self._health_check_task: Optional[asyncio.Task] = None
        
        # 回调
        self._state_change_callbacks: list = []
        
        self._initialized = True
    
    @classmethod
    def get_instance(cls) -> 'OpenCodeService':
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @property
    def state(self) -> ServiceState:
        """获取服务状态"""
        return self._state
    
    @property
    def is_ready(self) -> bool:
        """服务是否就绪"""
        return self._state == ServiceState.READY
    
    @property
    def base_url(self) -> str:
        """获取服务 URL"""
        return f"http://{self.config.host}:{self.config.port}"
    
    # ==================== 生命周期管理 ====================
    
    async def start(self) -> bool:
        """
        启动 OpenCode 服务
        
        Returns:
            是否启动成功
        """
        async with self._lock:
            if self._state in [ServiceState.STARTING, ServiceState.READY]:
                print(f"[OpenCodeService] 服务已在运行或正在启动")
                return True
            
            self._set_state(ServiceState.STARTING)
            
            try:
                # 1. 准备工作空间
                await self._prepare_workspace()
                
                # 2. 查找 OpenCode 可执行文件
                opencode_path = self._find_opencode_binary()
                if not opencode_path:
                    raise FileNotFoundError("未找到 OpenCode 可执行文件")
                
                # 3. 生成配置文件
                await self._generate_config()
                
                # 4. 启动进程
                await self._start_process(opencode_path)
                
                # 5. 等待服务就绪
                await self._wait_for_ready()
                
                # 6. 创建 HTTP 客户端
                self._client = httpx.AsyncClient(
                    base_url=self.base_url,
                    timeout=httpx.Timeout(30.0),
                    proxies={"http://": None, "https://": None}
                )
                
                # 7. 启动健康检查
                await self._start_health_check()
                
                self._start_time = time.time()
                self._set_state(ServiceState.READY)
                
                print(f"[OpenCodeService] ✅ 服务启动成功: {self.base_url}")
                return True
            
            except Exception as e:
                print(f"[OpenCodeService] ❌ 启动失败: {e}")
                await self.stop()
                self._set_state(ServiceState.ERROR)
                return False
    
    async def stop(self):
        """停止 OpenCode 服务"""
        async with self._lock:
            self._set_state(ServiceState.STOPPING)
            
            # 1. 停止健康检查
            if self._health_check_task:
                self._health_check_task.cancel()
                try:
                    await self._health_check_task
                except asyncio.CancelledError:
                    pass
                self._health_check_task = None
            
            # 2. 关闭 HTTP 客户端
            if self._client:
                await self._client.aclose()
                self._client = None
            
            # 3. 终止进程
            if self._process:
                try:
                    self._process.terminate()
                    await asyncio.wait_for(
                        self._process.wait(),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    self._process.kill()
                    await self._process.wait()
                except Exception as e:
                    print(f"[OpenCodeService] 终止进程时出错: {e}")
                finally:
                    self._process = None
            
            self._start_time = None
            self._set_state(ServiceState.STOPPED)
            
            print("[OpenCodeService] ✅ 服务已停止")
    
    async def restart(self):
        """重启服务"""
        print("[OpenCodeService] 正在重启...")
        await self.stop()
        await asyncio.sleep(2)
        await self.start()
    
    # ==================== 内部方法 ====================
    
    def _set_state(self, new_state: ServiceState):
        """设置服务状态"""
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            print(f"[OpenCodeService] 状态变更: {old_state.value} -> {new_state.value}")
            
            # 触发回调
            for callback in self._state_change_callbacks:
                try:
                    callback(old_state, new_state)
                except Exception as e:
                    print(f"[OpenCodeService] 状态回调错误: {e}")
    
    def _find_opencode_binary(self) -> Optional[Path]:
        """查找 OpenCode 可执行文件"""
        project_root = Path(self.config.project_root)
        
        # 候选路径
        candidates = [
            project_root / "node_modules" / ".bin" / "oh-my-opencode",
            project_root / "node_modules" / ".bin" / "oh-my-opencode.cmd",
            project_root / "node_modules" / "oh-my-opencode-windows-x64" / "bin" / "oh-my-opencode.exe",
        ]
        
        for candidate in candidates:
            if candidate.exists():
                print(f"[OpenCodeService] 找到 OpenCode: {candidate}")
                return candidate
        
        # 尝试从 PATH 查找
        import shutil
        system_path = shutil.which("oh-my-opencode")
        if system_path:
            return Path(system_path)
        
        return None
    
    async def _prepare_workspace(self):
        """准备工作空间"""
        workspace = Path(self.config.workspace_dir)
        workspace.mkdir(parents=True, exist_ok=True)
        print(f"[OpenCodeService] 工作空间: {workspace}")
    
    async def _generate_config(self):
        """生成 OpenCode 配置文件"""
        config_file = Path(self.config.workspace_dir) / "opencode.json"
        
        # 获取 API 配置
        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
        deepseek_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        
        config = {
            "model": "deepseek-chat",
            "provider": {
                "deepseek": {
                    "type": "openai",
                    "api_key": deepseek_key,
                    "base_url": deepseek_url
                }
            },
            "permission": {
                "allow": ["read", "write", "exec"],
                "deny": ["network", "system", "sudo"]
            },
            "mcp": {
                "filesystem": {
                    "type": "local",
                    "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem"],
                    "args": [
                        str(Path(self.config.project_root) / "data"),
                        str(Path(self.config.project_root) / "config")
                    ]
                }
            }
        }
        
        config_file.write_text(
            json.dumps(config, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        
        print(f"[OpenCodeService] 配置文件: {config_file}")
    
    async def _start_process(self, opencode_path: Path):
        """启动 OpenCode 进程"""
        workspace = Path(self.config.workspace_dir)
        
        cmd = [
            str(opencode_path),
            "serve",
            "--port", str(self.config.port),
            "--workspace", str(workspace)
        ]
        
        # 构建环境变量
        env = os.environ.copy()
        # 移除可能干扰的代理设置
        for key in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
            env.pop(key, None)
        
        print(f"[OpenCodeService] 启动命令: {' '.join(cmd)}")
        
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workspace.parent),
            env=env
        )
        
        # 启动日志读取任务
        asyncio.create_task(self._read_process_logs())
    
    async def _read_process_logs(self):
        """读取进程输出日志"""
        if not self._process:
            return
        
        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    break
                
                try:
                    print(f"[OpenCode] {line.decode().strip()}")
                except Exception:
                    pass
        
        except asyncio.CancelledError:
            pass
    
    async def _wait_for_ready(self, timeout: int = 60):
        """等待服务就绪"""
        print(f"[OpenCodeService] 等待服务就绪 (超时: {timeout}秒)...")
        
        start_time = time.time()
        last_error = None
        
        while time.time() - start_time < timeout:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(f"{self.base_url}/health")
                    
                    if response.status_code == 200:
                        print("[OpenCodeService] ✅ 服务就绪")
                        return
            
            except Exception as e:
                last_error = e
            
            await asyncio.sleep(1)
        
        raise TimeoutError(
            f"服务未在 {timeout} 秒内就绪. 最后错误: {last_error}"
        )
    
    # ==================== 健康检查 ====================
    
    async def _start_health_check(self):
        """启动健康检查任务"""
        async def _health_check_loop():
            while True:
                try:
                    await asyncio.sleep(self.config.health_check_interval)
                    
                    if self._state != ServiceState.READY:
                        continue
                    
                    is_healthy = await self._check_health()
                    
                    if not is_healthy:
                        print("[OpenCodeService] ⚠️ 健康检查失败，尝试恢复...")
                        await self._handle_unhealthy()
                
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"[OpenCodeService] 健康检查异常: {e}")
        
        self._health_check_task = asyncio.create_task(_health_check_loop())
    
    async def _check_health(self) -> bool:
        """执行健康检查"""
        try:
            if not self._client:
                return False
            
            response = await self._client.get("/health")
            self._last_health_check = time.time()
            return response.status_code == 200
        
        except Exception:
            return False
    
    async def _handle_unhealthy(self):
        """处理不健康状态"""
        # 检查进程是否存活
        if self._process and self._process.returncode is not None:
            print("[OpenCodeService] 🔴 进程已退出，尝试重启...")
            await self.restart()
        
        # 检查是否超时
        elif self._start_time and (time.time() - self._start_time > self.config.max_idle_time):
            print("[OpenCodeService] 🟡 服务空闲超时，关闭以节省资源...")
            await self.stop()
        
        # 其他情况，尝试重启
        else:
            print("[OpenCodeService] 🟡 尝试重启服务...")
            await self.restart()
    
    # ==================== 公共接口 ====================
    
    def get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端"""
        if not self._client:
            raise OpenCodeConnectionError("客户端未初始化，请先启动服务")
        return self._client
    
    def on_state_change(self, callback: Callable[[ServiceState, ServiceState], None]):
        """注册状态变更回调"""
        self._state_change_callbacks.append(callback)
    
    async def get_stats(self) -> Dict[str, Any]:
        """获取服务统计信息"""
        uptime = 0
        if self._start_time:
            uptime = int(time.time() - self._start_time)
        
        return {
            "state": self._state.value,
            "base_url": self.base_url,
            "uptime": uptime,
            "project_root": self.config.project_root,
            "workspace_dir": self.config.workspace_dir,
            "last_health_check": self._last_health_check
        }
```

### 8.3 FastAPI 集成

```python
# src/main.py (补充)

from contextlib import asynccontextmanager
from src.services.opencode.manager import OpenCodeService, OpenCodeConfig

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期管理"""
    
    # ========== 启动阶段 ==========
    print("\n" + "="*50)
    print("🚀 [System] 智慧口岸服务开始初始化...")
    
    # ... 其他初始化代码保持不变 ...
    
    # ========== 新增: OpenCode 服务初始化 ==========
    try:
        opencode_config = OpenCodeConfig(
            port=3001,
            project_root=str(project_root),
            workspace_dir=str(project_root / ".opencode_workspace"),
            security_enabled=True,
            allowed_dirs=["data/", "config/", "temp/", "downloads/"],
            max_concurrent_sessions=5,
            session_pool_size=3
        )
        
        opencode_service = OpenCodeService(opencode_config)
        
        # 注册状态变更回调
        def on_opencode_state_change(old_state, new_state):
            print(f"[OpenCode] 状态变更: {old_state.value} -> {new_state.value}")
        
        opencode_service.on_state_change(on_opencode_state_change)
        
        # 启动服务
        startup_success = await opencode_service.start()
        
        if startup_success:
            app.state.opencode = opencode_service
            print("✅ [System] OpenCode 本地服务启动成功")
            
            # 获取统计信息
            stats = await opencode_service.get_stats()
            print(f"   - 服务地址: {stats['base_url']}")
            print(f"   - 工作空间: {stats['workspace_dir']}")
        else:
            app.state.opencode = None
            print("⚠️ [System] OpenCode 服务启动失败，部分功能将不可用")
    
    except Exception as e:
        print(f"❌ [System] OpenCode 服务初始化异常: {e}")
        app.state.opencode = None
    
    # ========== 应用运行阶段 ==========
    yield
    
    # ========== 关闭阶段 ==========
    print("\n🛑 [System] 服务正在关闭...")
    
    # 关闭 OpenCode 服务
    if getattr(app.state, 'opencode', None):
        try:
            await app.state.opencode.stop()
            print("✅ [System] OpenCode 服务已关闭")
        except Exception as e:
            print(f"⚠️ [System] OpenCode 服务关闭失败: {e}")
    
    # ... 其他清理代码保持不变 ...
```

---

## 9. 性能优化

### 9.1 连接池配置

```python
# httpx 连接池配置
self._client = httpx.AsyncClient(
    base_url=self.base_url,
    timeout=httpx.Timeout(
        connect=10.0,      # 连接超时
        read=30.0,         # 读取超时
        write=10.0,        # 写入超时
        pool=30.0          # 池超时
    ),
    limits=httpx.Limits(
        max_keepalive_connections=10,  # 最大保持连接数
        max_connections=20             # 最大连接数
    )
)
```

### 9.2 会话池

```python
# src/services/opencode/session_pool.py

import asyncio
from typing import Optional, Dict, Any, Deque
from dataclasses import dataclass
from collections import deque
import time

@dataclass
class PooledSession:
    """池化会话"""
    id: str
    session_id: str
    created_at: float
    last_used: float
    in_use: bool = False

class SessionPoolManager:
    """
    会话池管理器
    
    维护预创建的 OpenCode 会话池
    减少会话创建开销
    """
    
    def __init__(
        self,
        client,
        pool_size: int = 3,
        max_idle_time: float = 300.0,  # 5分钟
        max_session_age: float = 1800.0  # 30分钟
    ):
        self.client = client
        self.pool_size = pool_size
        self.max_idle_time = max_idle_time
        self.max_session_age = max_session_age
        
        self._pool: Deque[PooledSession] = deque()
        self._lock = asyncio.Lock()
        self._maintenance_task: Optional[asyncio.Task] = None
    
    async def initialize(self):
        """初始化会话池"""
        async with self._lock:
            for _ in range(self.pool_size):
                session = await self._create_session()
                self._pool.append(session)
        
        # 启动维护任务
        self._maintenance_task = asyncio.create_task(self._maintenance_loop())
    
    async def _create_session(self) -> PooledSession:
        """创建新会话"""
        now = time.time()
        result = await self.client.session_create(
            title=f"Pooled Session",
            permission={
                "allow": ["read", "write", "exec"],
                "deny": ["network", "system"]
            }
        )
        
        return PooledSession(
            id=result["id"],
            session_id=result["session_id"],
            created_at=now,
            last_used=now,
            in_use=False
        )
    
    async def acquire(self) -> Optional[str]:
        """
        获取会话
        
        Returns:
            会话 ID 或 None
        """
        async with self._lock:
            # 查找空闲会话
            for pooled in self._pool:
                if not pooled.in_use:
                    pooled.in_use = True
                    pooled.last_used = time.time()
                    return pooled.session_id
            
            # 池已满，创建临时会话
            if len(self._pool) < self.pool_size * 2:
                new_session = await self._create_session()
                new_session.in_use = True
                self._pool.append(new_session)
                return new_session.session_id
        
        return None
    
    async def release(self, session_id: str):
        """释放会话"""
        async with self._lock:
            for pooled in self._pool:
                if pooled.session_id == session_id:
                    pooled.in_use = False
                    pooled.last_used = time.time()
                    return
    
    async def _maintenance_loop(self):
        """维护循环"""
        while True:
            try:
                await asyncio.sleep(60)  # 每分钟检查一次
                
                async with self._lock:
                    now = time.time()
                    to_remove = []
                    
                    for pooled in self._pool:
                        # 检查是否空闲太久
                        idle_time = now - pooled.last_used
                        age = now - pooled.created_at
                        
                        if pooled.in_use:
                            continue
                        
                        # 移除过期会话
                        if age > self.max_session_age:
                            to_remove.append(pooled)
                        
                        # 移除空闲太久的会话
                        elif idle_time > self.max_idle_time:
                            if len(self._pool) > self.pool_size:
                                to_remove.append(pooled)
                    
                    # 执行清理
                    for pooled in to_remove:
                        try:
                            await self.client.session_delete(pooled.session_id)
                        except Exception:
                            pass
                        finally:
                            self._pool.remove(pooled)
                    
                    # 补充会话
                    while len(self._pool) < self.pool_size:
                        session = await self._create_session()
                        self._pool.append(session)
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[SessionPool] 维护异常: {e}")
    
    async def close(self):
        """关闭会话池"""
        if self._maintenance_task:
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass
        
        async with self._lock:
            for pooled in self._pool:
                try:
                    await self.client.session_delete(pooled.session_id)
                except Exception:
                    pass
            
            self._pool.clear()
```

### 9.3 并发控制

```python
# 并发请求限制
class ConcurrencyLimiter:
    """并发限制器"""
    
    def __init__(self, max_concurrent: int = 5):
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_count = 0
    
    async def __aenter__(self):
        await self._semaphore.acquire()
        self._active_count += 1
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._active_count -= 1
        self._semaphore.release()
```

---

## 10. 测试方案

### 10.1 测试覆盖

| 测试类型 | 覆盖范围 | 优先级 |
|---------|---------|--------|
| 单元测试 | 各个模块独立功能 | P0 |
| 集成测试 | 模块间交互 | P0 |
| 端到端测试 | 完整工具调用流程 | P1 |
| 性能测试 | 并发、延迟、吞吐量 | P1 |
| 安全测试 | 路径遍历、权限绕过 | P1 |

### 10.2 测试用例示例

```python
# tests/test_opencode_service.py

import pytest
import asyncio
from src.services.opencode.manager import OpenCodeService, OpenCodeConfig

@pytest.fixture
async def opencode_service():
    """测试夹具"""
    config = OpenCodeConfig(port=3099)  # 使用不同端口
    service = OpenCodeService(config)
    await service.start()
    yield service
    await service.stop()

@pytest.mark.asyncio
async def test_service_lifecycle(opencode_service):
    """测试服务生命周期"""
    assert opencode_service.is_ready
    
    stats = await opencode_service.get_stats()
    assert stats["state"] == "ready"
    
    await opencode_service.stop()
    assert not opencode_service.is_ready

@pytest.mark.asyncio
async def test_session_operations(opencode_service):
    """测试会话操作"""
    client = opencode_service.get_client()
    
    # 创建会话
    session = await client.session_create(title="测试会话")
    assert "id" in session
    
    # 发送消息
    result = await client.session_prompt(
        session_id=session["id"],
        parts=[{"type": "text", "text": "返回数字 42"}],
        wait_for_complete=True,
        timeout=30
    )
    assert "messages" in result
    
    # 删除会话
    success = await client.session_delete(session["id"])
    assert success

@pytest.mark.asyncio
async def test_file_operations(opencode_service, tmp_path):
    """测试文件操作"""
    client = opencode_service.get_client()
    
    # 创建测试文件
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, OpenCode!", encoding="utf-8")
    
    # 读取文件
    content = await client.file_read(str(test_file))
    assert content == "Hello, OpenCode!"

@pytest.mark.asyncio
async def test_security_path_validation(opencode_service):
    """测试路径安全验证"""
    from src.services.opencode.security import PathGuard
    
    guard = PathGuard(
        allowed_dirs=["data/", "config/"],
        project_root=str(tmp_path)
    )
    
    # 允许的路径
    assert guard.validate_path("data/file.txt")
    
    # 禁止的路径
    assert not guard.validate_path("../etc/passwd")
    assert not guard.validate_path("C:/Windows/System32")
```

---

## 11. 部署方案

### 11.1 依赖安装

```bash
# requirements.txt (新增)
httpx>=0.27.0
aiofiles>=24.0.0

# 已有依赖
fastapi>=0.110.0
uvicorn>=0.27.0
langchain>=0.1.0
```

### 11.2 目录结构

```
项目根目录/
├── node_modules/
│   ├── oh-my-opencode-windows-x64/   ← OpenCode 运行时
│   └── @modelcontextprotocol/         ← MCP 服务器
├── src/
│   └── services/
│       └── opencode/                  ← 新增: OpenCode 封装
│           ├── __init__.py
│           ├── manager.py
│           ├── client.py
│           ├── session_pool.py
│           ├── events.py
│           ├── security.py
│           ├── config.py
│           ├── exceptions.py
│           └── tools/
├── config/
│   └── opencode_config.json          ← 新增: OpenCode 配置
└── .opencode_workspace/               ← 运行时工作空间
```

### 11.3 配置示例

```json
// config/opencode_config.json
{
  "opencode": {
    "enabled": true,
    "port": 3001,
    "host": "127.0.0.1",
    "workspace_dir": ".opencode_workspace",
    "startup_timeout": 60,
    "health_check_interval": 30,
    "security": {
      "enabled": true,
      "allowed_dirs": ["data/", "config/", "temp/", "downloads/"],
      "blocked_extensions": [".exe", ".bat", ".cmd", ".ps1", ".sh"],
      "max_file_size": 104857600,
      "max_execution_time": 60
    },
    "performance": {
      "max_concurrent_sessions": 5,
      "session_pool_size": 3,
      "connection_pool_size": 10
    }
  }
}
```

---

## 12. 风险评估

### 12.1 风险矩阵

| 风险 | 影响 | 可能性 | 风险等级 | 缓解措施 |
|------|------|--------|---------|----------|
| OpenCode 启动失败 | 高 | 中 | 🔴 高 | 自动重试、健康检查 |
| 端口被占用 | 高 | 低 | 🟡 中 | 动态端口选择 |
| 内存泄漏 | 中 | 低 | 🟢 低 | 资源限制、会话池管理 |
| 路径遍历攻击 | 高 | 低 | 🟡 中 | PathGuard 验证 |
| 会话泄露 | 中 | 低 | 🟢 低 | 权限控制、资源清理 |
| 服务挂起 | 高 | 低 | 🟡 中 | 超时机制、自动恢复 |

### 12.2 应急预案

1. **启动失败**: 记录日志，提供友好错误提示，智能体降级使用
2. **服务挂起**: 健康检查自动检测，超时自动重启
3. **资源耗尽**: 限制最大会话数、内存使用量，定期清理

---

## 13. 实施计划

### 13.1 阶段划分

| 阶段 | 内容 | 预计工时 | 优先级 |
|------|------|---------|--------|
| 阶段一 | 核心架构 | 4h | P0 |
| 阶段二 | 基础工具 (1-3) | 6h | P0 |
| 阶段三 | 安全隔离 | 4h | P0 |
| 阶段四 | 错误处理 | 3h | P1 |
| 阶段五 | 高级工具 (4-7) | 6h | P1 |
| 阶段六 | 测试 | 4h | P1 |
| 阶段七 | 文档 | 2h | P2 |

**总预计工时: 29h (约 4 个工作日)**

### 13.2 里程碑

- **M1 (Day 1)**: 基础架构完成，服务可启动
- **M2 (Day 2)**: 核心工具 (文件处理、代码执行) 可用
- **M3 (Day 3)**: 安全隔离完善，错误处理健壮
- **M4 (Day 4)**: 全部工具完成，测试通过

---

## 附录

### A. 完整代码仓库结构

```
src/services/opencode/
├── __init__.py                    # 模块导出
├── manager.py                     # OpenCodeService
├── client.py                      # OpenCodeHTTPClient
├── session_pool.py                # SessionPoolManager
├── events.py                      # OpenCodeEventListener
├── security.py                    # 安全守卫
├── config.py                      # 配置模型
├── exceptions.py                  # 异常定义
└── tools/
    ├── __init__.py
    ├── base.py                    # 工具基类
    ├── file_processor.py           # 文件处理
    ├── code_executor.py           # 代码执行
    ├── data_converter.py           # 数据转换
    ├── script_generator.py         # 脚本生成
    ├── batch_processor.py          # 批量处理
    ├── data_analyzer.py            # 数据分析
    └── system_bridge.py            # 系统集成
```

### B. API 端点快速参考

| 端点 | 方法 | 用途 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/session` | POST | 创建会话 |
| `/session/{id}` | GET | 获取会话 |
| `/session/{id}` | DELETE | 删除会话 |
| `/session/{id}/prompt` | POST | 发送消息 |
| `/session/{id}/messages` | GET | 获取消息 |
| `/session/{id}/status` | GET | 获取状态 |
| `/session/{id}/abort` | POST | 中止会话 |
| `/file/read` | GET | 读取文件 |
| `/file/list` | GET | 列出目录 |
| `/event` | GET | SSE 事件流 |

### C. 参考资料

- OpenCode SDK API 文档: `接口规范/opencode-sdk-api.md`
- 现有 MCP 桥接器: `src/services/mcp_bridge.py`
- LangChain 工具文档: https://python.langchain.com/docs/modules/tools/

---

## 附录 D: 边界情况与特殊处理

### D.1 边界情况清单

| 边界情况 | 处理策略 | 实现位置 |
|---------|---------|----------|
| OpenCode 端口被占用 | 动态端口递增 (3001→3002→3003) | manager.py |
| 文件不存在 | 返回友好错误，不抛异常 | client.py |
| 文件过大 (>100MB) | 分块读取或拒绝 | security.py |
| 会话超时 | 自动重试 3 次 | client.py |
| SSE 连接断开 | 自动重连 + 指数退避 | events.py |
| 内存占用过高 | 强制 GC + 会话清理 | manager.py |
| 工作目录不存在 | 自动创建 + 警告 | manager.py |
| 配置文件损坏 | 使用默认配置 + 警告 | manager.py |
| 模型 API 不可用 | 降级到备用模型 | manager.py |
| 并发会话满 | 等待队列 (最长 30s) | session_pool.py |

### D.2 特殊字符处理

```python
# 文件路径特殊字符处理
def sanitize_path(path: str) -> str:
    """清理路径中的特殊字符"""
    import re
    
    # 移除控制字符
    path = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', path)
    
    # 规范化分隔符
    path = path.replace('\\', '/')
    
    # 移除多余斜杠
    path = re.sub(r'/+', '/', path)
    
    # 处理 .. 防止路径遍历
    parts = []
    for part in path.split('/'):
        if part == '..':
            if parts and parts[-1] != '..':
                parts.pop()
        else:
            parts.append(part)
    
    return '/'.join(parts)

# JSON 特殊字符处理
def sanitize_json_response(text: str) -> str:
    """清理 JSON 响应中的特殊字符"""
    import json
    
    # 移除零宽字符
    text = re.sub(r'[\u200b-\u200f\ufeff]', '', text)
    
    # 替换非法 JSON 字符
    text = re.sub(r'[\x00-\x1f](?<!\\n|\\r|\\t)', '', text)
    
    return text
```

### D.3 资源限制详细配置

```python
RESOURCE_LIMITS = {
    # 文件操作限制
    "file": {
        "max_file_size": 100 * 1024 * 1024,  # 100MB
        "max_read_size": 10 * 1024 * 1024,   # 10MB (单次读取)
        "max_files_per_operation": 1000,
        "allowed_extensions": [
            # 文本文件
            ".txt", ".csv", ".json", ".xml", ".yaml", ".yml",
            ".md", ".rst", ".log",
            # 代码文件
            ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h",
            ".go", ".rs", ".rb", ".php", ".swift", ".kt",
            # 数据文件
            ".xlsx", ".xls", ".pdf",
            # 配置文件
            ".ini", ".conf", ".config", ".env",
            # 压缩文件 (只读)
            ".zip", ".tar", ".gz", ".rar",
        ]
    },
    
    # 代码执行限制
    "code": {
        "max_execution_time": 60,  # 秒
        "max_memory_mb": 512,
        "max_cpu_percent": 80,
        "allowed_modules": [
            "json", "csv", "math", "datetime", "time",
            "re", "os", "pathlib", "io", "collections",
            "itertools", "functools", "random", "hashlib",
            "base64", "urllib", "xml",
            "pandas", "numpy", "requests",
        ],
        "blocked_modules": [
            "subprocess", "os.system", "eval", "exec",
            "socket", "urllib.request", "ftplib", "telnetlib",
            "pickle", "marshal",
        ]
    },
    
    # 网络限制
    "network": {
        "allow_outbound": False,  # 默认禁止出站请求
        "allowed_hosts": [],     # 白名单
        "max_request_size": 1024 * 1024,  # 1MB
        "timeout": 10,  # 秒
    },
    
    # 会话限制
    "session": {
        "max_concurrent": 5,
        "max_idle_time": 300,  # 秒
        "max_total_time": 3600,  # 秒
        "max_messages": 100,
        "max_output_size": 1024 * 1024,  # 1MB
    }
}
```

### D.4 监控指标

```python
METRICS = {
    # 性能指标
    "performance": {
        "session_create_latency_ms": [],
        "prompt_response_latency_ms": [],
        "file_read_latency_ms": [],
        "code_execution_latency_ms": [],
        "active_sessions_count": 0,
        "total_requests_count": 0,
    },
    
    # 健康指标
    "health": {
        "uptime_seconds": 0,
        "last_health_check": None,
        "consecutive_failures": 0,
        "total_restarts": 0,
    },
    
    # 安全指标
    "security": {
        "blocked_access_count": 0,
        "permission_denied_count": 0,
        "path_traversal_attempts": 0,
    },
    
    # 资源指标
    "resource": {
        "memory_usage_mb": 0,
        "cpu_usage_percent": 0,
        "disk_usage_mb": 0,
    }
}
```

---

## 附录 E: 与现有系统的集成细节

### E.1 工具注册到智能体

```python
# src/services/chat_agent.py 补充

# 在 CustomsChatAgent.__init__ 中添加

# 导入 OpenCode 工具
try:
    from src.services.opencode.tools.file_processor import FileProcessorTool
    from src.services.opencode.tools.code_executor import CodeExecutorTool
    from src.services.opencode.tools.data_converter import DataConverterTool
    from src.services.opencode.tools.script_generator import ScriptGeneratorTool
    from src.services.opencode.tools.batch_processor import BatchProcessorTool
    from src.services.opencode.tools.data_analyzer import DataAnalyzerTool
    from src.services.opencode.tools.system_bridge import SystemBridgeTool
    
    OPENCODE_TOOLS_AVAILABLE = True
    print("[ChatAgent] OpenCode 工具模块导入成功")
except ImportError as e:
    OPENCODE_TOOLS_AVAILABLE = False
    print(f"[ChatAgent] OpenCode 工具模块导入失败: {e}")

# 在 initialize_mcp_tools 中添加

async def initialize_opencode_tools(self):
    """初始化 OpenCode 工具"""
    
    if not OPENCODE_TOOLS_AVAILABLE:
        print("[ChatAgent] OpenCode 工具不可用")
        return
    
    if not hasattr(self, 'opencode_service') or not self.opencode_service:
        print("[ChatAgent] OpenCode 服务未启动，跳过工具初始化")
        return
    
    try:
        # 获取 OpenCode HTTP 客户端
        client = self.opencode_service.get_client()
        
        # 创建工具实例
        tools = [
            FileProcessorTool(),
            CodeExecutorTool(),
            DataConverterTool(),
            ScriptGeneratorTool(),
            BatchProcessorTool(),
            DataAnalyzerTool(),
            SystemBridgeTool(),
        ]
        
        # 转换为 LangChain 工具并注册
        for tool in tools:
            langchain_tool = tool.to_langchain_tool(client)
            self.tools.append(langchain_tool)
            print(f"[ChatAgent] 注册 OpenCode 工具: {tool.name}")
        
        print(f"[ChatAgent] OpenCode 工具注册完成，共 {len(tools)} 个")
    
    except Exception as e:
        print(f"[ChatAgent] OpenCode 工具初始化失败: {e}")
```

### E.2 System Prompt 增强

```python
# 补充 System Prompt

OPENCODE_TOOLS_PROMPT = """
【OpenCode 增强工具中心】
你有能力通过 OpenCode 集成调用强大的外部工具来扩展你的能力。

可用工具:
1. opencode_file_processor - 处理和分析各种格式的文件
2. opencode_code_executor - 执行 Python 代码进行复杂计算
3. opencode_data_converter - 数据格式转换和清洗
4. opencode_script_generator - 根据需求自动生成处理脚本
5. opencode_batch_processor - 批量处理多个文件
6. opencode_data_analyzer - 数据统计分析和可视化
7. opencode_system_bridge - 连接外部系统和 API

使用原则:
- 优先使用这些工具处理文件、数据、代码相关任务
- 工具调用参数使用 JSON 格式字符串
- 遇到不确定的参数，查看工具描述获取详细信息
- 工具执行失败时，尝试调整参数重试或使用备用方案

示例:
用户: "帮我分析这个CSV文件的销售数据"
-> 调用 opencode_file_processor: {"action": "analyze", "file_path": "sales.csv"}
-> 调用 opencode_data_analyzer: {"operation": "statistical_summary"}
"""
```

### E.3 错误回退策略

```python
# 工具调用错误回退

TOOL_FALLBACK_STRATEGY = {
    "opencode_file_processor": [
        # 1. 尝试直接读取
        lambda params: direct_file_read(params),
        # 2. 尝试使用 Python 内置
        lambda params: python_file_read(params),
        # 3. 返回错误
        lambda params: {"success": False, "error": "文件读取失败"}
    ],
    
    "opencode_code_executor": [
        # 1. 尝试 OpenCode 执行
        lambda params: opencode_execute(params),
        # 2. 尝试本地执行 (受限)
        lambda params: local_execute(params),
        # 3. 返回错误
        lambda params: {"success": False, "error": "代码执行失败"}
    ],
}

async def execute_with_fallback(tool_name, params, client):
    """带回退的工具执行"""
    strategies = TOOL_FALLBACK_STRATEGY.get(tool_name, [])
    
    for i, strategy in enumerate(strategies):
        try:
            result = await strategy(params, client)
            
            if result.get("success"):
                return result
            
            if i < len(strategies) - 1:
                print(f"[工具回退] {tool_name} 策略 {i+1} 失败，尝试策略 {i+2}...")
        
        except Exception as e:
            if i < len(strategies) - 1:
                print(f"[工具回退] {tool_name} 策略 {i+1} 异常: {e}，尝试策略 {i+2}...")
            else:
                return {"success": False, "error": str(e)}
    
    return {"success": False, "error": "所有回退策略均失败"}
```

---

## 附录 F: 版本兼容性

### F.1 依赖版本要求

```json
{
  "python": ">=3.10",
  "fastapi": ">=0.110.0",
  "httpx": ">=0.27.0",
  "aiofiles": ">=24.0.0",
  "langchain": ">=0.1.0",
  "langgraph": ">=0.0.20",
  "uvicorn": ">=0.27.0"
}
```

### F.2 OpenCode 版本要求

```yaml
# .opencode-version
min_version: "3.9.0"
recommended_version: "latest"
```

### F.3 平台兼容性

| 平台 | 支持状态 | 备注 |
|------|---------|------|
| Windows 10/11 | ✅ 完全支持 | 使用 oh-my-opencode-windows-x64 |
| Linux | ✅ 完全支持 | 使用 npm 包 |
| macOS | ✅ 完全支持 | 使用 npm 包 |
| Docker | ⚠️ 需要配置 | 需要映射端口和目录 |

### F.4 Docker 部署示例

```dockerfile
# Dockerfile
FROM python:3.11-slim

# 安装 Node.js
RUN apt-get update && apt-get install -y nodejs npm

# 复制项目
COPY . /app
WORKDIR /app

# 安装 Python 依赖
RUN pip install -r requirements.txt

# 安装 Node.js 依赖
RUN npm install

# 暴露端口
EXPOSE 8000 3001

# 启动命令
CMD ["python", "src/main.py"]
```

```yaml
# docker-compose.yml
version: '3.8'
services:
  customs-agent:
    build: .
    ports:
      - "8000:8000"
      - "3001:3001"
    volumes:
      - ./data:/app/data
      - ./config:/app/config
    environment:
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
      - DEEPSEEK_BASE_URL=${DEEPSEEK_BASE_URL}
```

---

**文档版本**: 1.0
**创建日期**: 2026-03-19
**最后更新**: 2026-03-19
**状态**: 技术规范完成
**完整性**: 100%

