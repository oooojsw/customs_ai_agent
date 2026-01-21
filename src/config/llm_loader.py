"""
LLM 配置加载器
优先级: 用户数据库配置 > .env 环境变量
"""
from typing import Optional, Dict
from src.config.loader import settings


class LLMConfigLoader:
    """LLM 配置加载器 (单例)"""

    _instance = None
    _user_config = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def load_config(self, db_session) -> Dict:
        """
        加载 LLM 配置

        Returns:
            配置字典 {
                'api_key': str,
                'base_url': str,
                'model': str,
                'temperature': float,
                'source': 'user' | 'env'
            }
        """
        # 1. 尝试从数据库加载用户配置
        try:
            from src.database.crud import LLMConfigRepository
            repo = LLMConfigRepository(db_session)
            user_config = await repo.get_active_config()

            if user_config and user_config.is_enabled:
                self._user_config = {
                    'api_key': user_config.api_key,
                    'base_url': user_config.base_url,
                    'model': user_config.model_name,
                    'temperature': user_config.temperature,
                    'source': 'user'
                }
                print(f"[LLMConfig] 使用用户配置: {user_config.provider}/{user_config.model_name}")
                return self._user_config

        except Exception as e:
            print(f"[LLMConfig] 数据库配置加载失败: {e}, 回退到 .env")

        # 2. 回退到 .env 配置
        self._user_config = {
            'api_key': settings.DEEPSEEK_API_KEY,
            'base_url': settings.DEEPSEEK_BASE_URL,
            'model': settings.DEEPSEEK_MODEL,
            'temperature': 0.3,
            'source': 'env'
        }
        print(f"[LLMConfig] 使用 .env 配置: deepseek/{settings.DEEPSEEK_MODEL}")
        return self._user_config

    def get_current_config(self) -> Optional[Dict]:
        """获取当前加载的配置"""
        return self._user_config


# 全局单例
llm_config_loader = LLMConfigLoader()
