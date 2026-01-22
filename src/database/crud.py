from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.database.models import AuditTask, AuditDetail, BatchTask, BatchItem, UserLLMConfig
from datetime import datetime
from typing import Optional
import uuid

class AuditRepository:
    """
    仓库类：专门负责搬运数据进出数据库
    """
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_new_task(self, raw_data: str) -> int:
        """
        第一步：在分析开始前，先创建一个任务记录
        返回：新任务的 ID
        """
        new_task = AuditTask(
            raw_data=raw_data,
            final_status="PROCESSING", # 状态标记为进行中
            summary="正在分析中..."
        )
        self.db.add(new_task)
        await self.db.commit() # 提交保存
        await self.db.refresh(new_task) # 刷新，为了拿到自动生成的 ID
        return new_task.id

    async def save_task_results(self, task_id: int, final_status: str, summary: str, details: list):
        """
        最后一步：分析结束后，批量保存所有明细，并更新主任务状态
        """
        # 1. 找到之前创建的那个任务
        task = await self.db.get(AuditTask, task_id)
        if task:
            # 2. 更新主任务的结论
            task.final_status = final_status
            task.summary = summary
            task.finished_at = datetime.now()

            # 3. 批量添加明细 (把内存里的字典转成数据库对象)
            for item in details:
                detail_record = AuditDetail(
                    task_id=task_id,
                    rule_id=item['rule_id'],
                    rule_name=item['rule_name'],
                    is_risk=item['is_risk'],
                    llm_reason=item['reason']
                )
                self.db.add(detail_record)

            # 4. 一次性提交所有更改
            await self.db.commit()


class BatchRepository:
    """
    批量任务仓库类：处理批量任务的数据操作
    """
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_batch_task(self, total_count: int) -> str:
        """
        创建新的批量任务
        返回：task_uuid（用于前端查询）
        """
        task_uuid = str(uuid.uuid4())
        new_task = BatchTask(
            task_uuid=task_uuid,
            total_count=total_count,
            status="pending"
        )
        self.db.add(new_task)
        await self.db.commit()
        await self.db.refresh(new_task)
        return task_uuid

    async def start_batch_task(self, task_uuid: str):
        """标记批量任务开始处理"""
        stmt = select(BatchTask).where(BatchTask.task_uuid == task_uuid)
        result = await self.db.execute(stmt)
        task = result.scalar_one_or_none()
        if task:
            task.status = "processing"
            task.started_at = datetime.now()
            await self.db.commit()

    async def add_batch_items(self, task_uuid: str, items: list):
        """批量添加明细记录"""
        stmt = select(BatchTask).where(BatchTask.task_uuid == task_uuid)
        result = await self.db.execute(stmt)
        task = result.scalar_one_or_none()
        if not task:
            return

        for item_data in items:
            item = BatchItem(
                batch_task_id=task.id,
                row_index=item_data.get('row_index'),
                data_type=item_data.get('data_type'),
                content=item_data.get('content'),
                status="pending"
            )
            self.db.add(item)
        await self.db.commit()

    async def update_item_status(self, task_uuid: str, row_index: int, status: str,
                                 result_summary: str = None, detail_result: dict = None,
                                 error_message: str = None):
        """更新单条记录的处理状态"""
        stmt = select(BatchItem).join(BatchTask).where(
            BatchTask.task_uuid == task_uuid,
            BatchItem.row_index == row_index
        )
        result = await self.db.execute(stmt)
        item = result.scalar_one_or_none()
        if item:
            item.status = status
            if result_summary:
                item.result_summary = result_summary
            if detail_result:
                item.detail_result = detail_result
            if error_message:
                item.error_message = error_message

            # 更新父任务的计数
            task = await self.get_batch_task_by_uuid(task_uuid)
            if task:
                await self._update_task_counts(task)
            await self.db.commit()

    async def _update_task_counts(self, task: BatchTask):
        """更新批量任务的统计数据"""
        completed = len([i for i in task.items if i.status == "completed"])
        failed = len([i for i in task.items if i.status == "failed"])
        task.completed_count = completed
        task.failed_count = failed

        # 全部完成则更新任务状态
        if completed + failed >= task.total_count:
            task.status = "completed"
            task.finished_at = datetime.now()

    async def get_batch_task_by_uuid(self, task_uuid: str) -> BatchTask:
        """根据 UUID 获取批量任务（包含所有明细）"""
        stmt = select(BatchTask).where(BatchTask.task_uuid == task_uuid)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_batch_progress(self, task_uuid: str) -> dict:
        """获取批量任务的进度信息"""
        task = await self.get_batch_task_by_uuid(task_uuid)
        if not task:
            return None

        items_data = []
        for item in task.items:
            items_data.append({
                "row_index": item.row_index,
                "data_type": item.data_type,
                "status": item.status,
                "result_summary": item.result_summary,
                "error_message": item.error_message,
                "detail_result": item.detail_result
            })

        return {
            "task_uuid": task.task_uuid,
            "status": task.status,
            "total_count": task.total_count,
            "completed_count": task.completed_count,
            "failed_count": task.failed_count,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
            "items": items_data
        }


