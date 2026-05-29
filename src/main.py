import sys
import os
import webbrowser
import asyncio
import platform
from contextlib import asynccontextmanager
from pathlib import Path

# --- 1. 环境策略设置 (必须在导入任何异步库前) ---
if platform.system() == 'Windows':
    # ✅ 使用 SelectorEventLoop 支持 MCP stdio 通信
    # 同时在 executor 中初始化 KnowledgeBase 避免阻塞
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# --- 1.5. 清理代理环境变量（防止干扰 MCP 连接） ---
# 注意：必须在导入 src.config.loader 之前清理，因为 loader 会设置代理
for proxy_var in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
    if proxy_var in os.environ:
        print(f"[MCP Fix] 移除代理环境变量: {proxy_var}")
        del os.environ[proxy_var]

# --- 2. 路径初始化 (确保项目根目录在首位) ---
current_file_path = Path(__file__).resolve()
src_dir = current_file_path.parent
project_root = src_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# --- 3. 业务服务导入 ---
from src.api.routes import router as api_router
from src.services.chat_agent import CustomsChatAgent
from src.services.report_agent import ComplianceReporter
from src.database.base import init_database
from src.config.loader import settings

# --- 4. 生命周期管理 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n" + "="*50)
    print("🚀 [System] 智慧口岸服务开始初始化...")

    # 初始化数据库
    try:
        await init_database()
        print("✅ [System] 数据库初始化完成")
    except Exception as e:
        print(f"❌ [System] 数据库初始化失败: {e}")

    # 加载用户 LLM 配置
    llm_config = None
    try:
        from src.database.connection import AsyncSessionLocal
        from src.config.llm_loader import llm_config_loader

        async with AsyncSessionLocal() as db:
            llm_config = await llm_config_loader.load_config(db)
            print(f"✅ [System] LLM 配置加载完成 (来源: {llm_config['source']})")
    except Exception as e:
        print(f"⚠️ [System] LLM 配置加载失败: {e}, 使用 .env 默认配置")
        # 使用 .env 配置
        from src.config.loader import settings
        llm_config = {
            'api_key': settings.DEEPSEEK_API_KEY,
            'base_url': settings.DEEPSEEK_BASE_URL,
            'model': settings.DEEPSEEK_MODEL,
            'temperature': 0.3,
            'source': 'env'
        }

    # 加载用户图像识别配置
    image_config = None
    try:
        from src.database.connection import AsyncSessionLocal
        from src.database.image_config_crud import ImageConfigRepository
        from src.config.image_loader import image_config_loader

        async with AsyncSessionLocal() as db:
            repo = ImageConfigRepository(db)
            db_config = await repo.get_active_config()

            if db_config and db_config.is_enabled:
                image_config = repo.to_dict(db_config)
                image_config_loader.set_config(image_config)
                print(f"✅ [System] 图像识别配置加载完成 (来源: database, {image_config['provider']}/{image_config['model_name']})")
            else:
                # 使用 .env 默认配置
                image_config = image_config_loader.load_from_env()
                image_config_loader.set_config(image_config)
                print(f"✅ [System] 图像识别配置加载完成 (来源: env)")
    except Exception as e:
        print(f"⚠️ [System] 图像识别配置加载失败: {e}, 使用 .env 默认配置")
        from src.config.image_loader import image_config_loader
        image_config = image_config_loader.load_from_env()
        image_config_loader.set_config(image_config)

    # 初始化全局KnowledgeBase（单例模式，所有Agent共享）
    try:
        from src.services.knowledge_base import KnowledgeBase
        print("⚙️ [System] 正在初始化知识库（单例，全局共享）...")
        
        # ✅ 在 executor 中初始化，避免阻塞事件循环
        loop = asyncio.get_event_loop()
        app.state.kb = await loop.run_in_executor(None, KnowledgeBase)
        
        print("✅ [System] 知识库初始化完成")
    except Exception as e:
        print(f"❌ [System] 知识库初始化失败: {e}")
        app.state.kb = None

    # 初始化功能二：对话 Agent（传入全局kb实例 + llm配置）
    # 使用 Skill + MCP 双系统架构：先创建实例，再异步加载 MCP 工具
    try:
        agent = CustomsChatAgent(kb=app.state.kb, llm_config=llm_config)
        await agent.initialize_mcp_tools()
        app.state.agent = agent
        print("✅ [System] 对话引擎（Skill + MCP 双系统）就绪")
    except Exception as e:
        print(f"❌ [System] 对话引擎初始化失败: {e}")
        app.state.agent = None

    # 初始化功能三：报告 Agent（传入全局kb实例 + llm配置）
    try:
        app.state.reporter = ComplianceReporter(kb=app.state.kb, llm_config=llm_config)
        print("✅ [System] 研判建议书引擎（功能三）就绪")
    except Exception as e:
        print(f"❌ [System] 报告引擎初始化失败: {e}")
        app.state.reporter = None

    # 保存llm_config到app.state，供功能一使用
    app.state.llm_config = llm_config
    print(f"✅ [System] LLM配置已保存到 app.state (来源: {llm_config['source']})")

    # 确保导出目录存在（功能三：深度研究工具）
    export_dir = project_root / "data" / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    app.state.export_dir = export_dir
    print(f"✅ [System] 导出目录已就绪：{export_dir}")

    # 自动打开浏览器
    async def open_browser():
        await asyncio.sleep(2.5)
        url = "http://127.0.0.1:8000"
        print(f"🌐 [System] 自动打开操作界面: {url}")
        try:
            webbrowser.open(url)
        except:
            pass
            
    asyncio.create_task(open_browser())
    print("="*50 + "\n")
    yield
    print("\n🛑 [System] 服务正在关闭...")

    # 优雅停机：关闭 MCP 桥接器
    if getattr(app.state, 'agent', None):
        try:
            await app.state.agent.shutdown()
            print("✅ [System] MCP 桥接器已关闭")
        except Exception as e:
            print(f"⚠️ [System] MCP 桥接器关闭失败: {e}")

app = FastAPI(
    title="Customs AI Agent", 
    version="3.1.0 (Skill + MCP)", 
    lifespan=lifespan
)

# --- 5. 跨域与路由 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")

# 挂载下载目录（功能三：深度研究工具导出文件）
downloads_dir = project_root / "data" / "exports"
if downloads_dir.exists():
    app.mount("/downloads", StaticFiles(directory=str(downloads_dir)), name="downloads")
    print(f"✅ [System] 下载目录已挂载：/downloads -> {downloads_dir}")
else:
    print(f"⚠️ [Warning] 下载目录不存在：{downloads_dir}")

# --- 6. 静态文件挂载 ---
web_dir = project_root / "web"
if web_dir.exists() and (web_dir / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    print(f"✅ [System] 前端资源加载成功: {web_dir}")
else:
    print(f"❌ [Error] 找不到前端目录或 index.html")

if __name__ == "__main__":
    # 从环境变量或配置获取端口，默认8000
    port = settings.PORT
    host = settings.HOST

    # ⚠️ 关键：直接传入 app 对象而非字符串，禁用 reload 确保进程稳定
    uvicorn.run(app, host=host, port=port)