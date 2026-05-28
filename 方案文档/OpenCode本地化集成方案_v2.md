# OpenCode本地化集成方案\_v2

**版本**：v2.0  
**日期**：2026年3月  
**状态**：正式版

---

## 1. 概述

本文档详细描述了将OpenCode AI编码引擎集成到海关智能Agent系统（Customs AI Agent）的技术方案。通过此次集成，海关智能Agent系统将能够借助OpenCode强大的代码分析和工具调用能力，实现更智能的报关单智能审计、法规查询、文档生成等功能。

### 1.1 集成目标

本次集成的核心目标包括以下几个方面。首先，需要实现OpenCode HTTP Server的无缝接入，使海关Agent能够通过RESTful API与OpenCode进行通信。其次，要构建基于MCP（Model Context Protocol）的桥接层，使海关Agent能够调用OpenCode提供的各类MCP工具。第三，要实现流式响应的完整支持，确保用户能够实时获取AI处理进度和中间结果。第四，需要整合OpenCode的权限控制系统，在保障安全的前提下支持灵活的权限配置。最后，要建立完整的错误处理和重试机制，确保系统在各种异常情况下能够稳定运行。

### 1.2 集成范围

本次集成工作涵盖以下范围：OpenCode Server的部署和配置、HTTP API客户端的开发、MCP Bridge服务的构建、认证和安全机制的实现、流式事件处理系统的搭建、以及与现有海关Agent系统的深度整合。

### 1.3 术语说明

为避免歧义，本文采用以下术语定义。OpenCode指的是源代码项目（位于C:\Users\ZhuanZ\Desktop\opencode re\opencode - copy）。海关Agent或目标系统指的是待集成的目标项目（位于C:\Users\ZhuanZ\Desktop\Customs\auto Customs\001-customs_ai_agent - 1211 - 1215last stream try -）。HTTP Server指的是OpenCode的服务端组件，通过HTTP协议提供API接口。MCP Bridge是连接海关Agent与OpenCode MCP工具的桥接服务。

---

## 2. 项目分析

### 2.1 OpenCode项目分析

#### 2.1.1 项目架构

OpenCode是一个功能强大的AI编码引擎，采用现代化的架构设计。项目使用Bun作为运行时和包管理器，支持TypeScript原生执行。项目结构清晰，核心代码位于packages/opencode目录下，CLI入口位于packages/opencode/bin/opencode。

项目的主要组件包括TUI（交互式终端界面）和HTTP Server两部分。TUI通过bun run dev命令启动，提供交互式的命令行体验。HTTP Server通过CLI子命令serve启动，提供无头（Headless）模式的HTTP API服务。

#### 2.1.2 启动方式

OpenCode提供多种启动方式，具体如下。

开发调试模式使用命令bun run dev，该命令启动TUI交互界面，适用于本地开发和调试。

服务器模式是本次集成的核心启动方式。正确的启动命令为：bun run --conditions=browser ./src/index.ts serve --port 4096 --hostname 127.0.0.1。

需要特别注意的是，opencode serve本身并不是一个独立的命令，而需要通过Bun运行器执行src/index.ts并传入serve参数。另外，项目中的二进制文件oh-my-opencode.exe是一个独立的可执行文件，它能够自行启动完整的HTTP Server，这为部署提供了便利条件。

#### 2.1.3 网络配置

OpenCode HTTP Server的网络配置通过命令行参数和环境变量进行控制。端口配置使用--port参数，默认值为0（尝试4096端口，失败后随机分配）。主机配置使用--hostname参数，默认值为127.0.0.1（仅监听本地连接）。其他网络选项包括--mdns用于启用mDNS发现（默认关闭），以及--cors用于配置额外的CORS允许域名。

#### 2.1.4 认证机制

HTTP Server提供HTTP Basic Authentication支持。认证配置完全通过环境变量实现：OPENCODE_SERVER_PASSWORD用于设置密码，OPENCODE_SERVER_USERNAME用于设置用户名（默认为opencode）。

#### 2.1.5 工作目录机制

OpenCode支持灵活的请求级工作目录配置。用户可以通过directory查询参数或在请求头中设置x-opencode-directory来指定每个请求的工作目录。这对于多租户场景或需要隔离工作目录的应用非常有用。

#### 2.1.6 配置文件

OpenCode支持多种配置方式。项目级配置文件通过OPENCODE_CONFIG环境变量指定路径。配置内容可以直接通过OPENCODE_CONFIG_CONTENT环境变量以JSONC格式传入。额外的配置目录可以通过OPENCODE_CONFIG_DIR指定。项目级配置可以被OPENCODE_DISABLE_PROJECT_CONFIG环境变量禁用。

#### 2.1.7 实验性功能

OpenCode提供多个实验性功能，可通过OPENCODE_EXPERIMENTAL环境变量启用。Worktree功能支持创建隔离的Git Worktree。MCP相关功能提供增强的工具调用能力。

### 2.2 海关Agent项目分析

#### 2.2.1 项目架构

海关智能Agent系统是一个基于Python FastAPI构建的智能系统，采用LangChain/LangGraph作为AI推理框架。项目的主要入口文件为src/main.py，负责FastAPI的生命周期管理。API路由定义在src/api/routes.py中，该文件长达1645行，包含了系统的主要API端点。

