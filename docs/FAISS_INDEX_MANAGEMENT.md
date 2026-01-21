# FAISS索引文件管理指南

## ⚠️ 重要提示

**FAISS索引文件不被Git跟踪，需要在每个环境重新生成！**

---

## 📋 为什么索引不放在Git中？

1. **文件太大**：索引文件约50MB，会导致Git仓库臃肿
2. **环境相关**：不同机器/环境需要独立构建索引
3. **频繁变化**：每次知识库更新都会重新生成
4. **可重建**：可以通过 `quick_rebuild.py` 快速重建

---

## 🚀 快速开始

### 首次部署或克隆代码后

```bash
# 1. 确保依赖已安装
pip install -r requirements.txt

# 2. 重建FAISS索引（包含PDF和TXT文件）
python quick_rebuild.py

# 3. 启动服务
python src/main.py
```

**预计时间**：
- 首次重建：6-10分钟（取决于PDF数量）
- 缓存命中后：2-3分钟

---

## 🔄 什么时候需要重建索引？

### ✅ 需要重建的情况

1. **首次部署项目**
   ```bash
   python quick_rebuild.py
   ```

2. **添加/修改知识库文件**
   - 在 `data/knowledge/` 中添加新的PDF/TXT文件
   ```bash
   python quick_rebuild.py
   ```

3. **更新RAG优化后**
   - 修改了 `src/services/knowledge_base.py` 中的chunk策略
   - 切换了embedding模型
   ```bash
   python quick_rebuild.py
   ```

4. **遇到"无本地依据"错误**
   ```bash
   python quick_rebuild.py
   ```

### ❌ 不需要重建的情况

- 修改代码逻辑（不影响知识库）
- 修改API接口
- 修改前端界面

---

## 🛠️ 重建索引脚本

### quick_rebuild.py 功能

```bash
python quick_rebuild.py
```

**功能**：
- ✅ 自动加载所有PDF文件（13个）
- ✅ 自动加载所有TXT文件（2个）
- ✅ 使用SHA256缓存避免重复处理
- ✅ 应用chunk过滤（≥50字符）
- ✅ 使用中文embedding模型（bge-small-zh-v1.5）
- ✅ 生成7774个高质量chunks

**输出位置**：
```
config/faiss_index_local/
├── index.faiss  (16MB) - 向量索引
└── index.pkl    (19MB) - 元数据
```

---

## 🔍 索引文件说明

### 文件结构

```
config/
├── faiss_index_local/        ← FAISS索引（不提交到Git）
│   ├── index.faiss           ← 向量数据
│   └── index.pkl             ← 文档元数据
├── rag_r01_basic_info.txt    ← RAG指导文件
├── rag_r02_sensitive_goods.txt
├── rag_r03_price_logic.txt
├── rag_r04_hs_classification.txt
└── rag_r05_doc_match.txt
```

### 知识库文件

```
data/knowledge/
├── *.pdf  (13个PDF文件，170MB)
└── *.txt  (2个TXT文件)
```

---

## ⚠️ 常见问题和解决方案

### 问题1: "无本地依据"错误

**原因**：
- 索引文件不存在或损坏
- 合并分支时旧索引覆盖了新索引

**解决**：
```bash
# 删除旧索引
rm -rf config/faiss_index_local/*

# 重建索引
python quick_rebuild.py
```

---

### 问题2: Git提交了索引文件

**现象**：
```bash
$ git status
On branch main
Changes to be committed:
  new file:   config/faiss_index_local/index.faiss  ← 不应该出现！
```

**原因**：
- 索引文件被错误地添加到Git跟踪

**解决**：
```bash
# 1. 从Git中移除（保留本地文件）
git rm -r --cached config/faiss_index_local/

# 2. 提交移除操作
git commit -m "fix: remove FAISS index from git tracking"

# 3. 验证.gitignore包含该路径
grep "config/faiss_index_local/" .gitignore
```

**详细说明**：参见 `索引忽略指引.txt`

---

### 问题3: 索引重建很慢

**原因**：
- 首次重建需要处理所有PDF
- 向量化7774个chunks需要时间

**优化**：
- ✅ 已使用SHA256缓存，第二次重建只需2-3分钟
- ✅ 已使用bge-small-zh-v1.5轻量级模型（2.2秒/批次）
- ✅ 已移除tiny chunks减少向量数量

**进度监控**：
```bash
# 查看详细日志
python quick_rebuild.py 2>&1 | tee rebuild_log.txt
```

---

## 📊 索引统计信息

### 当前索引（2026-01-21）

| 指标 | 数值 |
|------|------|
| 总文档数 | 15个（PDF: 13, TXT: 2） |
| 总chunks | 7774个（PDF: 7706, TXT: 68） |
| 文件大小 | 35MB（16MB + 19MB） |
| Embedding模型 | BAAI/bge-small-zh-v1.5 |
| Chunk大小 | 1500字符 |
| 重叠度 | 150字符 |
| 最小chunk | 50字符（过滤阈值） |

### 性能指标

| 指标 | 数值 |
|------|------|
| 首次重建时间 | 约6分钟 |
| 缓存重建时间 | 约2-3分钟 |
| 向量化速度 | 2.2秒/批次 |
| 检索响应时间 | <100ms |

---

## 🔧 高级操作

### 清除PDF缓存（强制重新处理PDF）

```bash
# 删除SQLite中的PDF缓存
sqlite3 data/customs_audit.db "DELETE FROM pdf_documents;"

# 删除索引
rm -rf config/faiss_index_local/*

# 重建（会重新处理所有PDF）
python quick_rebuild.py
```

### 检查索引健康状态

```python
# 运行健康检查
python -c "
from src.services.knowledge_base import KnowledgeBase
kb = KnowledgeBase()
print(f'索引文档数: {len(kb.vector_store.docstore._dict)}')
"
```

---

## 📝 维护建议

### 定期维护

1. **每月检查**：确认索引文件未被Git跟踪
   ```bash
   git ls-files config/faiss_index_local/
   # 应该返回空
   ```

2. **知识库更新后**：立即重建索引
   ```bash
   python quick_rebuild.py
   ```

3. **切换分支前**：提交当前工作
   ```bash
   git add -A
   git commit -m "save current work"
   ```

### 备份建议

虽然索引不放在Git中，但建议：

1. **本地备份**：定期备份 `config/faiss_index_local/`
2. **云存储**：将索引上传到云盘（非Git仓库）
3. **重建脚本**：保留 `quick_rebuild.py` 和知识库文件

---

## 📚 相关文档

- `索引忽略指引.txt` - Git索引忽略详细说明
- `quick_rebuild.py` - 索引重建脚本
- `src/services/knowledge_base.py` - 知识库实现
- `进度报告/0119_RAG检索优化完成报告.md` - RAG优化详情

---

## 🆘 获取帮助

如果遇到问题：

1. 检查本文档的"常见问题"部分
2. 查看 `索引忽略指引.txt`
3. 运行健康检查脚本
4. 联系技术支持

**最后更新**: 2026-01-21
**维护者**: Claude AI Agent
