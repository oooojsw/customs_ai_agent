import traceback
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

# --- 核心服务导入 ---
from src.services.data_client import DataClient
from src.core.orchestrator import RiskAnalysisOrchestrator
from src.services.report_agent import ComplianceReporter

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

@router.get("/query/declaration/{entry_id}")
async def query_declaration_data(entry_id: str):
    client = DataClient()
    text_data = client.fetch_declaration_text(entry_id)