"""
混合动力PDF解析服务
结合pypdfium2快速提取和RapidOCR扫描件识别，实现智能自动选择最佳解析方式
"""
import asyncio
import time
from pathlib import Path
from typing import Tuple, Callable, Optional, List
from concurrent.futures import ThreadPoolExecutor

from src.services.pdf_service import PDFService, PDFProcessingError
from src.services.rapidocr_service import RapidOCRService, RapidOCRError
from src.database.pdf_repository import PDFRepository


class HybridPDFService:
    """
    混合动力PDF解析服务

    核心逻辑：
    1. 先用pypdfium2快速提取文本
    2. 质量评估算法判断文本质量
    3. 如果质量不达标，自动触发RapidOCR
    4. 记录处理方式到数据库的marker_version字段

    支持方法：
    - pypdfium2: 快速提取（原生PDF）
    - rapidocr: OCR识别（扫描件PDF）
    - cached: 数据库缓存
    """

    # 质量评估阈值
    QUALITY_THRESHOLD = 60  # 总分>=60视为高质量

    def __init__(self):
        """初始化混合解析服务"""
        self.fast_service = PDFService()  # pypdfium2快速提取
        self._ocr_service = None  # RapidOCR延迟初始化
        self.ocr_semaphore = asyncio.Semaphore(2)  # 限制并发OCR数量
        self.pdf_repo = PDFRepository()
        self.executor = ThreadPoolExecutor(max_workers=4)

        print("[HybridPDF] 混合解析服务已初始化")

    @property
    def ocr_service(self) -> RapidOCRService:
        """延迟初始化OCR服务"""
        if self._ocr_service is None:
            self._ocr_service = RapidOCRService()
        return self._ocr_service

    async def extract_text_with_fallback(
        self,
        pdf_path: str,
        force_ocr: bool = False,
        progress_callback: Optional[Callable] = None
    ) -> Tuple[str, str, float]:
        """
        混合提取文本（带回退机制）

        流程：
        1. 计算文件哈希，查询缓存
        2. 如果缓存命中 → 返回cached
        3. 如果force_ocr=True → 直接使用OCR
        4. 先用pypdfium2快速提取
        5. 质量评估，如果不达标 → 触发OCR
        6. 保存结果到缓存

        Args:
            pdf_path: PDF文件路径
            force_ocr: 强制使用OCR（跳过pypdfium2）
            progress_callback: 进度回调函数

        Returns:
            (text, method, time_cost)
            - text: 提取的文本内容
            - method: 处理方式 ("pypdfium2" | "rapidocr" | "cached")
            - time_cost: 处理耗时（秒）
        """
        start_time = time.time()
        pdf_path_obj = Path(pdf_path)

        # 检查文件存在
        if not pdf_path_obj.exists():
            raise PDFProcessingError(f"文件不存在: {pdf_path}")

        print(f"[HybridPDF] 开始处理: {pdf_path_obj.name}")

        # 1. 计算文件哈希
        if progress_callback:
            progress_callback("计算文件哈希...")

        file_hash = await asyncio.to_thread(
            PDFService.calculate_file_hash,
            str(pdf_path_obj)
        )

        # 2. 查询缓存
        if progress_callback:
            progress_callback("查询缓存...")

        cached_doc = await self.pdf_repo.get_by_hash(file_hash)

        if cached_doc and cached_doc.is_valid:
            print(f"[HybridPDF] [缓存命中] ({cached_doc.char_count}字符)")
            if progress_callback:
                progress_callback(f"缓存命中: {cached_doc.marker_version}")

            return cached_doc.processed_text, "cached", 0.0

        # 3. 强制OCR模式
        if force_ocr:
            print(f"[HybridPDF] 强制OCR模式")
            if progress_callback:
                progress_callback("使用RapidOCR识别...")

            text, ocr_time = await self._ocr_with_semaphore(pdf_path, progress_callback)
            method = "rapidocr"

            # 保存缓存
            await self._save_to_cache(
                pdf_path, file_hash, text, time.time() - start_time, method
            )

            return text, method, time.time() - start_time

        # 4. 快速提取模式（pypdfium2）
        try:
            if progress_callback:
                progress_callback("快速提取文本...")

            text, extract_time = await asyncio.to_thread(
                self.fast_service.extract_text,
                str(pdf_path_obj),
                validate_quality=False  # 不验证质量，我们自己评估
            )

            print(f"[HybridPDF] pypdfium2提取完成: {len(text)}字符")

            # 5. 质量评估
            if progress_callback:
                progress_callback("评估文本质量...")

            quality_score, quality_details = self._assess_quality(text)

            print(f"[HybridPDF] 质量评分: {quality_score}/100")
            print(f"[HybridPDF] 评估详情: {quality_details}")

            if quality_score >= self.QUALITY_THRESHOLD:
                # 高质量，使用pypdfium2结果
                print(f"[HybridPDF] [质量达标] 使用pypdfium2结果")
                method = "pypdfium2"

                # 保存缓存
                await self._save_to_cache(
                    pdf_path, file_hash, text, time.time() - start_time, method
                )

                return text, method, time.time() - start_time
            else:
                # 低质量，触发OCR
                print(f"[HybridPDF] [质量不达标] 触发OCR")
                if progress_callback:
                    progress_callback("质量不达标，启动OCR...")

                ocr_text, ocr_time = await self._ocr_with_semaphore(pdf_path, progress_callback)

                # 如果OCR结果更丰富，使用OCR结果
                if len(ocr_text) > len(text) * 1.5:  # OCR结果多50%以上
                    print(f"[HybridPDF] OCR结果更丰富，使用OCR")
                    method = "rapidocr"
                    final_text = ocr_text
                else:
                    print(f"[HybridPDF] OCR结果不理想，保留pypdfium2")
                    method = "pypdfium2"
                    final_text = text

                # 保存缓存
                await self._save_to_cache(
                    pdf_path, file_hash, final_text, time.time() - start_time, method
                )

                return final_text, method, time.time() - start_time

        except PDFProcessingError as e:
            print(f"[HybridPDF] pypdfium2提取失败: {e}")
            print(f"[HybridPDF] 回退到OCR...")

            if progress_callback:
                progress_callback("pypdfium2失败，使用OCR...")

            # pypdfium2失败，回退到OCR
            ocr_text, ocr_time = await self._ocr_with_semaphore(pdf_path, progress_callback)
            method = "rapidocr"

            # 保存缓存
            await self._save_to_cache(
                pdf_path, file_hash, ocr_text, time.time() - start_time, method
            )

            return ocr_text, method, time.time() - start_time

    async def _ocr_with_semaphore(
        self,
        pdf_path: str,
        progress_callback: Optional[Callable] = None
    ) -> Tuple[str, float]:
        """
        使用信号量控制OCR并发

        Args:
            pdf_path: PDF文件路径
            progress_callback: 进度回调

        Returns:
            (text, time_cost)
        """
        async with self.ocr_semaphore:
            if progress_callback:
                progress_callback("OCR识别中（并发控制）...")

            # 在线程池中执行OCR（避免阻塞）
            loop = asyncio.get_event_loop()
            text, ocr_time = await loop.run_in_executor(
                self.executor,
                self.ocr_service.extract_text,
                pdf_path,
                True  # validate_quality
            )

            return text, ocr_time

    def _assess_quality(self, text: str) -> Tuple[int, str]:
        """
        评估文本质量

        评分规则：
        - 字符数 > 1000: +50分
        - 字符数 > 500: +30分
        - 中文字符 > 500: +30分
        - 中文比例 > 30%: +20分

        Args:
            text: 待评估文本

        Returns:
            (score, details)
            - score: 总分（0-100）
            - details: 评分详情
        """
        score = 0
        details = []

        # 1. 字符数评分
        char_count = len(text)
        if char_count > 1000:
            score += 50
            details.append(f"字符数{char_count}(>1000): +50")
        elif char_count > 500:
            score += 30
            details.append(f"字符数{char_count}(>500): +30")
        else:
            details.append(f"字符数{char_count}(<500): +0")

        # 2. 中文字符评分
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        if chinese_chars > 500:
            score += 30
            details.append(f"中文{chinese_chars}个(>500): +30")
        else:
            details.append(f"中文{chinese_chars}个(<500): +0")

        # 3. 中文比例评分
        chinese_ratio = chinese_chars / char_count if char_count > 0 else 0
        if chinese_ratio > 0.3:
            score += 20
            details.append(f"中文比例{chinese_ratio:.1%}(>30%): +20")
        else:
            details.append(f"中文比例{chinese_ratio:.1%}(<30%): +0")

        details_str = ", ".join(details)
        return score, details_str

    async def _save_to_cache(
        self,
        pdf_path: str,
        file_hash: str,
        text: str,
        processing_time: float,
        extraction_method: str
    ):
        """
        保存处理结果到缓存

        Args:
            pdf_path: PDF文件路径
            file_hash: 文件哈希
            text: 提取的文本
            processing_time: 处理耗时
            extraction_method: 提取方法（pypdfium2/rapidocr）
        """
        pdf_path_obj = Path(pdf_path).resolve()

        # 尝试获取相对路径，如果失败则使用绝对路径
        try:
            base_dir = Path(__file__).resolve().parent.parent.parent
            rel_path = str(pdf_path_obj.relative_to(base_dir))
        except ValueError:
            # 如果pdf不在base_dir下，使用绝对路径
            rel_path = str(pdf_path_obj)

        await self.pdf_repo.save_cache(
            file_path=rel_path,
            file_name=pdf_path_obj.name,
            file_hash=file_hash,
            file_size=pdf_path_obj.stat().st_size,
            processed_text=text,
            processing_time=processing_time,
            marker_version=extraction_method  # 记录处理方式
        )

        print(f"[HybridPDF] [缓存已保存] {extraction_method}")

    async def batch_extract(
        self,
        pdf_paths: List[str],
        progress_callback: Optional[Callable] = None
    ) -> List[Tuple[str, str, float, str]]:
        """
        批量处理多个PDF文件

        Args:
            pdf_paths: PDF文件路径列表
            progress_callback: 进度回调

        Returns:
            [(text, method, time_cost, file_name), ...]
        """
        results = []

        for idx, pdf_path in enumerate(pdf_paths, 1):
            try:
                if progress_callback:
                    progress_callback(f"处理 {idx}/{len(pdf_paths)}: {Path(pdf_path).name}")

                text, method, time_cost = await self.extract_text_with_fallback(
                    pdf_path,
                    progress_callback=lambda msg: progress_callback(
                        f"[{idx}/{len(pdf_paths)}] {msg}"
                    ) if progress_callback else None
                )

                results.append((text, method, time_cost, Path(pdf_path).name))

            except Exception as e:
                print(f"[HybridPDF] 处理失败: {pdf_path} - {e}")
                results.append(("", "error", 0.0, Path(pdf_path).name))

        return results

    async def close(self):
        """关闭资源"""
        self.executor.shutdown(wait=True)
        print("[HybridPDF] 资源已释放")
