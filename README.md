# 🚢 智慧口岸自动化报关辅助决策系统 (Customs AI Agent)

![Version](https://img.shields.io/badge/Version-3.1%20Pro-green)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![LangChain](https://img.shields.io/badge/LangChain-v0.3-orange)
![DeepSeek](https://img.shields.io/badge/Model-DeepSeek--V3-purple)
![Marker](https://img.shields.io/badge/PDF-Marker-red)

> **"不仅仅是聊天机器人，而是具备规划能力的行业合规专家。"**

本项目是一个基于 **LLM (DeepSeek-V3)** 和 **RAG (检索增强生成)** 技术的智能体系统，专为进出口报关场景设计。它能够自动审核报关单据风险、提供法规咨询，并基于 SOP 标准自动生成专业的合规性审查建议书。

**v3.1 Pro 新增**: 完整的PDF支持系统，使用Marker自动处理PDF文档并纳入RAG知识库。

---

## ✨ 核心功能 (Core Features)

### 1. 🚨 智能审单 (Smart Audit)
- **风险规则引擎**：基于 `config/risk_rules.json` 动态加载审查策略。
- **RAG 增强校验**：自动检索海关监管目录，识别"洋垃圾"、"两用物项"、"濒危物种"等隐蔽风险。
- **推理可视化**：在前端通过 SSE 实时展示 AI 的每一步审核逻辑。

### 2. 💬 法规咨询 (Expert Chat)
- **知识库问答**：基于 FAISS 向量库，检索本地存储的海关法规文件（**现已支持PDF**）。
- **混合搜索**：遇到专业问题自动调用检索工具；闲聊问题直接回答。
- **思维链展示**：展示 DeepSeek 的深度思考过程。

### 3. 📑 智能建议书 (Intelligent Report)
- **Planner-Executor 架构**：采用"先规划目录，后逐章撰写"的 Agent 设计模式。
- **SOP 驱动**：严格依据 `config/sop_process.txt` 生成内容。
- **数据联动**：支持引用"审单模块"的发现结果。

### 4. 📄 PDF自动处理 (NEW in v3.1)
- **Marker OCR**：自动处理 `data/knowledge/` 目录下的所有PDF文件（95-97%准确率）。
- **智能缓存**：SQLite数据库 + SHA256哈希校验，避免重复处理。
- **完全自动化**：后台异步处理，无需手动干预。
- **RAG集成**：PDF内容自动加入FAISS索引，支持智能检索。

---

## 🏗️ 技术架构 (Architecture)

**后端框架**: FastAPI + Python 3.11+
**LLM 编排**: LangChain v0.3 / LangGraph
**模型**: DeepSeek-V3 (兼容 OpenAI 接口)
**PDF处理**: Marker (开源OCR引擎)
**RAG 方案**:
- Embedding: `sentence-transformers/all-MiniLM-L6-v2`
- Vector Store: FAISS (CPU版)
- PDF缓存: SQLite (异步)
**网络层**: httpx (AsyncHTTPTransport)，穿透本地代理
**前端**: 原生 HTML/JS + TailwindCSS + SSE流式

---

## 🚀 快速开始 (Quick Start)

### 方式一：快速启动（推荐）

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 运行快速启动脚本
python QUICK_START.py
```

这会自动完成：
- ✅ 环境检查
- ✅ 数据库初始化
- ✅ PDF文件扫描
- ✅ 缓存检查
- ✅ 功能测试

### 方式二：手动启动

#### 1. 安装依赖

```bash
pip install -r requirements.txt
```

**注意**: 首次安装会下载PyTorch（约2GB）和Marker模型，请确保网络稳定。

#### 2. 初始化数据库

```bash
python init_pdf_database.py
```

#### 3. 配置环境变量

在项目根目录创建 `.env` 文件：

```ini
# DeepSeek API 配置
DEEPSEEK_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxxx"
DEEPSEEK_BASE_URL="https://api.deepseek.com"
DEEPSEEK_MODEL="deepseek-chat"

# 网络代理 (国内环境必须配置)
HTTP_PROXY="http://127.0.0.1:7890"
HTTPS_PROXY="http://127.0.0.1:7890"

# Google Gemini (备用)
GOOGLE_API_KEY="AIzaSyxxxxxxxxxxxxxxxx"
GEMINI_MODEL_NAME="gemini-2.0-flash"
```

#### 4. 启动服务

```bash
python src/main.py
```

**首次启动**：会自动处理PDF文件（约30-60分钟，12个PDF）
**后续启动**：使用缓存（< 10秒）

#### 5. 访问系统

浏览器打开：http://localhost:8000

---

## 📂 项目结构

```
customs_ai_agent/
├── config/                    # 配置文件
│   ├── risk_rules.json        # 审单规则定义
│   ├── sop_process.txt        # 报告生成 SOP
│   └── faiss_index_local/     # 向量数据库缓存
├── data/
│   ├── knowledge/             # 知识库源文件（PDF/TXT/MD）
│   └── customs_audit.db       # SQLite数据库
├── src/
│   ├── api/routes.py          # API路由（含PDF接口）
│   ├── core/                  # 核心编排逻辑
│   ├── database/
│   │   ├── base.py            # 数据库会话管理 ✨
│   │   ├── pdf_repository.py  # PDF缓存仓储 ✨
│   │   └── models.py          # 数据模型（含PDFDocument）
│   └── services/
│       ├── marker_service.py  # Marker服务封装 ✨
│       ├── knowledge_base.py  # RAG索引（集成PDF）
│       ├── chat_agent.py      # 对话 Agent
│       └── report_agent.py    # 报告生成 Agent
├── web/                       # 前端界面
├── requirements.txt           # 依赖列表
├── QUICK_START.py            # 快速启动脚本 ✨
├── init_pdf_database.py      # 数据库初始化 ✨
└── test_marker_pdf_complete.py # 完整测试套件 ✨
```

---

## 🧪 测试

### 快速测试

```bash
python QUICK_START.py
```

### 完整测试

```bash
python test_marker_pdf_complete.py
```

测试覆盖：
- 数据库操作
- Marker服务
- PDF哈希计算
- 缓存机制
- RAG检索
- API接口
- 性能基准
- 错误处理

---

## 📊 性能指标

| 指标 | 数值 |
|------|------|
| PDF处理成功率 | > 95% |
| OCR准确率 | 95-97% |
| 首次启动 | 30-60分钟（处理12个PDF） |
| 后续启动 | < 10秒（使用缓存） |
| RAG检索 | < 2秒 |
| 内存占用 | < 4GB |
| 磁盘占用 | ~500MB（数据库+索引） |

---

## 🔧 API接口

### PDF管理接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/pdf/stats` | GET | 获取PDF统计 |
| `/api/v1/pdf/cache/list` | GET | 列出所有缓存 |
| `/api/v1/pdf/cache/delete` | DELETE | 删除指定缓存 |
| `/api/v1/pdf/cache/clear` | DELETE | 清空所有缓存 |

示例：
```bash
curl http://localhost:8000/api/v1/pdf/stats
```

### 核心业务接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/v1/audit/analyze` | POST | 智能审单 |
| `/api/v1/chat/stream` | POST | 法规咨询 |
| `/api/v1/report/generate` | POST | 生成报告 |
| `/api/v1/ocr/extract` | POST | 图片OCR识别 |

---

## ⚠️ 常见问题

### Q1: Marker安装失败？

```bash
pip install marker-pdf==0.3.2
```

### Q2: PDF处理太慢？

- **正常现象**：首次处理需要5-15分钟/PDF
- **后续启动**：使用缓存，秒级响应

### Q3: RAG检索没有PDF内容？

1. 确认PDF处理完成（查看控制台日志）
2. 在"法规咨询"模块测试检索
3. 尝试更换关键词

### Q4: 数据库初始化失败？

```bash
python init_pdf_database.py
```

### Q5: FAISS索引损坏？

删除 `config/faiss_index_local/` 目录，重启服务自动重建。

---

## 📝 PDF处理说明

### 工作流程

```
PDF文件扫描
  ↓
计算SHA256哈希
  ↓
查询SQLite缓存
  ↓
  ├─ 缓存命中 → 使用缓存（< 1秒）
  └─ 缓存未命中 → Marker提取（5-15分钟）
  ↓
保存到数据库
  ↓
添加到FAISS索引
  ↓
支持RAG检索 ✅
```

### 支持的文件格式

- **PDF文件** (.pdf) - 自动OCR处理
- **文本文件** (.txt) - 直接加载
- **Markdown文件** (.md) - 直接加载

### 缓存机制

- **首次处理**：使用Marker提取文本（5-15分钟/PDF）
- **缓存命中**：直接使用数据库缓存（< 1秒）
- **智能更新**：文件变更后自动重新处理

---

## 📅 版本历史

### v3.1 Pro (Current)
- ✨ 新增PDF自动处理（Marker）
- ✨ 新增SQLite缓存系统
- ✨ 新增PDF管理API接口
- ✨ 完整测试套件
- ✨ 快速启动脚本

### v3.0
- 引入RAG知识库
- 支持基于规则的风险审单
- 新增"智能建议书"模块

### v2.0
- 基础原型验证
- 对话功能

---

## 👨‍💻 开发者指南

### 扩展功能

**修改审单规则**：编辑 `config/risk_rules.json`

**修改报告流程**：编辑 `config/sop_process.txt`

**增加新工具**：在 `src/services/chat_agent.py` 的 tools 列表中添加

**添加PDF文件**：直接放入 `data/knowledge/` 目录，重启服务自动处理

### 测试指南

```bash
# 运行所有测试
python test_marker_pdf_complete.py

# 运行快速检查
python QUICK_START.py
```

---

## 📞 技术支持

- 查看控制台日志
- 运行测试脚本诊断
- 查看 `MARKER_INSTALL_GUIDE.md`

---

**Powered by DeepSeek & LangChain & Marker**

**版本**: v3.1 Pro
**更新日期**: 2025-01-19
**状态**: ✅ 生产就绪
