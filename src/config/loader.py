import os
import sys
from pathlib import Path
from dotenv import load_dotenv

class ConfigLoader:
    """
    配置加载器：单例模式，负责将环境变量映射为 Python 属性
    """
    def __init__(self):
        # 1. 强制寻找项目根目录的 .env 文件
        # src/config/loader.py -> src/config -> src -> 项目根目录
        self.BASE_DIR = Path(__file__).resolve().parent.parent.parent
        self.ENV_PATH = self.BASE_DIR / ".env"
        
        print(f"[Config] Loading config file: {self.ENV_PATH}")

        if self.ENV_PATH.exists():
            load_dotenv(dotenv_path=self.ENV_PATH, override=True) # override=True 强制覆盖系统变量
        else:
            print(f"[Config] Warning: .env file not found, using system environment variables")

        # --- 加载具体配置 ---
        
        # Google / Gemini
        self.GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
        # 如果没填，默认使用 gemini-2.0-flash-exp (速度最快)
        self.MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash-exp")

        # DeepSeek
        self.DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
        self.DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        
        # --- 【新增】Azure OpenAI 配置 ---
        self.AZURE_OAI_KEY = os.getenv("AZURE_OAI_KEY", "")
        self.AZURE_OAI_ENDPOINT = os.getenv("AZURE_OAI_ENDPOINT", "")
        self.AZURE_OAI_DEPLOYMENT = os.getenv("AZURE_OAI_DEPLOYMENT", "")
        self.AZURE_OAI_VERSION = os.getenv("AZURE_OAI_VERSION", "2024-02-01")

        # 网络代理
        self.HTTP_PROXY = os.getenv("HTTP_PROXY")
        self.HTTPS_PROXY = os.getenv("HTTPS_PROXY")

        # 外部服务
        self.DATA_PLATFORM_URL = os.getenv("DATA_PLATFORM_URL", "http://127.0.0.1:8088")
        
        # 服务基础配置
        self.HOST = os.getenv("API_HOST", "0.0.0.0")
        self.PORT = int(os.getenv("API_PORT", "8000"))

    def validate(self):
        """启动前自检"""
        # 打印部分 Key 用于调试 (只显示前4位)
        masked_key = self.GOOGLE_API_KEY[:4] + "****" if self.GOOGLE_API_KEY else "Not set"
        print(f"[Config] Google API Key: {masked_key}")

        if not self.GOOGLE_API_KEY:
            # 这里不抛出异常，防止导致 DeepSeek 模块也无法启动
            print("[Config] Warning: GOOGLE_API_KEY is empty, Gemini features will be unavailable!")

# 实例化单例
settings = ConfigLoader()
settings.validate()