系统的核心服务组件包括以下几个。CustomsChatAgent（src/services/chat_agent.py，1228行）是主要的对话代理，基于LangGraph ReAct模式实现。MCPBridge（src/services/mcp_bridge.py，369行）是MCP协议桥接器，管理MCP服务器的连接和通信。KnowledgeBase（src/services/knowledge_base.py，746行）提供海关法规知识库检索功能。ReportAgent（src/services/report_agent.py，1082行）负责生成合规报告。

#### 2.2.2 三大核心功能

系统提供三大核心功能模块。

智能审计功能（POST /api/v1/audit/analyze）实现基于五个维度的风险分析，能够自动识别报关单中的潜在风险点并给出评分和建议。

专家咨询功能（POST /api/v1/chat/stream）提供基于RAG增强的对话服务，支持流式响应，用户可以实时获取AI的推理过程和分析结果。

智能报告功能（POST /api/v1/report/generate）能够自动生成符合海关要求的合规报告，支持多种导出格式。

#### 2.2.3 对话代理架构

CustomsChatAgent采用LangGraph ReAct Agent架构，这是当前主流的AI Agent设计模式之一。Agent配备了丰富的工具集，包括audit_declaration（报关单审计）、search_customs_regulations（法规查询）、use_skill（使用技能）、read_skill_resource（读取技能资源）、list_skill_resources（列出技能资源）、run_skill_script（运行技能脚本）、generate_compliance_report（生成合规报告）、export_document_file（导出文档）、read_report_buffer（读取报告缓冲）等工具。

系统采用astream_events v2 API实现实时流式输出，支持SSE（Server-Sent Events）协议，能够将AI的思考过程和中间结果实时推送给客户端。

#### 2.2.4 MCP桥接架构

MCPBridge是连接海关Agent与外部MCP工具的关键组件。其架构设计包括两个核心类：MCPBridge负责管理单个MCP服务器的生命周期，通过标准输入输出（stdio）与MCP服务器通信；MCPBridgeManager负责管理多个MCP Bridge实例，提供统一的工具调用接口。

MCP Bridge的主要功能包括：将MCP工具转换为LangChain的StructuredTool格式，支持结构化参数传递；实现JSON Schema到Pydantic模型的自动转换，降低工具定义复杂度；提供工具调用的错误处理和重试机制。

#### 2.2.5 当前MCP配置

系统当前的MCP配置位于data/mcp_servers.json文件。配置内容包括：MCP服务器列表，目前仅配置了filesystem服务器；每个服务器的配置项包括名称、启用状态、描述、命令和参数；全局配置包括自动启动、超时时间、重试次数等参数。

filesystem服务器提供文件系统访问能力，工具包括read_file（读取文件）、read_text_file（读取文本文件）、write_file（写入文件）、list_directory（列出目录）、search_files（搜索文件）等。

#### 2.2.6 依赖环境

项目依赖的Python包包括：Web框架fastapi和uvicorn；AI框架langchain系列包；HTTP客户端httpx、aiohttp、requests；向量数据库faiss-cpu和sentence-transformers；文档处理pypdfium2、rapidocr_onnxruntime、pymupdf、marker-pdf；MCP协议sdk（mcp包）；二进制可执行文件oh-my-opencode-windows-x64。

---

## 3. 修正后的API端点详解

### 3.1 重要更正说明

经过深入研究，我们发现原集成方案中存在多处错误。以下是主要修正内容。

服务器启动命令的修正：原方案假设可以使用bun run serve或opencode serve命令启动服务器。实际上，正确的启动命令为：bun run --conditions=browser ./src/index.ts serve --port 4096 --hostname 127.0.0.1。oh-my-opencode.exe是独立可执行文件，可直接运行。

API路径的修正：原方案中的API路径存在多处错误，修正后的路径体系如下。

会话操作相关路径：创建会话使用POST /session；获取会话列表使用GET /session；获取会话状态使用GET /session/status；获取单个会话使用GET /session/:sessionID；获取子会话使用GET /session/:sessionID/children；获取待办事项使用GET /session/:sessionID/todo；删除会话使用DELETE /session/:sessionID；更新会话使用PATCH /session/:sessionID；初始化会话使用POST /session/:sessionID/init；派生会话使用POST /session/:sessionID/fork；中断会话使用POST /session/:sessionID/abort；分享会话使用POST /session/:sessionID/share；取消分享使用DELETE /session/:sessionID/share；总结会话使用POST /session/:sessionID/summarize。

消息操作相关路径：发送消息（流式）使用POST /session/:sessionID/message；异步发送消息（无回复）使用POST /session/:sessionID/prompt_async；执行命令使用POST /session/:sessionID/command；执行Shell命令使用POST /session/:sessionID/shell；撤销操作使用POST /session/:sessionID/revert；重做操作使用POST /session/:sessionID/unrevert；获取消息列表使用GET /session/:sessionID/message；获取单条消息使用GET /session/:sessionID/message/:messageID；更新消息片段使用PATCH /session/:sessionID/message/:messageID/part/:partID；删除消息片段使用DELETE /session/:sessionID/message/:messageID/part/:partID。

文件操作相关路径：搜索文件使用GET /find?pattern=...；搜索文件内容使用GET /find/file?query=...；获取文件信息使用GET /file?path=...；获取文件内容使用GET /file/content?path=...；获取文件状态使用GET /file/status。

全局路由相关路径：健康检查使用GET /global/health；事件流使用GET /global/event（SSE协议）。

