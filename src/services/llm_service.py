import json
import re
import requests
import urllib3
import time
from typing import List, Tuple
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 引入 OpenAI 兼容客户端 (支持 DeepSeek 和 Azure)
from openai import AzureOpenAI, OpenAI
from src.config.loader import settings

# 禁用 SSL 警告 (因为我们可能用代理)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class LLMService:
    def __init__(self):
        # ==========================================
        # 1. 初始化 HTTP Session (用于 Gemini REST API)
        # ==========================================
        self.session = requests.Session()
        
        # 底层连接重试配置 (针对 Connection Reset / 断网)
        retry_strategy = Retry(
            total=3,
            backoff_factor=1, 
            status_forcelist=[500, 502, 504],
            allowed_methods=["POST"],
            raise_on_status=False
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        # 代理配置
        if settings.HTTP_PROXY or settings.HTTPS_PROXY:
            self.session.proxies = {
                "http": settings.HTTP_PROXY,
                "https": settings.HTTPS_PROXY
            }
            # print(f"🌐 [LLMService] 已启用代理: {settings.HTTP_PROXY}")

        # ==========================================
        # 2. 初始化 Azure OpenAI 客户端 (新增)
        # ==========================================
        if all([settings.AZURE_OAI_KEY, settings.AZURE_OAI_ENDPOINT, settings.AZURE_OAI_DEPLOYMENT]):
            try:
                self._azure_client = AzureOpenAI(
                    api_key=settings.AZURE_OAI_KEY,
                    api_version=settings.AZURE_OAI_VERSION,
                    azure_endpoint=settings.AZURE_OAI_ENDPOINT,
                    timeout=60.0
                )
                print("[LLMService] Azure OpenAI client ready")
            except Exception as e:
                print(f"[Warning] [LLMService] Azure OpenAI 初始化失败: {e}")
                self._azure_client = None
        else:
            self._azure_client = None

        # ==========================================
        # 3. 初始化 DeepSeek 客户端 (作为备用)
        # ==========================================
        if settings.DEEPSEEK_API_KEY:
            try:
                self._deepseek_client = OpenAI(
                    api_key=settings.DEEPSEEK_API_KEY,
                    base_url=settings.DEEPSEEK_BASE_URL,
                    timeout=60.0
                )
                print("[LLMService] DeepSeek client ready")
            except Exception as e:
                print(f"[Warning] [LLMService] DeepSeek 初始化失败: {e}")
                self._deepseek_client = None
        else:
            self._deepseek_client = None

    def call_llm(self, system_prompt: str, user_prompt: str) -> List[str]:
        """
        核心 LLM 调用函数，实现了三级备用逻辑。
        返回格式: [ "符号", "理由" ]
        例如: ["x", "HS编码与品名不符"] 或 ["√", "申报要素完整"]
        """
        full_prompt = f"{system_prompt}\n\n{user_prompt}"

        # --- 第一级: 尝试 Gemini (速度最快，免费) ---
        if settings.GOOGLE_API_KEY:
            # print("INFO: [Attempt 1] Calling Gemini...")
            try:
                raw_text, model_name = self._call_gemini(system_prompt, user_prompt)
                return self._parse_json_response(raw_text)
            except Exception as e:
                print(f"[Warning] [LLM] Gemini 调用失败: {e}")
        else:
            print("INFO: [LLM] Google API Key 未配置，跳过 Gemini")

        # --- 第二级: 尝试 Azure OpenAI (企业级稳定) ---
        if self._azure_client:
            print("INFO: [Attempt 2] Calling Azure OpenAI...")
            try:
                raw_text, model_name = self._call_azure_openai(full_prompt)
                return self._parse_json_response(raw_text)
            except Exception as e:
                print(f"[Warning] [LLM] Azure OpenAI 调用失败: {e}")
        
        # --- 第三级: 尝试 DeepSeek (最强逻辑) ---
        if self._deepseek_client:
            print("INFO: [Attempt 3] Calling DeepSeek...")
            try:
                raw_text, model_name = self._call_deepseek(full_prompt)
                return self._parse_json_response(raw_text)
            except Exception as e:
                print(f"[Warning] [LLM] DeepSeek 调用失败: {e}")
        
        # --- 所有模型均失败 ---
        print("[Error] [LLM] 严重错误: 所有可用模型均调用失败")
        return ["x", "系统错误：所有AI服务均不可用，请检查网络连接或API配额。"]

    def _call_gemini(self, system_p: str, user_p: str) -> Tuple[str, str]:
        """
        调用 Google Gemini REST API (不依赖 google-generativeai 库，减少依赖冲突)
        """
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.MODEL_NAME}:generateContent?key={settings.GOOGLE_API_KEY}"
        
        payload = {
            "contents": [{
                "parts": [{"text": f"{system_p}\n\n{user_p}"}]
            }],
            "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 8192 
            }
        }
        
        # 逻辑层重试 (专门针对 503 Overloaded)
        max_retries = 2
        for attempt in range(max_retries + 1):
            response = self.session.post(api_url, json=payload, timeout=60, verify=False)
            
            # 503 服务繁忙 -> 等待重试
            if response.status_code == 503:
                if attempt < max_retries:
                    time.sleep(2 * (attempt + 1))
                    continue
                else:
                    raise RuntimeError("Gemini 503 Overloaded (Max retries reached)")
            
            # 其他错误
            if response.status_code != 200:
                raise RuntimeError(f"Gemini HTTP {response.status_code}: {response.text}")
            
            # 成功获取
            result = response.json()
            if 'candidates' not in result:
                # 可能是被安全策略拦截 (PromptFeedback)
                if 'promptFeedback' in result:
                    raise RuntimeError(f"Gemini 安全拦截: {json.dumps(result['promptFeedback'])}")
                raise RuntimeError(f"Gemini 返回格式异常: {json.dumps(result)}")
                
            candidate = result['candidates'][0]
            if 'content' not in candidate:
                finish_reason = candidate.get('finishReason', 'UNKNOWN')
                raise RuntimeError(f"Gemini 生成中断: {finish_reason}")

            return candidate['content']['parts'][0]['text'], "Gemini"

    def _call_azure_openai(self, prompt: str) -> Tuple[str, str]:
        """
        调用 Azure OpenAI
        """
        response = self._azure_client.chat.completions.create(
            model=settings.AZURE_OAI_DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8192,
            temperature=0.1
        )
        return response.choices[0].message.content, "Azure"

    def _call_deepseek(self, prompt: str) -> Tuple[str, str]:
        """
        调用 DeepSeek
        """
        response = self._deepseek_client.chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8192,
            temperature=0.1
        )
        return response.choices[0].message.content, "DeepSeek"

    def _parse_json_response(self, raw_text: str) -> List[str]:
        """
        鲁棒性极强的 JSON 解析器
        目标：从 AI 的胡言乱语中提取出 ["符号", "理由"]
        """
        clean_text = raw_text.strip()
        
        # 1. 尝试移除 Markdown 代码块标记 (```json ... ```)
        # re.DOTALL 让 . 可以匹配换行符
        match_code = re.search(r'```json\s*(.*?)\s*```', clean_text, re.DOTALL | re.IGNORECASE)
        if match_code:
            clean_text = match_code.group(1)
        else:
            # 尝试移除普通代码块 ``` ... ```
            clean_text = clean_text.replace("```", "")

        # 2. 尝试提取最外层的方括号 [...]
        match_bracket = re.search(r'\[.*?\]', clean_text, re.DOTALL)
        if match_bracket:
            clean_text = match_bracket.group(0)

        # 3. 尝试 JSON 解析
        try:
            parsed = json.loads(clean_text)
            if isinstance(parsed, list) and len(parsed) >= 2:
                # 强制转为字符串，防止 AI 返回数字或布尔值导致前端渲染崩溃
                return [str(parsed[0]), str(parsed[1])]
            return ["x", f"AI返回格式不符合二元数组要求: {clean_text}"]
        except json.JSONDecodeError:
            # 4. JSON 解析失败的兜底策略 (Heuristic Parsing)
            # 如果 AI 很蠢，直接返回了： √ 申报要素完整
            lower_text = clean_text.lower()
            
            # 判断通过
            if "√" in clean_text or "pass" in lower_text or "true" in lower_text:
                # 去掉一些常见的干扰字符
                reason = clean_text.replace('"', '').replace("'", "").replace("[", "").replace("]", "").replace("√", "").strip()
                return ["√", reason or "通过"]
            
            # 判断不通过
            if "x" in clean_text.lower() or "fail" in lower_text or "false" in lower_text or "风险" in clean_text:
                reason = clean_text.replace('"', '').replace("'", "").replace("[", "").replace("]", "").replace("x", "").replace("X", "").strip()
                return ["x", reason or "存在风险"]

            return ["x", f"无法解析AI响应: {clean_text}"]
        except Exception as e:
            return ["x", f"解析过程发生未知错误: {str(e)}"]

# --- 单元测试 ---
if __name__ == "__main__":
    # 简单的运行测试
    service = LLMService()
    print("正在测试 LLM 连接...")
    res = service.call_llm("你是一个测试助手。", "请返回json格式：[\"√\", \"测试成功\"]")
    print(f"测试结果: {res}")