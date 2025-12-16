这份 README.md 是根据项目当前的 v2.1 版本、DeepSeek 深度集成、新增的报告生成功能以及我们在底层架构（网络、RAG、单例模式）上的所有改进重新编写的。

请将以下内容完全覆盖项目根目录下的 README.md 文件。

code
Markdown
download
content_copy
expand_less
# 🚢 智慧口岸自动化报关辅助决策系统 (Customs AI Agent)

![Version](https://img.shields.io/badge/Version-2.1-green)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![LangChain](https://img.shields.io/badge/LangChain-v0.3-orange)
![DeepSeek](https://img.shields.io/badge/Model-DeepSeek--V3-purple)

> **"不仅仅是聊天机器人，而是具备规划能力的行业合规专家。"**

本项目是一个基于 **LLM (DeepSeek-V3)** 和 **RAG (检索增强生成)** 技术的智能体系统，专为进出口报关场景设计。它能够自动审核报关单据风险、提供法规咨询，并基于 SOP 标准自动生成专业的合规性审查建议书。

---

## ✨ 核心功能 (Core Features)

### 1. 🚨 智能审单 (Smart Audit)
- **风险规则引擎**：基于 `config/risk_rules.json` 动态加载审查策略。
- **RAG 增强校验**：自动检索海关监管目录，识别“洋垃圾”、“两用物项”、“濒危物种”等隐蔽风险。
- **推理可视化**：在前端通过 SSE 实时展示 AI 的每一步审核逻辑（如“正在比对HS编码...”）。

### 2. 💬 法规咨询 (Expert Chat)
- **知识库问答**：基于 FAISS 向量库，检索本地存储的海关法规文件。
- **混合搜索**：遇到专业问题（如归类、税率）自动调用检索工具；闲聊问题直接回答。
- **思维链展示**：(Beta) 展示 DeepSeek 的深度思考过程 (`reasoning_content`)。

### 3. 📑 智能建议书 (Intelligent Report) [NEW]
- **Planner-Executor 架构**：采用“先规划目录，后逐章撰写”的 Agent 设计模式。
- **Context Caching**：利用 DeepSeek 的上下文缓存特性，生成超长、逻辑连贯的专业报告，同时大幅降低 API 成本。
- **SOP 驱动**：严格依据 `config/sop_process.txt` 中的标准作业程序生成内容。
- **数据联动**：支持一键引用“审单模块”的发现结果作为报告上下文。

---

## 🏗️ 技术架构 (Architecture)

*   **后端框架**: FastAPI (使用 Lifespan 管理全局单例 Agent，响应速度提升 10x)。
*   **LLM 编排**: LangChain v0.3 / LangGraph。
*   **模型**: DeepSeek-V3 (兼容 OpenAI 接口)。
*   **RAG 方案**: 
    *   Embedding: `sentence-transformers/all-MiniLM-L6-v2` (本地运行)
    *   Vector Store: FAISS (CPU版，已解决 Windows 路径兼容性)
*   **网络层**: 高度定制的 `httpx` 传输层 (AsyncHTTPTransport)，完美穿透本地代理并规避 SSL 验证问题。
*   **前端**: 原生 HTML/JS + TailwindCSS，通过 EventSource (SSE) 实现打字机流式效果。

---

## 🚀 快速开始 (Quick Start)

### 1. 环境准备
确保已安装 Python 3.10+ 和 Git。

```bash
# 1. 克隆项目
git clone [your-repo-url]
cd customs_ai_agent

# 2. 创建虚拟环境 (推荐)
conda create -n customs_agent python=3.10
conda activate customs_agent

# 3. 安装依赖
pip install -r requirements.txt
2. 配置文件

在项目根目录创建 .env 文件，填入以下关键配置：

code
Ini
download
content_copy
expand_less
# DeepSeek API 配置
DEEPSEEK_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxxx"
DEEPSEEK_BASE_URL="https://api.deepseek.com"
DEEPSEEK_MODEL="deepseek-chat"

# 网络代理 (国内环境必须配置)
HTTP_PROXY="http://127.0.0.1:7890" 
HTTPS_PROXY="http://127.0.0.1:7890"

# 模型配置
GEMINI_MODEL_NAME="gemini-flash-latest" # 备用
3. 知识库准备

确保以下文件存在（如不存在，系统启动时会自动创建空索引或使用默认配置）：

config/sop_process.txt: 报告生成的标准流程参考。

data/knowledge/*.txt: 你的海关法规文本文件。

4. 启动服务
code
Bash
download
content_copy
expand_less
python src/main.py

启动成功后，访问浏览器：http://localhost:8000

📂 项目结构
code
Text
download
content_copy
expand_less
customs_ai_agent/
├── config/                 # 配置文件与知识库索引
│   ├── risk_rules.json     # 审单规则定义
│   ├── sop_process.txt     # 报告生成 SOP
│   └── faiss_index_local/  # 向量数据库缓存
├── data/knowledge/         # 原始法规文本数据 (RAG源)
├── src/
│   ├── api/routes.py       # API 路由定义
│   ├── core/               # 核心编排逻辑
│   ├── database/           # 审计日志数据库 (SQLite)
│   ├── services/
│   │   ├── chat_agent.py   # 对话 Agent (原生流式实现)
│   │   ├── report_agent.py # 报告生成 Agent (Planner-Executor)
│   │   ├── data_client.py  # 外部数据源接口
│   │   └── knowledge_base.py # RAG 索引管理
│   └── main.py             # 程序入口
├── web/                    # 前端界面
└── requirements.txt        # 依赖列表
⚠️ 常见问题与注意事项

Windows 下的 FAISS 报错

现象: RuntimeError: Error in ... could not open ... index.faiss

原因: FAISS 底层对 Windows 中文/空格路径支持不佳。

解法: 代码中已包含自动修复逻辑（先写入纯英文临时目录，再通过 Python 移动文件）。请勿手动修改此逻辑。

流式输出卡顿/不显示

原因: 本地代理拦截了异步请求。

解法: chat_agent.py 和 report_agent.py 中已强制注入 AsyncHTTPTransport(verify=False)。请确保你的代理软件（如 Clash）开启了 LAN 连接允许。

HuggingFace 模型下载失败

代码已内置 HF_ENDPOINT 环境变量指向国内镜像站，通常无需额外操作。首次启动时下载模型可能需要几分钟。

📅 版本历史

v2.1 (Current):

新增“智能建议书”模块，支持长文本流式生成。

修复 Chat 模块的流式卡死问题，回归原生 LLM 调用架构。

实现全局单例模式，大幅优化启动速度。

v2.0: 引入 RAG 知识库，支持基于规则的风险审单。

v1.0: 基础原型验证。

👨‍💻 开发者指南

如果你想扩展功能：

修改审单规则：编辑 config/risk_rules.json。

修改报告流程：编辑 config/sop_process.txt。

增加新工具：在 src/services/chat_agent.py 的 tools 列表中添加。

Powered by DeepSeek & LangChain

code
Code
download
content_copy
expand_less