import json
import re
import requests
import urllib3
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import List
from src.config.loader import settings 

# 禁用 SSL 警告 (因为我们可能用代理)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class LLMService:
    def __init__(self):
        self.session = requests.Session()
        
        # 1. 底层连接重试配置
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

        # 2. 代理配置
        if settings.HTTP_PROXY or settings.HTTPS_PROXY:
            self.session.proxies = {
                "http": settings.HTTP_PROXY,
                "https": settings.HTTPS_PROXY
            }
            print(f"🌐 [LLMService] 已启用代理: {settings.HTTP_PROXY}")

    def call_llm(self, system_prompt: str, user_prompt: str) -> List[str]:
        """
        调用 Google Gemini API
        """
        # 0. 检查 Key 是否存在
        if not settings.GOOGLE_API_KEY:
            return ["x", "系统配置错误: 缺少 GOOGLE_API_KEY，请检查 .env 文件"]

        # 1. 拼接 URL
        api_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.MODEL_NAME}:generateContent?key={settings.GOOGLE_API_KEY}"
        )

        # 构造请求体
        payload = {
            "contents": [{
                "parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}]
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

        # 2. 发起请求 (带重试机制)
        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                # 打印调试信息 (第一次尝试时)
                if attempt == 0:
                    masked_url = api_url.replace(settings.GOOGLE_API_KEY, "******")
                    # print(f"📤 [LLM] Requesting: {masked_url}")

                response = self.session.post(api_url, json=payload, timeout=60, verify=False)
                
                # 处理 503 服务过载
                if response.status_code == 503:
                    if attempt < max_retries:
                        sleep_time = (attempt + 1) * 2
                        print(f"⚠️ Google服务器忙 (503)，{sleep_time}秒后重试...")
                        time.sleep(sleep_time)
                        continue
                    else:
                        return ["x", "Google服务器过载 (Overloaded)"]

                # 处理 400/403 等客户端错误 (通常是 Key 或 参数问题)
                if response.status_code != 200:
                    error_msg = response.text
                    print(f"❌ [LLM Error] Status: {response.status_code}, Body: {error_msg}")
                    
                    # 尝试解析具体的错误原因
                    try:
                        err_json = response.json()
                        err_reason = err_json.get('error', {}).get('message', '未知错误')
                        return ["x", f"API调用拒绝: {err_reason}"]
                    except:
                        return ["x", f"HTTP错误 {response.status_code}"]

                # 3. 解析结果
                result_json = response.json()
                
                if 'candidates' not in result_json:
                    # 可能是被安全策略拦截，或者没有生成内容
                    if 'promptFeedback' in result_json:
                        return ["x", f"内容被拦截: {result_json['promptFeedback']}"]
                    return ["x", "Google未返回有效候选结果"]
                
                candidate = result_json['candidates'][0]
                
                # 检查是否因为某种原因停止 (如 FinishReason: STOP)
                if 'content' not in candidate:
                     finish_reason = candidate.get('finishReason', 'UNKNOWN')
                     return ["x", f"生成异常停止: {finish_reason}"]

                raw_text = candidate['content']['parts'][0]['text']
                return self._parse_json_response(raw_text)

            except Exception as e:
                # 网络层面的报错 (如断网、代理失败)
                print(f"❌ [LLM Exception] {e}")
                return ["x", f"连接中断: {str(e)}"]

        return ["x", "未知错误"]

    def _parse_json_response(self, raw_text: str) -> List[str]:
        """
        清洗和解析 AI 返回的 JSON 字符串
        """
        clean_text = raw_text.strip()
        # 尝试提取 [] 中的内容，防止 AI 说废话
        match = re.search(r'\[.*?\]', clean_text, re.DOTALL)
        if match:
            clean_text = match.group(0)
        
        # 移除 markdown 代码块标记
        clean_text = clean_text.replace("```json", "").replace("```", "")
        
        try:
            parsed = json.loads(clean_text)
            if isinstance(parsed, list) and len(parsed) >= 2:
                # 确保转成字符串，防止前端显示 Object
                return [str(parsed[0]), str(parsed[1])]
            return ["x", f"AI格式错误: {clean_text}"]
        except:
            # 容错：如果 AI 没返回 JSON，但包含关键字，尝试硬解析
            if "√" in clean_text or "pass" in clean_text.lower():
                return ["√", clean_text.replace('"', '').replace('[', '').replace(']', '')]
            return ["x", f"无法解析JSON: {clean_text}"]