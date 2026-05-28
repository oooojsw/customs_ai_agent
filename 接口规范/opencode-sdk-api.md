# OpenCode SDK API 完整参考

> 基于 `@opencode-ai/sdk` v2 和 `@opencode-ai/plugin` 类型定义逆向工程
> 生成时间: 2026-03-19

## 目录

1. [架构概览](#1-架构概览)
2. [Plugin 接口系统](#2-plugin-接口系统)
3. [SDK Client API 完整列表](#3-sdk-client-api-完整列表)
4. [事件系统（SSE）](#4-事件系统sse)
5. [oh-my-opencode 的调用方式](#5-oh-my-opencode-的调用方式)
6. [其他 Agent 构造能否调用](#6-其他-agent-构造能否调用)

---

## 1. 架构概览

```
OpenCode Server (HTTP/WebSocket)
    │
    ├── CLI (opencode run / opencode serve)
    │
    ├── TUI (Terminal UI)
    │
    └── Plugin System ← oh-my-opencode 在这里
            │
            ├── PluginInput.client  ← createOpencodeClient() 返回的 SDK 客户端
            ├── PluginInput.project ← 当前项目信息
            ├── PluginInput.directory ← 工作目录
            │
            └── Hooks (回调函数)
                ├── event          ← 监听所有 OpenCode 事件
                ├── chat.message   ← 用户发送消息时
                ├── chat.params    ← 修改 LLM 参数
                ├── tool.execute.before/after ← 工具执行前后
                └── ...
```

**核心关系**：
- OpenCode 是一个 **服务器进程**，监听 HTTP 端口
- Plugin 通过 `createOpencodeClient()` 创建一个 **HTTP 客户端** 连接到该服务器
- SDK Client 提供了对服务器所有功能的 TypeScript 类型安全访问
- Plugin 还可以通过 Hooks **拦截和修改** OpenCode 的行为

---

## 2. Plugin 接口系统

### 2.1 Plugin 入口签名

```typescript
// @opencode-ai/plugin 类型定义
type Plugin = (input: PluginInput) => Promise<Hooks>;

type PluginInput = {
  client: ReturnType<typeof createOpencodeClient>;  // SDK 客户端
  project: Project;                                  // 当前项目
  directory: string;                                 // 工作目录
  worktree: string;                                  // worktree 根目录
  serverUrl: URL;                                    // OpenCode 服务器 URL
  $: BunShell;                                       // Bun Shell 工具
};
```

### 2.2 Hooks 列表（插件可拦截的事件）

| Hook | 触发时机 | 可修改字段 |
|------|---------|-----------|
| `event` | 任何 OpenCode 事件发生 | 无（只读通知） |
| `config` | 配置加载时 | 配置对象 |
| `tool` | 注册自定义工具 | 工具定义 |
| `auth` | 认证流程 | 认证结果 |
| `chat.message` | 用户发送消息 | 消息内容、Part |
| `chat.params` | 调用 LLM 前 | temperature, topP, topK, options |
| `chat.headers` | 调用 LLM 前 | HTTP headers |
| `permission.ask` | AI 请求权限 | 权限结果 (ask/deny/allow) |
| `command.execute.before` | 执行命令前 | 命令 Part |
| `tool.execute.before` | 工具执行前 | 工具参数 |
| `tool.execute.after` | 工具执行后 | 工具输出、元数据 |
| `shell.env` | Shell 执行前 | 环境变量 |
| `experimental.chat.messages.transform` | 发送给 LLM 前 | 消息列表 |
| `experimental.chat.system.transform` | System Prompt 变换 | System 内容 |
| `experimental.session.compacting` | 会话压缩前 | 压缩 Prompt |
| `experimental.text.complete` | 文本补全 | 补全文本 |
| `tool.definition` | 工具定义发送给 LLM 前 | 描述、参数 |

### 2.3 PluginContext（oh-my-opencode 包装后的类型）

```typescript
// oh-my-opencode/src/plugin/types.ts
type PluginContext = Parameters<Plugin>[0];  // 等同于 PluginInput
```

---

## 3. SDK Client API 完整列表

`createOpencodeClient()` 返回一个 `OpencodeClient` 实例，包含以下命名空间：

### 3.1 Session（会话管理）— 最核心

```typescript
client.session.list(params?)                    // 列出所有会话
client.session.create(params?)                  // 创建新会话
client.session.get(params)                      // 获取会话详情
client.session.update(params)                   // 更新会话（标题等）
client.session.delete(params)                   // 删除会话
client.session.status(params?)                  // 获取所有会话状态
client.session.children(params)                 // 获取子会话
client.session.todo(params)                     // 获取会话 Todo 列表
client.session.init(params)                     // 初始化会话（生成 AGENTS.md）
client.session.fork(params)                     // 分叉会话
client.session.abort(params)                    // 中止会话
client.session.messages(params)                 // 获取会话消息
client.session.message(params)                  // 获取单条消息
client.session.prompt(params)                   // 发送消息（同步等待）
client.session.promptAsync(params)              // 发送消息（异步，不等待）
client.session.command(params)                  // 发送命令
client.session.shell(params)                    // 执行 Shell 命令
client.session.diff(params)                     // 获取文件 Diff
client.session.summarize(params)                // 生成会话摘要
client.session.deleteMessage(params)            // 删除消息
client.session.revert(params)                   // 回滚消息
client.session.unrevert(params)                 // 恢复回滚
client.session.share(params)                    // 分享会话
client.session.unshare(params)                  // 取消分享
```

**Session.create 参数**:
```typescript
{
  parentID?: string;        // 父会话 ID（用于子 Agent）
  title?: string;           // 会话标题
  permission?: PermissionRuleset;  // 权限规则
  directory?: string;       // 工作目录
  workspace?: string;       // Workspace ID
}
```

**Session.prompt 参数**（最常用）:
```typescript
{
  sessionID: string;
  agent?: string;           // 使用的 Agent
  model?: { providerID: string; modelID: string };  // 指定模型
  tools?: { [key: string]: boolean };  // 启用/禁用工具
  system?: string;          // System Prompt
  variant?: string;         // 模型变体
  parts: Array<TextPartInput | FilePartInput | AgentPartInput | SubtaskPartInput>;
  noReply?: boolean;        // 不等待回复
  format?: OutputFormat;    // 输出格式（text / json_schema）
}
```

**Session.promptAsync**：与 `prompt` 相同参数，但立即返回，不等待 AI 响应完成。

### 3.2 Event（事件订阅）

```typescript
client.event.subscribe(params?)  // SSE 事件流
```

**返回值**：
```typescript
{
  stream: AsyncIterable<{ event: Event }>;  // SSE 事件流
}
```

### 3.3 File（文件操作）

```typescript
client.file.list(params)     // 列出目录内容
client.file.read(params)     // 读取文件内容
client.file.status(params?)  // 获取 Git 文件状态
```

### 3.4 Find（搜索）

```typescript
client.find.text(params)     // 正则搜索文本（ripgrep）
client.find.files(params)    // 按名称搜索文件
client.find.symbols(params)  // LSP 符号搜索
```

### 3.5 Config（配置）

```typescript
client.config.get(params?)           // 获取项目配置
client.config.update(params?)        // 更新项目配置
client.config.providers(params?)     // 列出已配置的 Provider

client.global.config.get()           // 获取全局配置
client.global.config.update(config)  // 更新全局配置
```

### 3.6 Provider（AI Provider 管理）

```typescript
client.provider.list(params?)   // 列出所有 Provider
client.provider.auth(params?)   // 获取 Provider 认证方法

client.provider.oauth.authorize(params)  // OAuth 授权
client.provider.oauth.callback(params)   // OAuth 回调
```

### 3.7 Auth（认证管理）

```typescript
client.auth.set(params)    // 设置 Provider 认证
client.auth.remove(params) // 移除 Provider 认证
```

### 3.8 MCP（Model Context Protocol）

```typescript
client.mcp.status(params?)  // MCP 服务器状态
client.mcp.add(params?)     // 添加 MCP 服务器
client.mcp.connect(params)  // 连接 MCP 服务器
client.mcp.disconnect(params) // 断开 MCP 服务器

client.mcp.auth.start(params)     // MCP OAuth 开始
client.mcp.auth.callback(params)  // MCP OAuth 回调
client.mcp.auth.authenticate(params) // MCP OAuth 完整流程
client.mcp.auth.remove(params)    // 移除 MCP 认证
```

### 3.9 Permission（权限管理）

```typescript
client.permission.list(params?)           // 列出待处理权限
client.permission.reply(params)           // 回复权限请求
client.permission.respond(params)         // 回复权限（已废弃）
```

### 3.10 Question（问题交互）

```typescript
client.question.list(params?)   // 列出待处理问题
client.question.reply(params)   // 回复问题
client.question.reject(params)  // 拒绝问题
```

### 3.11 Part（消息 Part 管理）

```typescript
client.part.update(params)  // 更新 Part
client.part.delete(params)  // 删除 Part
```

### 3.12 Tool（工具查询）

```typescript
client.tool.ids(params?)   // 列出所有工具 ID
client.tool.list(params)   // 列出工具详情（含 JSON Schema）
```

### 3.13 Project（项目管理）

```typescript
client.project.list(params?)    // 列出所有项目
client.project.current(params?) // 获取当前项目
client.project.update(params)   // 更新项目
client.project.initGit(params?) // 初始化 Git
```

### 3.14 Workspace（工作区）

```typescript
client.workspace.list(params?)    // 列出工作区
client.workspace.create(params?)  // 创建工作区
client.workspace.remove(params)   // 删除工作区
```

### 3.15 PTY（伪终端）

```typescript
client.pty.list(params?)    // 列出 PTY 会话
client.pty.create(params?)  // 创建 PTY
client.pty.get(params)      // 获取 PTY 详情
client.pty.update(params)   // 更新 PTY
client.pty.connect(params)  // WebSocket 连接 PTY
client.pty.remove(params)   // 删除 PTY
```

### 3.16 TUI（终端界面控制）

```typescript
client.tui.appendPrompt(params?)     // 追加 Prompt
client.tui.submitPrompt(params?)     // 提交 Prompt
client.tui.clearPrompt(params?)      // 清除 Prompt
client.tui.executeCommand(params?)   // 执行命令
client.tui.showToast(params?)        // 显示 Toast
client.tui.publish(params?)          // 发布 TUI 事件
client.tui.selectSession(params?)    // 选择会话
client.tui.openHelp(params?)         // 打开帮助
client.tui.openSessions(params?)     // 打开会话列表
client.tui.openThemes(params?)       // 打开主题
client.tui.openModels(params?)       // 打开模型列表
```

### 3.17 其他

```typescript
client.global.health()         // 健康检查
client.global.event()          // 全局事件流
client.global.dispose()        // 销毁实例
client.instance.dispose()      // 销毁当前实例
client.path.get()              // 获取路径信息
client.vcs.get()               // 获取 VCS 信息（Git 分支等）
client.command.list()          // 列出所有命令
client.lsp.status()            // LSP 状态
client.formatter.status()      // Formatter 状态
client.app.log()               // 写日志
client.app.agents()            // 列出所有 Agent
client.app.skills()            // 列出所有 Skill
```

---

## 4. 事件系统（SSE）

### 4.1 订阅方式

```typescript
const { stream } = await client.event.subscribe({
  query: { directory: "/path/to/project" }
});

for await (const { event } of stream) {
  console.log(event.type, event.properties);
}
```

### 4.2 完整事件类型列表

| 事件类型 | 说明 | properties |
|---------|------|-----------|
| `session.created` | 会话创建 | `info: Session` |
| `session.updated` | 会话更新 | `info: Session` |
| `session.deleted` | 会话删除 | `info: Session` |
| `session.status` | 会话状态变化 | `sessionID, status: {type: "idle"\|"busy"\|"retry"}` |
| `session.idle` | 会话空闲 | `sessionID` |
| `session.error` | 会话错误 | `sessionID, error` |
| `session.diff` | 会话文件变化 | `sessionID, diff: FileDiff[]` |
| `session.compacted` | 会话压缩 | `sessionID` |
| `message.updated` | 消息更新 | `info: Message` |
| `message.removed` | 消息删除 | `sessionID, messageID` |
| `message.part.updated` | Part 更新 | `part: Part` |
| `message.part.delta` | Part 增量更新 | `sessionID, messageID, partID, field, delta` |
| `message.part.removed` | Part 删除 | `sessionID, messageID, partID` |
| `permission.asked` | 权限请求 | `PermissionRequest` |
| `permission.replied` | 权限回复 | `sessionID, requestID, reply` |
| `question.asked` | 问题请求 | `QuestionRequest` |
| `question.replied` | 问题回复 | `sessionID, requestID, answers` |
| `question.rejected` | 问题拒绝 | `sessionID, requestID` |
| `todo.updated` | Todo 更新 | `sessionID, todos: Todo[]` |
| `file.edited` | 文件编辑 | `file` |
| `file.watcher.updated` | 文件监视器 | `file, event: "add"\|"change"\|"unlink"` |
| `vcs.branch.updated` | Git 分支变化 | `branch` |
| `command.executed` | 命令执行 | `name, sessionID, arguments, messageID` |
| `mcp.tools.changed` | MCP 工具变化 | `server` |
| `lsp.client.diagnostics` | LSP 诊断 | `serverID, path` |
| `lsp.updated` | LSP 更新 | — |
| `pty.created` | PTY 创建 | `info: Pty` |
| `pty.updated` | PTY 更新 | `info: Pty` |
| `pty.exited` | PTY 退出 | `id, exitCode` |
| `pty.deleted` | PTY 删除 | `id` |
| `workspace.ready` | Workspace 就绪 | `name` |
| `workspace.failed` | Workspace 失败 | `message` |
| `worktree.ready` | Worktree 就绪 | `name, branch` |
| `worktree.failed` | Worktree 失败 | `message` |
| `installation.updated` | 安装更新 | `version` |
| `installation.update-available` | 有新版本 | `version` |
| `project.updated` | 项目更新 | `Project` |
| `server.connected` | 服务器连接 | — |
| `server.instance.disposed` | 实例销毁 | `directory` |
| `global.disposed` | 全局销毁 | — |
| `tui.prompt.append` | TUI Prompt 追加 | `text` |
| `tui.command.execute` | TUI 命令执行 | `command` |
| `tui.toast.show` | TUI Toast | `title, message, variant, duration` |
| `tui.session.select` | TUI 选择会话 | `sessionID` |
| `mcp.browser.open.failed` | MCP 浏览器打开失败 | `mcpName, url` |

### 4.3 事件流转（oh-my-opencode 的处理）

```typescript
// event.ts 中的处理流程：
1. 接收 SSE 事件
2. 分发给所有注册的 Hooks（20+ 个）
3. 特殊处理：
   - session.created → 设置主会话、初始化 Tmux
   - session.deleted → 清理状态、断开 MCP
   - session.idle → 触发 Ralph Loop、Todo Continuation
   - message.updated → 模型错误回退
   - session.error → Session Recovery、模型回退
```

---

## 5. oh-my-opencode 的调用方式

### 5.1 Plugin 入口

```typescript
// src/index.ts
const OhMyOpenCodePlugin: Plugin = async (ctx) => {
  // ctx 就是 PluginInput，包含 client、project、directory 等

  const pluginConfig = loadPluginConfig(ctx.directory, { command: "default" });
  const managers = createManagers(ctx, pluginConfig);
  const hooks = createHooks(ctx, pluginConfig, managers);
  const tools = createTools(ctx, pluginConfig, managers, hooks);

  return createPluginInterface({ ctx, pluginConfig, managers, hooks, tools });
};
```

### 5.2 Session 创建（子 Agent 调用）

```typescript
// src/tools/call-omo-agent/session-creator.ts
async function createOrGetSession(args, toolContext, ctx: PluginInput) {
  // 方式1：获取现有会话
  const sessionResult = await ctx.client.session.get({
    path: { id: args.session_id },
  });

  // 方式2：创建新会话（子会话）
  const createResult = await ctx.client.session.create({
    body: {
      parentID: toolContext.sessionID,  // 设置父会话
      title: `${args.description} (@${args.subagent_type} subagent)`,
    },
    query: { directory: parentDirectory },
  });

  return { sessionID: createResult.data.id, isNew: true };
}
```

### 5.3 发送 Prompt（同步等待结果）

```typescript
// src/tools/call-omo-agent/sync-executor.ts
// 通过 session.promptAsync 发送消息
await ctx.client.session.promptAsync({
  path: { id: sessionID },
  body: {
    agent: resolvedAgent,
    ...(resolvedModel ? { model: resolvedModel } : {}),
    tools: { question: false },
    parts: [{ type: "text", text: message }],
  },
  query: { directory },
});

// 然后轮询等待完成
const statusResult = await ctx.client.session.status();
const messagesCheck = await ctx.client.session.messages({ path: { id: sessionID } });
```

### 5.4 后台任务（异步执行）

```typescript
// src/features/background-agent/spawner.ts
// 创建会话后 fire-and-forget
client.session.promptAsync({
  path: { id: sessionID },
  body: {
    agent: input.agent,
    ...(launchModel ? { model: launchModel } : {}),
    tools: { task: false, call_omo_agent: true, question: false },
    parts: [createInternalAgentTextPart(input.prompt)],
  },
});
```

### 5.5 事件订阅

```typescript
// src/cli/run/runner.ts
const events = await client.event.subscribe({ query: { directory } });
const eventProcessor = processEvents(ctx, events.stream, eventState);
```

### 5.6 Ralph Loop 继续注入

```typescript
// src/hooks/ralph-loop/continuation-prompt-injector.ts
// 当 Session 空闲时，通过 promptAsync 注入继续消息
await pluginContext.client.session.promptAsync({
  path: { id: sessionID },
  body: { parts: [{ type: "text", text: "continue" }] },
  query: { directory: pluginContext.directory },
});
```

### 5.7 模型回退（中止 + 重试）

```typescript
// src/plugin/event.ts
// 1. 中止当前会话
await client.session.abort({ path: { id: sessionID } });

// 2. 发送 "continue" 触发模型回退
await client.session.promptAsync({
  path: { id: sessionID },
  body: { parts: [{ type: "text", text: "continue" }] },
  query: { directory },
});
```

---

## 6. 其他 Agent 构造能否调用

### 6.1 直接结论：可以

**OpenCode SDK API 是 OpenCode 服务器暴露的标准 HTTP API**。任何能连接到该服务器的客户端都可以调用。

### 6.2 调用方式

#### 方式 1：通过 Plugin Hook（推荐）

任何实现了 Plugin 接口的插件都可以获得 `client`：

```typescript
const myPlugin: Plugin = async (ctx: PluginInput) => {
  // ctx.client 就是完整的 SDK 客户端
  const sessions = await ctx.client.session.list();
  const { stream } = await ctx.client.event.subscribe();

  return { /* hooks */ };
};
```

#### 方式 2：直接创建 SDK 客户端

```typescript
import { createOpencodeClient } from "@opencode-ai/sdk";

// 连接到本地 OpenCode 服务器
const client = createOpencodeClient({
  directory: "/path/to/project",
});

// 直接调用 API
const sessions = await client.session.list();
await client.session.prompt({
  sessionID: "xxx",
  parts: [{ type: "text", text: "hello" }],
});
```

#### 方式 3：通过 HTTP 请求

OpenCode 服务器是一个标准的 HTTP API：

```bash
# 列出会话
curl http://localhost:3000/session

# 创建会话
curl -X POST http://localhost:3000/session \
  -H "Content-Type: application/json" \
  -d '{"title": "My Session"}'

# 发送消息
curl -X POST http://localhost:3000/session/{id}/prompt \
  -H "Content-Type: application/json" \
  -d '{"parts": [{"type": "text", "text": "hello"}]}'

# 订阅事件（SSE）
curl http://localhost:3000/event
```

### 6.3 限制和注意事项

| 限制 | 说明 |
|------|------|
| **需要连接到服务器** | SDK 客户端需要知道 OpenCode 服务器的地址和端口 |
| **认证** | 部分操作可能需要认证（OAuth Token） |
| **权限** | Plugin 的权限由配置决定，某些操作可能被 `permission` 配置阻止 |
| **会话隔离** | 子会话（subagent）有独立的上下文，不会污染主会话 |
| **并发限制** | 后台任务有并发限制（默认 5 个/模型） |

### 6.4 与其他 Agent 框架的对比

| 能力 | OpenCode SDK | Claude Code SDK | LangChain |
|------|-------------|-----------------|-----------|
| Session 管理 | 完整 CRUD | 受限 | 需自建 |
| 事件订阅 | SSE 实时 | Polling | 回调 |
| 子 Agent | 内置支持 | 需手动实现 | 需手动实现 |
| 工具系统 | 插件注册 | 固定 | 灵活 |
| 多模型 | 内置 | 仅 Claude | 需配置 |
| 权限系统 | 细粒度 | 受限 | 无 |

### 6.5 如果你想构造自己的 Agent

```typescript
// 示例：创建一个监控 Agent，监听所有会话事件
import { createOpencodeClient } from "@opencode-ai/sdk";

const client = createOpencodeClient({ directory: process.cwd() });

// 1. 订阅事件
const { stream } = await client.event.subscribe();

// 2. 监听特定事件
for await (const { event, directory } of stream) {
  if (event.type === "session.error") {
    // 处理错误...
  }

  if (event.type === "session.idle") {
    // 检查是否需要继续...
    const todos = await client.session.todo({
      sessionID: event.properties.sessionID,
    });

    if (todos.data?.some(t => t.status === "pending")) {
      // 注入继续消息
      await client.session.promptAsync({
        sessionID: event.properties.sessionID,
        parts: [{ type: "text", text: "继续处理未完成的 Todo" }],
      });
    }
  }
}
```

---

## 附录：类型定义摘要

### Part 类型

```typescript
type Part =
  | TextPart          // 文本
  | SubtaskPart       // 子任务
  | ReasoningPart     // 推理过程
  | FilePart          // 文件
  | ToolPart          // 工具调用
  | StepStartPart     // 步骤开始
  | StepFinishPart    // 步骤结束
  | SnapshotPart      // 快照
  | PatchPart         // 补丁
  | AgentPart         // Agent 引用
  | RetryPart         // 重试
  | CompactionPart;   // 压缩
```

### Message 类型

```typescript
type Message = UserMessage | AssistantMessage;

type UserMessage = {
  id: string;
  sessionID: string;
  role: "user";
  agent: string;
  model: { providerID: string; modelID: string };
  // ...
};

type AssistantMessage = {
  id: string;
  sessionID: string;
  role: "assistant";
  agent: string;
  modelID: string;
  providerID: string;
  error?: Error;  // 可能有错误
  tokens: { input: number; output: number; reasoning: number; cache: {...} };
  cost: number;
  // ...
};
```

### Session 类型

```typescript
type Session = {
  id: string;
  slug: string;
  projectID: string;
  directory: string;
  parentID?: string;        // 父会话
  title: string;
  version: string;
  time: { created: number; updated: number; archived?: number };
  permission?: PermissionRuleset;
  share?: { url: string };
  summary?: { additions: number; deletions: number; files: number; diffs: FileDiff[] };
};
```

---

## 关键文件位置

| 文件 | 说明 |
|------|------|
| `.opencode/node_modules/@opencode-ai/sdk/dist/v2/client.d.ts` | SDK Client 入口 |
| `.opencode/node_modules/@opencode-ai/sdk/dist/v2/gen/sdk.gen.d.ts` | SDK 完整 API 定义 |
| `.opencode/node_modules/@opencode-ai/sdk/dist/v2/gen/types.gen.d.ts` | SDK 类型定义 |
| `.opencode/node_modules/@opencode-ai/plugin/dist/index.d.ts` | Plugin 接口定义 |
| `.opencode/node_modules/@opencode-ai/plugin/dist/tool.d.ts` | Tool 定义 |
| `src/plugin-interface.ts` | oh-my-opencode 的 Plugin 实现 |
| `src/plugin/event.ts` | 事件处理器（最复杂的 Hook） |
| `src/tools/call-omo-agent/session-creator.ts` | Session 创建示例 |
| `src/features/background-agent/spawner.ts` | 后台任务示例 |
| `src/cli/run/runner.ts` | CLI 运行器示例 |
