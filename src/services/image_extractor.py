import base64
import json
import requests
from typing import Tuple, Optional, Dict
from openai import AzureOpenAI, OpenAI
from fastapi import UploadFile

from src.config.loader import settings
from src.services.document_models import (
    DocumentResult, DocumentType, ConfidenceLevel,
    FieldEvidence, TableResult, CellResult,
    classify_confidence, needs_review,
)

# 自定义异常
class NotDeclarationError(ValueError):
    """当图片内容不是报关单时抛出"""
    pass

class ImageTextExtractor:
    def __init__(self, image_config: Dict = None):
        """
        初始化图片识别器

        Args:
            image_config: 图像模型配置字典，如果为 None 则从数据库加载
        """
        self._config = image_config or self._load_config()

        # 从配置中获取参数
        self._provider = self._config.get('provider', 'gemini')
        self._api_key = self._config.get('api_key', '')
        self._model = self._config.get('model', settings.MODEL_NAME)
        self._temperature = self._config.get('temperature', 0.1)
        self._max_tokens = self._config.get('max_tokens', 16384)
        self._endpoint = self._config.get('endpoint')
        self._api_version = self._config.get('api_version', settings.AZURE_OAI_VERSION)
        self._base_url = self._config.get('base_url')

        # 初始化客户端
        self._azure_client = None
        self._openai_client = None

        if self._provider == "azure" and all([self._api_key, self._endpoint]):
            try:
                self._azure_client = AzureOpenAI(
                    api_key=self._api_key,
                    api_version=self._api_version,
                    azure_endpoint=self._endpoint
                )
                print(f"[ImageExtractor] Azure OpenAI 客户端初始化成功")
            except Exception as e:
                print(f"[Warning] Azure OpenAI 客户端初始化失败: {e}")

        elif self._provider in ["deepseek", "openai", "qwen", "zhipu", "siliconflow", "custom"]:
            if self._api_key:
                try:
                    self._openai_client = OpenAI(
                        api_key=self._api_key,
                        base_url=self._base_url
                    )
                    print(f"[ImageExtractor] {self._provider} OpenAI 兼容客户端初始化成功")
                except Exception as e:
                    print(f"[Warning] {self._provider} 客户端初始化失败: {e}")

        # Gemini 的特殊属性
        if self._provider == "gemini":
            self._gemini_model = self._model or "gemini-2.0-flash-exp"
        else:
            # 保留 _gemini_model 用于内容校验
            self._gemini_model = "gemini-2.0-flash-exp"

        # Azure 的部署名称
        if self._provider == "azure":
            self._azure_deployment = self._model

    @staticmethod
    def _load_config() -> Dict:
        """加载图像模型配置（静态方法，用于初始化）"""
        try:
            # 优先从 image_config_loader 加载用户配置
            from src.config.image_loader import image_config_loader
            config = image_config_loader.get_config()

            # 如果用户配置已启用，使用用户配置
            if config.get('is_enabled', False):
                provider = config['provider']
                model = config['model_name']
                print(f"[ImageExtractor] ✓ 使用用户配置: {provider}/{model}")
                return {
                    'provider': provider,
                    'api_key': config['api_key'],
                    'base_url': config.get('base_url'),
                    'model': model,
                    'temperature': config.get('temperature', 0.1),
                    'max_tokens': config.get('max_tokens', 16384),
                    'endpoint': config.get('endpoint'),
                    'api_version': config.get('api_version'),
                    'source': 'database'
                }
            else:
                # 使用 .env 默认配置
                print(f"[ImageExtractor] 使用 .env 配置: gemini")
                return {
                    'provider': 'gemini',
                    'api_key': settings.GOOGLE_API_KEY,
                    'base_url': None,
                    'model': settings.MODEL_NAME,
                    'temperature': 0.1,
                    'max_tokens': 16384,
                    'endpoint': settings.AZURE_OAI_ENDPOINT,
                    'api_version': settings.AZURE_OAI_VERSION,
                    'source': 'env'
                }
        except Exception as e:
            print(f"[Error] 配置加载失败: {e}")
            return {
                'provider': 'gemini',
                'api_key': '',
                'model': 'gemini-2.0-flash-exp',
                'temperature': 0.1,
                'max_tokens': 16384
            }

    @classmethod
    async def create_async(cls, db=None):
        """
        异步工厂方法：从数据库加载配置创建实例

        Args:
            db: 数据库会话，如果为 None 则使用 .env 配置

        Returns:
            ImageTextExtractor 实例
        """
        if db:
            try:
                from src.config.image_loader import image_config_loader
                config = await image_config_loader.load_config(db)
                return cls(image_config=config)
            except Exception as e:
                print(f"[Warning] 从数据库加载图像配置失败: {e}，使用 .env 配置")

        # 回退到静态配置
        return cls()

    def extract_text(self, image_bytes: bytes, mime_type: str, language: str = "zh") -> Tuple[str, str]:
        """
        核心函数：从图片中提取报关单字段
        根据配置的 provider 调用对应的图像识别 API
        """
        print(f"[DEBUG] ========== 开始图片识别 ==========")
        print(f"[DEBUG] Provider: {self._provider}")
        print(f"[DEBUG] Model: {self._model}")
        print(f"[DEBUG] Language: {language}, Size: {len(image_bytes)} bytes")
        print(f"[DEBUG] Config Source: {self._config.get('source', 'unknown')}")

        # 1. 内容校验（使用 Gemini，因为最快）
        try:
            print("[DEBUG] 步骤 1: 内容校验...")
            is_declaration, reason = self._validate_image_content(image_bytes, mime_type, language)
            if not is_declaration:
                raise NotDeclarationError(f"图片似乎不是报关单，因为：{reason}")
            print("[DEBUG] ✓ 内容校验通过")
        except Exception as e:
            print(f"[WARN] 内容校验失败: {e}，跳过校验继续识别...")

        # 2. 根据 provider 调用对应 API
        text = None
        model_used = self._model
        primary_error = None

        try:
            print(f"[INFO] 步骤 2: 使用 {self._provider} 进行识别...")

            if self._provider == "gemini":
                text = self._call_gemini_vision(image_bytes, mime_type, language)
                model_used = self._gemini_model

            elif self._provider == "azure":
                if not self._azure_client:
                    raise RuntimeError("Azure OpenAI 客户端未初始化，请检查配置")
                text = self._call_azure_openai_vision(image_bytes, mime_type, language)
                model_used = self._azure_deployment

            elif self._provider in ["deepseek", "openai", "qwen", "zhipu", "siliconflow", "custom"]:
                if not self._openai_client:
                    raise RuntimeError(f"{self._provider} 客户端未初始化，请检查 API Key 和 Base URL")
                text = self._call_openai_compatible_vision(image_bytes, mime_type, language)
                model_used = self._model

            else:
                raise ValueError(f"不支持的 provider: {self._provider}")

            # 格式化检查
            print("[DEBUG] 步骤 3: 格式化检查...")
            text = self._ensure_multi_item_format(text, language)

            print(f"[SUCCESS] ✓ 识别成功！")
            print(f"[SUCCESS] 使用模型: {model_used}")
            print(f"[DEBUG] ========== 识别完成 ==========\n")
            return text, model_used

        except Exception as e:
            primary_error = e
            error_type = type(e).__name__
            error_msg = str(e)
            print(f"[ERROR] {self._provider} 识别失败: {error_type}: {error_msg}")

            # 降级策略：尝试备用模型
            if self._azure_client and self._provider != "azure":
                print(f"[INFO] 尝试降级到 Azure OpenAI...")
                try:
                    text = self._call_azure_openai_vision(image_bytes, mime_type, language)
                    model_used = f"Azure-{self._azure_deployment}"
                    text = self._ensure_multi_item_format(text, language)
                    print(f"[SUCCESS] ✓ Azure OpenAI 降级成功！")
                    print(f"[DEBUG] ========== 识别完成 ==========\n")
                    return text, model_used
                except Exception as az_e:
                    print(f"[ERROR] Azure OpenAI 降级也失败: {az_e}")

            # 所有尝试都失败
            print(f"[FATAL] 所有模型均无法处理该图片")
            raise RuntimeError(
                f"图片识别失败\n"
                f"主模型 ({self._provider}/{self._model}): {error_type}: {error_msg}\n"
                f"备用模型: Azure OpenAI {'未配置' if not self._azure_client else '也失败了'}"
            ) from primary_error

    def extract_document(self, image_bytes: bytes, mime_type: str, language: str = "zh") -> DocumentResult:
        """核心方法 V2：返回统一的 DocumentResult 结构化数据。

        内部调用 VLM 进行文档分类 + 字段提取 + 置信度评估，
        输出对齐 src/services/document_models.py 的 DocumentResult 模型。

        Args:
            image_bytes: 图片字节数据
            mime_type: 图片 MIME 类型
            language: 输出语言

        Returns:
            DocumentResult 包含文档类型、字段列表、原始文本和置信度
        """
        import time
        start_time = time.time()

        print(f"[DEBUG] ========== 开始图片识别 (DocumentResult 模式) ==========")
        print(f"[DEBUG] Provider: {self._provider}, Model: {self._model}")
        print(f"[DEBUG] Language: {language}, Size: {len(image_bytes)} bytes")

        # 1. 调用 VLM 获取结构化 JSON
        raw_text = None
        model_used = self._model
        primary_error = None

        try:
            print(f"[INFO] 调用 {self._provider} 进行文档识别...")

            if self._provider == "gemini":
                raw_text = self._call_gemini_vision_document(image_bytes, mime_type, language)
                model_used = self._gemini_model
            elif self._provider == "azure":
                if not self._azure_client:
                    raise RuntimeError("Azure OpenAI 客户端未初始化")
                raw_text = self._call_azure_openai_vision_document(image_bytes, mime_type, language)
                model_used = self._azure_deployment
            elif self._provider in ["deepseek", "openai", "qwen", "zhipu", "siliconflow", "custom"]:
                if not self._openai_client:
                    raise RuntimeError(f"{self._provider} 客户端未初始化")
                raw_text = self._call_openai_compatible_vision_document(image_bytes, mime_type, language)
                model_used = self._model
            else:
                raise ValueError(f"不支持的 provider: {self._provider}")

        except Exception as e:
            primary_error = e
            print(f"[ERROR] {self._provider} 识别失败: {type(e).__name__}: {str(e)}")

            # 降级到备用模型
            if self._azure_client and self._provider != "azure":
                print(f"[INFO] 降级到 Azure OpenAI...")
                try:
                    raw_text = self._call_azure_openai_vision_document(image_bytes, mime_type, language)
                    model_used = f"Azure-{self._azure_deployment}"
                except Exception as az_e:
                    print(f"[ERROR] 降级也失败: {az_e}")
                    raise RuntimeError(
                        f"文档识别失败: 主模型 {self._provider}/{self._model}: {primary_error}; "
                        f"备用 Azure: {az_e}"
                    ) from primary_error
            else:
                raise

        if not raw_text:
            raise RuntimeError("VLM 返回空响应")

        # 2. 解析 VLM JSON 响应 → DocumentResult
        doc = self._parse_document_response(
            raw_text, image_bytes, mime_type, language, model_used,
            int((time.time() - start_time) * 1000),
        )

        print(f"[SUCCESS] 文档识别完成: type={doc.document_type.value}, "
              f"fields={len(doc.fields)}, tables={len(doc.tables)}, "
              f"confidence={doc.confidence.value}")
        print(f"[DEBUG] ========== 识别完成 ==========\n")
        return doc

    # ------------------------------------------------------------------
    # Document 模式 VLM 调用（使用统一提示词，请求结构化 JSON）
    # ------------------------------------------------------------------

    def _build_document_prompt(self, language: str = "zh") -> str:
        """构建文档识别统一提示词 — 请求 JSON 结构化输出。"""
        lang_instr = self._get_language_instruction(language)

        if language == "vi":
            return (
                f"{lang_instr}\n\n"
                "Bạn là chuyên gia phân tích chứng từ hải quan. Phân tích hình ảnh này.\n\n"
                "【Nhiệm vụ 1 — Phân loại chứng từ】\n"
                "declaration / invoice / packing_list / certificate / general_image / unknown\n\n"
                "【Nhiệm vụ 2 — Nếu là chứng từ, trích xuất các trường sau】\n"
                "Với mỗi trường: field_name, original_text, standard_value, confidence_score (0.0-1.0)\n"
                "Các trường: entry_id, hs_code, goods_name, quantity, unit, unit_price, "
                "total_price, currency, origin_country, declaration_elements, invoice_total\n\n"
                "【Nhiệm vụ 3 — Nếu là ảnh thường, mô tả nội dung và liệt kê hàng hóa】\n\n"
                "Trả về CHỈ JSON (không Markdown):\n"
                '{{"document_type":"...","fields":[{{"field_name":"...","original_text":"...",'
                '"standard_value":"...","confidence_score":0.9,"notes":""}}],'
                '"description":"...","items":[],"category":"...","tags":[],'
                '"customs_relevance":"high/medium/low/none","overall_confidence":0.85,"notes":""}}'
            )
        else:
            return (
                f"{lang_instr}\n\n"
                "你是海关单证分析专家。请分析这张图片。\n\n"
                "【任务1 — 文档分类】判断类型：\n"
                "declaration(报关单) / invoice(发票) / packing_list(装箱单) / "
                "certificate(原产地证) / general_image(普通图片) / unknown\n\n"
                "【任务2 — 如是单证，提取以下字段】\n"
                "对每个字段提供: field_name, original_text(OCR原文), standard_value(标准化值), "
                "confidence_score(0.0-1.0), notes\n"
                "可提取字段: entry_id(报关单号), hs_code(HS编码), goods_name(货物名称), "
                "quantity(数量), unit(单位), unit_price(单价), total_price(总价), "
                "currency(币种), origin_country(原产国), declaration_elements(申报要素), "
                "invoice_total(发票总额)\n\n"
                "【任务3 — 如是普通图片，描述内容并列物品】\n"
                "每个物品: name, category(电子产品/纺织品/机械设备/食品/原材料/包装材料/化工产品/其他), "
                "quantity, attributes, confidence(high/medium/low)\n\n"
                "严格只返回 JSON（不要 Markdown 代码块标记）：\n"
                '{"document_type":"...","fields":[{...}],"description":"...","items":[{...}],'
                '"category":"...","tags":[],"customs_relevance":"high/medium/low/none",'
                '"overall_confidence":0.85,"notes":""}'
            )

    def _call_gemini_vision_document(self, image_bytes: bytes, mime_type: str, language: str) -> str:
        """Gemini Vision — Document 模式"""
        prompt = self._build_document_prompt(language)
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        api_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._gemini_model}:generateContent?key={self._api_key}"
        )
        payload = {
            "contents": [{"parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime_type, "data": image_b64}},
            ]}],
            "generationConfig": {"temperature": self._temperature, "maxOutputTokens": self._max_tokens},
        }
        print(f"[DEBUG] 调用 Gemini Document API: {self._gemini_model}")
        response = requests.post(api_url, json=payload, timeout=60, verify=False)
        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()

    def _call_azure_openai_vision_document(self, image_bytes: bytes, mime_type: str, language: str) -> str:
        """Azure OpenAI — Document 模式"""
        if not self._azure_client:
            raise RuntimeError("Azure OpenAI 客户端未初始化")
        prompt = self._build_document_prompt(language)
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        image_url = f"data:{mime_type};base64,{image_b64}"
        response = self._azure_client.chat.completions.create(
            model=self._azure_deployment,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]}],
            max_tokens=self._max_tokens, temperature=self._temperature,
        )
        return response.choices[0].message.content.strip()

    def _call_openai_compatible_vision_document(self, image_bytes: bytes, mime_type: str, language: str) -> str:
        """OpenAI 兼容 — Document 模式"""
        if not self._openai_client:
            raise RuntimeError(f"{self._provider} 客户端未初始化")
        prompt = self._build_document_prompt(language)
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        image_url = f"data:{mime_type};base64,{image_b64}"
        response = self._openai_client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]}],
            max_tokens=self._max_tokens, temperature=self._temperature,
        )
        return response.choices[0].message.content.strip()

    def _parse_document_response(
        self, raw_text: str, image_bytes: bytes, mime_type: str,
        language: str, model_used: str, processing_time_ms: int,
    ) -> DocumentResult:
        """将 VLM 返回的 JSON 文本解析为 DocumentResult。"""
        import re as _re

        # 1. 解析 JSON
        parsed = None
        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError:
            m = _re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw_text, _re.DOTALL)
            if m:
                try:
                    parsed = json.loads(m.group(1))
                except json.JSONDecodeError:
                    pass
            if parsed is None:
                brace_start = raw_text.find("{")
                brace_end = raw_text.rfind("}")
                if brace_start >= 0 and brace_end > brace_start:
                    try:
                        parsed = json.loads(raw_text[brace_start:brace_end + 1])
                    except json.JSONDecodeError:
                        pass

        if parsed is None:
            # 无法解析，返回原始文本作为描述
            return DocumentResult(
                document_id=f"doc_{len(image_bytes)}_{hash(raw_text[:50]) & 0xFFFF:04x}",
                document_type=DocumentType.UNKNOWN,
                raw_text=raw_text[:1000],
                model_used=model_used,
                processing_time_ms=processing_time_ms,
                warnings=["VLM 返回格式不符合预期，已保留原始文本"],
            )

        # 2. 确定文档类型
        doc_type_str = parsed.get("document_type", "unknown")
        try:
            doc_type = DocumentType(doc_type_str)
        except ValueError:
            doc_type = DocumentType.UNKNOWN

        # 3. 构建字段
        fields = []
        for f in parsed.get("fields", []):
            fname = f.get("field_name", "")
            score = float(f.get("confidence_score", 0.80))
            is_crit = fname in {"entry_id", "hs_code", "total_price", "currency", "quantity"}
            conf = classify_confidence(score, is_crit)
            fields.append(FieldEvidence(
                field_name=fname,
                original_text=f.get("original_text", ""),
                standard_value=f.get("standard_value", ""),
                confidence=conf,
                confidence_score=score,
                needs_review=needs_review(conf, is_crit),
                is_critical=is_crit,
                notes=f.get("notes", ""),
            ))

        # 4. 构建物品表格（从 items 转换）
        items = parsed.get("items", [])
        tables = []
        if items:
            headers = ["序号", "物品名称", "类别", "数量", "特征", "置信度"]
            cells = []
            for i, item in enumerate(items):
                row = i + 2
                data = [
                    str(i + 1),
                    str(item.get("name", "")),
                    str(item.get("category", "")),
                    str(item.get("quantity", "")),
                    str(item.get("attributes", "")),
                    str(item.get("confidence", "medium")),
                ]
                for col, text in enumerate(data):
                    conf_str = item.get("confidence", "medium") if col == 5 else "high"
                    cells.append(CellResult(
                        row=row, column=col + 1, text=text,
                        confidence=ConfidenceLevel(conf_str if conf_str in ("high","medium","low") else "medium"),
                        confidence_score=0.90 if conf_str == "high" else (0.70 if conf_str == "medium" else 0.40),
                        cell_id=f"R{row}C{col+1}",
                    ))
            for col_idx, h in enumerate(headers):
                cells.append(CellResult(row=1, column=col_idx + 1, text=h,
                                        confidence=ConfidenceLevel.HIGH, confidence_score=1.0,
                                        cell_id=f"R1C{col_idx+1}"))
            tables.append(TableResult(
                table_id="items_table",
                caption=parsed.get("description", "")[:100],
                rows=len(items) + 1, columns=len(headers),
                headers=headers, cells=cells,
            ))

        # 5. 组装 DocumentResult
        overall_conf = float(parsed.get("overall_confidence", 0.80))
        warnings_list = []
        if doc_type == DocumentType.UNKNOWN:
            warnings_list.append("图片类型无法确定，结果仅供参考")
        if not fields and not items:
            warnings_list.append("未识别到结构化字段或物品")

        return DocumentResult(
            document_id=f"doc_{hash(raw_text[:50]) & 0xFFFFFFFF:08x}",
            document_type=doc_type,
            tables=tables,
            fields=fields,
            raw_text=parsed.get("description", raw_text[:500]),
            confidence=classify_confidence(overall_conf, False),
            page_count=1,
            model_used=model_used,
            processing_time_ms=processing_time_ms,
            warnings=warnings_list,
            metadata={
                "category": parsed.get("category", ""),
                "tags": parsed.get("tags", []),
                "customs_relevance": parsed.get("customs_relevance", ""),
                "notes": parsed.get("notes", ""),
                "language": language,
            },
        )

    def _validate_image_content(self, image_bytes: bytes, mime_type: str, language: str = "zh") -> Tuple[bool, str]:
        """
        使用 Gemini 的快速能力判断图片内容是否为报关单
        """
        language_instruction = self._get_language_instruction(language)

        # 根据语言设置校验提示词
        if language == "vi":
            prompt = f'{language_instruction}\nHình ảnh này có phải là tờ khai hải quan không? Vui lòng trả lời "Có" hoặc "Không". Nếu là "Không", hãy giải thích ngắn gọn bằng tiếng Việt nội dung hình ảnh là gì (ví dụ: Đây là ảnh phong cảnh).'
        else:
            prompt = f'{language_instruction}\n这张图片是海关货物报关单吗？请直接回答"是"或"否"。如果是"否"，请用一句话简单说明图片内容（例如：这是一张风景照）。'

        try:
            # 使用 Gemini Flash 快速校验（始终使用 Gemini，因为最快）
            api_url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.0-flash-exp:generateContent?key={self._api_key if self._provider == 'gemini' else settings.GOOGLE_API_KEY}"
            )
            image_b64 = base64.b64encode(image_bytes).decode("ascii")
            payload = {
                "contents": [{"parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": image_b64}}
                ]}],
                "generationConfig": {"temperature": 0.0, "maxOutputTokens": 50}
            }
            response = requests.post(api_url, json=payload, timeout=30, verify=False)
            response.raise_for_status()
            data = response.json()
            result_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()

            # 根据语言设置解析响应
            if language == "vi":
                if result_text.startswith("Có") or result_text.startswith("có"):
                    return True, "Là tờ khai hải quan"
                else:
                    reason = result_text.replace("Không", "").replace("không", "").strip("，。,. ")
                    return False, reason if reason else "Nội dung không phù hợp"
            else:
                if result_text.startswith("是"):
                    return True, "是报关单"
                else:
                    reason = result_text.replace("否", "").strip("，。,. ")
                    return False, reason if reason else "内容不符"
        except Exception as e:
            print(f"[Warning] 图片内容校验步骤失败: {e}，默认通过")
            return True, "校验异常，已跳过"

    def _call_gemini_vision(self, image_bytes: bytes, mime_type: str, language: str = "zh") -> str:
        """调用 Gemini Vision API"""
        api_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._gemini_model}:generateContent?key={self._api_key}"
        )
        prompt = self._build_prompt(language)
        image_b64 = base64.b64encode(image_bytes).decode("ascii")

        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": image_b64}}
                ]
            }],
            "generationConfig": {
                "temperature": self._temperature,
                "maxOutputTokens": self._max_tokens
            }
        }

        print(f"[DEBUG] 调用 Gemini API: {self._gemini_model}")
        response = requests.post(api_url, json=payload, timeout=60, verify=False)
        response.raise_for_status()
        data = response.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Gemini 响应格式解析错误: {json.dumps(data)}") from e

    def _call_azure_openai_vision(self, image_bytes: bytes, mime_type: str, language: str = "zh") -> str:
        """调用 Azure OpenAI GPT-4o 模型进行图片识别"""
        if not self._azure_client:
            raise RuntimeError("Azure OpenAI 客户端未初始化")

        image_b64 = base64.b64encode(image_bytes).decode('ascii')
        image_url = f"data:{mime_type};base64,{image_b64}"
        prompt = self._build_prompt(language)

        print(f"[DEBUG] 调用 Azure OpenAI API: {self._azure_deployment}")

        response = self._azure_client.chat.completions.create(
            model=self._azure_deployment,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}}
                    ],
                }
            ],
            max_tokens=self._max_tokens,
            temperature=self._temperature
        )
        return response.choices[0].message.content.strip()

    def _call_openai_compatible_vision(self, image_bytes: bytes, mime_type: str, language: str = "zh") -> str:
        """
        调用 OpenAI 兼容的 Vision API
        支持: deepseek, openai, qwen, zhipu, siliconflow, custom
        """
        if not self._openai_client:
            raise RuntimeError(f"{self._provider} 客户端未初始化")

        image_b64 = base64.b64encode(image_bytes).decode('ascii')
        image_url = f"data:{mime_type};base64,{image_b64}"
        prompt = self._build_prompt(language)

        print(f"[DEBUG] 调用 {self._provider} API: {self._model}")
        print(f"[DEBUG] Base URL: {self._base_url}")

        response = self._openai_client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}}
                    ]
                }
            ],
            max_tokens=self._max_tokens,
            temperature=self._temperature
        )
        return response.choices[0].message.content.strip()

    def _call_gemini_text(self, prompt: str, language: str = "zh") -> str:
        """调用 Gemini Text API"""
        api_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._gemini_model}:generateContent?key={self._api_key if self._provider == 'gemini' else settings.GOOGLE_API_KEY}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self._temperature,
                "maxOutputTokens": self._max_tokens
            }
        }
        response = requests.post(api_url, json=payload, timeout=60, verify=False)
        response.raise_for_status()
        data = response.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Gemini 文本响应解析错误: {json.dumps(data)}") from e

    def _build_prompt(self, language: str = "zh") -> str:
        """构建 OCR 提示词"""
        language_instruction = self._get_language_instruction(language)

        if language == "vi":
            return (
                f"{language_instruction}\n\n"
                "Bạn là trợ lý OCR tờ khai hải quan. Chỉ xuất văn bản thuần túy, KHÔNG Markdown.\n"
                "Trích xuất thông tin từ hình ảnh và xuất TOÀN BỘ bằng tiếng Việt.\n"
                "Nếu thông tin trống, ghi: để trống.\n\n"
                "Định dạng xuất:\n"
                "Số tờ khai:...\n"
                "Danh mục hàng hóa:\n"
                "- Hàng hóa 1:\n"
                "  Tên hàng hóa:...\n"
                "  Mã HS:... (giữ giải thích tiếng Trung nếu có)\n"
                "  Số lượng:... (kèm đơn vị)\n"
                "  Đơn giá:... (kèm tiền tệ)\n"
                "  Tổng giá:... (kèm tiền tệ)\n"
                "  Yếu tố khai báo:... (cách bằng dấu chấm phẩy)\n"
                "- Hàng hóa 2:\n"
                "  Tên hàng hóa:...\n"
                "  Mã HS:...\n"
                "  Số lượng:...\n"
                "  Đơn giá:...\n"
                "  Tổng giá:...\n"
                "  Yếu tố khai báo:...\n"
                "【Chứng từ đính kèm】\n"
                "Tổng trị giá hóa đơn:... (kèm tiền tệ)\n\n"
                "Quy tắc:\n"
                "1) Luôn dùng định dạng \"Danh mục hàng hóa/Hàng hóa 1\" ngay cả khi chỉ có 1 hàng.\n"
                "2) Đánh số theo thứ tự xuất hiện.\n"
                "3) Không gộp trường của các hàng khác nhau.\n"
                "4) Không đoán, thiếu thì ghi \"không xác định\".\n"
                "5) Kết quả phải hoàn toàn bằng tiếng Việt."
            )
        else:
            return (
                f"{language_instruction}\n\n"
                "你是报关单OCR与结构化助手。只输出纯文本，不要Markdown。\n"
                "从图片中提取报关单关键信息，全部用简体中文输出。\n"
                "如果某些信息为空，请标明为：为空。\n\n"
                "严格按以下格式输出：\n"
                "报关单号：...\n"
                "商品清单：\n"
                "- 商品1：\n"
                "  货物名称：...\n"
                "  HS编码：... (如果有中文释义请保留)\n"
                "  数量：... (含单位)\n"
                "  单价：... (含币种)\n"
                "  总价：... (含币种)\n"
                "  申报要素：... (用分号分隔)\n"
                "- 商品2：\n"
                "  货物名称：...\n"
                "  HS编码：...\n"
                "  数量：...\n"
                "  单价：...\n"
                "  总价：...\n"
                "  申报要素：...\n"
                "【随附单证】\n"
                "发票总额：... (含币种)\n\n"
                "规则：\n"
                "1) 若只有一个商品，也必须使用\"商品清单/商品1\"格式。\n"
                "2) 多个商品时按图片出现顺序编号。\n"
                "3) 不要合并不同商品的字段。\n"
                "4) 不要猜测，缺失字段写\"未知\"。\n"
                "5) 所有输出必须使用简体中文。"
            )

    def _build_reformat_prompt(self, raw_text: str, language: str = "zh") -> str:
        """构建重新格式化的提示词"""
        language_instruction = self._get_language_instruction(language)

        if language == "vi":
            return (
                f"{language_instruction}\n\n"
                "Sắp xếp nội dung tờ khai sau thành định dạng cố định. Chỉ xuất văn bản thuần túy, KHÔNG Markdown.\n"
                "Toàn bộ kết quả phải bằng tiếng Việt.\n\n"
                "Định dạng:\n"
                "Số tờ khai:...\n"
                "Danh mục hàng hóa:\n"
                "- Hàng hóa 1:\n"
                "  Tên hàng hóa:...\n"
                "  Mã HS:... (giữ giải thích tiếng Trung nếu có)\n"
                "  Số lượng:... (kèm đơn vị)\n"
                "  Đơn giá:... (kèm tiền tệ)\n"
                "  Tổng giá:... (kèm tiền tệ)\n"
                "  Yếu tố khai báo:... (cách bằng dấu chấm phẩy)\n"
                "- Hàng hóa 2:...\n"
                "【Chứng từ đính kèm】\n"
                "Tổng trị giá hóa đơn:... (kèm tiền tệ)\n\n"
                "Quy tắc:\n"
                "1) Luôn dùng \"Danh mục hàng hóa/Hàng hóa 1\" ngay cả khi chỉ có 1 hàng.\n"
                "2) Đánh số theo thứ tự xuất hiện.\n"
                "3) Không gộp trường.\n"
                "4) Không đoán, thiếu thì ghi \"không xác định\".\n"
                "5) Kết quả phải hoàn toàn bằng tiếng Việt.\n\n"
                f"Nội dung gốc:\n{raw_text}"
            )
        else:
            return (
                f"{language_instruction}\n\n"
                "将下面的报关单内容整理成固定格式。只输出纯文本，不要Markdown。所有输出必须使用简体中文。\n\n"
                "格式：\n"
                "报关单号：...\n"
                "商品清单：\n"
                "- 商品1：\n"
                "  货物名称：...\n"
                "  HS编码：... (如果有中文释义请保留)\n"
                "  数量：... (含单位)\n"
                "  单价：... (含币种)\n"
                "  总价：... (含币种)\n"
                "  申报要素：... (用分号分隔)\n"
                "- 商品2：...\n"
                "【随附单证】\n"
                "发票总额：... (含币种)\n\n"
                "规则：\n"
                "1) 若只有一个商品，也必须使用\"商品清单/商品1\"格式。\n"
                "2) 多个商品按出现顺序编号。\n"
                "3) 不要合并不同商品的字段。\n"
                "4) 不要猜测，缺失字段写\"未知\"。\n"
                "5) 所有输出必须使用简体中文。\n\n"
                f"原始内容：\n{raw_text}"
            )

    def _ensure_multi_item_format(self, text: str, language: str = "zh") -> str:
        """确保输出格式符合多商品要求"""
        format_markers = ["商品清单", "商品1", "Danh mục hàng hóa", "Hàng hóa 1"]
        if any(marker in text for marker in format_markers):
            return text
        print("INFO: 识别结果格式不完全符合要求，正在尝试自动修正...")
        prompt = self._build_reformat_prompt(text, language)
        return self._call_gemini_text(prompt, language)

    def _get_language_instruction(self, language: str) -> str:
        """生成语言输出指令"""
        language_names = {
            "zh": "简体中文",
            "vi": "Tiếng Việt"
        }
        language_name = language_names.get(language, language_names["zh"])

        if language == "vi":
            return f"[NGÔN NGỮ: PHẢI xuất kết quả bằng TIẾNG VIỆT. Không dùng tiếng Trung/Anh. Dịch mọi nội dung sang tiếng Việt.]"
        else:
            return f"[语言：必须使用简体中文输出。禁止使用越南语/英语等其他语言。将所有内容翻译成中文。]"
