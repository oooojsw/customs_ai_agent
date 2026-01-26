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
    from src.database.connection import AsyncSessionLocal
    from src.database.crud import BatchRepository
    BATCH_AVAILABLE = True
except ImportError:
    BATCH_AVAILABLE = False
    print("⚠️ [System] 数据库相关依赖未完全安装，批量功能将受限")

router = APIRouter()

# --- 辅助函数：动态获取 LLM 配置 ---
async def get_current_llm_config(req: Request) -> dict:
    """
    动态获取当前 LLM 配置，每次都检查数据库的 is_enabled 状态

    Returns:
        配置字典 {
            'api_key': str,
            'base_url': str,
            'model': str,
            'temperature': float,
            'source': 'user' | 'env'
        }
    """
    try:
        from src.config.llm_loader import llm_config_loader

        # 每次都从数据库重新加载配置，检查 is_enabled 状态
        async with AsyncSessionLocal() as db:
            config = await llm_config_loader.load_config(db)
        return config

    except Exception as e:
        print(f"[Config] 配置获取失败: {e}，回退到 .env")
        from src.config.loader import settings
        return {
            'api_key': settings.DEEPSEEK_API_KEY,
            'base_url': settings.DEEPSEEK_BASE_URL,
            'model': settings.DEEPSEEK_MODEL,
            'temperature': 0.3,
            'source': 'env'
        }

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
async def analyze_customs_declaration(request: AnalysisRequest, req: Request):
    if not request.raw_data or len(request.raw_data.strip()) < 5:
        raise HTTPException(status_code=400, detail="数据太短，无法分析")

    # 动态获取 LLM 配置（每次都检查数据库的 is_enabled 状态）
    llm_config = await get_current_llm_config(req)
    print(f"[功能一] 使用配置来源: {llm_config['source']}")

    orchestrator = RiskAnalysisOrchestrator(llm_config=llm_config)
    return StreamingResponse(
        orchestrator.analyze_stream(request.raw_data, language=request.language),
        media_type="text/event-stream"
    )

# ==========================================
# 2. 法规咨询接口 (功能二)
# ==========================================
@router.post("/chat")
async def chat_with_agent(body: ChatRequest, request: Request):
    # 动态获取配置并创建临时 agent
    llm_config = await get_current_llm_config(request)

    # 获取全局 kb 实例（如果存在）
    kb = getattr(request.app.state, "kb", None)

    # 使用当前配置创建临时 agent
    from src.services.chat_agent import CustomsChatAgent
    agent = CustomsChatAgent(kb=kb, llm_config=llm_config)

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
        # 动态获取配置并创建临时 reporter
        llm_config = await get_current_llm_config(req)

        # 获取全局 kb 实例（如果存在）
        kb = getattr(req.app.state, "kb", None)

        # 使用当前配置创建临时 reporter
        reporter = ComplianceReporter(kb=kb, llm_config=llm_config)

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

    # 使用异步工厂方法创建实例（从数据库加载配置）
    try:
        from src.database.connection import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            extractor = await ImageTextExtractor.create_async(db)
    except Exception as e:
        print(f"[Warning] 数据库配置加载失败，使用 .env: {e}")
        extractor = ImageTextExtractor()

    try:
        text, model = extractor.extract_text(content, file.content_type, language=language)
        return {"text": text, "model": model}
    except NotDeclarationError as e:
        raise HTTPException(status_code=400, detail=str(e))
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

        async with AsyncSessionLocal() as db:
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
    async with AsyncSessionLocal() as db:
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

# ==========================================
# 8. 知识库索引管理接口
# ==========================================

@router.post("/index/rebuild")
async def rebuild_knowledge_base_index(request: Request):
    """
    重建知识库索引 (流式SSE响应)

    SSE事件类型：
    - init: 开始重建
    - progress: 更新进度 {current, total, current_file, percentage}
    - step: 阶段提示 {message, step}
    - complete: 完成统计 {message, stats}
    - error: 错误信息 {message}
    - cancelled: 取消信息 {message}
    """
    kb = getattr(request.app.state, "kb", None)
    if not kb:
        raise HTTPException(status_code=503, detail="知识库服务未就绪")

    return StreamingResponse(
        kb.rebuild_index_stream(),
        media_type="text/event-stream"
    )

