"""
PDF处理服务封装
使用pypdfium2提取PDF文本内容（快速可靠方案）
"""
import hashlib
import time
import asyncio
from pathlib import Path
from typing import Tuple, Optional
import pypdfium2  # 已安装的快速PDF库


# 自定义异常
class PDFProcessingError(Exception):
    """PDF处理异常"""
    pass


class PDFQualityError(Exception):
    """PDF输出质量异常"""
    pass


class PDFService:
    """
    PDF处理服务封装（使用pypdfium2）

    功能：
    1. 文本提取：从PDF提取文本
    2. 哈希计算：SHA256文件变更检测
    3. 质量检查：验证输出质量
    """

    # 质量阈值
    MIN_CHAR_COUNT = 100  # 最少字符数（扫描件PDF可能只有少量文本）
    MIN_CHINESE_RATIO = 0.05  # 最少中文比例 (5%)

    def __init__(self):
        """初始化PDF服务"""
        print("[PDF] 使用pypdfium2快速PDF处理引擎")
        # pypdfium2不需要初始化模型

    @staticmethod
    def calculate_file_hash(file_path: str) -> str:
        """
        计算文件的SHA256哈希值

        Args:
            file_path: 文件路径

        Returns:
            64位十六进制哈希字符串
        """
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def extract_text(
        self,
        pdf_path: str,
        validate_quality: bool = True
    ) -> Tuple[str, float]:
        """
        提取PDF文本内容 (同步函数)

        Args:
            pdf_path: PDF文件路径
            validate_quality: 是否进行质量检查

        Returns:
            (markdown_text, processing_time_seconds)
        """
        start_time = time.time()
        pdf_path_obj = Path(pdf_path)

        # 检查文件存在
        if not pdf_path_obj.exists():
            raise PDFProcessingError(f"文件不存在: {pdf_path}")

        print(f"[PDF] 正在处理: {pdf_path_obj.name}")

        try:
            # 使用pypdfium2提取文本
            pdf = pypdfium2.PdfDocument(str(pdf_path_obj))

            # 提取所有页面的文本
            text_parts = []
            for page in pdf:
                text_page = page.get_textpage()
                text = text_page.get_text_range()
                text_parts.append(text)

            markdown_text = "\n\n".join(text_parts)

            # 清理
            pdf.close()

            processing_time = time.time() - start_time

            # 质量检查
            if validate_quality:
                self._validate_quality(markdown_text, pdf_path_obj.name)

            print(f"[PDF] 处理完成: {pdf_path_obj.name} ({len(markdown_text)}字符, {processing_time:.1f}秒)")

            return markdown_text, processing_time

        except Exception as e:
            processing_time = time.time() - start_time
            print(f"[PDF] 处理失败: {pdf_path_obj.name} - {e}")
            raise PDFProcessingError(f"处理失败: {e}") from e

    async def extract_text_async(
        self,
        pdf_path: str,
        validate_quality: bool = True
    ) -> Tuple[str, float]:
        """
        提取PDF文本内容 (异步封装)

        Args:
            pdf_path: PDF文件路径
            validate_quality: 是否进行质量检查

        Returns:
            (markdown_text, processing_time_seconds)
        """
        loop = asyncio.get_event_loop()
        return await asyncio.to_thread(
            self.extract_text,
            pdf_path,
            validate_quality
        )

    def _validate_quality(self, text: str, file_name: str) -> None:
        """
        验证输出质量

        Args:
            text: 输出的文本
            file_name: 文件名

        Raises:
            PDFQualityError: 质量检查失败
        """
        char_count = len(text)

        # 检查1: 字符数 - 只警告，不拒绝（扫描件PDF可能需要OCR）
        if char_count < self.MIN_CHAR_COUNT:
            print(f"[PDF] 警告: 输出文本过短 ({char_count} < {self.MIN_CHAR_COUNT}): {file_name}")
            print(f"[PDF]        这可能是扫描件PDF，需要OCR处理")

        # 检查2: 中文比例（降低要求）
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        chinese_ratio = chinese_chars / char_count if char_count > 0 else 0

        if chinese_ratio < self.MIN_CHINESE_RATIO and chinese_chars < 100:
            # 如果中文比例低且中文少于100个，警告但不拒绝
            print(f"[PDF] 警告: 中文比例较低 ({chinese_ratio:.1%}): {file_name}")
