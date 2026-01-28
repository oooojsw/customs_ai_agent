import json
import re
import requests
import urllib3
import time
from typing import List, Tuple
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 引入 OpenAI 兼容客户端 (支持 DeepSeek 和 Azure)
from openai import AzureOpenAI, OpenAI, APITimeoutError, APIConnectionError
from src.config.loader import settings

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class LLMService:
    def __init__(self, llm_config: dict = None):
        """
        初始化 LLM 服务 - 深度修复版
        """
        # ==========================================
        # 1. 基础网络会话 (用于 Gemini REST API)
        # ==========================================
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3, backoff_factor=1, status_forcelist=[500, 502, 504],
            allowed_methods=["POST"], raise_on_status=False
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry_strategy))
        self.session.mount("http://", HTTPAdapter(max_retries=retry_strategy))

        if settings.HTTP_PROXY or settings.HTTPS_PROXY:
            self.session.proxies = {"http": settings.HTTP_PROXY, "https": settings.HTTPS_PROXY}

        # ==========================================
        # 2. 确定配置来源 (用户 vs 系统)
        # ==========================================
        self.client = None
        self.model_name = settings.DEEPSEEK_MODEL
        self._config_source = "env"
        self.provider = "deepseek" # 默认为 deepseek

        # 提取配置参数
        api_key = settings.DEEPSEEK_API_KEY
        base_url = settings.DEEPSEEK_BASE_URL

        # Azure 特有默认值
        azure_endpoint = settings.AZURE_OAI_ENDPOINT
        api_version = settings.AZURE_OAI_VERSION

        # 如果用户配置存在且启用，覆盖默认值
        if llm_config and llm_config.get('source') == 'user':
            self._config_source = "user"
            self.provider = llm_config.get('provider', 'deepseek')
            self.model_name = llm_config.get('model', 'deepseek-chat')

            api_key = llm_config.get('api_key')
            base_url = llm_config.get('base_url')

            # Azure 特有字段
            if self.provider == 'azure':
                # 注意：Azure 配置通常把 endpoint 存在 base_url 字段，或者单独字段
                # 这里做兼容处理
                azure_endpoint = llm_config.get('base_url')
                api_version = llm_config.get('api_version')

        print(f"[LLMService] 初始化... 来源: {self._config_source}, 厂商: {self.provider}, 模型: {self.model_name}")

        # ==========================================
        # 3. 客户端初始化 (严格分支)
        # ==========================================
        try:
            if self.provider == 'azure':
                # --- Azure 分支 ---
                if not azure_endpoint or not api_key:
                    raise ValueError("Azure 配置缺失 Endpoint 或 API Key")

                print(f"[LLMService] 初始化 Azure OpenAI 客户端: {azure_endpoint}")
                self.client = AzureOpenAI(
                    api_key=api_key,
                    api_version=api_version,
                    azure_endpoint=azure_endpoint,
                    timeout=60.0,
                    max_retries=2
                )

            else:
                # --- OpenAI 兼容分支 (DeepSeek, SiliconFlow, Qwen, Custom) ---
                if not base_url or not api_key:
                    # 只有在非 Gemini 情况下才报错 (Gemini 使用 REST API)
                    if self.provider != 'gemini':
                        raise ValueError(f"{self.provider} 配置缺失 Base URL 或 API Key")

                if self.provider != 'gemini':
                    print(f"[LLMService] 初始化 OpenAI 兼容客户端: {base_url}")
                    self.client = OpenAI(
                        api_key=api_key,
                        base_url=base_url,
                        timeout=60.0,
                        max_retries=2
                    )

        except Exception as e:
            print(f"❌ [LLMService] 客户端初始化失败: {e}")
            self.client = None

    def call_llm(self, system_prompt: str, user_prompt: str) -> List[str]:
        """
        核心 LLM 调用函数
        """
        full_prompt = f"{system_prompt}\n\n{user_prompt}"

        # 1. Gemini 特殊处理 (REST API)
        if self.provider == 'gemini':
            try:
                # 注意：Gemini 在 .env 中使用 GOOGLE_API_KEY，需要确保此处逻辑兼容
                # 这里简化处理，假设 Gemini 总是走 _call_gemini
                return self._parse_json_response(self._call_gemini(full_prompt)[0])
            except Exception as e:
                return ["x", f"Gemini 调用失败: {str(e)[:50]}"]

        # 2. Azure / OpenAI 兼容处理
        if not self.client:
            return ["x", "系统错误：LLM 客户端未成功初始化，请检查配置"]

        try:
            raw_text = self._call_standard_client(full_prompt)
            return self._parse_json_response(raw_text)
        except Exception as e:
            error_msg = str(e)
            print(f"[LLM] 调用失败: {error_msg[:100]}...")
            if "401" in error_msg:
                return ["x", "认证失败：API Key 无效"]
            if "404" in error_msg:
                return ["x", "路径错误：Base URL 或 模型名称不正确"]
            return ["x", f"AI服务调用异常: {error_msg[:30]}"]

    def _call_standard_client(self, prompt: str) -> str:
        """统一调用 Azure 或 OpenAI 兼容接口"""
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8192,
            temperature=0.1,
            stream=False # 审单功能不需要流式
        )
        return response.choices[0].message.content

    def _call_gemini(self, prompt: str) -> Tuple[str, str]:
        """Gemini REST API 调用"""
        # 使用配置中的 Key 或者 .env 中的 Key
        api_key = settings.GOOGLE_API_KEY
        if self._config_source == 'user' and self.provider == 'gemini':
            # 如果用户专门配置了 Gemini，尝试从用户配置获取 Key (虽然目前前端主要配 DeepSeek)
            # 这里暂时保留使用 .env 的逻辑，除非架构大改支持 Gemini 用户配置
            pass

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.MODEL_NAME}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1}
        }

        resp = self.session.post(url, json=payload, timeout=60, verify=False)
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini {resp.status_code}: {resp.text}")

        return resp.json()['candidates'][0]['content']['parts'][0]['text'], "Gemini"

    def _parse_json_response(self, raw_text: str) -> List[str]:
        """JSON 解析器 (保持原样)"""
        clean_text = raw_text.strip()
        match_code = re.search(r'```json\s*(.*?)\s*```', clean_text, re.DOTALL | re.IGNORECASE)
        if match_code: clean_text = match_code.group(1)
        else: clean_text = clean_text.replace("```", "")

        match_bracket = re.search(r'\[.*?\]', clean_text, re.DOTALL)
        if match_bracket: clean_text = match_bracket.group(0)

        try:
            parsed = json.loads(clean_text)
            if isinstance(parsed, list) and len(parsed) >= 2:
                return [str(parsed[0]), str(parsed[1])]
            return ["x", f"格式错误: {clean_text[:20]}..."]
        except:
            if "√" in clean_text or "pass" in clean_text.lower():
                return ["√", clean_text.replace("√","").strip()]
            return ["x", "无法解析响应"]

# --- 单元测试 ---
if __name__ == "__main__":
    # 简单的运行测试
    service = LLMService()
    print("正在测试 LLM 连接...")
    res = service.call_llm("你是一个测试助手。", "请返回json格式：[\"√\", \"测试成功\"]")
    print(f"测试结果: {res}")
