import os
import shutil
import asyncio
import json
import numpy as np
from pathlib import Path
from typing import List, AsyncGenerator
from langchain_community.document_loaders import TextLoader, DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

# PDF处理相关
from src.services.pdf_service import PDFService, PDFProcessingError
from src.database.pdf_repository import PDFRepository

class KnowledgeBase:
    def __init__(self, process_pdfs: bool = True):
        # 1. 定义绝对路径
        self.base_dir = Path(__file__).resolve().parent.parent.parent
        self.data_path = self.base_dir / "data" / "knowledge"

        # 向量数据库最终保存目录
        self.vector_db_path = self.base_dir / "config" / "faiss_index_local"

        # 确保目录存在
        self.vector_db_path.mkdir(parents=True, exist_ok=True)

        # PDF处理配置
        self.process_pdfs = process_pdfs
        self.pdf_service = None  # 延迟初始化
        self.pdf_repo = PDFRepository() if process_pdfs else None

        # 索引状态管理
        self.is_rebuilding = False
        self._rebuild_cancelled = False
        self.progress = {
            "current": 0,
            "total": 0,
            "current_file": "",
            "percentage": 0.0
        }
        self.last_rebuild_time = None
        self.file_count = 0
        self._rebuild_lock = asyncio.Lock()

        print(f"⚙️ [KnowledgeBase] 初始化中文 Embedding 模型 (bge-small-zh-v1.5 轻量版)...")
        try:
            self.embeddings = HuggingFaceEmbeddings(
                model_name="BAAI/bge-small-zh-v1.5",
                model_kwargs={'device': 'cpu'},
                encode_kwargs={'normalize_embeddings': True},
                show_progress=True  # 显示下载进度
            )
        except Exception as e:
            print(f"❌ [KnowledgeBase] Embedding 模型加载失败: {e}")
            raise e

        # 加载或重建索引
        self.vector_store = self._load_or_create_index()

        # ❌ 不再自动启动后台PDF处理任务，改为用户手动触发
        # self._pdf_task = None
        # if self.process_pdfs:
        #     self._pdf_task = asyncio.create_task(self._process_pdfs_background())

    def _load_or_create_index(self):
        # 检查索引文件是否存在
        index_file = self.vector_db_path / "index.faiss"
        
        if index_file.exists():
            print("📂 [KnowledgeBase] 加载本地向量索引 (Hit Cache)...")
            try:
                return FAISS.load_local(
                    str(self.vector_db_path), 
                    self.embeddings,
                    allow_dangerous_deserialization=True 
                )
            except Exception as e:
                print(f"⚠️ [KnowledgeBase] 索引文件损坏，正在重建: {e}")
                return self._create_index()
        else:
            print("⚙️ [KnowledgeBase] 本地无索引，正在重建向量数据库...")
            return self._create_index()

    def _create_index(self):
        if not self.data_path.exists():
            print(f"⚠️ [KnowledgeBase] 数据目录不存在: {self.data_path}，将创建空索引。")
            return FAISS.from_texts(["初始化空白文档"], self.embeddings)

        # 1. 加载文档
        loaders = [
            DirectoryLoader(str(self.data_path), glob="**/*.txt", loader_cls=TextLoader, loader_kwargs={"encoding": "utf-8"}),
            DirectoryLoader(str(self.data_path), glob="**/*.md", loader_cls=TextLoader, loader_kwargs={"encoding": "utf-8"}),
        ]
        
        documents = []
        for loader in loaders:
            try:
                documents.extend(loader.load())
            except Exception as e:
                print(f"⚠️ [KnowledgeBase] 加载文件出错: {e}")

        if not documents:
            print("⚠️ [KnowledgeBase] 未找到文档，创建空索引。")
            return FAISS.from_texts(["无数据"], self.embeddings)

        # 2. 切分文档（增大分块以包含更多上下文）
        # 🔥 关键调整：避免在分号处切分，防止产生只有"；"的碎片chunk
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1500,  # 增加到 1500 字符，确保包含完整的段落
            chunk_overlap=150,  # 增加重叠以保持上下文连贯性
            separators=[
                "。\n",        # 优先：句子结束+换行
                "！\n",        # 感叹句结束+换行
                "？\n",        # 问句结束+换行
                "\n\n\n",      # 三个换行（章节标题后）
                "\n\n",        # 两个换行（段落之间）
                "\n",          # 单个换行
                "。",          # 句号
                "！",          # 感叹号
                "？",          # 问号
                "，",          # 逗号
                " ",          # 空格
                # ❌ 移除"；\n"和"；"，避免在分号处切分产生无意义chunk
                ""            # 最后才按字符切分
            ]
        )
        chunks = text_splitter.split_documents(documents)

        # 🔥 过滤掉小于50字符的低质量chunk（避免"；"等无意义chunk）
        original_count = len(chunks)
        chunks = [c for c in chunks if len(c.page_content) >= 50]
        filtered_count = original_count - len(chunks)
        print(f"📄 [KnowledgeBase] 切分出 {original_count} 个片段，过滤 {filtered_count} 个小片段，保留 {len(chunks)} 个有效片段...")

        # 3. 创建向量库 (内存中)
        vector_store = FAISS.from_documents(chunks, self.embeddings)

        # 4. 保存到本地 (Windows 路径兼容性修复)
        try:
            # 定义临时目录
            temp_dir_name = "temp_faiss_build"
            temp_path = self.base_dir / temp_dir_name
            
            if temp_path.exists():
                shutil.rmtree(temp_path)

            # 保存到临时目录
            vector_store.save_local(str(temp_path))

            # 搬运
            if self.vector_db_path.exists():
                shutil.rmtree(self.vector_db_path)
            self.vector_db_path.mkdir(parents=True, exist_ok=True)

            for file_name in os.listdir(temp_path):
                shutil.move(str(temp_path / file_name), str(self.vector_db_path / file_name))

            shutil.rmtree(temp_path)
            print(f"💾 [KnowledgeBase] 索引已保存至: {self.vector_db_path}")
        except Exception as e:
            print(f"❌ [KnowledgeBase] 保存索引失败: {e}")
        
        return vector_store

    def _init_pdf_service_if_needed(self):
        """延迟初始化PDF服务"""
        if self.pdf_service is None and self.process_pdfs:
            try:
                self.pdf_service = PDFService()
            except Exception as e:
                print(f"[KnowledgeBase] PDF服务初始化失败，将跳过PDF处理: {e}")
                self.process_pdfs = False

    async def _process_pdfs(self) -> List[Document]:
        """
        处理所有PDF文件

        流程：
        1. 扫描data/knowledge/目录下的所有PDF
        2. 对每个PDF：
           a. 计算文件哈希
           b. 查询SQLite缓存
           c. 如果缓存有效 → 使用缓存
           d. 如果缓存无效 → 调用Marker提取
           e. 保存缓存
        3. 返回Document列表

        Returns:
            List[Document]: 包含所有PDF文本的Document对象列表
        """
        if not self.process_pdfs:
            return []

        self._init_pdf_service_if_needed()
        if not self.pdf_service:
            return []

        # 扫描PDF文件
        pdf_files = list(self.data_path.glob("**/*.pdf"))

        if not pdf_files:
            print("📂 [KnowledgeBase] 未发现PDF文件")
            return []

        print(f"📄 [KnowledgeBase] 发现 {len(pdf_files)} 个PDF文件")

        documents = []
        cache_hits = 0
        cache_misses = 0
        processing_errors = 0

        for idx, pdf_path in enumerate(pdf_files, 1):
            try:
                # 相对路径 (用于存储)
                rel_path = str(pdf_path.relative_to(self.base_dir))
                file_name = pdf_path.name
                file_size = pdf_path.stat().st_size

                print(f"\n📄 [{idx}/{len(pdf_files)}] 处理: {file_name}")

                # 1. 计算文件哈希
                print(f"   计算 SHA256 哈希...")
                file_hash = await asyncio.to_thread(
                    PDFService.calculate_file_hash,
                    str(pdf_path)
                )

                # 2. 查询缓存
                print(f"   💾 查询缓存...")
                cached_doc = await self.pdf_repo.get_by_hash(file_hash)

                # 3. 判断缓存是否有效
                if cached_doc and cached_doc.is_valid:
                    print(f"   ✅ 缓存命中 ({cached_doc.char_count}字符)")
                    cache_hits += 1
                    markdown_text = cached_doc.processed_text
                else:
                    print(f"   ⚠️ 缓存未命中，调用Marker提取...")
                    cache_misses += 1

                    # 调用PDF服务提取
                    try:
                        markdown_text, processing_time = await self.pdf_service.extract_text_async(
                            str(pdf_path),
                            validate_quality=True
                        )

                        # 保存缓存
                        await self.pdf_repo.save_cache(
                            file_path=rel_path,
                            file_name=file_name,
                            file_hash=file_hash,
                            file_size=file_size,
                            processed_text=markdown_text,
                            processing_time=processing_time,
                            marker_version="0.3.2"
                        )
                        print(f"   💾 缓存已保存")

                    except PDFProcessingError as e:
                        print(f"   [PDF] 处理失败: {e}")
                        processing_errors += 1
                        continue

                # 4. 创建Document对象
                doc = Document(
                    page_content=markdown_text,
                    metadata={
                        "source": file_name,
                        "file_path": rel_path,
                        "file_type": "pdf",
                        "char_count": len(markdown_text),
                        "file_hash": file_hash
                    }
                )
                documents.append(doc)

            except Exception as e:
                print(f"   ❌ 处理异常: {e}")
                processing_errors += 1
                continue

        # 统计信息
        print(f"\n{'='*60}")
        print(f"📊 [KnowledgeBase] PDF处理统计:")
        print(f"   总文件数: {len(pdf_files)}")
        print(f"   缓存命中: {cache_hits}")
        print(f"   新处理: {cache_misses}")
        print(f"   处理失败: {processing_errors}")
        if len(pdf_files) > 0:
            print(f"   成功率: {((len(pdf_files)-processing_errors)/len(pdf_files)*100):.1f}%")
        print(f"{'='*60}\n")

        return documents

    async def _process_pdfs_background(self):
        """后台异步处理PDF任务"""
        try:
            # 等待一段时间，让主服务先启动
            await asyncio.sleep(5)

            print("⚙️ [KnowledgeBase] 后台任务: 开始处理PDF文件...")
            pdf_docs = await self._process_pdfs()

            if pdf_docs:
                # 将PDF文档添加到现有索引
                print(f"⚙️ [KnowledgeBase] 正在添加 {len(pdf_docs)} 个PDF文档到索引...")

                # 切分PDF文本（优化分隔符，避免在分号处切分）
                text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=1500,
                    chunk_overlap=150,
                    separators=[
                        "。\n", "！\n", "？\n",
                        "\n\n\n", "\n\n", "\n",
                        "。", "！", "？",
                        "，", " ",
                        # ❌ 移除"；\n"和"；"，避免在分号处切分产生无意义chunk
                        ""
                    ]
                )
                chunks = text_splitter.split_documents(pdf_docs)

                # 🔥 过滤掉小于50字符的低质量chunk
                original_count = len(chunks)
                chunks = [c for c in chunks if len(c.page_content) >= 50]
                print(f"📄 过滤: {original_count} → {len(chunks)} 个chunk（过滤了{original_count - len(chunks)}个小片段）")

                # 向量化
                new_vector_store = await asyncio.to_thread(
                    FAISS.from_documents,
                    chunks,
                    self.embeddings
                )

                # 合并索引
                self.vector_store.merge_from(new_vector_store)

                # 保存索引
                await asyncio.to_thread(
                    self._save_index,
                    self.vector_store
                )
                print(f"✅ [KnowledgeBase] PDF索引更新完成 ({len(chunks)}个片段)")
            else:
                print("ℹ️ [KnowledgeBase] 无PDF文件需要处理")

        except Exception as e:
            print(f"❌ [KnowledgeBase] PDF后台任务失败: {e}")
            import traceback
            traceback.print_exc()

    def _save_index(self, vector_store):
        """保存FAISS索引到本地"""
        try:
            # 定义临时目录
            temp_dir_name = "temp_faiss_build"
            temp_path = self.base_dir / temp_dir_name

            if temp_path.exists():
                shutil.rmtree(temp_path)

            # 保存到临时目录
            vector_store.save_local(str(temp_path))

            # 搬运
            if self.vector_db_path.exists():
                shutil.rmtree(self.vector_db_path)
            self.vector_db_path.mkdir(parents=True, exist_ok=True)

            for file_name in os.listdir(temp_path):
                shutil.move(str(temp_path / file_name), str(self.vector_db_path / file_name))

            shutil.rmtree(temp_path)
            print(f"💾 [KnowledgeBase] 索引已保存至: {self.vector_db_path}")
        except Exception as e:
            print(f"❌ [KnowledgeBase] 保存索引失败: {e}")

    def get_retriever(self):
        return self.vector_store.as_retriever(search_kwargs={"k": 3})

    # 🔥🔥🔥 优化后的搜索方法 🔥🔥🔥
    async def search_with_score(self, query: str, k: int = 6):
        """
        异步执行向量检索并返回真实相似度分数
        """
        if not self.vector_store:
            return []

        # ✅ 关键优化：将同步的 FAISS 搜索放入线程池，防止阻塞 FastAPI 主循环
        try:
            results = await asyncio.to_thread(
                self.vector_store.similarity_search_with_score, 
                query, 
                k=k
            )
        except Exception as e:
            print(f"❌ [KnowledgeBase] 搜索出错: {e}")
            return []

        import math
        processed_results = []
        for doc, squared_distance in results:
            # FAISS L2 距离转换相似度算法
            distance = math.sqrt(max(0, float(squared_distance)))
            distance = min(distance, 2.0)
            similarity = float((1 - distance / 2))
            processed_results.append((doc, similarity))

        return processed_results

    # ==========================================
    # 索引管理功能 (手动重建索引)
    # ==========================================

    def _format_sse(self, data: dict) -> str:
        """格式化SSE事件"""
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    def _scan_knowledge_files(self) -> List[Path]:
        """扫描知识库目录下的所有 .txt, .md 和 .pdf 文件"""
        files = []
        if self.data_path.exists():
            files = list(self.data_path.glob("**/*.txt")) + list(self.data_path.glob("**/*.md")) + list(self.data_path.glob("**/*.pdf"))
        return files

    async def rebuild_index_stream(self) -> AsyncGenerator[str, None]:
        """
        流式重建索引 (SSE响应)

        Yields:
            str: SSE格式的JSON事件
        """
        async with self._rebuild_lock:
            if self.is_rebuilding:
                yield self._format_sse({
                    "type": "error",
                    "message": "索引重建任务正在进行中，请稍后再试"
                })
                return

            self.is_rebuilding = True
            self._rebuild_cancelled = False

        try:
            # 1. 初始化事件
            yield self._format_sse({
                "type": "init",
                "message": "开始重建知识库索引"
            })

            # 2. 扫描文件
            files = self._scan_knowledge_files()
            total_files = len(files)

            if total_files == 0:
                yield self._format_sse({
                    "type": "complete",
                    "message": "未找到知识库文件",
                    "stats": {"total_files": 0, "total_chunks": 0}
                })
                return

            # 分类文件
            pdf_files = [f for f in files if f.suffix.lower() == '.pdf']
            txt_files = [f for f in files if f.suffix.lower() in ['.txt', '.md']]

            self.progress["total"] = total_files
            self.file_count = total_files

            yield self._format_sse({
                "type": "step",
                "message": f"发现 {total_files} 个文件，开始处理...",
                "step": "scanning"
            })

            # 3. 加载文档
            yield self._format_sse({
                "type": "step",
                "message": "正在加载文档...",
                "step": "loading"
            })

            documents = []

            # 先处理txt/md文件
            for idx, file_path in enumerate(txt_files, 1):
                # 检查是否取消
                if self._rebuild_cancelled:
                    yield self._format_sse({
                        "type": "cancelled",
                        "message": "索引重建已取消"
                    })
                    return

                try:
                    # 更新进度
                    self.progress["current"] = idx
                    self.progress["current_file"] = file_path.name
                    self.progress["percentage"] = round((idx / total_files) * 50, 1)  # txt文件占前50%

                    yield self._format_sse({
                        "type": "progress",
                        "current": idx,
                        "total": total_files,
                        "current_file": file_path.name,
                        "percentage": self.progress["percentage"]
                    })

                    # 加载文档
                    loader = TextLoader(str(file_path), encoding="utf-8")
                    docs = loader.load()
                    documents.extend(docs)

                except Exception as e:
                    print(f"⚠️ [KnowledgeBase] 加载文件 {file_path.name} 失败: {e}")
                    continue

            # 再处理PDF文件
            if pdf_files and self.process_pdfs:
                yield self._format_sse({
                    "type": "step",
                    "message": f"正在处理 {len(pdf_files)} 个PDF文件...",
                    "step": "processing_pdfs"
                })

                for idx, file_path in enumerate(pdf_files, 1):
                    # 检查是否取消
                    if self._rebuild_cancelled:
                        yield self._format_sse({
                            "type": "cancelled",
                            "message": "索引重建已取消"
                        })
                        return

                    try:
                        # 更新进度（PDF文件占后50%）
                        pdf_progress = 50 + round((idx / len(pdf_files)) * 50, 1)
                        self.progress["current"] = len(txt_files) + idx
                        self.progress["current_file"] = file_path.name
                        self.progress["percentage"] = pdf_progress

                        yield self._format_sse({
                            "type": "progress",
                            "current": len(txt_files) + idx,
                            "total": total_files,
                            "current_file": file_path.name,
                            "percentage": pdf_progress
                        })

                        # 处理PDF
                        if self.pdf_service is None:
                            from src.services.pdf_service import PDFService
                            self.pdf_service = PDFService()

                        pdf_text, _ = await asyncio.to_thread(
                            self.pdf_service.extract_text,
                            str(file_path)
                        )

                        if pdf_text and len(pdf_text.strip()) > 100:
                            doc = Document(page_content=pdf_text, metadata={"source": file_path.name})
                            documents.append(doc)

                    except Exception as e:
                        print(f"⚠️ [KnowledgeBase] 处理PDF {file_path.name} 失败: {e}")
                        continue

            if not documents:
                yield self._format_sse({
                    "type": "complete",
                    "message": "未加载到有效文档",
                    "stats": {"total_files": total_files, "total_chunks": 0}
                })
                return

            # 4. 切分文档
            yield self._format_sse({
                "type": "step",
                "message": "正在切分文档...",
                "step": "splitting"
            })

            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=1500,
                chunk_overlap=150,
                separators=[
                    "。\n", "！\n", "？\n",
                    "\n\n\n", "\n\n", "\n",
                    "。", "！", "？",
                    "，", " ",
                    ""
                ]
            )

            chunks = text_splitter.split_documents(documents)
            original_count = len(chunks)
            chunks = [c for c in chunks if len(c.page_content) >= 50]
            filtered_count = original_count - len(chunks)

            # 5. 向量化（手动实现以发送进度）
            from langchain_community.docstore.in_memory import InMemoryDocstore
            import faiss

            # 计算embeddings
            batch_size = 100
            all_embeddings = []
            total_chunks = len(chunks)
            total_batches = (total_chunks + batch_size - 1) // batch_size

            yield self._format_sse({
                "type": "embedding_start",
                "message": f"正在向量化 {len(chunks)} 个片段...",
                "total_chunks": total_chunks,
                "total_batches": total_batches
            })

            for batch_num, i in enumerate(range(0, total_chunks, batch_size), 1):
                batch = chunks[i:i + batch_size]
                batch_texts = [doc.page_content for doc in batch]

                # 在线程池中计算embeddings
                batch_embeddings = await asyncio.to_thread(
                    self.embeddings.embed_documents,
                    batch_texts
                )
                all_embeddings.extend(batch_embeddings)

                # 发送进度（批次号）
                progress = min(100, round((i + len(batch)) / total_chunks * 100, 1))
                yield self._format_sse({
                    "type": "embedding_progress",
                    "batch_num": batch_num,
                    "total_batches": total_batches,
                    "percentage": progress
                })

            # 创建FAISS索引
            embedding_dim = len(all_embeddings[0])
            index = faiss.IndexFlatL2(embedding_dim)
            index.add(np.array(all_embeddings).astype('float32'))

            # 创建docstore
            docstore = InMemoryDocstore(
                {i: doc for i, doc in enumerate(chunks)}
            )
            index_to_docstore_id = {i: i for i in range(len(chunks))}

            # 创建VectorStore
            vector_store = FAISS(
                index=index,
                docstore=docstore,
                index_to_docstore_id=index_to_docstore_id,
                embedding_function=self.embeddings.embed_query
            )

            # 6. 保存索引
            yield self._format_sse({
                "type": "step",
                "message": "正在保存索引...",
                "step": "saving"
            })

            await asyncio.to_thread(
                self._save_index,
                vector_store
            )

            # 更新当前向量库
            self.vector_store = vector_store
            self.last_rebuild_time = asyncio.get_event_loop().time()

            # 7. 完成事件
            yield self._format_sse({
                "type": "complete",
                "message": "索引重建完成",
                "stats": {
                    "total_files": total_files,
                    "txt_files": len(txt_files),
                    "pdf_files": len(pdf_files),
                    "total_chunks": len(chunks),
                    "filtered_chunks": filtered_count
                }
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            yield self._format_sse({
                "type": "error",
                "message": f"索引重建失败: {str(e)}"
            })

        finally:
            async with self._rebuild_lock:
                self.is_rebuilding = False
                self._rebuild_cancelled = False

    def cancel_rebuild(self):
        """取消索引重建任务"""
        self._rebuild_cancelled = True