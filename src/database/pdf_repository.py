"""
PDF文档缓存数据库操作
"""
from typing import Optional, List
from datetime import datetime
from sqlalchemy import select, func, delete
from src.database.models import PDFDocument
from src.database.base import async_session_maker


class PDFRepository:
    """PDF文档缓存数据库操作"""

    async def get_by_hash(self, file_hash: str) -> Optional[PDFDocument]:
        """
        根据文件哈希获取缓存

        Args:
            file_hash: SHA256哈希值

        Returns:
            PDFDocument对象或None
        """
        async with async_session_maker() as db:
            result = await db.execute(
                select(PDFDocument).where(PDFDocument.file_hash == file_hash)
            )
            return result.scalar_one_or_none()

    async def get_by_path(self, file_path: str) -> Optional[PDFDocument]:
        """
        根据文件路径获取缓存

        Args:
            file_path: 文件相对路径

        Returns:
            PDFDocument对象或None
        """
        async with async_session_maker() as db:
            result = await db.execute(
                select(PDFDocument).where(PDFDocument.file_path == file_path)
            )
            return result.scalar_one_or_none()

    async def save_cache(
        self,
        file_path: str,
        file_name: str,
        file_hash: str,
        file_size: int,
        processed_text: str,
        processing_time: float,
        marker_version: str = "pypdfium2",
        page_count: int = 0
    ) -> PDFDocument:
        """
        保存或更新缓存

        Args:
            file_path: 文件相对路径
            file_name: 文件名
            file_hash: SHA256哈希值
            file_size: 文件大小(字节)
            processed_text: 处理后的文本
            processing_time: 处理耗时(秒)
            marker_version: 处理器版本号
            page_count: 页数

        Returns:
            保存后的PDFDocument对象
        """
        async with async_session_maker() as db:
            # 查询是否已存在
            existing = await db.execute(
                select(PDFDocument).where(PDFDocument.file_hash == file_hash)
            )
            doc = existing.scalar_one_or_none()

            if doc:
                # 更新
                doc.processed_text = processed_text
                doc.char_count = len(processed_text)
                doc.processing_time = processing_time
                doc.marker_version = marker_version
                doc.page_count = page_count
                doc.processing_status = "completed"
                doc.updated_at = datetime.now()
            else:
                # 新建
                doc = PDFDocument(
                    file_path=file_path,
                    file_name=file_name,
                    file_hash=file_hash,
                    file_size=file_size,
                    processed_text=processed_text,
                    char_count=len(processed_text),
                    processing_time=processing_time,
                    marker_version=marker_version,
                    page_count=page_count,
                    processing_status="completed"
                )
                db.add(doc)

            await db.commit()
            await db.refresh(doc)
            return doc

    async def get_all_cached(self) -> List[PDFDocument]:
        """
        获取所有有效的缓存文档

        Returns:
            PDFDocument对象列表
        """
        async with async_session_maker() as db:
            result = await db.execute(
                select(PDFDocument).where(
                    PDFDocument.processing_status == "completed"
                )
            )
            return list(result.scalars().all())

    async def delete_by_path(self, file_path: str) -> bool:
        """
        删除指定路径的缓存

        Args:
            file_path: 文件路径

        Returns:
            是否删除成功
        """
        async with async_session_maker() as db:
            result = await db.execute(
                select(PDFDocument).where(PDFDocument.file_path == file_path)
            )
            doc = result.scalar_one_or_none()
            if doc:
                await db.delete(doc)
                await db.commit()
                return True
            return False

    async def clear_all(self) -> int:
        """
        清空所有PDF缓存

        Returns:
            删除的文档数量
        """
        async with async_session_maker() as db:
            result = await db.execute(
                select(func.count(PDFDocument.id))
            )
            count = result.scalar() or 0

            await db.execute(delete(PDFDocument))
            await db.commit()
            return count

    async def get_statistics(self) -> dict:
        """
        获取统计信息

        Returns:
            统计数据字典
        """
        async with async_session_maker() as db:
            total = await db.execute(
                select(func.count(PDFDocument.id))
            )
            total_count = total.scalar() or 0

            completed = await db.execute(
                select(func.count(PDFDocument.id)).where(
                    PDFDocument.processing_status == "completed"
                )
            )
            completed_count = completed.scalar() or 0

            total_chars = await db.execute(
                select(func.sum(PDFDocument.char_count))
            )
            total_chars = total_chars.scalar() or 0

            total_time = await db.execute(
                select(func.sum(PDFDocument.processing_time))
            )
            total_time = total_time.scalar() or 0

            return {
                "total_documents": total_count,
                "completed_documents": completed_count,
                "failed_documents": total_count - completed_count,
                "total_characters": total_chars,
                "total_processing_time_seconds": total_time,
                "average_processing_time": total_time / completed_count if completed_count > 0 else 0
            }
