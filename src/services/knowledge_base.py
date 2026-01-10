import os
import shutil
from pathlib import Path
from langchain_community.document_loaders import TextLoader, DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS

class KnowledgeBase:
    def __init__(self):
        # 1. 定义绝对路径
        # __file__ 是当前脚本文件的路径
        # .parent.parent.parent 回退三层找到项目根目录
        self.base_dir = Path(__file__).resolve().parent.parent.parent
        self.data_path = self.base_dir / "data" / "knowledge"
        
        # 向量数据库最终保存目录
        self.vector_db_path = self.base_dir / "config" / "faiss_index_local"
        
        # 确保目录存在
        self.vector_db_path.mkdir(parents=True, exist_ok=True)

        print(f"⚙️ [KnowledgeBase] 初始化本地 Embedding 模型 (all-MiniLM-L6-v2)...")
        self.embeddings = HuggingFaceEmbeddings(
            model_name="all-MiniLM-L6-v2",
            model_kwargs={'device': 'cpu'},
            encode_kwargs={'normalize_embeddings': True}
        )

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
                print(f"⚠️ 索引文件损坏，正在重建: {e}")
                return self._create_index()
        else:
            print("⚙️ [KnowledgeBase] 本地无索引，正在重建向量数据库...")
            return self._create_index()

    def _create_index(self):
        if not self.data_path.exists():
            print(f"⚠️ 数据目录不存在: {self.data_path}，将创建空索引。")
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
                print(f"⚠️ 加载文件出错: {e}")

        if not documents:
            print("⚠️ 未找到文档，创建空索引。")
            return FAISS.from_texts(["无数据"], self.embeddings)

        # 2. 切分文档
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        chunks = text_splitter.split_documents(documents)
        print(f"📄 正在向量化 {len(chunks)} 个文本片段...")

        # 3. 创建向量库 (内存中)
        vector_store = FAISS.from_documents(chunks, self.embeddings)

        # 4. 保存到本地 (【⭐ 核心修复：先存临时目录，再搬运】)
        try:
            # 定义一个纯英文、无空格的临时目录名
            temp_dir_name = "temp_faiss_build"
            temp_path = self.base_dir / temp_dir_name
            
            # 如果上次异常退出残留了临时目录，先删掉
            if temp_path.exists():
                shutil.rmtree(temp_path)

            # A. 保存到临时目录 (FAISS 对这里的路径很满意)
            # 注意：save_local 接受的是文件夹路径字符串
            vector_store.save_local(temp_dir_name)

            # B. 搬运文件到目标目录 (Python 处理中文路径很强)
            # 先清空目标目录
            if self.vector_db_path.exists():
                shutil.rmtree(self.vector_db_path)
            self.vector_db_path.mkdir(parents=True, exist_ok=True)

            # 移动文件 (index.faiss 和 index.pkl)
            for file_name in os.listdir(temp_dir_name):
                src_file = temp_path / file_name
                dst_file = self.vector_db_path / file_name
                shutil.move(str(src_file), str(dst_file))

            # C. 删除临时目录
            shutil.rmtree(temp_path)

            print(f"💾 索引已成功构建并保存至: {self.vector_db_path}")
        except Exception as e:
            print(f"❌ 保存索引失败 (不影响本次运行，但下次需重建): {e}")
        
        return vector_store

    def get_retriever(self):
        return self.vector_store.as_retriever(search_kwargs={"k": 3})

    async def search_with_score(self, query: str, k: int = 6):
        """
        执行向量检索并返回真实相似度分数

        Args:
            query: 查询文本
            k: 返回结果数量

        Returns:
            List[Tuple[Document, float]]: 文档和对应的相似度分数
            注意：FAISS 返回的是距离（L2距离），需要转换为相似度百分比
        """
        # similarity_search_with_score 返回 (Document, score)
        # score 是 L2 距离的平方，越小越相似（0 表示完全相同）
        results = self.vector_store.similarity_search_with_score(query, k=k)

        # 将 L2 距离的平方转换为相似度百分比
        # FAISS 返回的是 squared L2 距离，对于归一化向量范围是 [0, 4]
        # 相似度 = (1 - sqrt(distance)/2)
        import math
        processed_results = []
        for doc, squared_distance in results:
            # 取平方根得到真实的 L2 距离
            distance = math.sqrt(max(0, float(squared_distance)))
            # 对于归一化向量，L2 距离范围是 [0, 2]
            distance = min(distance, 2.0)
            # 转换为相似度 (0-1范围)，前端显示时乘100
            similarity = float((1 - distance / 2))
            processed_results.append((doc, similarity))

        return processed_results