@router.get("/index/status")
async def get_index_status(request: Request):
    """
    获取索引状态

    Returns:
        {
            "status": "success",
            "data": {
                "is_rebuilding": bool,
                "progress": {
                    "current": int,
                    "total": int,
                    "current_file": str,
                    "percentage": float
                },
                "file_count": int,
                "last_rebuild_time": float | None
            }
        }
    """
    kb = getattr(request.app.state, "kb", None)
    if not kb:
        return {
            "status": "error",
            "message": "知识库服务未就绪"
        }

    return {
        "status": "success",
        "data": {
            "is_rebuilding": kb.is_rebuilding,
            "progress": kb.progress,
            "file_count": kb.file_count,
            "last_rebuild_time": kb.last_rebuild_time
        }
    }

@router.post("/index/cancel")
async def cancel_index_rebuild(request: Request):
    """
    取消索引重建任务

    Returns:
        {
            "status": "success",
            "message": "取消请求已发送"
        }
    """
    kb = getattr(request.app.state, "kb", None)
    if not kb:
        return {
            "status": "error",
            "message": "知识库服务未就绪"
        }

    if not kb.is_rebuilding:
        return {
            "status": "error",
            "message": "没有正在进行的重建任务"
        }

    kb.cancel_rebuild()
    return {
        "status": "success",
        "message": "取消请求已发送"
    }

# ==========================================
# 9. LLM 配置管理接口
# ==========================================

class LLMConfigRequest(BaseModel):
    provider: str
    api_key: str
    base_url: str
    model_name: str
    api_version: Optional[str] = None
    temperature: Optional[float] = 0.3
    is_enabled: Optional[bool] = True  # 新增：接收前端开关状态

    # ==================== 新增：图像识别配置 ====================
    image_enabled: Optional[bool] = True  # 是否启用图像识别功能
    image_model_name: Optional[str] = None  # 图像模型名称（如 gpt-4-vision-preview）
    # ============================================================


class LLMConfigResponse(BaseModel):
    is_enabled: bool
    provider: str
    base_url: str
    model_name: str
    temperature: float
    test_status: str
    last_tested_at: Optional[str] = None
    api_key: Optional[str] = None  # 添加API Key字段用于前端填充

    # ==================== 新增：图像识别配置 ====================
    image_enabled: Optional[bool] = True
    image_model_name: Optional[str] = None
    # ============================================================

    model_config = {"exclude_unset": False}  # 确保所有字段都被序列化


@router.get("/config/llm")
async def get_llm_config():
    """获取当前 LLM 配置"""
    if not BATCH_AVAILABLE:
        raise HTTPException(status_code=501, detail="数据库不可用")

    from src.database.connection import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        from src.database.crud import LLMConfigRepository
        repo = LLMConfigRepository(db)
        config = await repo.get_active_config()

        if not config:
            from src.config.loader import settings
            return LLMConfigResponse(
                is_enabled=False,
                provider="deepseek",
                base_url=settings.DEEPSEEK_BASE_URL,
                model_name=settings.DEEPSEEK_MODEL,
                temperature=0.3,
                test_status="never",
                last_tested_at=None,
                image_enabled=False,
                image_model_name=None
            )

        return LLMConfigResponse(
            is_enabled=config.is_enabled,
            provider=config.provider,
            base_url=config.base_url,
            model_name=config.model_name,
            temperature=config.temperature,
            test_status=config.test_status,
            last_tested_at=config.last_tested_at.isoformat() if config.last_tested_at else None,
            api_key=config.api_key,  # 返回API Key用于前端填充
            # ==================== 新增：图像识别配置 ====================
            image_enabled=getattr(config, 'image_enabled', False),
            image_model_name=getattr(config, 'image_model_name', None)
            # ============================================================
        )


@router.post("/config/llm")
async def save_llm_config(config: LLMConfigRequest):
    """保存 LLM 配置"""
    if not BATCH_AVAILABLE:
        raise HTTPException(status_code=501, detail="数据库不可用")

    from src.database.connection import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        from src.database.crud import LLMConfigRepository
        repo = LLMConfigRepository(db)
        saved_config = await repo.save_config(config.dict())

        return {
            "status": "success",
            "message": "配置已保存",
            "config_id": saved_config.id
        }


@router.post("/config/llm/test")
async def test_llm_connection(config: LLMConfigRequest):
    """测试 LLM 连接"""
    try:
        import httpx
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage

        async_client = httpx.AsyncClient(verify=False, timeout=30.0)
        test_llm = ChatOpenAI(
            model=config.model_name,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=0.1,
            http_async_client=async_client,
            max_tokens=10,
        )

        response = await test_llm.ainvoke([HumanMessage(content="Hi")])
        await async_client.aclose()

        if response.content:
            return {
                "status": "success",
                "message": "连接成功",
                "response_preview": str(response.content[:50])
            }
        else:
            return {
                "status": "error",
                "message": "无响应内容"
            }

    except Exception as e:
        traceback.print_exc()
        return {
            "status": "error",
            "message": f"连接失败: {str(e)}"
        }


