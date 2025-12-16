import os
from pathlib import Path
from dotenv import load_dotenv

# 1. 自动寻找并加载项目根目录下的 .env 文件
# 获取当前文件 (loader.py) 的上级目录的上级目录，即项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)
else:
    print(f"⚠️ 警告: 未找到配置文件 {ENV_PATH}，将尝试读取系统环境变量。")

class ConfigLoader:
    """
    配置加载器：单例模式，负责将环境变量映射为 Python 属性
    """
    
    # --- API Key 配置 ---
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
        # 新增 DeepSeek 配置
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    
    # --- 模型配置 ---
    # 强制默认策略：如果没填，默认也是 2.5-flash，禁止回退到 1.5
    MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.0-flash")
    
    # --- 网络/代理配置 ---
    HTTP_PROXY = os.getenv("HTTP_PROXY")
    HTTPS_PROXY = os.getenv("HTTPS_PROXY")

    # --- 外部服务配置 ---
    DATA_PLATFORM_URL = os.getenv("DATA_PLATFORM_URL", "http://127.0.0.1:8088")
    
    # --- 服务基础配置 ---
    HOST = os.getenv("API_HOST", "0.0.0.0")
    PORT = int(os.getenv("API_PORT", "8000"))

    @classmethod
    def validate(cls):
        """启动前自检，确保关键配置存在"""
        if not cls.GOOGLE_API_KEY:
            raise ValueError("❌ 严重错误: 未检测到 GOOGLE_API_KEY！请检查 .env 文件。")

# 实例化一个对象供外部直接导入使用
settings = ConfigLoader()

# 模块加载时自动执行检查，有问题直接报错，防止系统带病运行
settings.validate()