class LLMConfigRepository:
    """用户 LLM 配置仓库（支持多厂商配置）"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_active_config(self) -> Optional[UserLLMConfig]:
        """获取当前启用的配置"""
        stmt = select(UserLLMConfig).where(
            UserLLMConfig.is_enabled == True
        ).order_by(UserLLMConfig.updated_at.desc()).limit(1)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_config_by_provider(self, provider: str) -> Optional[UserLLMConfig]:
        """获取指定厂商的配置"""
        stmt = select(UserLLMConfig).where(
            UserLLMConfig.provider == provider
        ).order_by(UserLLMConfig.updated_at.desc()).limit(1)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_configs(self) -> list:
        """获取所有厂商的配置"""
        stmt = select(UserLLMConfig).order_by(UserLLMConfig.provider)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def save_config(self, config_data: dict) -> UserLLMConfig:
        """保存或更新指定厂商的配置（不影响其他厂商配置）"""
        provider = config_data['provider']

        # 查找是否已有该provider的配置
        existing = await self.get_config_by_provider(provider)

        if existing:
            # 更新现有配置
            existing.api_key = config_data['api_key']
            existing.base_url = config_data['base_url']
            existing.model_name = config_data['model_name']
            existing.api_version = config_data.get('api_version')
            existing.temperature = config_data.get('temperature', 0.3)
            existing.test_status = 'never'
            # 使用前端传入的 is_enabled 值，而不是强制设为 True
            existing.is_enabled = config_data.get('is_enabled', True)
            await self.db.commit()
            await self.db.refresh(existing)
            return existing
        else:
            # 创建新配置（先禁用其他配置，保持只有一个启用）
            await self.disable_all_configs()

            new_config = UserLLMConfig(
                provider=provider,
                is_enabled=config_data.get('is_enabled', True),  # 使用前端传入的 is_enabled 值
                api_key=config_data['api_key'],
                base_url=config_data['base_url'],
                model_name=config_data['model_name'],
                api_version=config_data.get('api_version'),
                temperature=config_data.get('temperature', 0.3),
                test_status='never'
            )
            self.db.add(new_config)
            await self.db.commit()
            await self.db.refresh(new_config)
            return new_config

    async def activate_provider(self, provider: str) -> Optional[UserLLMConfig]:
        """启用指定厂商的配置（禁用其他所有配置）"""
        # 检查该厂商是否有配置
        config = await self.get_config_by_provider(provider)
        if not config:
            return None

        # 禁用所有配置
        await self.disable_all_configs()

        # 启用指定配置
        config.is_enabled = True
        await self.db.commit()
        await self.db.refresh(config)
        return config

    async def disable_all_configs(self):
        """禁用所有配置"""
        stmt = select(UserLLMConfig).where(UserLLMConfig.is_enabled == True)
        result = await self.db.execute(stmt)
        configs = result.scalars().all()
        for config in configs:
            config.is_enabled = False
        await self.db.commit()

    async def reset_to_env(self):
        """重置为 .env 配置（禁用所有用户配置）"""
        await self.disable_all_configs()