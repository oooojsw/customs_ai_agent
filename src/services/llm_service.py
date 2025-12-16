import json
import re
import requests
import urllib3
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import List
from src.config.loader import settings 

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class LLMService:
    def __init__(self):
        self.session = requests.Session()
        
        # 1. 底层连接重试 (针对 Connection Reset / 断网)
        retry_strategy = Retry(
            total=3,
            backoff_factor=1, # 增加间隔
            status_forcelist=[500, 502, 504], # 注意：503 我们手动处理，不在这里处理
            allowed_methods=["POST"],
            raise_on_status=False
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        if settings.HTTP_PROXY or settings.HTTPS_PROXY:
            self.session.proxies = {
                "http": settings.HTTP_PROXY,
                "https": settings.HTTPS_PROXY
            }

    def call_llm(self, system_prompt: str, user_prompt: str) -> List[str]:
        api_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.MODEL_NAME}:generateContent?key={settings.GOOGLE_API_KEY}"
        )

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

        # 2. 逻辑层重试 (专门针对 503 Overloaded)
        max_retries = 3
        
        for attempt in range(max_retries + 1):
            try:
                # 发送请求
                response = self.session.post(api_url, json=payload, timeout=60, verify=False)
                
                # 如果是 503 (Overloaded)，我们需要休息一下再试
                if response.status_code == 503:
                    if attempt < max_retries:
                        sleep_time = (attempt + 1) * 2  # 等待 2s, 4s, 6s...
                        print(f"⚠️ Google服务器忙 (503)，正在进行第 {attempt+1} 次重试 (等待 {sleep_time}s)...")
                        time.sleep(sleep_time)
                        continue # 跳过当前循环，重试
                    else:
                        return ["x", "Google服务器过载 (Overloaded)，已重试多次失败。"]

                # 如果是其他错误码 (400, 403 等)，直接报错不重试
                if response.status_code != 200:
                    return ["x", f"HTTP错误 {response.status_code}: {response.text}"]

                result_json = response.json()

                # 检查数据有效性
                if 'candidates' not in result_json:
                    return ["x", f"Google返回异常: {json.dumps(result_json)}"]
                
                # 针对 Preview 模型 "只思考不说话" 的 Bug 防御
                try:
                    raw_text = result_json['candidates'][0]['content']['parts'][0]['text']
                except KeyError:
                     finish_reason = result_json['candidates'][0].get('finishReason', 'UNKNOWN')
                     if finish_reason == "STOP":
                         # 如果也是这种情况，也可以重试
                         if attempt < max_retries:
                             print(f"⚠️ 模型未输出内容 (Bug)，重试中...")
                             time.sleep(1)
                             continue
                         return ["x", "模型思考后未输出内容"]
                     return ["x", f"解析失败: {json.dumps(result_json)}"]

                # 成功拿到文本，退出循环并解析
                return self._parse_json_response(raw_text)

            except Exception as e:
                # 如果是断网等底层错误，底层 Adapter 已经重试过了，这里直接报错
                return ["x", f"连接中断: {str(e)}"]

        return ["x", "未知错误"]

    def _parse_json_response(self, raw_text: str) -> List[str]:
        # ... (保持不变) ...
        clean_text = raw_text.strip()
        match = re.search(r'\[.*?\]', clean_text, re.DOTALL)
        if match:
            clean_text = match.group(0)
        
        try:
            parsed = json.loads(clean_text)
            if isinstance(parsed, list) and len(parsed) >= 2:
                return [str(parsed[0]), str(parsed[1])]
            return ["x", f"AI格式错误: {clean_text}"]
        except:
            if "√" in clean_text or "pass" in clean_text.lower():
                return ["√", clean_text.replace('"', '').replace('[', '').replace(']', '')]
            return ["x", f"无法解析JSON: {clean_text}"]