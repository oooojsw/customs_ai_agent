# OpenCode HTTP API 完整规范

> 版本: 2.0
> 日期: 2026-03-20
> 来源: 深度研究 OpenCode 项目源码

---

## 3. HTTP API 详细规范

### 3.1 会话管理 API

#### 3.1.1 创建会话

```
POST /session
Content-Type: application/json
x-opencode-directory: C:\path\to\workspace  # 必需，通过 header 或 ?directory= 指定工作目录

Request Body (可选):
{
  "parentID": "sess_xxxx",     # 可选，父会话ID
  "title": "会话标题",         # 可选
  "permission": [...]          # 可选，权限规则集（PermissionNext.Ruleset）
}

注意：工作目录不通过 body 传递，而是通过 x-opencode-directory header 或
?directory= 查询参数传递。如果不指定，默认使用服务器进程的 cwd。

Response: Session.Info
{
  "id": "sess_xxxx",
  "slug": "auto-generated-slug",
  "projectID": "proj_xxxx",
  "directory": "C:\\path\\to\\workspace",
  "title": "会话标题",
  "version": "x.x.x",
  "time": {
    "created": 1710000000000,
    "updated": 1710000000000
  }
}
```

#### 3.1.2 列出会话

```
GET /session?directory=C:\path&roots=true&limit=50

Query Parameters:
- directory: string (可选) - 按项目目录过滤
- roots: boolean (可选) - 只返回根会话
- start: number (可选) - 过滤更新时间 >= 此时间戳的会话
- search: string (可选) - 按标题搜索
- limit: number (可选) - 最大返回数量

Response: Session.Info[]
```

#### 3.1.3 发送消息（核心接口）

```
POST /session/:sessionID/message
Content-Type: application/json

Request Body (PromptInput):
{
  "messageID": "msg_xxxx",     # 可选，消息ID
  "model": {                    # 可选，指定模型
    "providerID": "anthropic",
    "modelID": "claude-sonnet-4-20250514"
  },
  "agent": "general",          # 可选，指定Agent
  "noReply": false,            # 可选，是否不回复
  "system": "额外系统提示",    # 可选
  "variant": "default",        # 可选
  "parts": [                   # 必需，消息内容
    {
      "type": "text",
      "text": "用户消息内容"
    }
  ]
}

Response (SSE Streaming):
data: {"info": {...}, "parts": [...]}
```

#### 3.1.4 获取消息

```
GET /session/:sessionID/message?limit=50

Response: MessageV2.WithParts[]
[
  {
    "info": {
      "id": "msg_xxxx",
      "sessionID": "sess_xxxx",
      "role": "user",
      "time": {"created": 1710000000000},
      "agent": "general",
      "model": {"providerID": "anthropic", "modelID": "claude-sonnet-4-20250514"}
    },
    "parts": [
      {
        "type": "text",
        "id": "part_xxxx",
        "sessionID": "sess_xxxx",
        "messageID": "msg_xxxx",
        "text": "消息内容"
      }
    ]
  }
]
```

#### 3.1.5 中止会话

```
POST /session/:sessionID/abort

Response: boolean (true)
```

#### 3.1.6 删除会话

```
DELETE /session/:sessionID

Response: boolean (true)
```

### 3.2 文件操作 API

#### 3.2.1 搜索文本

```
GET /find?pattern=search_term

Response: Ripgrep.Match[]
[
  {
    "data": {
      "path": {"text": "file.txt"},
      "lines": {"text": "matching line"},
      "line_number": 42,
      "absolute_offset": 1234
    }
  }
]
```

#### 3.2.2 搜索文件

```
GET /find/file?query=filename&type=file&limit=10

Query Parameters:
- query: string (必需) - 搜索关键词
- dirs: "true" | "false" (可选) - 是否包含目录
- type: "file" | "directory" (可选) - 文件类型过滤
- limit: number (可选, 1-200) - 最大返回数量

Response: string[]
["file1.txt", "file2.py", "dir/file3.js"]
```

#### 3.2.3 列出目录

```
GET /file?path=relative/path

Response: File.Node[]
[
  {
    "name": "file.txt",
    "path": "relative/path/file.txt",
    "type": "file",
    "size": 1024
  }
]
```

#### 3.2.4 读取文件

```
GET /file/content?path=relative/path/file.txt

Response: File.Content
{
  "path": "relative/path/file.txt",
  "content": "文件内容...",
  "encoding": "utf-8"
}
```

