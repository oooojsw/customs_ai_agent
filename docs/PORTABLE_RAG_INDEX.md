# 可迁移 RAG 索引

## 部署约定

知识原文位于 `data/knowledge/`，可迁移索引位于
`config/faiss_index_local/`。完整索引包含：

- `index.faiss`：向量数据；
- `index.pkl`：文本片段和相对来源元数据；
- `manifest.json`：索引版本、Embedding 模型、知识内容指纹和来源清单。

索引仍不提交到 Git。首次启动时，如果索引不存在、缺少清单、模型发生变化，
或者知识内容指纹不一致，服务会自动重建。重启后直接复用。

## 迁移到另一台机器

可以只复制代码和 `data/knowledge/`，由目标机首次启动自动构建；也可以把整个
`config/faiss_index_local/` 一并复制，以跳过向量化。索引元数据使用项目相对路径，
不依赖原机器用户名、盘符或项目绝对目录。

目标机仍需能够加载与 `manifest.json` 一致的 Embedding 模型。可通过以下变量指定：

```text
KNOWLEDGE_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
KNOWLEDGE_EMBEDDING_REVISION=7999e1d3359715c523056ef9478215996d62a620
KNOWLEDGE_EMBEDDING_CACHE_DIR=/data/models
KNOWLEDGE_AUTO_INCLUDE_PDFS=true
```

Docker Compose 会同时持久化 FAISS 索引和 Hugging Face 模型缓存。

## 重建与检查

命令行完整重建：

```bash
python quick_rebuild.py
```

服务运行时可调用：

```text
POST /api/v1/index/rebuild
POST /api/v1/pdf/reindex
GET  /api/v1/index/status
```

两个重建接口均通过 SSE 返回进度。状态接口的 `index_health` 会返回来源数量、
向量数量、模型、清单版本、是否可迁移以及是否过期。

## PDF 处理

原生 PDF 先通过 `pypdfium2` 提取文本；文本层质量不足时自动切换 RapidOCR。
RapidOCR 按页渲染和识别，不再一次把整本 PDF 的页面图片放入内存。文本、Markdown、
无扩展名知识文件和 PDF 使用同一切分、向量化和持久化流程。
