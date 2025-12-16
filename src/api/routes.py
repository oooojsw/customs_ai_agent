from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.services.data_client import DataClient
from src.core.orchestrator import RiskAnalysisOrchestrator
# 【新增】引入 Reporter
from src.services.report_agent import ComplianceReporter

router = APIRouter()

# 定义请求体的数据结构
class AnalysisRequest(BaseModel):
    raw_data: str

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default_session"

# 【新增】报告请求体
class ReportRequest(BaseModel):
    raw_data: str

@router.post("/analyze")
async def analyze_customs_declaration(request: AnalysisRequest):
    """
    核心分析接口 (SSE 流式输出)
    """
    if not request.raw_data or len(request.raw_data.strip()) < 5:
        raise HTTPException(status_code=400, detail="请输入有效的报关数据")

    orchestrator = RiskAnalysisOrchestrator()

    return StreamingResponse(
        orchestrator.analyze_stream(request.raw_data),
        media_type="text/event-stream"
    )

@router.post("/chat")
async def chat_with_agent(body: ChatRequest, request: Request):
    """
    LangChain 对话接口 (SSE 流) - 使用全局单例模式
    """
    agent = getattr(request.app.state, "agent", None)
    
    if not agent:
        raise HTTPException(status_code=503, detail="AI 服务初始化失败或正在启动中，请稍后重试")

    return StreamingResponse(
        agent.chat_stream(body.message, body.session_id),
        media_type="text/event-stream"
    )

# 【新增】生成报告接口
@router.post("/generate_report")
async def generate_compliance_report(body: ReportRequest, req: Request):
    """
    生成合规性建议书 (SSE 流式)
    """
    if not body.raw_data or len(body.raw_data.strip()) < 2:
        raise HTTPException(status_code=400, detail="请输入上下文数据")

    # 获取全局单例 Reporter
    reporter = getattr(req.app.state, "reporter", None)
    
    if not reporter:
        # 容错：如果全局没初始化（极少情况），临时创建一个
        reporter = ComplianceReporter()

    return StreamingResponse(
        reporter.generate_stream(body.raw_data),
        media_type="text/event-stream"
    )

@router.get("/health")
def health_check():
    return {"status": "ok", "service": "Customs AI Agent"}

@router.get("/query/declaration/{entry_id}")
async def query_declaration_data(entry_id: str):
    client = DataClient()
    text_data = client.fetch_declaration_text(entry_id)
    
    if not text_data:
        raise HTTPException(status_code=404, detail="未找到该报关单数据")
        
    return {"status": "success", "text": text_data}