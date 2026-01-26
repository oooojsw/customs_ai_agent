"""
图像识别模型配置 CRUD 操作
"""
from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import ImageModelConfig


class ImageConfigRepository:
    """图像模型配置仓库"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_active_config(self) -> Optional[ImageModelConfig]:
        """获取当前启用的图像配置"""
        stmt = select(ImageModelConfig).where(
            ImageModelConfig.is_enabled == True
        ).order_by(
            ImageModelConfig.updated_at.desc()
        ).limit(1)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_config(self) -> Optional[ImageModelConfig]:
        """获取最新保存的配置（无论是否启用）"""
        stmt = select(ImageModelConfig).order_by(
            ImageModelConfig.updated_at.desc()
        ).limit(1)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, config_id: int) -> Optional[ImageModelConfig]:
        """根据ID获取配置"""
        stmt = select(ImageModelConfig).where(ImageModelConfig.id == config_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_provider(self, provider: str) -> Optional[ImageModelConfig]:
        """根据provider获取配置"""
        stmt = select(ImageModelConfig).where(
            ImageModelConfig.provider == provider
        ).order_by(
            ImageModelConfig.updated_at.desc()
        ).limit(1)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_or_update(self, config_data: Dict[str, Any]) -> ImageModelConfig:
        """创建或更新指定provider的配置"""
        provider = config_data.get('provider')

        # 根据 provider 查找已存在的配置
        stmt = select(ImageModelConfig).where(
            ImageModelConfig.provider == provider
        ).limit(1)
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()

        # 添加调试日志
        print(f"[ImageConfig CRUD] 操作: {'更新' if existing else '创建'}")
        print(f"[ImageConfig CRUD] Provider: {provider}")
        print(f"[ImageConfig CRUD] Existing: {existing.id if existing else None}")
        print(f"[ImageConfig CRUD] New data: {config_data}")

        if existing:
            # 更新现有配置
            for key, value in config_data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            existing.updated_at = datetime.now()
            existing.test_status = "never"
            await self.db.commit()
            await self.db.refresh(existing)
            print(f"[ImageConfig CRUD] ✅ 更新成功: ID={existing.id}")
            return existing
        else:
            # 创建新配置
            new_config = ImageModelConfig(**config_data)
            self.db.add(new_config)
            await self.db.commit()
            await self.db.refresh(new_config)
            print(f"[ImageConfig CRUD] ✅ 创建成功: ID={new_config.id}")
            return new_config

    async def disable_all(self) -> None:
        """禁用所有配置"""
        stmt = update(ImageModelConfig).values(is_enabled=False)
        await self.db.execute(stmt)
        await self.db.commit()

    async def update_test_status(self, config_id: int, status: str) -> None:
        """更新测试状态"""
        config = await self.get_by_id(config_id)
        if config:
            config.test_status = status
            config.last_tested_at = datetime.now()
            await self.db.commit()

    def to_dict(self, config: ImageModelConfig) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": config.id,
            "provider": config.provider,
            "is_enabled": config.is_enabled,
            "api_key": config.api_key,
            "base_url": config.base_url,
            "model_name": config.model_name,
            "api_version": config.api_version,
            "endpoint": config.endpoint,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "test_status": config.test_status,
            "description": config.description
        }
