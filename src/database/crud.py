from sqlalchemy.ext.asyncio import AsyncSession
from src.database.models import AuditTask, AuditDetail
from datetime import datetime

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