根级端点相关路径：事件流使用GET /event（SSE协议）；获取路径信息使用GET /path；获取版本控制信息使用GET /vcs；获取命令列表使用GET /command；日志记录使用POST /log；获取Agent信息使用GET /agent；获取Skill信息使用GET /skill；获取LSP状态使用GET /lsp。

### 3.2 会话创建详解

创建新会话的API规范如下。

端点：POST /session

请求体（可选）：

```json
{
  "parentID": "string (可选, 父会话ID)",
  "title": "string (可选, 会话标题)",
  "permission": "PermissionNext.Ruleset (可选, 权限规则)"
}
```

响应：Session.Info对象

说明：parentID用于创建子会话或会话分支；title用于给会话起一个描述性名称，便于后续管理；permission用于设置该会话的权限规则，控制Agent可以执行的操作。

### 3.3 消息发送详解

发送消息是OpenCode API最核心的功能之一，支持流式响应。

端点：POST /session/:sessionID/message

请求体（PromptInput格式）：

```json
{
  "sessionID": "string (必填)",
  "messageID": "string (可选, 回复指定消息)",
  "model": {
    "providerID": "string",
    "modelID": "string"
  },
  "agent": "string (可选, 指定Agent类型)",
  "noReply": "boolean (可选, 是否需要回复)",
  "system": "string (可选, 系统提示词覆盖)",
  "variant": "string (可选, 变体类型)",
  "parts": [
    {
      "type": "text",
      "text": "string",
      "id": "string (可选)"
    },
    {
      "type": "file",
      "url": "string",
      "mime": "string",
      "filename": "string (可选)"
    },
    {
      "type": "agent",
      "name": "string"
    },
    {
      "type": "subtask",
      "prompt": "string",
      "description": "string",
      "agent": "string",
      "model": "object (可选)",
      "command": "string (可选)"
    }
  ]
}
```

响应（流式）：{info, parts}

说明：parts数组支持多种内容类型，可以组合文本、文件、Agent调用和子任务；使用流式响应时，服务器会实时推送处理进度和结果。

### 3.4 权限系统详解

OpenCode的权限系统通过PermissionNext.Ruleset进行配置。与原方案中的allow/deny列表不同，实际的权限系统采用更灵活的事件驱动模式。

权限配置可以通过环境变量OPENCODE_PERMISSION进行全局设置，也可以在创建会话时通过permission字段指定。权限相关的事件会通过SSE推送，客户端需要监听permission.asked事件并通过permission.replied事件响应。

### 3.5 SSE事件详解

OpenCode通过SSE（Server-Sent Events）提供实时事件推送。主要事件类型包括：

会话事件：session.created（新会话创建）、session.updated（会话更新）、session.deleted（会话删除）、session.diff（会话差异）、session.error（会话错误）。

消息事件：message.updated（消息更新）、message.removed（消息删除）、message.part.updated（消息片段更新）、message.part.removed（消息片段删除）。

终端事件：pty.created（终端创建）、pty.updated（终端输出）、pty.exited（终端退出）、pty.deleted（终端删除）。

交互事件：question.asked（提问）、question.replied（回答）、question.rejected（拒绝）。

权限事件：permission.asked（权限请求）、permission.replied（权限响应）。

系统事件：server.instance.disposed（实例释放）、server.connected（服务器连接）、server.heartbeat（心跳检测）。

### 3.6 配置与提供方

获取配置信息的端点为GET /config，响应包含系统当前配置详情。更新配置使用PATCH /config，接收部分配置更新。

获取模型提供方列表的端点为GET /config/providers，响应包含providers列表和default提供方信息。

### 3.7 MCP管理

获取所有MCP服务器状态的端点为GET /mcp，返回serverName到MCP.Status的映射。

配置MCP服务器的端点为POST /mcp，接收{name, config}格式的请求体。

连接MCP服务器的端点为POST /mcp/:name/connect。

断开MCP连接的端点为POST /mcp/:name/disconnect。

### 3.8 实验性功能

获取工具ID列表的端点为GET /experimental/tool/ids。

获取工具详情的端点为GET /experimental/tool?provider=...&model=...，返回工具定义列表。

工作树操作包括POST /experimental/worktree（创建）、GET /experimental/worktree（列表）、DELETE /experimental/worktree（删除）。

获取实验性资源的端点为GET /experimental/resource，返回各服务器的实验性资源列表。

### 3.9 其他根级端点

OpenAPI文档可在服务器运行时通过/doc端点访问，提供完整的API文档。

认证配置通过PUT /auth/:providerID进行。

实例释放通过POST /instance/dispose执行。

---

## 4. 集成架构设计

### 4.1 整体架构

本次集成采用分层架构设计，确保各组件之间解耦且易于维护。整体架构分为五个层次：应用层、桥接层、通信层、服务层、基础设施层。

应用层是海关Agent的核心业务逻辑，包括CustomsChatAgent、ReportAgent和KnowledgeBase等组件。这一层直接面向用户请求，提供智能审计、专家咨询和报告生成等功能。

桥接层是本次集成的核心新增组件，包括OpenCodeBridge和MCPToolsAdapter。OpenCodeBridge负责管理OpenCode Server的连接和会话；MCPToolsAdapter将OpenCode的MCP工具转换为海关Agent可用的格式。