@router.post("/config/llm/reload")
async def reload_llm_config(request: Request):
    """
    热重载 LLM 配置（无需重启服务）

    重新初始化所有 Agent，使新配置立即生效
    """
    try:
        from src.database.connection import AsyncSessionLocal
        from src.config.llm_loader import llm_config_loader
        from src.services.chat_agent import CustomsChatAgent
        from src.services.report_agent import ComplianceReporter

        # 加载新配置
        async with AsyncSessionLocal() as db:
            llm_config = await llm_config_loader.load_config(db)

        # ✅ 修复：更新 app.state.llm_config（关键！）
        # 功能一依赖此配置，必须更新
        request.app.state.llm_config = llm_config

        # 重新初始化 Agent
        kb = request.app.state.kb
        request.app.state.agent = CustomsChatAgent(kb=kb, llm_config=llm_config)
        request.app.state.reporter = ComplianceReporter(kb=kb, llm_config=llm_config)

        return {
            "status": "success",
            "message": "配置已重新加载",
            "config": {
                "source": llm_config.get('source', 'unknown'),
                "provider": llm_config.get('source', 'unknown'),
                "model": llm_config['model'],
                "base_url": llm_config['base_url']
            }
        }
    except Exception as e:
        traceback.print_exc()
        return {
            "status": "error",
            "message": f"重载失败: {str(e)}",
            "detail": traceback.format_exc()[:500]
        }


@router.post("/config/llm/reset")
async def reset_llm_config():
    """重置为 .env 默认配置"""
    if not BATCH_AVAILABLE:
        raise HTTPException(status_code=501, detail="数据库不可用")

    from src.database.connection import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        from src.database.crud import LLMConfigRepository
        repo = LLMConfigRepository(db)
        await repo.reset_to_env()

        return {
            "status": "success",
            "message": "已重置为 .env 默认配置"
        }


@router.get("/config/llm/all")
async def get_all_llm_configs():
    """获取所有已保存的厂商配置"""
    if not BATCH_AVAILABLE:
        raise HTTPException(status_code=501, detail="数据库不可用")

    from src.database.connection import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        from src.database.crud import LLMConfigRepository
        repo = LLMConfigRepository(db)
        configs = await repo.get_all_configs()

        # 返回配置列表（隐藏API Key）
        result = []
        for config in configs:
            result.append({
                "provider": config.provider,
                "is_enabled": config.is_enabled,
                "base_url": config.base_url,
                "model_name": config.model_name,
                "temperature": config.temperature,
                "test_status": config.test_status,
                "api_key_preview": config.api_key[:8] + "..." if config.api_key else "",
                "has_api_key": bool(config.api_key)
            })

        return {
            "status": "success",
            "configs": result
        }


@router.get("/config/llm/provider/{provider}")
async def get_provider_config(provider: str):
    """获取指定厂商的配置"""
    if not BATCH_AVAILABLE:
        raise HTTPException(status_code=501, detail="数据库不可用")

    from src.database.connection import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        from src.database.crud import LLMConfigRepository
        repo = LLMConfigRepository(db)
        config = await repo.get_config_by_provider(provider)

        if not config:
            return {
                "status": "not_found",
                "message": f"未找到 {provider} 的配置"
            }

        return {
            "status": "success",
            "config": {
                "provider": config.provider,
                "is_enabled": config.is_enabled,
                "base_url": config.base_url,
                "model_name": config.model_name,
                "temperature": config.temperature,
                "api_version": config.api_version,
                "test_status": config.test_status,
                # 返回完整API Key用于前端填充
                "api_key": config.api_key
            }
        }


@router.post("/config/llm/activate/{provider}")
async def activate_provider_config(provider: str):
    """激活指定厂商的配置"""
    if not BATCH_AVAILABLE:
        raise HTTPException(status_code=501, detail="数据库不可用")

    from src.database.connection import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        from src.database.crud import LLMConfigRepository
        repo = LLMConfigRepository(db)
        config = await repo.activate_provider(provider)

        if not config:
            raise HTTPException(status_code=404, detail=f"未找到 {provider} 的配置")

        # 热重载配置
        from src.config.llm_loader import llm_config_loader
        llm_config = await llm_config_loader.load_config(db)

        return {
            "status": "success",
            "message": f"已切换到 {provider}",
            "config": {
                "provider": provider,
                "model": llm_config['model'],
                "base_url": llm_config['base_url']
            }
        }


