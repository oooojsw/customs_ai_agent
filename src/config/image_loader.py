"""
图像识别模型配置加载器（单例模式）
优先级：数据库配置 > .env 配置
"""
import os
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()


class ImageConfigLoader:
    """图像识别配置加载器（单例）"""

    _instance: Optional['ImageConfigLoader'] = None
    _config: Optional[Dict[str, Any]] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load_from_env(self) -> Dict[str, Any]:
        """从 .env 加载配置"""
        provider = os.getenv("IMAGE_PROVIDER", "gemini")

        # 根据provider选择合适的默认模型
        if provider == "azure":
            default_model = os.getenv("AZURE_OAI_DEPLOYMENT", "gpt-4-vision")
        elif provider == "gemini":
            default_model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        else:
            default_model = "gpt-4-vision"  # 默认

        return {
            "provider": provider,
            "api_key": os.getenv("AZURE_OAI_KEY", os.getenv("GOOGLE_API_KEY", "")),
            "endpoint": os.getenv("AZURE_OAI_ENDPOINT", ""),
            "base_url": os.getenv("AZURE_OAI_ENDPOINT", ""),
            "model_name": default_model,
            "api_version": os.getenv("AZURE_API_VERSION", "2024-02-01"),
            "temperature": float(os.getenv("IMAGE_TEMPERATURE", "0.1")),
            "max_tokens": int(os.getenv("IMAGE_MAX_TOKENS", "16384")),
            "is_enabled": False  # .env 配置默认不启用自定义配置
        }

    def load_from_database(self, db_config: Dict[str, Any]) -> Dict[str, Any]:
        """从数据库加载配置"""
        return {
            "provider": db_config.get("provider", "azure"),
            "api_key": db_config.get("api_key", ""),
            "endpoint": db_config.get("endpoint", ""),
            "base_url": db_config.get("base_url", ""),
            "model_name": db_config.get("model_name", "gpt-4-vision"),
            "api_version": db_config.get("api_version", "2024-02-01"),
            "temperature": db_config.get("temperature", 0.1),
            "max_tokens": db_config.get("max_tokens", 16384),
            "is_enabled": db_config.get("is_enabled", False),
            "source": "database"
        }

    def set_config(self, config: Dict[str, Any]):
        """设置当前配置（由系统启动时调用）"""
        self._config = config

    def get_config(self) -> Dict[str, Any]:
        """获取当前配置"""
        if self._config is None:
            # 如果没有设置配置，从 .env 加载
            self._config = self.load_from_env()
        return self._config

    def is_enabled(self) -> bool:
        """检查是否启用自定义配置"""
        return self._config.get("is_enabled", False) if self._config else False


# 全局单例
image_config_loader = ImageConfigLoader()