通信层负责HTTP/SSE通信处理，包括HttpClient（HTTP请求客户端）、SSEClient（SSE事件监听客户端）和AuthManager（认证信息管理）。

服务层是OpenCode Server组件，运行在独立的进程中，通过HTTP API对外提供服务。

基础设施层包括网络配置、文件系统、日志系统等底层支持。

### 4.2 组件交互流程

当用户发起一个海关法规查询请求时，请求首先到达海关Agent的API层。CustomsChatAgent接收请求后，根据请求类型选择合适的工具进行处理。如果需要使用OpenCode的能力，Agent会调用OpenCodeBridge提供的接口。OpenCodeBridge通过HTTP客户端向OpenCode Server发送请求，Server处理完成后返回结果。如果涉及MCP工具调用，OpenCode会调用相应的MCP服务器并返回结果。整个过程中，SSE客户端会持续监听服务器推送的事件，实现实时进度更新。

### 4.3 会话管理策略

OpenCode的会话机制非常灵活，我们采用以下会话管理策略。

对于每个海关Agent会话（对应一个用户对话），我们会创建一个对应的OpenCode会话。这种一一对应的映射关系简化了状态管理。

会话的创建采用延迟策略，只有在真正需要使用OpenCode能力时才创建会话。会话的标题自动设置为与海关会话相关的描述，便于调试和管理。

会话的销毁采用显式管理，在海关会话结束时或超时后主动销毁OpenCode会话，释放资源。

对于需要使用OpenCode MCP工具的场景，我们会预先初始化MCP连接，确保工具调用的低延迟。

### 4.4 流式响应集成

OpenCode支持SSE协议的事件流，海关Agent通过astream_events v2 API消费这些事件。集成的关键点包括事件过滤（只处理与当前请求相关的事件）、进度提取（从事件中提取有用的进度信息）、错误处理（优雅处理连接中断和协议错误）、回退策略（在SSE不可用时降级为轮询模式）。

### 4.5 数据流设计

请求数据流的设计考虑了海关业务的特点。用户请求首先经过API网关进行基本校验，然后到达海关Agent的业务逻辑层。业务逻辑层根据请求类型构造PromptInput，其中可以包含文件引用（报关单图片、附件等）。PromptInput通过OpenCodeBridge发送到OpenCode Server。OpenCode处理请求时产生的中间结果（如文件内容提取、代码分析）会暂存在文件系统中，最终结果通过HTTP响应返回给桥接层。桥接层对结果进行解析和格式化，然后返回给业务逻辑层进行后续处理。

### 4.6 错误传播机制

OpenCode的错误会通过多种方式传播给调用方。API错误（如400、401、404、500等）会转换为对应的异常类型通过HTTP响应返回。运行时错误（如工具执行失败）会通过SSE的session.error事件推送。认证错误会触发permission相关的事件流，需要客户端响应。连接错误（如网络中断、Server宕机）会触发重连逻辑。

### 4.7 资源隔离策略

为了确保系统稳定性，我们采用以下资源隔离策略。每个OpenCode会话有独立的文件系统视图，通过directory参数隔离不同会话的访问范围。MCP工具调用有超时限制，防止单个工具占用过多时间。内存密集型操作有资源配额限制。日志和监控数据与业务数据分离存储。

---

## 5. 实施步骤

### 5.1 第一阶段：基础设施准备

#### 5.1.1 环境检查

在开始集成之前，需要确认以下环境条件。OpenCode项目需要Bun运行时（建议最新稳定版）。目标项目需要Python 3.10+环境及所有依赖包。系统需要能够访问OpenCode项目的源代码。

#### 5.1.2 依赖安装

在目标系统中安装OpenCode相关的npm包。确认oh-my-opencode-windows-x64已正确安装，其二进制文件位于node_modules/oh-my-opencode-windows-x64/bin/oh-my-opencode.exe。

#### 5.1.3 目录结构规划

规划OpenCode Server的数据存储目录。建议的目录结构包括：logs目录用于存储OpenCode Server的运行日志；config目录用于存储OpenCode配置文件；data目录用于存储会话数据；cache目录用于缓存临时文件。

### 5.2 第二阶段：OpenCode Server封装

#### 5.2.1 Server管理服务

开发OpenCodeServerManager类，负责OpenCode Server的启动、停止和监控。关键功能包括：start_server()方法启动Server进程，支持配置端口和主机；stop_server()方法优雅停止Server进程；is_running()方法检查Server状态；get_base_url()方法获取Server的访问地址；restart_server()方法在必要时重启Server。

#### 5.2.2 进程管理策略

Server进程管理采用以下策略。进程启动后进行健康检查，确认服务可用。定期进行心跳检测，发现异常时自动重启。支持手动重启和自动重启两种模式。优雅关闭时等待现有请求完成后再退出。

#### 5.2.3 配置管理

创建OpenCode Server的配置文件模板，包含端口、主机、认证等基本配置。实现配置的读取和更新接口。支持环境变量覆盖配置文件。

### 5.3 第三阶段：HTTP API客户端开发

#### 5.3.1 基础客户端

开发OpenCodeAPIClient类，封装所有HTTP API调用。该类应该具备以下特性：基于httpx异步HTTP客户端；自动处理认证信息；自动处理会话ID；支持重试机制；支持超时控制。

#### 5.3.2 会话管理