#### 3.2.5 获取文件状态

```
GET /file/status

Response: File.Info[]
[
  {
    "name": "modified.txt",
    "path": "path/to/modified.txt",
    "status": "modified",
    "added": 10,
    "removed": 5
  }
]
```

### 3.3 配置管理 API

#### 3.3.1 获取配置

```
GET /config

Response: Config.Info
{
  "provider": {...},
  "model": {...},
  "agent": {...},
  "server": {
    "port": 4096,
    "hostname": "127.0.0.1"
  }
}
```

#### 3.3.2 更新配置

```
PATCH /config
Content-Type: application/json

Request Body: Config.Info (部分更新)

Response: Config.Info
```

### 3.4 MCP 管理 API

#### 3.4.1 获取 MCP 状态

```
GET /mcp

Response: Record<serverName, MCP.Status>
{
  "filesystem": {
    "status": "connected",
    "tools": ["read_file", "write_file", "list_directory"]
  }
}
```

#### 3.4.2 添加 MCP 服务器

```
POST /mcp
Content-Type: application/json

Request Body:
{
  "name": "my-server",
  "config": {
    "command": "npx",
    "args": ["@modelcontextprotocol/server-filesystem", "data"],
    "env": {}
  }
}

Response: Record<serverName, MCP.Status>
```

#### 3.4.3 连接/断开 MCP 服务器

```
POST /mcp/:name/connect    → boolean
POST /mcp/:name/disconnect → boolean
```

### 3.5 系统 API

#### 3.5.1 健康检查

```
GET /global/health

Response: { "healthy": true, "version": "1.1.29" }
```

#### 3.5.2 获取路径信息

```
GET /path

Response: {
  "home": "C:\\Users\\xxx",
  "state": "C:\\Users\\xxx\\.local\\state\\opencode",
  "config": "C:\\Users\\xxx\\.config\\opencode",
  "worktree": "C:\\path\\to\\worktree",
  "directory": "C:\\path\\to\\project"
}
```

#### 3.5.3 列出可用工具

```
GET /experimental/tool?provider=anthropic&model=claude-sonnet-4-20250514

Response: [
  {
    "id": "bash",
    "description": "Execute shell commands",
    "parameters": {
      "type": "object",
      "properties": {
        "command": {"type": "string"}
      }
    }
  }
]
```

#### 3.5.4 列出 Agent

```
GET /agent

Response: Agent.Info[]
[
  {
    "name": "general",
    "description": "General purpose agent",
    "tools": ["bash", "read", "write", "edit"]
  }
]
```

#### 3.5.5 列出技能

```
GET /skill

Response: Skill.Info[]
```

### 3.6 事件订阅 API

#### 3.6.1 会话事件

```
GET /event

Response (SSE):
data: {"type": "session.created", "properties": {"info": {...}}}
data: {"type": "message.updated", "properties": {"info": {...}}}
data: {"type": "message.part.updated", "properties": {"part": {...}, "delta": "..."}}
data: {"type": "server.heartbeat", "properties": {}}
```

#### 3.6.2 全局事件

```
GET /global/event

Response (SSE):
data: {"type": "server.connected", "properties": {}}
data: {"directory": "C:\\path", "payload": {"type": "...", "properties": {}}}
```

### 3.7 权限管理 API

#### 3.7.1 获取待处理权限

```
GET /permission

Response: PermissionNext.Request[]
[
  {
    "id": "perm_xxxx",
    "sessionID": "sess_xxxx",
    "tool": "bash",
    "args": {"command": "rm -rf"},
    "time": {"created": 1710000000000}
  }
]
```

#### 3.7.2 回复权限请求

```
POST /permission/:requestID/reply
Content-Type: application/json

Request Body:
{
  "reply": "once",      # "once" | "always" | "reject"
  "message": "批准原因"  # 可选
}

Response: boolean
```

### 3.8 问题管理 API

#### 3.8.1 获取待处理问题

```
GET /question

Response: Question.Request[]
```

#### 3.8.2 回复问题

```
POST /question/:requestID/reply
Content-Type: application/json

Request Body:
{
  "answers": [["选项1", "选项2"]]  # 嵌套数组
}

Response: boolean
```

#### 3.8.3 拒绝问题

```
POST /question/:requestID/reject

Response: boolean
```
