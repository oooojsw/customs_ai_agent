import base64
import json
import requests
from typing import Tuple
from openai import AzureOpenAI

from src.config.loader import settings

# 自定义异常
class NotDeclarationError(ValueError):
    """当图片内容不是报关单时抛出"""
    pass

class ImageTextExtractor:
    def __init__(self):
        self._gemini_model = settings.MODEL_NAME
        self._azure_deployment = settings.AZURE_OAI_DEPLOYMENT
        
        # 初始化 Azure OpenAI 客户端
        if all([settings.AZURE_OAI_KEY, settings.AZURE_OAI_ENDPOINT, settings.AZURE_OAI_DEPLOYMENT]):
            self._azure_client = AzureOpenAI(
                api_key=settings.AZURE_OAI_KEY,
                api_version=settings.AZURE_OAI_VERSION,
                azure_endpoint=settings.AZURE_OAI_ENDPOINT
            )
        else:
            self._azure_client = None

    def extract_text(self, image_bytes: bytes, mime_type: str) -> Tuple[str, str]:
        """
        核心函数：从图片中提取报关单字段
        1. 校验图片是否为报关单
        2. 尝试用 Gemini 提取
        3. 如果 Gemini 失败，自动切换到 Azure OpenAI
        """
        # 1. 内容校验
        is_declaration, reason = self._validate_image_content(image_bytes, mime_type)
        if not is_declaration:
            raise NotDeclarationError(f"图片似乎不是报关单，因为：{reason}")

        # 2. 主模型 (Gemini)
        try:
            print("INFO: 正在尝试使用 Gemini-Flash 模型进行图片识别...")
            text = self._call_gemini_vision(image_bytes, mime_type)
            # 格式化检查与修正
            text = self._ensure_multi_item_format(text)
            print("INFO: Gemini-Flash 识别成功。")
            return text, self._gemini_model
        except Exception as e:
            print(f"[Warning] 警告: Gemini-Flash 识别失败: {e}")
            # 3. 备用模型 (Azure OpenAI)
            if self._azure_client:
                print("INFO: 已切换到 Azure OpenAI 模型进行重试...")
                try:
                    text = self._call_azure_openai_vision(image_bytes, mime_type)
                    # 格式化检查与修正 (用 Gemini-Text)
                    text = self._ensure_multi_item_format(text)
                    print("INFO: Azure OpenAI 识别成功。")
                    return text, self._azure_deployment
                except Exception as az_e:
                    print(f"[Error] 错误: Azure OpenAI 备用模型也识别失败: {az_e}")
                    raise RuntimeError("主模型和备用模型均无法处理该图片") from az_e
            else:
                print("[Error] 错误: 未配置 Azure OpenAI 备用模型，无法重试。")
                raise RuntimeError("Gemini 图片识别失败，且未配置备用模型") from e


    def _validate_image_content(self, image_bytes: bytes, mime_type: str) -> Tuple[bool, str]:
        """
        使用 Gemini 的快速能力判断图片内容是否为报关单
        """
        prompt = "这张图片是海关货物报关单吗？请直接回答“是”或“否”。如果是“否”，请用一句话简单说明图片内容（例如：这是一张风景照）"
        try:
            # 直接调用原始 Gemini 接口
            api_url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self._gemini_model}:generateContent?key={settings.GOOGLE_API_KEY}"
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
            
            if result_text.startswith("是"):
                return True, "是报关单"
            else:
                # 提取“否”之后的理由
                reason = result_text.replace("否", "").strip("，。,. ")
                return False, reason if reason else "内容不符"
        except Exception as e:
            print(f"[Warning] 警告: 图片内容校验步骤失败: {e}。为保证流程继续，暂时跳过校验。")
            # 在校验失败时默认通过，以避免网络问题导致整个流程中断
            return True, "校验异常，已跳过"

    def _call_azure_openai_vision(self, image_bytes: bytes, mime_type: str) -> str:
        """调用 Azure OpenAI GPT-4o 模型进行图片识别"""
        if not self._azure_client:
            raise RuntimeError("Azure OpenAI 客户端未初始化")
            
        image_b64 = base64.b64encode(image_bytes).decode('ascii')
        image_url = f"data:{mime_type};base64,{image_b64}"
        
        prompt = self._build_prompt() # 复用相同的结构化 Prompt

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
            max_tokens=2048,
            temperature=0.1
        )
        return response.choices[0].message.content.strip()

    def _build_prompt(self) -> str:
        return (
            "你是报关单OCR与结构化助手。请只输出纯文本，不要Markdown。"
            "请从图片中提取报关单关键信息，如果某些信息为空，请标明为：为空，并严格按以下格式输出：\n"
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
            "发票总额：... (含币种)\n"
            "规则：\n"
            "1) 若只有一个商品，也必须使用“商品清单/商品1”格式。\n"
            "2) 多个商品时按图片出现顺序编号。\n"
            "3) 不要合并不同商品的字段。\n"
            "4) 不要猜测，缺失字段写“未知”。"
        )

    def _build_reformat_prompt(self, raw_text: str) -> str:
        # ... (和之前一样)
        return (
            "请将下面的报关单内容整理成固定格式，输出纯文本，不要Markdown：\n"
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
            "发票总额：... (含币种)\n"
            "规则：\n"
            "1) 若只有一个商品，也必须使用“商品清单/商品1”格式。\n"
            "2) 多个商品按出现顺序编号。\n"
            "3) 不要合并不同商品的字段。\n"
            "4) 不要猜测，缺失字段写“未知”。\n"
            "原始内容：\n"
            f"{raw_text}"
        )

    def _ensure_multi_item_format(self, text: str) -> str:
        if "商品清单" in text or "商品1" in text:
            return text
        print("INFO: 识别结果格式不完全符合要求，正在尝试自动修正...")
        prompt = self._build_reformat_prompt(text)
        # 统一使用 Gemini-Text 进行修正，成本低、速度快
        return self._call_gemini_text(prompt)

    def _call_gemini_vision(self, image_bytes: bytes, mime_type: str) -> str:
        api_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self._gemini_model}:generateContent?key={settings.GOOGLE_API_KEY}"
        )
        prompt = self._build_prompt()
        image_b64 = base64.b64encode(image_bytes).decode("ascii")

        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": image_b64}}
                ]
            }],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 2048
            }
        }

        response = requests.post(api_url, json=payload, timeout=60, verify=False)
        response.raise_for_status() # 失败时抛出 HTTPError
        data = response.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Gemini 响应格式解析错误: {json.dumps(data)}") from e

    def _call_gemini_text(self, prompt: str) -> str:
        # ... (和之前一样)
        api_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.MODEL_NAME.replace('vision', '')}:generateContent?key={settings.GOOGLE_API_KEY}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048}
        }
        response = requests.post(api_url, json=payload, timeout=60, verify=False)
        response.raise_for_status()
        data = response.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Gemini 文本响应解析错误: {json.dumps(data)}") from e