import traceback
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

# --- 核心服务导入 ---
from src.services.data_client import DataClient
from src.core.orchestrator import RiskAnalysisOrchestrator
from src.services.report_agent import ComplianceReporter
from src.database.pdf_repository import PDFRepository

# 容错导入
try:
    from src.services.image_extractor import ImageTextExtractor, NotDeclarationError
except ImportError:
    ImageTextExtractor = None

# --- 批量处理与数据库 (保留全量功能) ---
try:
    from src.services.batch_processor import BatchProcessor, start_batch_processing
    from src.database.connection import AsyncSessionLocal, get_async_session
    from src.database.crud import BatchRepository
    BATCH_AVAILABLE = True
except ImportError:
    BATCH_AVAILABLE = False
    print("⚠️ [System] 数据库相关依赖未完全安装，批量功能将受限")

router = APIRouter()

# --- 请求体定义 ---
class AnalysisRequest(BaseModel):
    raw_data: str
    language: str = "zh"  # 新增：语言参数，默认中文

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default_session"
    language: str = "zh"  # 新增：语言参数，默认中文

class ReportRequest(BaseModel):
    raw_data: str
    language: str = "zh"  # 新增：语言参数，默认中文

# ==========================================
# 1. 智能审单接口 (功能一)
# ==========================================
@router.post("/analyze")
async def analyze_customs_declaration(request: AnalysisRequest):
    if not request.raw_data or len(request.raw_data.strip()) < 5:
        raise HTTPException(status_code=400, detail="数据太短，无法分析")

    orchestrator = RiskAnalysisOrchestrator()
    return StreamingResponse(
        orchestrator.analyze_stream(request.raw_data, language=request.language),
        media_type="text/event-stream"
    )

# ==========================================
# 2. 法规咨询接口 (功能二)
# ==========================================
@router.post("/chat")
async def chat_with_agent(body: ChatRequest, request: Request):
    agent = getattr(request.app.state, "agent", None)
    if not agent:
        raise HTTPException(status_code=503, detail="对话引擎未就绪")

    return StreamingResponse(
        agent.chat_stream(body.message, body.session_id, language=body.language),
        media_type="text/event-stream"
    )

# ==========================================
# 3. 报告生成接口 (功能三)
# ==========================================
@router.post("/generate_report")
async def generate_compliance_report(body: ReportRequest, req: Request):
    try:
        reporter = getattr(req.app.state, "reporter", None)
        if not reporter:
            reporter = ComplianceReporter() # 现场兜底初始化

        return StreamingResponse(
            reporter.generate_stream(body.raw_data, language=body.language),
            media_type="text/event-stream"
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"报告引擎崩溃: {str(e)}")

# ==========================================
# 4. 图片 OCR 识别
# ==========================================
@router.post("/analyze_image")
async def analyze_declaration_image(
    file: UploadFile = File(...),
    language: str = "zh"  # 新增：语言参数，默认中文
):
    if not ImageTextExtractor:
        raise HTTPException(status_code=501, detail="OCR 模块缺失")

    content = await file.read()
    extractor = ImageTextExtractor()
    try:
        text, model = extractor.extract_text(content, file.content_type, language=language)
        return {"text": text, "model": model}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# 5. 批量分析接口 (全量保留)
# ==========================================
@router.post("/analyze_batch")
async def analyze_batch(file: UploadFile = File(...)):
    if not BATCH_AVAILABLE:
        raise HTTPException(status_code=501, detail="数据库依赖未就绪")

    if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
        raise HTTPException(status_code=400, detail="格式不支持")

    content = await file.read()
    try:
        processor = BatchProcessor()
        items = await processor.parse_file(content, file.filename)
        
        async with get_async_session() as db:
            repo = BatchRepository(db)
            task_uuid = await repo.create_batch_task(len(items))
            await repo.add_batch_items(task_uuid, items)

        start_batch_processing(task_uuid)
        return {"status": "success", "task_id": task_uuid, "count": len(items)}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/analyze_batch/{task_id}")
async def get_batch_progress(task_id: str):
    if not BATCH_AVAILABLE:
        raise HTTPException(status_code=501, detail="数据库不可用")
    async with get_async_session() as db:
        repo = BatchRepository(db)
        result = await repo.get_batch_progress(task_id)
        if not result:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {"status": "success", "data": result}

# ==========================================
# 6. 其他辅助接口
# ==========================================
@router.get("/health")
def health_check():
    return {"status": "ok", "version": "3.0.PRO"}