@router.get("/config/llm/models")
async def get_available_models(
    provider: str,
    api_key: str,
    base_url: str = None,
    api_version: str = None
):
    """
    获取指定厂商的模型列表

    参数：
    - provider: 厂商名称 (deepseek, openai, qwen, zhipu, siliconflow, azure, custom)
    - api_key: API密钥
    - base_url: 自定义base_url（用于azure和custom provider）
    - api_version: API版本（Azure特有，如：2024-03-01-preview）
    """
    try:
        import httpx

        # 1. 智谱GLM：无模型列表API，返回硬编码列表
        if provider == "zhipu":
            models = [
                "glm-4.7",
                "glm-4-turbo",
                "glm-4-plus",
                "glm-4-air",
                "glm-4-flash"
            ]
            return {
                "status": "success",
                "models": models,
                "source": "hardcoded"
            }

        # 2. Azure OpenAI：特殊处理（api-key header + api-version参数）
        if provider == "azure":
            if not base_url:
                return {
                    "status": "error",
                    "message": "Azure需要提供Endpoint（如：https://your-resource.openai.azure.com）"
                }
            if not api_version:
                api_version = "2024-03-01-preview"  # 默认版本

            url = f"{base_url.rstrip('/')}/openai/models?api-version={api_version}"
            headers = {"api-key": api_key}  # Azure使用api-key header

            async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
                response = await client.get(url, headers=headers)

                if response.status_code == 200:
                    data = response.json()
                    models = [item["id"] for item in data.get("data", [])]
                    return {
                        "status": "success",
                        "models": models,
                        "source": "api"
                    }
                elif response.status_code == 401:
                    return {"status": "error", "message": "API Key 无效"}
                else:
                    return {
                        "status": "error",
                        "message": f"API调用失败 (HTTP {response.status_code})"
                    }

        # 3. 其他厂商：使用标准OpenAI兼容格式
        # 如果用户提供了 base_url，优先使用用户提供的
        if base_url and base_url.strip():
            url = f"{base_url.rstrip('/')}/models"
        else:
            # 使用默认的 provider_urls（根据官方文档配置）
            provider_urls = {
                "deepseek": "https://api.deepseek.com/v1/models",
                "openai": "https://api.openai.com/v1/models",
                "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
                "siliconflow": "https://api.siliconflow.cn/v1/models",  # 国内主域名（文档第24行）
                "zhipu": "https://open.bigmodel.cn/api/paas/v4/models",
            }

            if provider not in provider_urls:
                return {
                    "status": "error",
                    "message": f"不支持的服务商: {provider}"
                }

            url = provider_urls[provider]
            if not url:
                return {
                    "status": "error",
                    "message": "自定义服务商需要提供base_url"
                }

        # 4. 标准OpenAI格式调用（Authorization: Bearer）
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            response = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
            )

            if response.status_code == 200:
                data = response.json()
                # OpenAI兼容格式：data[].id
                models = [item["id"] for item in data.get("data", [])]

                return {
                    "status": "success",
                    "models": models,
                    "source": "api"
                }
            elif response.status_code == 401:
                return {
                    "status": "error",
                    "message": "API Key 无效或已过期"
                }
            else:
                return {
                    "status": "error",
                    "message": f"API调用失败 (HTTP {response.status_code})"
                }

    except httpx.TimeoutException:
        return {
            "status": "error",
            "message": "请求超时，请检查网络连接"
        }
    except Exception as e:
        traceback.print_exc()
        return {
            "status": "error",
            "message": f"获取模型列表失败: {str(e)}"
        }


# ==================== 图像识别配置 API ====================

class ImageConfigRequest(BaseModel):
    """图像配置请求模型"""
    provider: str
    api_key: str
    base_url: Optional[str] = None
    model_name: str
    api_version: Optional[str] = None
    endpoint: Optional[str] = None
    temperature: Optional[float] = 0.1
    max_tokens: Optional[int] = 16384
    is_enabled: Optional[bool] = True
    description: Optional[str] = None


class ImageConfigResponse(BaseModel):
    """图像配置响应模型"""
    id: Optional[int] = None
    provider: str
    is_enabled: bool
    api_key: Optional[str] = None  # ✅ 添加 API Key 字段
    base_url: Optional[str] = None
    model_name: str
    api_version: Optional[str] = None
    endpoint: Optional[str] = None
    temperature: float
    max_tokens: int
    test_status: str
    description: Optional[str] = None