在OpenCodeAPIClient中实现会话管理功能。create_session()方法创建新会话；get_session()方法获取会话信息；list_sessions()方法列出所有会话；delete_session()方法删除会话；update_session()方法更新会话属性。

#### 5.3.3 消息处理

实现消息发送功能。send_message()方法发送消息并处理流式响应；abort_session()方法中断正在进行的会话；fork_session()方法创建会话分支。

#### 5.3.4 SSE事件处理

实现SSE事件监听功能。EventListener类负责连接管理、事件解析、回调分发、错误处理和重连逻辑。

### 5.4 第四阶段：MCP Bridge增强

#### 5.4.1 MCP工具映射

分析OpenCode提供的MCP工具与海关业务需求的对应关系。当前filesystem MCP服务器提供的工具可以用于：读取海关法规文档（read_file）；写入审计报告（write_file）；搜索历史案例（search_files）；列出工作目录结构（list_directory）。

#### 5.4.2 工具转换器

开发MCPToolAdapter，将OpenCode的MCP工具转换为LangChain StructuredTool格式。转换器需要处理：参数类型映射（JSON Schema到Pydantic）；返回值处理（标准化输出格式）；错误转换（统一异常类型）；文档生成（自动生成工具说明）。

#### 5.4.3 工具注册

在海关Agent的系统中注册OpenCode提供的工具。更新工具清单，支持动态发现新工具。配置工具的使用权限和调用限制。

### 5.5 第五阶段：与海关Agent整合

#### 5.5.1 服务初始化

在海关Agent的main.py中集成OpenCode服务。创建OpenCode服务实例；初始化OpenCodeAPIClient；启动OpenCodeServerManager（如采用嵌入式模式）。

#### 5.5.2 路由扩展

如果需要通过API暴露OpenCode能力，创建新的API路由。路由应该包括：健康检查端点；会话状态端点；工具列表端点。

#### 5.5.3 提示词优化

根据海关业务特点优化OpenCode的系统提示词。定义海关领域的专业术语映射；提供海关业务背景知识；设置输出格式规范。

### 5.6 第六阶段：测试与调优

#### 5.6.1 单元测试

为新增组件编写单元测试。测试覆盖率应包括：OpenCodeAPIClient的所有方法；OpenCodeServerManager的状态管理；MCPToolAdapter的工具转换；错误处理逻辑。

#### 5.6.2 集成测试

编写端到端的集成测试。测试场景包括：完整的会话创建和消息发送流程；流式响应的接收和解析；SSE事件的处理；MCP工具的调用和结果处理。

#### 5.6.3 性能测试

进行性能测试以评估系统容量。测试指标包括：并发会话数量；平均响应时间；吞吐量；资源占用。

#### 5.6.4 调优

根据测试结果进行系统调优。调整超时参数；优化重试策略；优化缓存配置；优化并发控制参数。

---

## 6. 安全配置

### 6.1 认证配置

#### 6.1.1 HTTP Basic Auth

OpenCode Server支持HTTP Basic Authentication。生产环境中必须配置强密码。认证信息通过环境变量配置：OPENCODE_SERVER_PASSWORD（必填）和OPENCODE_SERVER_USERNAME（可选，默认opencode）。

密码要求：长度至少16位；包含大小写字母、数字和特殊字符；定期更换；不要使用默认值或弱密码。

#### 6.1.2 客户端认证

客户端需要配置认证信息。在OpenCodeAPIClient初始化时传入认证凭据。认证信息应安全存储，不要硬编码在代码中。建议使用环境变量或安全的密钥管理服务。

### 6.2 网络安全

#### 6.2.1 主机绑定

默认情况下，OpenCode Server仅监听127.0.0.1（本地回环地址）。如果需要在局域网内访问，可以指定0.0.0.0或特定IP地址。但开放外部访问前必须确保认证已正确配置。

#### 6.2.2 防火墙配置

在服务器环境中配置防火墙规则。只允许必要的端口访问；限制来源IP地址范围；启用连接日志记录。

#### 6.2.3 HTTPS支持

当前版本的OpenCode Server不支持直接配置HTTPS。可以通过反向代理（如Nginx）实现HTTPS支持。代理服务器需要配置SSL证书。

### 6.3 权限控制

#### 6.3.1 会话级权限

每个会话可以设置独立的权限规则。通过会话创建时的permission字段配置。权限规则采用PermissionNext.Ruleset格式。

#### 6.3.2 全局权限

通过OPENCODE_PERMISSION环境变量设置全局默认权限。可以设置文件访问白名单、命令执行限制等。

#### 6.3.3 权限审计

记录所有权限相关的操作。审计日志应包括：权限请求的来源；权限响应的内容；权限变更的历史。

### 6.4 数据安全

#### 6.4.1 会话数据

会话数据默认存储在OpenCode的状态目录中。对于敏感数据，需要考虑加密存储或不使用持久化存储。

#### 6.4.2 传输数据

API通信使用HTTP协议（默认）。敏感场景建议在传输层加密（通过反向代理实现TLS）。

#### 6.4.3 临时文件

OpenCode处理过程中可能产生临时文件。需要定期清理临时文件目录；设置合理的文件保留策略；监控磁盘空间使用。

### 6.5 访问控制

#### 6.5.1 IP白名单

通过反向代理或防火墙配置IP白名单。只允许受信任的IP地址访问OpenCode API。

#### 6.5.2 请求限流

