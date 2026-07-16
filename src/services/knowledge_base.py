import os
import shutil
import asyncio
import json
import time
import hashlib
import numpy as np
from pathlib import Path
from typing import List, AsyncGenerator, Iterable
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

# PDF处理相关
from src.services.pdf_service import PDFService
from src.database.pdf_repository import PDFRepository

class KnowledgeBase:
    INDEX_SCHEMA_VERSION = 2
    DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
    DEFAULT_EMBEDDING_REVISION = "7999e1d3359715c523056ef9478215996d62a620"
    MANIFEST_FILE = "manifest.json"

    def __init__(
        self,
        process_pdfs: bool = False,
        force_rebuild: bool = False,
    ):
        """
        初始化知识库

        Args:
            process_pdfs: 是否处理PDF文件（默认False，只有前端手动触发时才为True）
        """
        # 1. 定义绝对路径
        self.base_dir = Path(__file__).resolve().parent.parent.parent
        self.data_path = self.base_dir / "data" / "knowledge"

        # 向量数据库最终保存目录
        self.vector_db_path = self.base_dir / "config" / "faiss_index_local"

        # 确保目录存在
        self.vector_db_path.mkdir(parents=True, exist_ok=True)

        # PDF处理配置（默认禁用，只有手动触发时才启用）
        self.process_pdfs = process_pdfs
        self.force_rebuild = force_rebuild
        self.pdf_service = None  # 保留兼容性（废弃）
        self.hybrid_pdf_service = None  # 混合解析服务（延迟初始化）
        self.pdf_repo = PDFRepository()

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

        self.embedding_model_name = os.getenv(
            "KNOWLEDGE_EMBEDDING_MODEL",
            self.DEFAULT_EMBEDDING_MODEL,
        )
        self.embedding_cache_dir = os.getenv("KNOWLEDGE_EMBEDDING_CACHE_DIR")
        self.embedding_model_revision = os.getenv(
            "KNOWLEDGE_EMBEDDING_REVISION",
            self.DEFAULT_EMBEDDING_REVISION,
        )
        self.auto_include_pdfs = os.getenv(
            "KNOWLEDGE_AUTO_INCLUDE_PDFS", "true"
        ).strip().lower() in {"1", "true", "yes", "on"}

        print(
            "[KnowledgeBase] 初始化 Embedding 模型 "
            f"({self.embedding_model_name})..."
        )
        try:
            self.embeddings = HuggingFaceEmbeddings(
                model_name=self.embedding_model_name,
                cache_folder=self.embedding_cache_dir,
                model_kwargs={
                    'device': 'cpu',
                    'revision': self.embedding_model_revision,
                },
                encode_kwargs={'normalize_embeddings': True},
                show_progress=True  # 显示下载进度
            )
        except Exception as e:
            print(f"[错误] [KnowledgeBase] Embedding 模型加载失败: {e}")
            raise e

        # 加载或重建索引
        self.vector_store = self._load_or_create_index()

        # [错误] 不再自动启动后台PDF处理任务，改为用户手动触发
        # self._pdf_task = None
        # if self.process_pdfs:
        #     self._pdf_task = asyncio.create_task(self._process_pdfs_background())

    def _load_or_create_index(self):
        index_file = self.vector_db_path / "index.faiss"
        pickle_file = self.vector_db_path / "index.pkl"
        manifest = self._read_manifest()

        if (
            not self.force_rebuild
            and index_file.exists()
            and pickle_file.exists()
            and self._manifest_is_current(manifest)
        ):
            print("[文件] [KnowledgeBase] 加载本地向量索引 (Hit Cache)...")
            try:
                vector_store = FAISS.load_local(
                    str(self.vector_db_path), 
                    self.embeddings,
                    allow_dangerous_deserialization=True 
                )
                self._normalize_vector_store_metadata(vector_store)
                return vector_store
            except Exception as e:
                print(f"[警告] [KnowledgeBase] 索引文件损坏，正在重建: {e}")
                return self._create_index()

        reason = "已请求强制重建" if self.force_rebuild else "本地无索引"
        if not self.force_rebuild and (index_file.exists() or pickle_file.exists()):
            reason = "索引清单缺失、版本不兼容或知识文件已变化"
        print(f"[设置] [KnowledgeBase] {reason}，正在重建向量数据库...")
        return self._create_index()

    def _read_manifest(self) -> dict | None:
        manifest_path = self.vector_db_path / self.MANIFEST_FILE
        try:
            with manifest_path.open("r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
            return payload if isinstance(payload, dict) else None
        except (OSError, ValueError):
            return None

    def _manifest_is_current(self, manifest: dict | None) -> bool:
        if not manifest:
            return False
        if manifest.get("schema_version") != self.INDEX_SCHEMA_VERSION:
            return False
        if manifest.get("embedding_model") != self.embedding_model_name:
            return False
        if manifest.get("embedding_revision") != self.embedding_model_revision:
            return False
        include_pdfs = bool(manifest.get("includes_pdfs", self.auto_include_pdfs))
        expected = self._knowledge_fingerprint(
            self._scan_indexable_files(include_pdfs=include_pdfs)
        )
        return manifest.get("knowledge_fingerprint") == expected

    def _scan_indexable_files(self, *, include_pdfs: bool) -> List[Path]:
        if not self.data_path.exists():
            return []
        files = []
        for path in self.data_path.rglob("*"):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix in {".txt", ".md"} or suffix == "":
                files.append(path)
            elif include_pdfs and suffix == ".pdf":
                files.append(path)
        return sorted(files, key=lambda item: item.relative_to(self.data_path).as_posix())

    def _knowledge_fingerprint(self, files: Iterable[Path]) -> str:
        digest = hashlib.sha256()
        for path in files:
            digest.update(self._portable_source(path).encode("utf-8"))
            if path.suffix.lower() == ".pdf":
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
            else:
                content = path.read_bytes().replace(b"\r\n", b"\n")
                digest.update(content)
        return digest.hexdigest()

    def _portable_source(self, path: Path) -> str:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(self.base_dir.resolve())
            return relative.as_posix()
        except ValueError:
            return f"data/knowledge/{resolved.name}"

    def _normalize_document_metadata(self, document: Document) -> Document:
        metadata = dict(document.metadata or {})
        raw_source = str(metadata.get("source") or metadata.get("file_path") or "")
        normalized_source = raw_source.replace("\\", "/")
        source_name = str(
            metadata.get("source_name") or normalized_source.rsplit("/", 1)[-1]
        )
        if raw_source:
            raw_path = Path(raw_source)
            marker = "/data/knowledge/"
            if marker in normalized_source.lower():
                marker_index = normalized_source.lower().index(marker)
                source = "data/knowledge/" + normalized_source[
                    marker_index + len(marker):
                ]
            elif raw_path.exists():
                source = self._portable_source(raw_path)
            else:
                source = f"data/knowledge/{source_name}"
        else:
            source = f"data/knowledge/{source_name}" if source_name else "unknown"
        metadata["source"] = source
        metadata["source_name"] = source_name or Path(source).name
        metadata.pop("file_path", None)
        return Document(page_content=document.page_content, metadata=metadata)

    def _normalize_vector_store_metadata(self, vector_store) -> None:
        docstore = getattr(vector_store, "docstore", None)
        documents = getattr(docstore, "_dict", {})
        for key, document in list(documents.items()):
            documents[key] = self._normalize_document_metadata(document)

    def _create_index(self):
        if not self.data_path.exists():
            print(f"[警告] [KnowledgeBase] 数据目录不存在: {self.data_path}，将创建空索引。")
            return FAISS.from_texts(["初始化空白文档"], self.embeddings)

        documents = []
        source_files = self._scan_indexable_files(include_pdfs=self.auto_include_pdfs)
        for file_path in source_files:
            try:
                if file_path.suffix.lower() == ".pdf":
                    text, method = self._extract_pdf_for_index(file_path)
                    if text.strip():
                        documents.append(Document(
                            page_content=text,
                            metadata={
                                "source": self._portable_source(file_path),
                                "source_name": file_path.name,
                                "file_type": "pdf",
                                "extraction_method": method,
                            },
                        ))
                else:
                    loaded = TextLoader(str(file_path), encoding="utf-8").load()
                    documents.extend(self._normalize_document_metadata(doc) for doc in loaded)
            except Exception as e:
                print(f"[警告] [KnowledgeBase] 加载文件 {file_path.name} 出错: {e}")

        if not documents:
            print("[警告] [KnowledgeBase] 未找到文档，创建空索引。")
            vector_store = FAISS.from_texts(["无数据"], self.embeddings)
            self._save_index(vector_store, source_files=[])
            return vector_store

        # 2. 切分文档（增大分块以包含更多上下文）
        # [重要] 关键调整：避免在分号处切分，防止产生只有"；"的碎片chunk
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
                # [错误] 移除"；\n"和"；"，避免在分号处切分产生无意义chunk
                ""            # 最后才按字符切分
            ]
        )
        chunks = text_splitter.split_documents(documents)

        # [重要] 过滤掉小于50字符的低质量chunk（避免"；"等无意义chunk）
        original_count = len(chunks)
        chunks = [c for c in chunks if len(c.page_content) >= 50]
        filtered_count = original_count - len(chunks)
        print(
            f"[文档] [KnowledgeBase] 切分出 {original_count} 个片段，"
            f"过滤 {filtered_count} 个小片段，保留 {len(chunks)} 个有效片段..."
        )

        if not chunks:
            raise RuntimeError("知识文件未生成任何有效向量片段")

        vector_store = FAISS.from_documents(chunks, self.embeddings)
        self._save_index(vector_store, source_files=source_files)
        return vector_store

    def _extract_pdf_for_index(self, pdf_path: Path) -> tuple[str, str]:
        fast_service = PDFService()
        text, _ = fast_service.extract_text(str(pdf_path), validate_quality=False)
        quality_score = self._pdf_text_quality_score(text)
        if quality_score >= 60:
            return text, "pypdfium2"

        from src.services.rapidocr_service import RapidOCRService
        print(f"[KnowledgeBase] {pdf_path.name} 文本层质量不足，切换 RapidOCR")
        ocr_text, _ = RapidOCRService().extract_text(str(pdf_path), True)
        return ocr_text, "rapidocr"

    @staticmethod
    def _pdf_text_quality_score(text: str) -> int:
        char_count = len(text)
        chinese_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
        ratio = chinese_count / char_count if char_count else 0
        score = 50 if char_count > 1000 else 30 if char_count > 500 else 0
        score += 30 if chinese_count > 500 else 0
        score += 20 if ratio > 0.3 else 0
        return score

    def _init_hybrid_pdf_service_if_needed(self):
        """延迟初始化混合PDF服务"""
        if self.hybrid_pdf_service is None and self.process_pdfs:
            try:
                from src.services.hybrid_pdf_service import HybridPDFService
                self.hybrid_pdf_service = HybridPDFService()
                print("[KnowledgeBase] 混合PDF解析服务已初始化")
            except Exception as e:
                print(f"[KnowledgeBase] 混合PDF服务初始化失败，将跳过PDF处理: {e}")
                self.process_pdfs = False

    async def _process_pdfs(self) -> AsyncGenerator[dict, None]:
        """
        处理PDF文件（使用混合解析服务）- 异步生成器版本

        注意：只有通过API手动触发（前端点击）时才会调用此方法
        服务启动时由于process_pdfs=False，不会自动处理

        Yields:
            dict: 包含类型和数据的字典
            - {"type": "log", "payload": {...}} - 进度日志（通过SSE发送到前端）
            - {"type": "result", "doc": Document(...)} - 处理结果（文档对象）
        """
        # 安全检查：确保只有手动触发时才处理
        if not self.process_pdfs:
            print("[KnowledgeBase] PDF处理已禁用（等待手动触发）")
            return

        self._init_hybrid_pdf_service_if_needed()
        if not self.hybrid_pdf_service:
            return

        # 扫描PDF文件
        pdf_files = list(self.data_path.glob("**/*.pdf"))

        if not pdf_files:
            print("[KnowledgeBase] 未发现PDF文件")
            return

        print(f"\n{'='*60}")
        print(f"[KnowledgeBase] 手动触发：开始处理 {len(pdf_files)} 个PDF文件")
        print(f"{'='*60}")

        # 发送开始消息
        yield {
            "type": "log",
            "payload": {
                "type": "step",
                "message": f"开始处理 {len(pdf_files)} 个PDF文件（混合模式：快速提取 + 智能OCR）",
                "step": "processing_pdfs",
                "sub_mode": "hybrid"
            }
        }

        cache_hits = 0
        ocr_triggered = 0
        pypdfium2_count = 0
        processing_errors = 0
        total_chars = 0
        total_time = 0

        for idx, pdf_path in enumerate(pdf_files, 1):
            try:
                file_name = pdf_path.name
                file_size_mb = pdf_path.stat().st_size / (1024 * 1024)

                # 更新进度
                progress = round((idx / len(pdf_files)) * 100, 1)
                yield {
                    "type": "log",
                    "payload": {
                        "type": "progress",
                        "current_file": file_name,
                        "current": idx,
                        "total": len(pdf_files),
                        "percentage": progress
                    }
                }

                # 打印处理开始信息
                print(f"\n{'─'*60}")
                print(f"[PDF {idx}/{len(pdf_files)}] {file_name}")
                print(f"  文件大小: {file_size_mb:.2f} MB")
                print(f"  开始时间: {time.strftime('%H:%M:%S')}")

                # 使用混合解析服务（内部进度回调转换为yield）
                text, method, time_cost = await self._extract_pdf_with_progress(
                    pdf_path, file_name
                )

                char_count = len(text)
                total_chars += char_count
                total_time += time_cost

                # 打印处理完成信息
                print(f"  提取方法: {method}")
                print(f"  文本字符: {char_count:,} 字符")
                print(f"  处理耗时: {time_cost:.2f} 秒")
                print(f"  完成时间: {time.strftime('%H:%M:%S')}")

                # 统计
                if method == "cached":
                    cache_hits += 1
                    print(f"  状态: [缓存命中] ")
                elif method == "pypdfium2":
                    pypdfium2_count += 1
                    print(f"  状态: [快速提取] ")
                elif method == "rapidocr":
                    ocr_triggered += 1
                    print(f"  状态: [OCR识别] ")

                # 创建Document对象并yield
                doc = Document(
                    page_content=text,
                    metadata={
                        "source": self._portable_source(pdf_path),
                        "source_name": file_name,
                        "file_type": "pdf",
                        "char_count": char_count,
                        "extraction_method": method,
                        "processing_time": time_cost
                    }
                )
                yield {
                    "type": "result",
                    "doc": doc
                }

            except Exception as e:
                print(f"  [错误] 处理异常: {e}")
                processing_errors += 1
                yield {
                    "type": "log",
                    "payload": {
                        "type": "error",
                        "file": pdf_path.name,
                        "message": f"处理失败: {str(e)}"
                    }
                }
                continue

        # 统计信息
        print(f"\n{'='*60}")
        print(f"[KnowledgeBase] PDF处理统计报告")
        print(f"{'='*60}")
        print(f"  总文件数: {len(pdf_files)} 个")
        print(f"  └─ 快速提取 (pypdfium2): {pypdfium2_count} 个")
        print(f"  └─ OCR识别 (rapidocr): {ocr_triggered} 个")
        print(f"  └─ 缓存命中 (cached): {cache_hits} 个")
        print(f"  └─ 处理失败: {processing_errors} 个")
        print(f"{'─'*60}")
        print(f"  总字符数: {total_chars:,} 字符")
        print(f"  总耗时: {total_time:.2f} 秒")
        if len(pdf_files) > 0:
            avg_time = total_time / len(pdf_files)
            print(f"  平均耗时: {avg_time:.2f} 秒/文件")
            success_rate = ((len(pdf_files)-processing_errors)/len(pdf_files)*100)
            print(f"  成功率: {success_rate:.1f}%")
        print(f"{'='*60}\n")

    async def _extract_pdf_with_progress(
        self,
        pdf_path: Path,
        file_name: str
    ) -> tuple[str, str, float]:
        """
        提取PDF文本，并在处理过程中yield OCR进度

        Args:
            pdf_path: PDF文件路径
            file_name: 文件名

        Returns:
            (text, method, time_cost)
        """
        # 使用混合解析服务
        text, method, time_cost = await self.hybrid_pdf_service.extract_text_with_fallback(
            str(pdf_path),
            progress_callback=lambda msg: None  # 不使用回调，改为内部处理
        )

        return text, method, time_cost

    async def _process_pdfs_background(self):
        """后台异步处理PDF任务"""
        try:
            # 等待一段时间，让主服务先启动
            await asyncio.sleep(5)

            print("[设置] [KnowledgeBase] 后台任务: 开始处理PDF文件...")
            pdf_docs = []
            async for event in self._process_pdfs():
                if event.get("type") == "result":
                    pdf_docs.append(event["doc"])

            if pdf_docs:
                # 将PDF文档添加到现有索引
                print(f"[设置] [KnowledgeBase] 正在添加 {len(pdf_docs)} 个PDF文档到索引...")

                # 切分PDF文本（优化分隔符，避免在分号处切分）
                text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=1500,
                    chunk_overlap=150,
                    separators=[
                        "。\n", "！\n", "？\n",
                        "\n\n\n", "\n\n", "\n",
                        "。", "！", "？",
                        "，", " ",
                        # [错误] 移除"；\n"和"；"，避免在分号处切分产生无意义chunk
                        ""
                    ]
                )
                chunks = text_splitter.split_documents(pdf_docs)

                # [重要] 过滤掉小于50字符的低质量chunk
                original_count = len(chunks)
                chunks = [c for c in chunks if len(c.page_content) >= 50]
                print(
                    f"[文档] 过滤: {original_count} → {len(chunks)} 个chunk"
                    f"（过滤了{original_count - len(chunks)}个小片段）"
                )

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
                print(f"[成功] [KnowledgeBase] PDF索引更新完成 ({len(chunks)}个片段)")
            else:
                print("[信息] [KnowledgeBase] 无PDF文件需要处理")

        except Exception as e:
            print(f"[错误] [KnowledgeBase] PDF后台任务失败: {e}")
            import traceback
            traceback.print_exc()

    def _save_index(self, vector_store, source_files: Iterable[Path] | None = None):
        """原子保存FAISS索引及可迁移清单。"""
        source_files = list(
            source_files
            if source_files is not None
            else self._scan_indexable_files(include_pdfs=self.auto_include_pdfs)
        )
        self._normalize_vector_store_metadata(vector_store)
        try:
            temp_path = self.vector_db_path.parent / (
                f".{self.vector_db_path.name}.building-{os.getpid()}"
            )

            if temp_path.exists():
                shutil.rmtree(temp_path)

            # 保存到临时目录
            vector_store.save_local(str(temp_path))

            self.vector_db_path.mkdir(parents=True, exist_ok=True)

            manifest = {
                "schema_version": self.INDEX_SCHEMA_VERSION,
                "embedding_model": self.embedding_model_name,
                "embedding_revision": self.embedding_model_revision,
                "knowledge_fingerprint": self._knowledge_fingerprint(source_files),
                "source_count": len(source_files),
                "vector_count": int(vector_store.index.ntotal),
                "includes_pdfs": any(path.suffix.lower() == ".pdf" for path in source_files),
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "sources": [
                    self._portable_source(path) for path in source_files
                ],
            }
            with (temp_path / self.MANIFEST_FILE).open("w", encoding="utf-8") as handle:
                json.dump(manifest, handle, ensure_ascii=False, indent=2)

            # manifest最后替换；进程中断时不会把半套索引标记为可用。
            for file_name in ("index.faiss", "index.pkl", self.MANIFEST_FILE):
                os.replace(temp_path / file_name, self.vector_db_path / file_name)

            shutil.rmtree(temp_path)
            print(f"[保存] [KnowledgeBase] 索引已保存至: {self.vector_db_path}")
        except Exception as e:
            print(f"[错误] [KnowledgeBase] 保存索引失败: {e}")
            raise

    def get_retriever(self):
        return self.vector_store.as_retriever(search_kwargs={"k": 3})

    # [重要][重要][重要] 优化后的搜索方法 [重要][重要][重要]
    async def search_with_score(self, query: str, k: int = 6):
        """
        异步执行向量检索并返回真实相似度分数
        """
        if not self.vector_store:
            return []

        # [成功] 关键优化：将同步的 FAISS 搜索放入线程池，防止阻塞 FastAPI 主循环
        try:
            results = await asyncio.to_thread(
                self.vector_store.similarity_search_with_score, 
                query, 
                k=k
            )
        except Exception as e:
            print(f"[错误] [KnowledgeBase] 搜索出错: {e}")
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

    def get_index_health(self) -> dict:
        """返回可用于部署检查的索引完整性信息。"""
        manifest = self._read_manifest()
        include_pdfs = bool(
            manifest.get("includes_pdfs", self.auto_include_pdfs)
        ) if manifest else self.auto_include_pdfs
        source_files = self._scan_indexable_files(include_pdfs=include_pdfs)
        is_current = self._manifest_is_current(manifest)
        vector_count = int(self.vector_store.index.ntotal) if self.vector_store else 0
        return {
            "ready": bool(self.vector_store) and is_current and vector_count > 0,
            "portable": bool(manifest)
            and manifest.get("schema_version") == self.INDEX_SCHEMA_VERSION,
            "schema_version": manifest.get("schema_version") if manifest else None,
            "embedding_model": self.embedding_model_name,
            "embedding_revision": self.embedding_model_revision,
            "vector_count": vector_count,
            "indexed_source_count": manifest.get("source_count", 0) if manifest else 0,
            "available_source_count": len(source_files),
            "includes_pdfs": include_pdfs,
            "stale": not is_current,
            "manifest_path": str(self.vector_db_path / self.MANIFEST_FILE),
        }

    # ==========================================
    # 索引管理功能 (手动重建索引)
    # ==========================================

    def _format_sse(self, data: dict) -> str:
        """格式化SSE事件"""
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    def _scan_knowledge_files(self) -> List[Path]:
        """扫描文本、无扩展名知识文件和PDF。"""
        return self._scan_indexable_files(include_pdfs=True)

    async def rebuild_index_stream(
        self,
        force_process_pdfs: bool = True,
    ) -> AsyncGenerator[str, None]:
        """
        流式重建索引（手动触发）

        Args:
            force_process_pdfs: 强制处理PDF（默认True，因为这是手动触发）

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
            # 临时启用PDF处理（手动触发）
            original_process_pdfs = self.process_pdfs
            self.process_pdfs = force_process_pdfs

            # 1. 初始化事件
            yield self._format_sse({
                "type": "init",
                "message": "开始重建知识库索引（手动触发）"
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
            txt_files = [
                f for f in files if f.suffix.lower() in [".txt", ".md", ""]
            ]

            self.progress["total"] = total_files
            self.file_count = total_files

            yield self._format_sse({
                "type": "step",
                "message": f"发现 {total_files} 个文件（PDF: {len(pdf_files)}, 文本: {len(txt_files)}）",
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
                    documents.extend(
                        self._normalize_document_metadata(doc) for doc in docs
                    )

                except Exception as e:
                    print(f"[警告] [KnowledgeBase] 加载文件 {file_path.name} 失败: {e}")
                    continue

            # 再处理PDF文件（使用混合解析服务）
            if pdf_files and self.process_pdfs:
                yield self._format_sse({
                    "type": "step",
                    "message": f"正在处理 {len(pdf_files)} 个PDF文件（混合模式：快速提取 + 智能OCR）...",
                    "step": "processing_pdfs",
                    "sub_mode": "hybrid",
                    "pdf_count": len(pdf_files)
                })

                # 使用混合解析服务处理PDF（异步生成器模式）
                pdf_documents = []
                async for event in self._process_pdfs():
                    if event["type"] == "log":
                        # 将进度通过 SSE 发送到前端
                        yield self._format_sse(event["payload"])
                    elif event["type"] == "result":
                        # 累积最终需要的文档对象
                        pdf_documents.append(event["doc"])

                documents.extend(pdf_documents)

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

            documents = [
                self._normalize_document_metadata(doc) for doc in documents
            ]
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
                vector_store,
                files,
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
            # 恢复原始设置
            self.process_pdfs = original_process_pdfs

            async with self._rebuild_lock:
                self.is_rebuilding = False
                self._rebuild_cancelled = False

    def cancel_rebuild(self):
        """取消索引重建任务"""
        self._rebuild_cancelled = True
