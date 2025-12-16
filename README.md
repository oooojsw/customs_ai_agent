这是一个非常详尽且专业的 README.md 文档，涵盖了项目背景、架构设计、技术亮点、部署指南以及我们之前讨论的核心逻辑。

# Smart Customs AI Agent (海关智能报关决策系统)
> **面向智慧口岸的自动化报关辅助决策原型系统 (v1.0)**  
> 结合 **RAG (检索增强生成)** 与 **Agentic Workflow (智能体工作流)** 技术，实现对报关单据的流式风险研判与可视化推理。

---

## 📖 项目背景与目标

在海关报关场景中，传统的人工审单面临**规则复杂（如归类、估价）、知识更新快、单证比对繁琐**等痛点。
本项目旨在构建一个**“低耦合、高内聚”**的 AI 智能体系统，通过以下方式赋能业务：

1.  **自动化研判**：利用大模型语义理解能力，自动处理非结构化报关文本。
2.  **知识外挂 (RAG)**：将海关专业查验指南（几千字）挂载为外部知识库，解决模型幻觉与专业性不足问题。
3.  **过程透明化**：拒绝黑盒，通过 SSE 流式技术实时展示 AI 的“思考路径”与决策依据。

---

## 🏗️ 系统架构设计

本项目遵循**分层架构**与**配置驱动**的设计理念，实现了业务逻辑与代码逻辑的彻底解耦。

### 1. 逻辑架构图


2. 核心模块解析 (低耦合、高内聚体现)
模块层级	目录路径	职责 (High Cohesion)	解耦体现 (Low Coupling)
知识层	config/	存放 risk_rules.json 和 rag_*.txt。纯业务逻辑，由业务人员维护。	业务规则变化无需修改 Python 代码。
编排层	src/core/	orchestrator.py 负责流程控制；prompt_builder.py 负责组装指令。	不关心底层用什么模型，只管流程调度。
执行层	src/services/	llm_service.py 封装 API 通信、重试、清洗逻辑。	网络层复杂度被封闭，更换模型只需改此一层。
接口层	src/api/	处理 HTTP 请求与 SSE 响应。	前后端分离，仅通过 JSON 数据交互。
✨ 核心技术亮点
1. 细粒度 RAG (Fine-grained RAG)

痛点解决：避免将整本法规塞入 Context 导致 Token 浪费和注意力分散。

实现：将知识库拆解为 rag_r01_basic_info.txt (基础要素)、rag_r03_price_logic.txt (价格逻辑) 等独立文件。AI 执行某条规则时，只动态加载对应的几百字指南，精准度极高。

2. 鲁棒的 LLM 工程化 (Robust Engineering)

指数退避重试：针对 503 Server Overloaded 错误，实现了智能的 Exponential Backoff 重试机制，确保高并发下的可用性。

防御性编程：针对 Preview 模型偶尔“思考后不输出内容”的 Bug，增加了自动检测与重试逻辑。

安全拦截绕过：通过配置 safetySettings: BLOCK_NONE，解决了海关数据中“走私、毒品”等敏感词被误杀的问题。

3. 流式可视化 (Streaming Visualization)

使用 Server-Sent Events (SSE) 技术，将后端的推理步骤（思考 -> 判定 -> 解释）实时推送到前端。

前端通过呼吸灯动画与增量渲染，给用户呈现出“AI 正在逐项审查”的视觉体验。

📂 文件结构说明
code
Text
download
content_copy
expand_less
customs_ai_agent/
├── config/                  # [知识库] 存放规则配置与 RAG 文本
│   ├── risk_rules.json      # 核心规则定义（指令、关联RAG文件）
│   ├── rag_r01_basic.txt    # RAG: 基础要素审查指南
│   └── ...                  # 其他 RAG 文件
├── src/                     # [后端代码]
│   ├── main.py              # 启动入口 (CORS, 路由挂载)
│   ├── api/routes.py        # 接口定义 (SSE 流式响应)
│   ├── core/                # 核心逻辑
│   │   ├── orchestrator.py  # 流程编排器 (生成器模式)
│   │   └── prompt_builder.py# Prompt 组装工厂
│   ├── services/            # 外部服务
│   │   └── llm_service.py   # Gemini API 封装 (重试、清洗)
│   └── config/loader.py     # 环境变量加载器 (.env)
├── web/                     # [前端代码]
│   ├── index.html           # 单页应用 (含 Tailwind CSS)
│   └── ... 
├── .env                     # 敏感配置 (API Key)
└── requirements.txt         # 依赖清单
🚀 快速启动指南
1. 环境准备

Python 3.10+

Git

2. 安装依赖
code
Bash
download
content_copy
expand_less
# 建议使用 Conda 或 venv 创建虚拟环境
pip install -r requirements.txt
3. 配置环境变量

在项目根目录创建 .env 文件，填入以下内容：

code
Ini
download
content_copy
expand_less
# Google Gemini API Key (必填)
GOOGLE_API_KEY="你的API_KEY_HERE"

# 模型选择 (推荐使用 1.5-flash 以获得最佳稳定性)
GEMINI_MODEL_NAME="gemini-1.5-flash"

# 代理配置 (如果需要)
HTTP_PROXY="http://127.0.0.1:7890"
HTTPS_PROXY="http://127.0.0.1:7890"
4. 启动后端服务
code
Bash
download
content_copy
expand_less
# 在项目根目录下运行
python src/main.py

成功启动后会显示：INFO: Uvicorn running on http://0.0.0.0:8000

5. 启动前端 (解决跨域问题)

为了避免浏览器直接打开本地文件的跨域限制，建议用 Python 启动一个临时静态服务器：

code
Bash
download
content_copy
expand_less
cd web
python -m http.server 5500

然后访问：👉 http://localhost:5500

🧪 边界测试用例

前端界面内置了 10 组边界测试样本，覆盖以下场景，可用于压力测试：

归类欺诈 (无人机报成玩具)

隐蔽洋垃圾 (再生原料掩盖固体废物)

微小误差 (重量误差 >1%)

价格洗钱 (圆珠笔申报 $100)

濒危物种 (红木家具未申报)

... 以及标准合规样本。

📝 维护与扩展

修改规则：无需改代码。直接编辑 config/risk_rules.json 调整指令，或修改 config/rag_*.txt 更新审查指南。

更换模型：修改 .env 中的 GEMINI_MODEL_NAME 即可切换至 Gemini 2.0 或 Pro 版本。

Author: Wang Kai (M4 Module)
Project: Intelligent Customs Clearance System

