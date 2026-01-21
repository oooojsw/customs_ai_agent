"""
Marker PDF处理服务封装
使用Marker库提取PDF文本内容
"""
import hashlib
import time
import asyncio
from pathlib import Path
from typing import Tuple, Optional


# 自定义异常
class MarkerProcessingError(Exception):
    """Marker处理异常"""
    pass


class MarkerQualityError(Exception):
    """Marker输出质量异常"""
    pass


class MarkerService:
    """
    Marker PDF处理服务封装

    功能：
    1. 文本提取：从PDF提取Markdown文本
    2. 哈希计算：SHA256文件变更检测
    3. 质量检查：验证输出质量
    """

    # 质量阈值
    MIN_CHAR_COUNT = 1000  # 最少字符数
    MIN_CHINESE_RATIO = 0.1  # 最少中文比例 (10%)

    def __init__(self):
        """初始化Marker模型"""
        print("⚙️ [Marker] 正在初始化Marker模型...")
        try:
            from marker.converters.pdf import PdfConverter
            from marker.models import create_model_dict

            self.model_dict = create_model_dict()
            self.converter = PdfConverter(artifact_dict=self.model_dict)
            print("✅ [Marker] Marker模型初始化完成")
        except ImportError as e:
            print(f"❌ [Marker] Marker未安装: {e}")
            print("💡 [Marker] 请运行: pip install marker-pdf==0.3.2")
            raise MarkerProcessingError(f"Marker未安装: {e}") from e
        except Exception as e:
            print(f"❌ [Marker] 模型初始化失败: {e}")
            raise MarkerProcessingError(f"Marker初始化失败: {e}") from e

    @staticmethod
    def calculate_file_hash(file_path: str) -> str:
        """
        计算文件的SHA256哈希值

        Args:
            file_path: 文件路径

        Returns:
            64位十六进制哈希字符串

        Example:
            >>> hash = MarkerService.calculate_file_hash("test.pdf")
            >>> len(hash)
            64
        """
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            # 分块读取，避免大文件内存溢出
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

        Raises:
            MarkerProcessingError: 处理失败
            MarkerQualityError: 质量检查失败
        """
        start_time = time.time()
        pdf_path_obj = Path(pdf_path)

        # 检查文件存在
        if not pdf_path_obj.exists():
            raise MarkerProcessingError(f"文件不存在: {pdf_path}")

        print(f"📄 [Marker] 正在处理: {pdf_path_obj.name}")

        try:
            # 调用Marker处理
            rendered = self.converter(str(pdf_path_obj))
            markdown_text = rendered.markdown

            processing_time = time.time() - start_time

            # 质量检查
            if validate_quality:
                self._validate_quality(markdown_text, pdf_path_obj.name)

            print(f"✅ [Marker] 处理完成: {pdf_path_obj.name} ({len(markdown_text)}字符, {processing_time:.1f}秒)")

            return markdown_text, processing_time

        except Exception as e:
            processing_time = time.time() - start_time
            print(f"❌ [Marker] 处理失败: {pdf_path_obj.name} - {e}")
            raise MarkerProcessingError(f"处理失败: {e}") from e

    async def extract_text_async(
        self,
        pdf_path: str,
        validate_quality: bool = True
    ) -> Tuple[str, float]:
        """
        提取PDF文本内容 (异步封装)

        将同步的Marker调用放入线程池，避免阻塞事件循环

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
        验证Marker输出质量

        检查项：
        1. 字符数 >= MIN_CHAR_COUNT
        2. 中文比例 >= MIN_CHINESE_RATIO
        3. 不包含明显的错误标记

        Args:
            text: Marker输出的Markdown文本
            file_name: 文件名 (用于日志)

        Raises:
            MarkerQualityError: 质量检查失败
        """
        char_count = len(text)

        # 检查1: 字符数
        if char_count < self.MIN_CHAR_COUNT:
            raise MarkerQualityError(
                f"输出文本过短 ({char_count} < {self.MIN_CHAR_COUNT}): {file_name}"
            )

        # 检查2: 中文比例
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        chinese_ratio = chinese_chars / char_count

        if chinese_ratio < self.MIN_CHINESE_RATIO:
            print(
                f"⚠️ [Marker] 中文比例过低 "
                f"({chinese_ratio:.1%} < {self.MIN_CHINESE_RATIO:.1%}): {file_name}"
            )
            # 不抛出异常，仅警告

        # 检查3: 明显错误标记
        error_patterns = [
            "ERROR:",
            "Exception:",
            "Traceback:",
            "无法识别",
            "recognition failed"
        ]
        text_lower = text.lower()
        for pattern in error_patterns:
            if pattern.lower() in text_lower:
                raise MarkerQualityError(
                    f"输出包含错误标记 '{pattern}': {file_name}"
                )