配置API请求限流策略。防止恶意请求耗尽资源；保护系统稳定性。

#### 6.5.3 API密钥

如果需要对外提供OpenCode API访问，考虑使用API密钥机制。为每个调用方分配独立的密钥；记录密钥使用情况；支持密钥吊销。

---

## 7. 错误处理

### 7.1 错误分类

#### 7.1.1 客户端错误（4xx）

400 Bad Request：请求格式错误或参数无效。需要检查请求体的格式和参数类型。

401 Unauthorized：认证失败或未提供认证信息。需要检查认证凭据是否正确配置。

403 Forbidden：权限不足，无法执行请求的操作。需要检查权限配置。

404 Not Found：请求的资源不存在。需要检查会话ID或路径是否正确。

429 Too Many Requests：请求频率超限。需要实现请求退避和重试。

#### 7.1.2 服务器错误（5xx）

500 Internal Server Error：服务器内部错误。可能需要重启Server或检查日志。

502 Bad Gateway：代理错误或上游服务器问题。检查OpenCode Server状态。

503 Service Unavailable：服务暂时不可用。可能需要等待Server启动完成。

#### 7.1.3 连接错误

ConnectionError：无法连接到OpenCode Server。需要检查Server是否正在运行；检查网络连接；检查主机和端口配置。

TimeoutError：请求超时。可能是Server负载过高或操作耗时过长。需要增加超时时间或优化操作。

#### 7.1.4 协议错误

SSE连接错误：事件流中断。需要实现重连逻辑；处理连接中断的善后工作。

响应解析错误：服务器返回的数据格式不符合预期。需要检查API版本兼容性。

### 7.2 重试策略

#### 7.2.1 重试条件

以下情况应该进行重试：连接超时（网络瞬时问题）；503 Service Unavailable；502 Bad Gateway；429 Too Many Requests（在退避后）。

以下情况不应重试：401 Unauthorized（认证信息错误，重试无意义）；400 Bad Request（请求格式问题，需要修复代码）；404 Not Found（资源不存在，重试无法解决）。

#### 7.2.2 指数退避

使用指数退避算法计算重试间隔。初始间隔建议1秒；最大间隔建议60秒；退避系数建议2；最大重试次数建议5次。

#### 7.2.3 重试示例

```python
async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    max_retries: int = 3,
    base_delay: float = 1.0
) -> httpx.Response:
    for attempt in range(max_retries):
        try:
            response = await client.request(method, url)
            if response.status_code in [502, 503]:
                delay = base_delay * (2 ** attempt)
                await asyncio.sleep(delay)
                continue
            response.raise_for_status()
            return response
        except (httpx.ConnectTimeout, httpx.ReadTimeout):
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            await asyncio.sleep(delay)
    raise Exception("Max retries exceeded")
```

### 7.3 异常处理设计

#### 7.3.1 自定义异常

定义OpenCode相关的自定义异常类型。OpenCodeError作为基类；ConnectionError、AuthenticationError、PermissionError、TimeoutError、APIError作为子类。

#### 7.3.2 异常处理链

在适当层级捕获和处理异常。HTTP客户端层：处理连接错误和超时；API客户端层：处理认证和权限错误；业务逻辑层：处理业务相关的错误；API路由层：返回友好的错误响应。

#### 7.3.3 日志记录

所有异常都需要记录日志。日志应包括：异常类型和消息；堆栈跟踪；相关上下文（会话ID、请求ID等）；时间戳。

### 7.4 熔断机制

#### 7.4.1 熔断条件

当错误率超过阈值时触发熔断。建议的阈值：错误率超过50%；连续失败次数超过10次。

#### 7.4.2 熔断恢复

熔断后进入半开状态，尝试放行少量请求。如果请求成功则恢复正常；如果请求失败则继续熔断。熔断持续时间建议至少30秒。

---

## 8. 测试计划

### 8.1 单元测试

#### 8.1.1 OpenCodeAPIClient测试

测试用例应覆盖：会话创建的各种场景；消息发送和流式响应处理；文件操作的正确性；错误响应的处理。

#### 8.1.2 OpenCodeServerManager测试

测试用例应覆盖：Server启动和停止；健康检查功能；异常状态处理；配置更新。

#### 8.1.3 MCPToolAdapter测试

测试用例应覆盖：工具定义转换；参数验证；返回值解析；错误传播。

### 8.2 集成测试

#### 8.2.1 完整流程测试

测试场景：创建会话；发送包含文本的消息；接收流式响应；获取会话历史；关闭会话。

预期结果：整个流程顺利完成；响应时间在可接受范围内；无内存泄漏。

#### 8.2.2 MCP工具测试

测试场景：通过OpenCode调用filesystem MCP工具；读取文件内容；执行文件搜索；处理工具错误。

预期结果：工具调用成功；参数传递正确；结果解析正确。

#### 8.2.3 SSE事件测试

测试场景：建立SSE连接；接收各种类型的事件；处理连接中断；验证事件顺序。

预期结果：事件正确接收和处理；重连机制正常工作。

### 8.3 性能测试

#### 8.3.1 并发测试

测试方法：使用并发客户端同时发送多个请求；逐步增加并发数量直到系统达到瓶颈。

指标：最大并发数；平均响应时间；错误率；资源使用率。

#### 8.3.2 压力测试

测试方法：持续高负载运行一段时间；观察系统稳定性和资源消耗。

