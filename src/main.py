import sys
import os
import webbrowser
import asyncio
import platform
from contextlib import asynccontextmanager
from pathlib import Path

# --- 1. 环境策略设置 (必须在导入任何异步库前) ---
if platform.system() == 'Windows':
    # 强制使用 SelectorEventLoop 解决 httpx 代理/SSL 冲突
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

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

    # 初始化全局KnowledgeBase（单例模式，所有Agent共享）
    try:
        from src.services.knowledge_base import KnowledgeBase
        print("⚙️ [System] 正在初始化知识库（单例，全局共享）...")
        app.state.kb = KnowledgeBase()  # ← 只创建一次，所有Agent共享
        print("✅ [System] 知识库初始化完成")
    except Exception as e:
        print(f"❌ [System] 知识库初始化失败: {e}")
        app.state.kb = None

    # 初始化功能二：对话 Agent（传入全局kb实例）
    try:
        app.state.agent = CustomsChatAgent(kb=app.state.kb)  # ← 传入kb，避免重复创建
        print("✅ [System] 对话引擎（功能二）就绪")
    except Exception as e:
        print(f"❌ [System] 对话引擎初始化失败: {e}")
        app.state.agent = None

    # 初始化功能三：报告 Agent（传入全局kb实例）
    try:
        app.state.reporter = ComplianceReporter(kb=app.state.kb)  # ← 传入kb，避免重复创建
        print("✅ [System] 研判建议书引擎（功能三）就绪")
    except Exception as e:
        print(f"❌ [System] 报告引擎初始化失败: {e}")
        app.state.reporter = None
    
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

app = FastAPI(
    title="Customs AI Agent", 
    version="3.0 Pro", 
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

# --- 6. 静态文件挂载 ---
web_dir = project_root / "web"
if web_dir.exists() and (web_dir / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    print(f"✅ [System] 前端资源加载成功: {web_dir}")
else:
    print(f"❌ [Error] 找不到前端目录或 index.html")

if __name__ == "__main__":
    # ⚠️ 关键：直接传入 app 对象而非字符串，禁用 reload 确保进程稳定
    uvicorn.run(app, host="127.0.0.1", port=8000)