@router.get("/config/image")
async def get_image_config():
    """获取当前图像识别配置"""
    if not BATCH_AVAILABLE:
        # 降级：返回 .env 配置
        from src.config.image_loader import image_config_loader
        config = image_config_loader.load_from_env()

        return ImageConfigResponse(
            provider=config["provider"],
            is_enabled=config["is_enabled"],
            api_key=config.get("api_key"),  # ✅ 添加 API Key
            base_url=config.get("base_url"),
            model_name=config["model_name"],
            api_version=config.get("api_version"),
            endpoint=config.get("endpoint"),
            temperature=config["temperature"],
            max_tokens=config["max_tokens"],
            test_status="never"
        )

    from src.database.connection import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        from src.database.image_config_crud import ImageConfigRepository
        repo = ImageConfigRepository(db)

        # 优先获取启用的配置，如果没有则获取最新保存的配置
        config = await repo.get_active_config()
        if not config:
            config = await repo.get_latest_config()

        if config:
            return ImageConfigResponse(
                id=config.id,
                provider=config.provider,
                is_enabled=config.is_enabled,  # 告诉前端配置是否启用
                api_key=config.api_key,  # ✅ 添加 API Key
                base_url=config.base_url,
                model_name=config.model_name,
                api_version=config.api_version,
                endpoint=config.endpoint,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                test_status=config.test_status,
                description=config.description
            )
        else:
            # 没有数据库配置，返回 .env 默认配置
            from src.config.image_loader import image_config_loader
            env_config = image_config_loader.load_from_env()

            return ImageConfigResponse(
                provider=env_config["provider"],
                is_enabled=False,
                api_key=env_config.get("api_key"),  # ✅ 添加 API Key
                base_url=env_config.get("base_url"),
                model_name=env_config["model_name"],
                api_version=env_config.get("api_version"),
                endpoint=env_config.get("endpoint"),
                temperature=env_config["temperature"],
                max_tokens=env_config["max_tokens"],
                test_status="never"
            )


@router.post("/config/image")
async def save_image_config(config: ImageConfigRequest):
    """保存图像识别配置"""
    print(f"\n{'='*80}")
    print(f"📝 [Image Config] 保存图像识别配置")
    print(f"{'='*80}")
    print(f"Provider: {config.provider}")
    print(f"API Key: {config.api_key[:15]}...{config.api_key[-5:] if len(config.api_key) > 20 else '***'} (长度: {len(config.api_key)})")
    print(f"Base URL: {config.base_url}")
    print(f"Model: {config.model_name}")
    print(f"Enabled: {config.is_enabled}")
    print(f"{'='*80}\n")

    if not BATCH_AVAILABLE:
        raise HTTPException(status_code=501, detail="数据库不可用")

    from src.database.connection import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        from src.database.image_config_crud import ImageConfigRepository
        repo = ImageConfigRepository(db)

        # 转换为字典
        config_data = config.dict(exclude_unset=True)

        # 保存配置
        saved_config = await repo.create_or_update(config_data)

        print(f"\n{'='*80}")
        print(f"✅ [Image Config] 配置保存完成")
        print(f"{'='*80}")
        print(f"ID: {saved_config.id}")
        print(f"Provider: {saved_config.provider}")
        print(f"Model: {saved_config.model_name}")
        print(f"Enabled: {saved_config.is_enabled}")
        print(f"{'='*80}\n")

        return {
            "status": "success",
            "message": "图像识别配置已保存",
            "config": repo.to_dict(saved_config)
        }