@router.get("/knowledge/content/{filename}")
async def get_knowledge_file_content(filename: str):
    """
    获取知识库文件内容（用于前端展示 RAG 检索结果）

    Args:
        filename: 文件名（如 "01-1", "test_policy.txt"）

    Returns:
        文件内容或错误信息
    """
    from pathlib import Path
    import os

    try:
        base_dir = Path(__file__).resolve().parent.parent.parent
        knowledge_dir = base_dir / "data" / "knowledge"

        # 尝试多个可能的文件名匹配
        possible_names = [
            filename,
            filename + ".txt",
            filename.replace('.txt', ''),
        ]

        content = None
        matched_file = None

        for name in possible_names:
            file_path = knowledge_dir / name
            if file_path.exists() and file_path.is_file():
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    matched_file = name
                    break
                except UnicodeDecodeError:
                    # 尝试用其他编码
                    try:
                        with open(file_path, 'r', encoding='gbk') as f:
                            content = f.read()
                        matched_file = name
                        break
                    except:
                        continue

        if content is None:
            # 如果直接匹配失败，尝试模糊匹配（按优先级）
            # 优先级1: 完全匹配
            # 优先级2: 包含匹配
            # 优先级3: 移除扩展名后匹配
            found_files = list(knowledge_dir.glob('*'))

            # 先尝试完全匹配（忽略大小写）
            for file_path in found_files:
                if file_path.is_file():
                    file_name = file_path.name
                    if file_name.lower() == filename.lower():
                        try:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                            matched_file = file_name
                            break
                        except UnicodeDecodeError:
                            try:
                                with open(file_path, 'r', encoding='gbk') as f:
                                    content = f.read()
                                matched_file = file_name
                                break
                            except:
                                continue

            # 如果还是没找到，尝试包含匹配
            if content is None:
                for file_path in found_files:
                    if file_path.is_file():
                        file_name = file_path.name
                        # 请求的文件名包含在实际文件名中，或实际文件名包含请求的文件名
                        if filename.lower() in file_name.lower() or file_name.lower() in filename.lower():
                            try:
                                with open(file_path, 'r', encoding='utf-8') as f:
                                    content = f.read()
                                matched_file = file_name
                                break
                            except UnicodeDecodeError:
                                try:
                                    with open(file_path, 'r', encoding='gbk') as f:
                                        content = f.read()
                                    matched_file = file_name
                                    break
                                except:
                                    continue

        if content is None:
            # 列出所有可用的 .txt 文件（用于调试）
            available_files = [f.name for f in knowledge_dir.iterdir() if f.is_file() and f.suffix in ['.txt', '.md', '']]
            available_list = "\n".join(sorted(available_files)[:20])  # 只显示前20个

            return {
                "status": "not_found",
                "filename": filename,
                "content": f"未找到文件: {filename}\n\n可用的文件:\n{available_list}"
            }

        return {
            "status": "success",
            "filename": matched_file,
            "content": content
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "status": "error",
            "filename": filename,
            "content": f"读取文件失败: {str(e)}"
        }

@router.get("/query/declaration/{entry_id}")
async def query_declaration_data(entry_id: str):
    client = DataClient()
    text_data = client.fetch_declaration_text(entry_id)
    return {"status": "success", "data": text_data}

# ==========================================
# 7. PDF管理接口 (Marker支持)
# ==========================================

@router.get("/pdf/stats")
async def get_pdf_stats():
    """
    获取PDF统计信息

    Returns:
        {
            "status": "success",
            "data": {
                "total_documents": int,
                "completed_documents": int,
                "failed_documents": int,
                "total_characters": int,
                "total_processing_time_seconds": float,
                "average_processing_time": float
            }
        }
    """
    try:
        repo = PDFRepository()
        stats = await repo.get_statistics()
        return {"status": "success", "data": stats}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.get("/pdf/cache/list")
async def list_pdf_cache():
    """
    列出所有PDF缓存

    Returns:
        {
            "status": "success",
            "data": [
                {
                    "id": int,
                    "file_name": str,
                    "file_path": str,
                    "file_size": int,
                    "char_count": int,
                    "processing_time": float,
                    "created_at": str,
                    "updated_at": str
                },
                ...
            ]
        }
    """
    try:
        repo = PDFRepository()
        docs = await repo.get_all_cached()
        return {
            "status": "success",
            "data": [
                {
                    "id": doc.id,
                    "file_name": doc.file_name,
                    "file_path": doc.file_path,
                    "file_size": doc.file_size,
                    "char_count": doc.char_count,
                    "processing_time": doc.processing_time,
                    "created_at": doc.created_at.isoformat(),
                    "updated_at": doc.updated_at.isoformat()
                }
                for doc in docs
            ]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.delete("/pdf/cache/delete")
async def delete_pdf_cache(file_path: str):
    """
    删除指定PDF的缓存

    Args:
        file_path: PDF文件路径 (如: data/knowledge/xxx.pdf)

    Returns:
        {
            "status": "success",
            "message": "缓存已删除"
        }
    """
    try:
        repo = PDFRepository()
        success = await repo.delete_by_path(file_path)
        if success:
            return {"status": "success", "message": "缓存已删除"}
        else:
            return {"status": "error", "message": "缓存不存在"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.delete("/pdf/cache/clear")
async def clear_pdf_cache():
    """
    清空所有PDF缓存

    警告：此操作不可逆

    Returns:
        {
            "status": "success",
            "deleted_count": int
        }
    """
    try:
        repo = PDFRepository()
        count = await repo.clear_all()
        return {"status": "success", "deleted_count": count}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/pdf/reindex")
async def rebuild_pdf_index():
    """
    重建PDF索引 (强制重新处理所有PDF)

    注意：此操作会清除所有PDF缓存并重新处理，耗时较长

    Returns:
        {
            "status": "success",
            "message": "后台任务已启动"
        }
    """
    try:
        # TODO: 实现后台任务队列
        return {"status": "success", "message": "功能开发中"}
    except Exception as e:
        return {"status": "error", "message": str(e)}