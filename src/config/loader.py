import os
import sys
from pathlib import Path
from dotenv import load_dotenv


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

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
            # ✅ 修复：不使用 override=True，避免污染 os.environ
            # 这样可以防止代理环境变量干扰 MCP 连接
            load_dotenv(dotenv_path=self.ENV_PATH, override=False)
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

        # Agent V1 integration layer. Enabled by default because the unified
        # platform API is now the primary external entrypoint.
        self.AGENT_V1_ENABLED = _env_bool("AGENT_V1_ENABLED", True)
        self.AGENT_V1_USE_NEW_VISION = _env_bool(
            "AGENT_V1_USE_NEW_VISION", False
        )
        self.AGENT_V1_USE_PLATFORM_FILES = _env_bool(
            "AGENT_V1_USE_PLATFORM_FILES", False
        )
        self.AGENT_V1_USE_NEW_ORCHESTRATOR = _env_bool(
            "AGENT_V1_USE_NEW_ORCHESTRATOR", False
        )
        self.AGENT_V1_DEMO_MODE = _env_bool("AGENT_V1_DEMO_MODE", True)
        self.AGENT_V1_ATTACHMENT_ALLOWED_HOSTS = tuple(
            host.strip()
            for host in os.getenv(
                "AGENT_V1_ATTACHMENT_ALLOWED_HOSTS", ""
            ).split(",")
            if host.strip()
        )
        self.AGENT_V1_ATTACHMENT_MAX_BYTES = int(
            os.getenv("AGENT_V1_ATTACHMENT_MAX_BYTES", str(20 * 1024 * 1024))
        )
        self.AGENT_V1_TEMP_DIR = os.getenv(
            "AGENT_V1_TEMP_DIR", str(self.BASE_DIR / "data" / "agent_runs")
        )
        self.AGENT_V1_OUTPUT_DIR = os.getenv(
            "AGENT_V1_OUTPUT_DIR", str(self.BASE_DIR / "data" / "agent_outputs")
        )
        self.AGENT_V1_OUTPUT_TTL_SECONDS = int(
            os.getenv("AGENT_V1_OUTPUT_TTL_SECONDS", "86400")
        )
        self.AGENT_V1_AUTH_ENABLED = _env_bool(
            "AGENT_V1_AUTH_ENABLED", False
        )
        self.AGENT_V1_SERVICE_API_KEY = os.getenv(
            "AGENT_V1_SERVICE_API_KEY", ""
        )
        self.AGENT_V1_PLATFORM_FILE_UPLOAD_URL = os.getenv(
            "AGENT_V1_PLATFORM_FILE_UPLOAD_URL", ""
        )
        self.AGENT_V1_PLATFORM_FILE_API_KEY = os.getenv(
            "AGENT_V1_PLATFORM_FILE_API_KEY", ""
        )
        self.AGENT_V1_PLATFORM_FILE_TIMEOUT_SECONDS = float(
            os.getenv("AGENT_V1_PLATFORM_FILE_TIMEOUT_SECONDS", "30")
        )
        self.AGENT_TOOL_TIMEOUT_L1_SECONDS = float(
            os.getenv("AGENT_TOOL_TIMEOUT_L1_SECONDS", "30")
        )
        self.AGENT_TOOL_TIMEOUT_L2_SECONDS = float(
            os.getenv("AGENT_TOOL_TIMEOUT_L2_SECONDS", "120")
        )
        self.AGENT_TOOL_TIMEOUT_L3_SECONDS = float(
            os.getenv("AGENT_TOOL_TIMEOUT_L3_SECONDS", "300")
        )
        self.AGENT_TOOL_TIMEOUT_L4_SECONDS = float(
            os.getenv("AGENT_TOOL_TIMEOUT_L4_SECONDS", "1200")
        )
        self.AGENT_TOOL_TIMEOUT_L5_SECONDS = float(
            os.getenv("AGENT_TOOL_TIMEOUT_L5_SECONDS", "3600")
        )
        self.AGENT_V1_CALLBACK_ALLOWED_HOSTS = tuple(
            host.strip().lower()
            for host in os.getenv(
                "AGENT_V1_CALLBACK_ALLOWED_HOSTS", ""
            ).split(",")
            if host.strip()
        )
        self.AGENT_V1_RUN_DB_PATH = os.getenv(
            "AGENT_V1_RUN_DB_PATH",
            str(self.BASE_DIR / "data" / "agent_v1_runs.db"),
        )
        self.AGENT_V1_RUN_STORE = os.getenv(
            "AGENT_V1_RUN_STORE", "sqlite"
        ).strip().lower()
        self.MOCK_CUSTOMS_DB_PATH = os.getenv(
            "MOCK_CUSTOMS_DB_PATH",
            str(self.BASE_DIR / "data" / "mock_customs_cases.db"),
        )
        self.MOCK_CUSTOMS_FIXTURE_DIR = os.getenv(
            "MOCK_CUSTOMS_FIXTURE_DIR",
            str(self.BASE_DIR / "data" / "mock_customs_cases"),
        )

    def validate(self):
        """启动前自检"""
        # 打印部分 Key 用于调试 (只显示前4位)
        masked_key = self.GOOGLE_API_KEY[:4] + "****" if self.GOOGLE_API_KEY else "Not set"
        print(f"[Config] Google API Key: {masked_key}")

        if not self.GOOGLE_API_KEY:
            # 这里不抛出异常，防止导致 DeepSeek 模块也无法启动
            print("[Config] Warning: GOOGLE_API_KEY is empty, Gemini features will be unavailable!")
        if self.AGENT_V1_AUTH_ENABLED and not self.AGENT_V1_SERVICE_API_KEY:
            raise ValueError(
                "AGENT_V1_AUTH_ENABLED=true requires AGENT_V1_SERVICE_API_KEY"
            )
        if (
            self.AGENT_V1_USE_PLATFORM_FILES
            and not self.AGENT_V1_PLATFORM_FILE_UPLOAD_URL
        ):
            raise ValueError(
                "AGENT_V1_USE_PLATFORM_FILES=true requires "
                "AGENT_V1_PLATFORM_FILE_UPLOAD_URL"
            )
        if self.AGENT_V1_RUN_STORE not in {"memory", "sqlite"}:
            raise ValueError("AGENT_V1_RUN_STORE must be memory or sqlite")

# 实例化单例
settings = ConfigLoader()
settings.validate()