@router.post("/config/image/test")
async def test_image_connection(config: ImageConfigRequest):
    """测试图像识别配置连接（真实API调用）"""
    try:
        import httpx

        # 验证必要参数
        if not config.api_key or len(config.api_key) < 10:
            return {
                "status": "error",
                "message": "API Key 无效或太短"
            }

        if not config.model_name:
            return {
                "status": "error",
                "message": "请指定模型名称"
            }

        # 根据provider真实测试API
        if config.provider == "gemini":
            # 测试 Gemini API
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.model_name}:generateContent?key={config.api_key}"
            test_payload = {
                "contents": [{
                    "parts": [{"text": "Hi"}]
                }]
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=test_payload)

                if response.status_code == 200:
                    return {
                        "status": "success",
                        "message": f"✅ Gemini 连接成功 ({config.model_name})"
                    }
                elif response.status_code == 429:
                    return {
                        "status": "error",
                        "message": "❌ API 配额已用完或请求频率超限 (429)"
                    }
                elif response.status_code == 401:
                    return {
                        "status": "error",
                        "message": "❌ API Key 无效 (401)"
                    }
                else:
                    return {
                        "status": "error",
                        "message": f"❌ API 调用失败 (HTTP {response.status_code})"
                    }

        elif config.provider == "azure":
            # 测试 Azure OpenAI API
            if not config.endpoint:
                return {
                    "status": "error",
                    "message": "❌ Azure Endpoint 未配置"
                }

            url = f"{config.endpoint}/openai/deployments/{config.model_name}/chat/completions?api-version={config.api_version}"
            headers = {
                "api-key": config.api_key,
                "Content-Type": "application/json"
            }
            test_payload = {
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 10
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=test_payload, headers=headers)

                if response.status_code == 200:
                    return {
                        "status": "success",
                        "message": f"✅ Azure 连接成功 ({config.model_name})"
                    }
                elif response.status_code == 401:
                    return {
                        "status": "error",
                        "message": "❌ API Key 无效 (401)"
                    }
                else:
                    return {
                        "status": "error",
                        "message": f"❌ API 调用失败 (HTTP {response.status_code})"
                    }

        else:
            return {
                "status": "success",
                "message": f"⚠️ {config.provider} 配置已保存（无法自动测试）"
            }

    except httpx.TimeoutException:
        return {
            "status": "error",
            "message": "❌ 请求超时，请检查网络连接"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"❌ 测试失败: {str(e)}"
        }


@router.post("/config/image/reset")
async def reset_image_config():
    """重置为 .env 默认配置"""
    if not BATCH_AVAILABLE:
        raise HTTPException(status_code=501, detail="数据库不可用")

    from src.database.connection import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        from src.database.image_config_crud import ImageConfigRepository
        repo = ImageConfigRepository(db)
        await repo.disable_all()

        return {
            "status": "success",
            "message": "已重置为 .env 默认配置"
        }


@router.post("/config/image/reload")
async def reload_image_config():
    """热重载图像识别配置"""
    if not BATCH_AVAILABLE:
        raise HTTPException(status_code=501, detail="数据库不可用")

    from src.database.connection import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        from src.database.image_config_crud import ImageConfigRepository
        from src.config.image_loader import image_config_loader

        repo = ImageConfigRepository(db)
        config = await repo.get_active_config()

        if config:
            config_dict = repo.to_dict(config)
            image_config_loader.set_config(config_dict)

            return {
                "status": "success",
                "message": "配置已重载",
                "config": {
                    "provider": config_dict["provider"],
                    "model": config_dict["model_name"],
                    "enabled": config_dict["is_enabled"]
                }
            }
        else:
            # 使用 .env 配置
            env_config = image_config_loader.load_from_env()
            image_config_loader.set_config(env_config)

            return {
                "status": "success",
                "message": "已重载 .env 默认配置",
                "config": {
                    "provider": env_config["provider"],
                    "model": env_config["model_name"],
                    "enabled": False
                }
            }


@router.get("/config/image/provider/{provider}")
async def get_image_provider_config(provider: str):
    """获取指定服务商的图像配置（返回完整API Key用于前端填充）"""
    if not BATCH_AVAILABLE:
        raise HTTPException(status_code=501, detail="数据库不可用")

    from src.database.connection import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        from src.database.image_config_crud import ImageConfigRepository
        repo = ImageConfigRepository(db)
        config = await repo.get_by_provider(provider)

        if config:
            return {
                "status": "success",
                "config": {
                    "provider": config.provider,
                    "api_key": config.api_key,  # 返回完整API Key
                    "base_url": config.base_url,
                    "model_name": config.model_name,
                    "endpoint": config.endpoint,
                    "api_version": config.api_version,
                    "has_api_key": bool(config.api_key)
                }
            }
        else:
            return {
                "status": "error",
                "message": f"未找到 {provider} 的配置"
            }


