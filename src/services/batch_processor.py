"""
批量处理服务：处理 Excel/CSV 文件的批量报关单分析
"""
import io
import asyncio
import pandas as pd
from typing import AsyncGenerator

from src.core.orchestrator import RiskAnalysisOrchestrator
from src.database.connection import get_async_session
from src.database.crud import BatchRepository


class BatchProcessor:
    """
    批量处理器：解析文件并逐条处理报关单分析
    """

    def __init__(self):
        self.orchestrator = RiskAnalysisOrchestrator()

    async def parse_file(self, file_content: bytes, filename: str) -> list:
        """
        解析上传的文件内容
        返回：[{row_index, data_type, content}, ...]
        """
        try:
            # 根据文件扩展名判断类型
            if filename.endswith('.csv'):
                df = pd.read_csv(io.BytesIO(file_content), encoding='utf-8')
            elif filename.endswith(('.xls', '.xlsx')):
                df = pd.read_excel(io.BytesIO(file_content))
            else:
                # 默认尝试 Excel
                df = pd.read_excel(io.BytesIO(file_content))

            # 标准化列名（去除前后空格，转小写）
            df.columns = df.columns.str.strip().str.lower()

            # 检查必需的列
            # 支持的列名映射：序号/编号/index，数据类型/type，内容/图片路径/content
            required_columns = []
            col_mapping = {}

            # 查找序号列
            for col in ['序号', '编号', 'index', 'no', '编号']:
                if col in df.columns:
                    col_mapping['row_index'] = col
                    break
            if 'row_index' not in col_mapping:
                # 如果没有序号列，使用 DataFrame 索引
                df = df.reset_index()
                col_mapping['row_index'] = 'index'

            # 查找数据类型列
            for col in ['数据类型', 'type', '类型', 'data_type']:
                if col in df.columns:
                    col_mapping['data_type'] = col
                    break

            # 查找内容列
            for col in ['内容', '图片路径', 'content', '内容/图片路径']:
                if col in df.columns:
                    col_mapping['content'] = col
                    break

            if 'content' not in col_mapping:
                raise ValueError("文件缺少必要的列：内容/图片路径")

            # 构建结果列表
            items = []
            for idx, row in df.iterrows():
                row_index = row.get(col_mapping.get('row_index', 'index'), idx + 1)
                data_type = row.get(col_mapping.get('data_type'), 'text')
                content = row.get(col_mapping['content'], '')

                # 清理数据
                if pd.isna(content) or str(content).strip() == '':
                    continue

                # 标准化 data_type
                data_type = str(data_type).strip().lower()
                if data_type not in ['text', 'image']:
                    # 根据 content 自动判断
                    content_str = str(content).strip()
                    if content_str.startswith(('http://', 'https://')):
                        data_type = 'image'
                    else:
                        data_type = 'text'

                items.append({
                    'row_index': int(row_index),
                    'data_type': data_type,
                    'content': str(content).strip()
                })

            return items

        except Exception as e:
            raise ValueError(f"文件解析失败: {str(e)}")

    async def process_batch(self, task_uuid: str):
        """
        异步处理批量任务（后台执行）
        """
        async with get_async_session() as db:
            repo = BatchRepository(db)

            # 标记任务开始
            await repo.start_batch_task(task_uuid)

            # 获取任务数据
            task_data = await repo.get_batch_progress(task_uuid)
            if not task_data:
                return

            # 逐条处理
            for item in task_data['items']:
                if item['status'] in ['completed', 'failed']:
                    continue  # 跳过已处理的

                try:
                    # 更新为处理中
                    await repo.update_item_status(task_uuid, item['row_index'], 'processing')

                    # 根据类型处理
                    if item['data_type'] == 'image':
                        # 图片类型：暂时标记为不支持
                        await repo.update_item_status(
                            task_uuid,
                            item['row_index'],
                            'failed',
                            error_message='图片识别功能暂未实现，请使用文本类型'
                        )
                    else:
                        # 文本类型：调用风险分析
                        result = await self._analyze_single(item['content'])

                        # 保存结果
                        await repo.update_item_status(
                            task_uuid,
                            item['row_index'],
                            'completed',
                            result_summary=result['final_status'],
                            detail_result=result
                        )

                    # 避免过快请求
                    await asyncio.sleep(0.5)

                except Exception as e:
                    # 处理失败，记录错误
                    await repo.update_item_status(
                        task_uuid,
                        item['row_index'],
                        'failed',
                        error_message=str(e)
                    )

    async def _analyze_single(self, raw_data: str) -> dict:
        """
        分析单条数据
        返回：完整的分析结果字典
        """
        result = {
            'raw_data': raw_data,
            'steps': [],
            'final_status': 'pass',
            'summary': ''
        }

        # 收集所有 SSE 事件
        async for event in self.orchestrator.analyze_stream(raw_data):
            # 解析 SSE 事件
            if event.startswith('data: '):
                json_str = event[6:]  # 去掉 'data: '
                import json
                try:
                    data = json.loads(json_str)

                    if data.get('type') == 'init':
                        result['total_steps'] = data.get('total_steps')

                    elif data.get('type') == 'step_result':
                        result['steps'].append({
                            'rule_id': data.get('rule_id'),
                            'status': data.get('status'),
                            'icon': data.get('icon'),
                            'message': data.get('message'),
                            'color': data.get('color')
                        })

                    elif data.get('type') == 'complete':
                        result['final_status'] = data.get('final_status')
                        result['summary'] = data.get('summary')

                except json.JSONDecodeError:
                    pass

        return result


# 后台任务管理器（用于启动异步任务）
_background_tasks = set()


def start_batch_processing(task_uuid: str):
    """
    启动后台批量处理任务
    """
    async def run_task():
        processor = BatchProcessor()
        await processor.process_batch(task_uuid)

    # 创建并启动任务
    import asyncio
    task = asyncio.create_task(run_task())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
