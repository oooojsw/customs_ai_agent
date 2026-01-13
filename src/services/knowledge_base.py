import os
import shutil
import asyncio
from pathlib import Path
from langchain_community.document_loaders import TextLoader, DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

class KnowledgeBase:
    def __init__(self):
        # 1. 定义绝对路径
        self.base_dir = Path(__file__).resolve().parent.parent.parent
        self.data_path = self.base_dir / "data" / "knowledge"
        
        # 向量数据库最终保存目录
        self.vector_db_path = self.base_dir / "config" / "faiss_index_local"
        
        # 确保目录存在
        self.vector_db_path.mkdir(parents=True, exist_ok=True)

        print(f"⚙️ [KnowledgeBase] 初始化本地 Embedding 模型 (all-MiniLM-L6-v2)...")
        try:
            self.embeddings = HuggingFaceEmbeddings(
                model_name="all-MiniLM-L6-v2",
                model_kwargs={'device': 'cpu'},
                encode_kwargs={'normalize_embeddings': True}
            )
        except Exception as e:
            print(f"❌ [KnowledgeBase] Embedding 模型加载失败: {e}")
            raise e

        # 加载或重建索引
        self.vector_store = self._load_or_create_index()

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

        # 2. 切分文档
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        chunks = text_splitter.split_documents(documents)
        print(f"📄 [KnowledgeBase] 正在向量化 {len(chunks)} 个文本片段...")

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