@router.get("/config/image/models")
async def get_image_models(
    provider: str,
    api_key: str,
    base_url: str = None,
    api_version: str = None
):
    """
    获取图像识别模型列表（复用LLM配置的相同逻辑）
    参数与 LLM 配置完全相同
    """
    # ========== 详细调试信息 ==========
    print("\n" + "="*80)
    print(f"🔍 [图像模型列表] 开始获取 {provider} 的模型列表")
    print("="*80)
    print(f"📌 参数信息:")
    print(f"  - provider: {provider}")
    print(f"  - api_key: {api_key[:15]}...{api_key[-5:] if len(api_key) > 20 else '***'} (长度: {len(api_key)})")
    print(f"  - base_url: {base_url}")
    print(f"  - api_version: {api_version}")
    print("="*80 + "\n")

    try:
        import httpx

        # 智谱GLM：使用硬编码列表
        if provider == "zhipu":
            print(f"✅ [智谱GLM] 使用硬编码模型列表")
            return {
                "status": "success",
                "models": ["glm-4v", "glm-4v-plus", "glm-4v-flash"],
                "source": "builtin"
            }

        # Azure：需要endpoint和apiVersion
        elif provider == "azure":
            print(f"🔧 [Azure] 检查参数...")
            if not base_url:
                print(f"❌ [Azure] 缺少 base_url 参数")
                return {
                    "status": "error",
                    "message": "Azure需要 base_url 参数"
                }

            url = f"{base_url}/openai/deployments?api-version={api_version}"
            headers = {"api-key": api_key}

            print(f"📡 [Azure] 发送请求:")
            print(f"  - URL: {url}")
            print(f"  - Headers: api-key={headers['api-key'][:10]}...***")

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, headers=headers)

                print(f"📥 [Azure] 响应状态: HTTP {response.status_code}")
                print(f"📄 [Azure] 响应内容: {response.text[:500]}")

                if response.status_code == 200:
                    data = response.json()
                    models = [item["id"] for item in data.get("data", [])]
                    print(f"✅ [Azure] 成功获取 {len(models)} 个模型")
                    return {
                        "status": "success",
                        "models": models,
                        "source": "api"
                    }
                else:
                    print(f"❌ [Azure] 请求失败")
                    return {
                        "status": "error",
                        "message": f"API调用失败 (HTTP {response.status_code})\n响应: {response.text[:200]}"
                    }

        # 其他厂商：调用标准OpenAI兼容API
        else:
            # 没有API Key时的处理
            if not api_key:
                print(f"⚠️  [{provider.upper()}] 未提供API Key，使用预设模型列表")

                # 返回预设列表（更新硅基流动图像模型，基于官方文档）
                provider_presets = {
                    "deepseek": ["deepseek-chat", "deepseek-coder", "deepseek-reasoner"],
                    "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
                    "qwen": ["qwen-turbo", "qwen-plus", "qwen-max", "qwen-max-longcontext", "qwen-vl-max", "qwen2.5-vl-7b-instruct", "qwen2.5-vl-72b-instruct"],
                    "siliconflow": [
                        # 硅基流动支持的视觉语言模型（基于官方文档）
                        "Qwen/Qwen2-VL-7B-Instruct",
                        "Qwen/Qwen2-VL-72B-Instruct",
                        "Qwen/Qwen2.5-VL-7B-Instruct",
                        "Qwen/Qwen2.5-VL-32B-Instruct",
                        "Qwen/Qwen2.5-VL-72B-Instruct",
                        "Qwen/Qwen3-VL-32B-Instruct",
                        "OpenGVLab/InternVL2-Llama3-76B",
                        "deepseek-ai/deepseek-vl-7b"
                    ],
                    "zhipu": ["glm-4v", "glm-4v-plus", "glm-4v-flash"]
                }

                if provider in provider_presets:
                    models = provider_presets[provider]
                    print(f"✅ [{provider.upper()}] 返回预设模型列表 ({len(models)} 个模型)")
                    for i, model in enumerate(models, 1):
                        print(f"   {i}. {model}")
                    return {
                        "status": "success",
                        "models": models,
                        "source": "builtin"
                    }
                else:
                    print(f"❌ [{provider.upper()}] 无预设模型列表")
                    return {
                        "status": "error",
                        "message": "请先输入 API Key"
                    }

            # 有API Key时的处理
            print(f"🔑 [{provider.upper()}] 已提供API Key，尝试从API获取模型列表")

            # 如果用户提供了 base_url，优先使用用户提供的
            if base_url and base_url.strip():
                url = f"{base_url.rstrip('/')}/models"
                print(f"📝 使用用户提供的 base_url")
            else:
                # 使用默认的 provider_urls（根据官方文档配置）
                provider_urls = {
                    "deepseek": "https://api.deepseek.com/v1/models",
                    "openai": "https://api.openai.com/v1/models",
                    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1/models",
                    "siliconflow": "https://api.siliconflow.cn/v1/models",  # 国内主域名（文档第24行）
                    "zhipu": "https://open.bigmodel.cn/api/paas/v4/models",
                }

                url = provider_urls.get(provider)
                print(f"📝 使用预设的 provider_urls")
                if not url:
                    print(f"❌ 不支持的服务商: {provider}")
                    return {
                        "status": "error",
                        "message": f"不支持的服务商: {provider}"
                    }

            # ========== 构建请求 ==========
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }

            print("\n" + "─"*80)
            print(f"📡 [{provider.upper()}] 发送HTTP请求")
            print("─"*80)
            print(f"请求方法: GET")
            print(f"请求URL: {url}")
            print(f"请求Headers:")
            print(f"  - Authorization: Bearer {api_key[:15]}...{api_key[-5:] if len(api_key) > 20 else '***'}")
            print(f"  - Content-Type: {headers['Content-Type']}")
            print(f"  - 长度: {len(api_key)} 字符")
            print("─"*80 + "\n")

            # 4. 标准OpenAI格式调用
            try:
                async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
                    response = await client.get(url, headers=headers)

                    print("\n" + "─"*80)
                    print(f"📥 [{provider.upper()}] 收到HTTP响应")
                    print("─"*80)
                    print(f"响应状态码: HTTP {response.status_code}")
                    print(f"响应头:")
                    for key, value in response.headers.items():
                        if key.lower() in ['authorization', 'set-cookie']:
                            continue  # 跳过敏感信息
                        print(f"  - {key}: {value}")
                    print(f"响应内容类型: {response.headers.get('content-type', 'unknown')}")
                    print(f"响应内容长度: {len(response.content)} 字节")
                    print("─"*80)

                    # 打印响应内容（截取前500字符）
                    response_text = response.text
                    print(f"\n📄 响应内容 (前500字符):")
                    print("─"*80)
                    print(response_text[:500])
                    if len(response_text) > 500:
                        print(f"\n... (还有 {len(response_text) - 500} 字符)")
                    print("─"*80 + "\n")

                    if response.status_code == 200:
                        data = response.json()
                        models = [item["id"] for item in data.get("data", [])]
                        print(f"✅ [{provider.upper()}] 成功获取 {len(models)} 个模型")
                        if len(models) <= 20:
                            # 如果模型不多，全部打印
                            for i, model in enumerate(models, 1):
                                print(f"   {i}. {model}")
                        else:
                            # 如果模型太多，只打印前10个和后5个
                            print(f"   前10个模型:")
                            for i in range(10):
                                print(f"   {i+1}. {models[i]}")
                            print(f"   ... 还有 {len(models) - 15} 个模型")
                            print(f"   最后5个模型:")
                            for i in range(5):
                                print(f"   {len(models)-4+i}. {models[-5+i]}")

                        return {
                            "status": "success",
                            "models": models,
                            "source": "api"
                        }
                    elif response.status_code == 401:
                        print(f"❌ [{provider.upper()}] API Key 认证失败 (HTTP 401)")
                        return {
                            "status": "error",
                            "message": "API Key 无效或已过期 (HTTP 401)"
                        }
                    elif response.status_code == 404:
                        print(f"❌ [{provider.upper()}] API端点不存在 (HTTP 404)")
                        print(f"可能的原因:")
                        print(f"  1. Base URL配置错误: {base_url}")
                        print(f"  2. 该服务商不支持模型列表API")
                        print(f"  3. 服务商端点已变更")
                        return {
                            "status": "error",
                            "message": f"API端点不存在 (HTTP 404)\n\n请检查：\n1. Base URL是否正确：{base_url}\n2. 该服务商是否支持模型列表API\n3. 查看控制台获取详细错误信息"
                        }
                    else:
                        print(f"❌ [{provider.upper()}] API调用失败 (HTTP {response.status_code})")
                        return {
                            "status": "error",
                            "message": f"API调用失败 (HTTP {response.status_code})\n\n响应内容:\n{response_text[:300]}\n\n请检查网络连接和API配置"
                        }

            except httpx.TimeoutException as e:
                print(f"⏱️  [{provider.upper()}] 请求超时")
                print(f"错误详情: {e}")
                return {
                    "status": "error",
                    "message": "请求超时，请检查网络连接"
                }
            except Exception as e:
                print(f"💥 [{provider.upper()}] 请求异常")
                print(f"异常类型: {type(e).__name__}")
                print(f"异常信息: {str(e)}")
                import traceback
                print(f"异常堆栈:\n{traceback.format_exc()}")
                return {
                    "status": "error",
                    "message": f"请求异常: {type(e).__name__}: {str(e)}"
                }
    except Exception as e:
        print(f"💥 [图像模型列表] 顶级异常捕获")
        print(f"异常类型: {type(e).__name__}")
        print(f"异常信息: {str(e)}")
        import traceback
        print(f"异常堆栈:\n{traceback.format_exc()}")
        return {
            "status": "error",
            "message": f"获取模型列表失败: {type(e).__name__}: {str(e)}"
        }