指标：长时间运行的稳定性；内存泄漏检测；资源增长曲线。

#### 8.3.3 响应时间测试

测试方法：分别测试各主要API的响应时间。

指标：各API的P50、P90、P99响应时间。

### 8.4 安全测试

#### 8.4.1 认证测试

测试场景：使用错误凭据访问；使用过期会话访问；跨权限访问。

预期结果：认证失败被正确拦截。

#### 8.4.2 权限测试

测试场景：超出权限的操作尝试；权限变更后的访问控制。

预期结果：权限检查正常工作。

### 8.5 兼容性测试

#### 8.5.1 版本兼容性

测试不同版本的OpenCode Server与客户端的兼容性。测试OpenCode的不同配置组合。

#### 8.5.2 网络环境

测试在不同网络条件下的表现。正常网络；高延迟网络；不稳定网络。

---

## 9. 部署指南

### 9.1 环境要求

#### 9.1.1 系统要求

操作系统：Windows Server 2019+或Windows 10/11（开发环境）。处理器：建议多核处理器以支持并发处理。内存：建议16GB以上。磁盘：建议SSD，至少50GB可用空间。

#### 9.1.2 软件要求

运行时：Bun最新稳定版。Node.js：v18+（用于MCP服务器）。Python：3.10+。已安装所有Python依赖包。

#### 9.1.3 网络要求

OpenCode Server端口（默认4096）需要开放。HTTP Basic Auth认证需要正确配置。如果使用反向代理，代理端口也需要开放。

### 9.2 安装步骤

#### 9.2.1 OpenCode Server安装

下载或克隆OpenCode项目到指定目录。使用bun install安装依赖。验证安装：运行bun run dev确认TUI可以启动。

#### 9.2.2 oh-my-opencode安装

如果使用独立的可执行文件：npm install oh-my-opencode-windows-x64。验证安装：node_modules/.bin/oh-my-opencode --version。

#### 9.2.3 目标项目配置

确保海关Agent项目的所有依赖已安装。配置OpenCode相关的环境变量。验证现有功能正常运行。

### 9.3 配置步骤

#### 9.3.1 环境变量配置

配置必需的环境变量：OPENCODE_SERVER_PASSWORD（认证密码）；OPENCODE_SERVER_USERNAME（用户名，可选）；OPENCODE_CONFIG（配置文件路径，可选）。

可选的环境变量：OPENCODE_CONFIG_CONTENT（内联配置）；OPENCODE_CONFIG_DIR（额外配置目录）；OPENCODE_PERMISSION（全局权限规则）；OPENCODE_EXPERIMENTAL（实验性功能开关）。

#### 9.3.2 目录权限配置

创建OpenCode所需的工作目录并配置权限。目录包括日志目录、数据目录、配置目录、缓存目录。

### 9.4 启动步骤

#### 9.4.1 启动模式选择

独立模式：OpenCode Server作为独立进程运行。海关Agent通过HTTP API连接。适用场景：多实例部署、需要独立管理Server。

嵌入式模式：OpenCode Server由海关Agent直接启动和管理。适用场景：简单部署、单实例运行。

#### 9.4.2 启动命令

独立模式启动命令：bun run --conditions=browser ./src/index.ts serve --port 4096 --hostname 127.0.0.1。

或使用可执行文件：node_modules/.bin/oh-my-opencode serve --port 4096 --hostname 127.0.0.1。

#### 9.4.3 健康检查

启动后验证Server状态。检查进程是否正常运行；检查端口是否监听；访问GET /global/health端点确认返回正常。

### 9.5 监控配置

#### 9.5.1 日志配置

配置日志输出级别和格式。建议将日志写入文件便于排查问题。配置日志轮转防止磁盘空间耗尽。

#### 9.5.2 监控指标

监控以下关键指标：Server进程状态；API请求量和响应时间；错误率；资源使用率（CPU、内存、磁盘）。

#### 9.5.3 告警配置

设置告警阈值：错误率超过10%；响应时间超过30秒；磁盘空间低于20%；内存使用超过90%。

### 9.6 维护操作

#### 9.6.1 日志清理

配置日志保留策略。建议保留最近30天的日志；定期归档历史日志。

#### 9.6.2 数据清理

清理过期会话数据。清理临时文件。清理缓存数据。

#### 9.6.3 更新流程

备份当前配置和状态。停止Server。更新代码或依赖。验证更新。启动Server。确认功能正常。

---

## 10. 风险评估

### 10.1 技术风险

#### 10.1.1 OpenCode Server稳定性

风险描述：OpenCode Server可能存在稳定性问题，导致服务中断。

影响程度：高。服务中断会影响海关Agent的核心功能。

缓解措施：实现Server状态监控；配置自动重启机制；准备降级方案。

#### 10.1.2 API兼容性

风险描述：OpenCode的API可能在版本更新中发生变化。

影响程度：中。API变更可能导致集成代码失效。

缓解措施：锁定OpenCode版本；实现API版本检测；预留升级窗口。

#### 10.1.3 性能瓶颈

风险描述：OpenCode的处理能力可能无法满足高并发需求。

影响程度：高。性能问题会直接影响用户体验。

缓解措施：进行充分的性能测试；配置适当的并发限制；实现请求队列。

### 10.2 安全风险

#### 10.2.1 认证信息泄露

