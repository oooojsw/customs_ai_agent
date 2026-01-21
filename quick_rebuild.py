"""
快速重建FAISS索引（只包含真实文档）
"""
import asyncio
import sys
import io
from pathlib import Path

# 设置UTF-8输出
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from src.services.knowledge_base import KnowledgeBase
from langchain_community.document_loaders import TextLoader, DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS


async def rebuild():
    """重建索引"""
    print("=" * 70)
    print("重建FAISS索引（仅包含真实文档）")
    print("=" * 70)

    # 1. 初始化KB（加载PDF）
    print("\n步骤1: 加载PDF文档...")
    kb = KnowledgeBase()
    pdf_docs = await kb._process_pdfs()
    print(f"✅ 加载了 {len(pdf_docs)} 个PDF文档")

    # 2. 加载txt文件（只有2个真实文件）
    print("\n步骤2: 加载文本文件...")
    data_path = Path("data/knowledge")
    loaders = [
        DirectoryLoader(str(data_path), glob="*.txt", loader_cls=TextLoader, loader_kwargs={"encoding": "utf-8"}),
    ]

    txt_docs = []
    for loader in loaders:
        try:
            txt_docs.extend(loader.load())
        except Exception as e:
            print(f"⚠️ 加载出错: {e}")

    print(f"✅ 加载了 {len(txt_docs)} 个文本文件")
    for doc in txt_docs:
        print(f"   - {Path(doc.metadata['source']).name}")

    # 3. 合并
    all_docs = txt_docs + pdf_docs
    print(f"\n步骤3: 合并文档，总计 {len(all_docs)} 个")

    # 4. 切分（优化分隔符，避免在分号处切分）
    print("\n步骤4: 切分文档...")
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1500,
        chunk_overlap=150,
        separators=["。\n", "！\n", "？\n", "\n\n\n", "\n\n", "\n", "。", "！", "？", "，", " ", ""]
    )
    chunks = splitter.split_documents(all_docs)
    print(f"✅ 切分为 {len(chunks)} 个片段")

    # 🔥 过滤掉小于50字符的低质量chunk
    original_count = len(chunks)
    chunks = [c for c in chunks if len(c.page_content) >= 50]
    filtered_count = original_count - len(chunks)
    print(f"📄 过滤小chunk: {original_count} → {len(chunks)} (过滤了{filtered_count}个小片段)")

    # 统计
    pdf_chunks = sum(1 for c in chunks if c.metadata.get('file_type') == 'pdf')
    txt_chunks = len(chunks) - pdf_chunks
    print(f"   PDF片段: {pdf_chunks}")
    print(f"   TXT片段: {txt_chunks}")

    # 5. 创建索引
    print("\n步骤5: 创建FAISS索引...")
    vector_store = FAISS.from_documents(chunks, kb.embeddings)
    print("✅ 向量化完成")

    # 6. 保存
    print("\n步骤6: 保存索引...")
    import shutil
    import os

    vector_db_path = kb.base_dir / "config" / "faiss_index_local"
    temp_path = kb.base_dir / "temp_faiss"

    if temp_path.exists():
        shutil.rmtree(temp_path)

    vector_store.save_local(str(temp_path))

    if vector_db_path.exists():
        shutil.rmtree(vector_db_path)
    vector_db_path.mkdir(parents=True, exist_ok=True)

    for file_name in os.listdir(temp_path):
        shutil.move(str(temp_path / file_name), str(vector_db_path / file_name))

    shutil.rmtree(temp_path)
    print(f"✅ 索引已保存")

    print("\n" + "=" * 70)
    print("重建完成！")
    print(f"总文档: {len(all_docs)} (TXT: {len(txt_docs)}, PDF: {len(pdf_docs)})")
    print(f"总片段: {len(chunks)} (TXT: {txt_chunks}, PDF: {pdf_chunks})")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(rebuild())
