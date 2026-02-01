这份文档是为 Cursor 量身定制的**“RAG 系统全自动 OCR 补全计划”**。它将指导 Cursor 如何将“沉睡”在测试文件夹中的 OCR 能力，正式接入到生产环境的 PDF 处理链路中，并利用三层缓存架构（Hash -> SQLite -> FAISS）确保性能。

📑 最终任务指令书：RAG 知识库“混合动力解析”与扫描件 OCR 全自动集成规范
1. 核心目标

解决当前 RAG 系统对“扫描件 PDF（纯图片 PDF）”无法识别的问题。
核心逻辑：建立 “快速提取 -> 质量评估 -> 自动补回 -> 深度 OCR” 的混合解析引擎。

2. 基础设施迁移 (Component Migration)

请 Cursor 执行以下文件操作，将测试代码转为生产代码：

移动服务文件：

从 测试文件_无用文件/test_services/rapidocr_service.py 移动并覆盖至 src/services/rapidocr_service.py。

注意：优先选择 RapidOCR，因为它在 CPU 环境下速度最快，且无需复杂的显卡驱动配置。

依赖库补全：

确保 requirements.txt 包含：rapidocr_onnxruntime, pymupdf (即 fitz), opencv-python-headless。

3. 改造 PDFService：实现“混合引擎”逻辑

文件路径：src/services/pdf_service.py

请重写 extract_text 方法，实现以下像素级逻辑：

3.1 初始化增强

在 __init__ 中，除了 pypdfium2，还需实例化 RapidOCRService。

3.2 提取算法流 (Algorithm Flow)

阶段 A (尝试文本层提取)：使用 pypdfium2 进行快速解析。

阶段 B (质量质检点)：

计算提取到的 text 长度。

判定标准：如果 len(text) < 150（不足以构成一页有效报关法律条文）。

阶段 C (自动回退并 OCR)：

若阶段 B 判定不合格，打印日志：[PDF-Hybrid] 检测到疑似扫描件，内容长度不足，正在触发深度 OCR 补偿...。

调用 RapidOCRService.extract_text。

提取逻辑：

使用 PyMuPDF 将 PDF 每一页渲染为高质量图片（DPI 建议 200）。

调用 RapidOCR 识别图片中的中文字符。

合并各页结果为 Markdown。

阶段 D (返回结果)：将 OCR 生成的长文本作为最终内容返回。

4. 优化 KnowledgeBase：实现异步初始化与流式反馈

文件路径：src/services/knowledge_base.py

4.1 异步处理规范

由于 OCR 非常耗时（单个大文件可能需要 20-60 秒），禁止阻塞主线程。

指令：在 _process_pdfs 方法中，调用 pdf_service.extract_text_async（这是异步方法）。

并发控制：为防止 OCR 瞬间撑爆 CPU，使用 asyncio.Semaphore(2) 限制同时进行 OCR 的文件数量。

4.2 索引重建流 (SSE Stream) 增强

用户在前端点击“重建索引”时，应能看到 OCR 的进度。

指令：在 rebuild_index_stream 方法中，针对 PDF 处理步骤，增加细分事件：

code
JSON
download
content_copy
expand_less
{ "type": "step", "message": "正在对扫描件 [xxx.pdf] 进行深度 OCR 识别，请耐心等待...", "step": "ocr_processing" }
5. 存储与缓存链路闭环 (Persistence)

必须确保 OCR 后的昂贵结果被永久保存，避免下次启动重复处理。

逻辑自查：

KnowledgeBase 获取文件 SHA256。

查询 pdf_documents 表。

若哈希匹配，直接从 processed_text 字段提取 OCR 后的文本。

若哈希不匹配（新文件），执行混合解析流程，最后调用 pdf_repo.save_cache。

字段映射：确保 pdf_documents 表的 marker_version 字段能记录是 pypdfium2 提取的还是 RapidOCR 提取的，方便后期审计。

6. L4 导出脚本兼容性检查 (Document Exporter)

文件路径：data/skills/document_exporter/scripts/export_engine.py

任务：检查该脚本对 OCR 产生的内容是否兼容。

规范：OCR 生成的 Markdown 有时会包含大量的换行符或表格乱码。请在脚本中加入简单的 text.strip() 和正则清理逻辑，确保导出的 Word 文档不会因为 OCR 产生的多余空行而显得松散。

7. 验收与冒烟测试用例 (Test Cases)

请让 Cursor 编写并在 tests/test_hybrid_pdf.py 中实现：

文字 PDF 测试：

输入：中华人民共和国海关法.pdf (文字版)。

预期：耗时 < 3s，使用 pypdfium2 快速通道。

扫描 PDF 测试：

输入：一份只有图片的 PDF 文件。

预期：触发 OCR 通道，日志显示“深度 OCR 补偿”，耗时 > 10s，最终提取到文字。

缓存命中测试：

操作：在完成测试 2 后重启服务。

预期：耗时 < 1s，直接从 SQLite 返回 OCR 结果。

💡 给 Cursor 的专家建议

PyMuPDF 导入：在代码中使用 import fitz 并在注释里注明 pip install pymupdf。

内存管理：OCR 图片非常占内存，处理完一个 PDF 后，必须显式调用 del images 并进行 gc.collect()。

字段长度：SQLite 的 TEXT 字段支持几百万字，不用担心报关单目录过长存不下。

请 Cursor 立即开始：先迁移 rapidocr_service.py，然后重写 pdf_service.py 的核心逻辑，最后运行测试验证缓存命中。