风险描述：认证凭据可能通过日志或错误信息泄露。

影响程度：高。认证信息泄露可能导致未授权访问。

缓解措施：不将凭据写入日志；使用安全的凭据存储；定期更换密码。

#### 10.2.2 权限控制失效

风险描述：权限配置可能无法有效限制危险操作。

影响程度：高。权限失效可能导致安全问题。

缓解措施：仔细配置权限规则；进行权限测试；监控权限相关事件。

#### 10.2.3 数据泄露

风险描述：敏感数据可能在传输或存储过程中泄露。

影响程度：高。涉及报关数据等敏感信息。

缓解措施：使用加密传输；敏感数据脱敏处理；严格的访问控制。

### 10.3 运维风险

#### 10.3.1 依赖冲突

风险描述：OpenCode的依赖可能与现有项目冲突。

影响程度：中。依赖冲突可能导致运行错误。

缓解措施：使用虚拟环境隔离；仔细检查依赖版本；准备备用方案。

#### 10.3.2 资源泄漏

风险描述：长时间运行可能出现资源泄漏。

影响程度：中。资源泄漏会导致性能下降甚至服务崩溃。

缓解措施：定期重启Server；监控系统资源；设置资源限制。

#### 10.3.3 回滚困难

风险描述：集成后发现问题可能难以回滚。

影响程度：中。回滚失败可能导致长时间服务中断。

缓解措施：制定详细的回滚计划；保留回滚所需的备份；进行回滚演练。

### 10.4 业务风险

#### 10.4.1 功能影响

风险描述：集成OpenCode可能影响现有功能的稳定性。

影响程度：中。功能问题可能导致业务中断。

缓解措施：充分的集成测试；灰度发布；准备回退方案。

#### 10.4.2 性能影响

风险描述：OpenCode的引入可能影响系统整体性能。

影响程度：中。性能下降影响用户体验。

缓解措施：性能测试；性能调优；资源扩容。

### 10.5 风险应对策略总结

针对高风险项目，建议在实施前制定应急预案。应急预案应包括：风险触发条件；应急响应流程；负责人和联系方式；备用方案。对于中等风险项目，建议持续监控并准备快速响应方案。对于低风险项目，建议定期检查和评估。

---

## 附录

### 附录A：OpenCode启动命令参考

标准启动命令：

```
bun run --conditions=browser ./src/index.ts serve --port 4096 --hostname 127.0.0.1
```

使用可执行文件启动：

```
node_modules/.bin/oh-my-opencode serve --port 4096 --hostname 127.0.0.1
```

带认证启动：

```
set OPENCODE_SERVER_PASSWORD=your_secure_password
bun run --conditions=browser ./src/index.ts serve --port 4096 --hostname 127.0.0.1
```

### 附录B：API端点速查表

| 功能     | 方法 | 路径                             |
| -------- | ---- | -------------------------------- |
| 创建会话 | POST | /session                         |
| 获取会话 | GET  | /session/:sessionID              |
| 发送消息 | POST | /session/:sessionID/message      |
| 异步发送 | POST | /session/:sessionID/prompt_async |
| 健康检查 | GET  | /global/health                   |
| SSE事件  | GET  | /global/event                    |
| MCP状态  | GET  | /mcp                             |
| 工具列表 | GET  | /experimental/tool/ids           |
| API文档  | GET  | /doc                             |

### 附录C：环境变量清单

| 变量名                          | 必填 | 默认值   | 说明                 |
| ------------------------------- | ---- | -------- | -------------------- |
| OPENCODE_SERVER_PASSWORD        | 是   | -        | HTTP Basic认证密码   |
| OPENCODE_SERVER_USERNAME        | 否   | opencode | HTTP Basic认证用户名 |
| OPENCODE_CONFIG                 | 否   | -        | 配置文件路径         |
| OPENCODE_CONFIG_CONTENT         | 否   | -        | 内联JSONC配置        |
| OPENCODE_CONFIG_DIR             | 否   | -        | 额外配置目录         |
| OPENCODE_DISABLE_PROJECT_CONFIG | 否   | false    | 禁用项目级配置       |
| OPENCODE_PERMISSION             | 否   | -        | 全局权限规则         |
| OPENCODE_EXPERIMENTAL           | 否   | -        | 启用实验性功能       |

### 附录D：状态码说明

| 状态码 | 含义       | 处理建议             |
| ------ | ---------- | -------------------- |
| 200    | 成功       | 正常处理响应         |
| 204    | 成功无内容 | 通常用于异步操作确认 |
| 400    | 请求错误   | 检查请求格式和参数   |
| 401    | 认证失败   | 检查认证凭据         |
| 403    | 权限不足   | 检查权限配置         |
| 404    | 资源不存在 | 检查会话ID和路径     |
| 429    | 请求过多   | 实现退避重试         |
| 500    | 服务器错误 | 检查Server状态和日志 |
| 502    | 网关错误   | 检查上游服务状态     |
| 503    | 服务不可用 | 等待服务恢复后重试   |

---

**文档版本历史**

| 版本 | 日期      | 修改内容                                    |
| ---- | --------- | ------------------------------------------- |
| v1.0 | 2026年1月 | 初始版本                                    |
| v2.0 | 2026年3月 | 修正API端点错误；完善安全配置；增加风险评估 |

---

_本文档由技术团队编制，如有疑问请联系相关负责人。_
