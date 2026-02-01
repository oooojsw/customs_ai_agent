"""
RapidOCR 服务封装
使用 RapidOCR (PaddleOCR轻量化版本) 处理扫描件PDF
"""
import hashlib
import time
import asyncio
from pathlib import Path
from typing import Tuple, Optional, List


class RapidOCRError(Exception):
    """RapidOCR处理异常"""
    pass


class RapidOCRQualityError(Exception):
    """RapidOCR输出质量异常"""
    pass


class RapidOCRService:
    """RapidOCR 服务封装"""

    MIN_CHAR_COUNT = 300  # 扫描件OCR可能识别不完整
    MIN_CHINESE_RATIO = 0.03  # 降低中文比例要求

    def __init__(self):
        """初始化RapidOCR"""
        print("[RapidOCR] Initializing RapidOCR...")
        try:
            from rapidocr_onnxruntime import RapidOCR
            # 初始化OCR引擎
            self.ocr = RapidOCR()
            print("[RapidOCR] RapidOCR initialized successfully")

            # 检查 pymupdf 是否可用
            try:
                # 尝试导入PyMuPDF（pymupdf 1.23.0+支持此导入名）
                import pymupdf
                print("[RapidOCR] Using pymupdf for PDF→image conversion (no poppler required)")
                self.use_pymupdf = True
            except ImportError:
                try:
                    # 回退到fitz导入名（PyMuPDF的历史名称）
                    import fitz
                    print("[RapidOCR] Using fitz (pymupdf alias) for PDF→image conversion")
                    self.use_pymupdf = True
                except ImportError:
                    print("[RapidOCR] pymupdf/fitz not available, will use pdf2image (requires poppler)")
                    print("[RapidOCR] Install: conda run -n llm-sprint pip install pymupdf")
                    self.use_pymupdf = False

        except ImportError as e:
            print(f"[RapidOCR] ERROR: RapidOCR not installed: {e}")
            print("[RapidOCR] Please run: pip install rapidocr_onnxruntime")
            raise RapidOCRError(f"RapidOCR not installed: {e}") from e
        except Exception as e:
            print(f"[RapidOCR] ERROR: Initialization failed: {e}")
            raise RapidOCRError(f"Initialization failed: {e}") from e

    @staticmethod
    def calculate_file_hash(file_path: str) -> str:
        """
        计算文件的SHA256哈希值

        Args:
            file_path: 文件路径

        Returns:
            64位 hexadecimal哈希字符串
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
            RapidOCRError: 处理失败
            RapidOCRQualityError: 质量检查失败
        """
        start_time = time.time()
        pdf_path_obj = Path(pdf_path)

        # 检查文件存在
        if not pdf_path_obj.exists():
            raise RapidOCRError(f"File not found: {pdf_path}")

        print(f"[RapidOCR] Processing: {pdf_path_obj.name}")

        try:
            # 将PDF转换为图片
            print(f"[RapidOCR] Converting PDF to images...")

            if self.use_pymupdf:
                # 使用 pymupdf（不需要 poppler）
                import numpy as np

                # 尝试使用pymupdf或fitz导入
                try:
                    import pymupdf as pdf_lib
                    pdf_lib_name = "pymupdf"
                except ImportError:
                    import fitz as pdf_lib
                    pdf_lib_name = "fitz"

                doc = pdf_lib.open(str(pdf_path_obj))
                images = []

                for page_num, page in enumerate(doc):
                    # 渲染页面为图片（zoom=2 相当于 200 DPI）
                    pix = page.get_pixmap(matrix=pdf_lib.Matrix(2, 2))

                    # 转换为 numpy 数组（RapidOCR 需要的格式）
                    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                        pix.height, pix.width, pix.n
                    )

                    # 如果是 RGBA，转为 RGB
                    if pix.n == 4:
                        img = img[:, :, :3]  # 去掉 alpha 通道
                    elif pix.n == 1:
                        # 灰度图转为 RGB
                        img = np.stack([img, img, img], axis=2)

                    images.append(img)

                doc.close()
                print(f"[RapidOCR] Converted {len(images)} pages using {pdf_lib_name}")
            else:
                # 使用 pdf2image（需要 poppler）
                from pdf2image import convert_from_path
                import numpy as np

                pil_images = convert_from_path(str(pdf_path_obj), dpi=200)
                # 将 PIL Image 转换为 numpy 数组
                images = [np.array(img) for img in pil_images]

            print(f"[RapidOCR] Extracting text from {len(images)} pages...")
            all_text = []

            # 逐页OCR识别
            for page_num, image in enumerate(images, 1):
                # RapidOCR返回：(result, metadata)
                # result格式：[[[x1,y1,x2,y2], text, confidence], ...]
                ocr_result, _ = self.ocr(image)

                # 提取文本（合并所有识别结果）
                page_text = []
                for block in ocr_result:
                    if len(block) >= 2:
                        page_text.append(block[1])  # 文本在第二个位置

                all_text.append("\n".join(page_text))

                if page_num % 5 == 0 or page_num == len(images):
                    print(f"[RapidOCR] Processed {page_num}/{len(images)} pages...")

            # 合并所有页面文本
            markdown_text = "\n\n".join(all_text)

            processing_time = time.time() - start_time

            # 质量检查
            if validate_quality:
                self._validate_quality(markdown_text, pdf_path_obj.name)

            print(f"[RapidOCR] Completed: {pdf_path_obj.name} ({len(markdown_text)} chars, {processing_time:.1f}s)")

            return markdown_text, processing_time

        except Exception as e:
            processing_time = time.time() - start_time
            print(f"[RapidOCR] ERROR: Processing failed for {pdf_path_obj.name} - {e}")
            raise RapidOCRError(f"Processing failed: {e}") from e

    async def extract_text_async(
        self,
        pdf_path: str,
        validate_quality: bool = True
    ) -> Tuple[str, float]:
        """
        提取PDF文本内容 (异步封装)

        将同步的RapidOCR调用放入线程池，避免阻塞事件循环

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
        验证RapidOCR输出质量

        检查项：
        1. 字符数 >= MIN_CHAR_COUNT
        2. 中文比例 >= MIN_CHINESE_RATIO

        Args:
            text: RapidOCR输出的文本
            file_name: 文件名 (用于日志)

        Raises:
            RapidOCRQualityError: 质量检查失败
        """
        char_count = len(text)

        # 检查1: 字符数
        if char_count < self.MIN_CHAR_COUNT:
            raise RapidOCRQualityError(
                f"Output too short ({char_count} < {self.MIN_CHAR_COUNT}): {file_name}"
            )

        # 检查2: 中文比例
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        chinese_ratio = chinese_chars / char_count if char_count > 0 else 0

        if chinese_ratio < self.MIN_CHINESE_RATIO:
            print(
                f"[RapidOCR] WARNING: Low Chinese ratio "
                f"({chinese_ratio:.1%} < {self.MIN_CHINESE_RATIO:.1%}): {file_name}"
            )
            # 不抛出异常，仅警告
