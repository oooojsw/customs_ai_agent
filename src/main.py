import sys
import os
import webbrowser
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

# 1. 路径修正：确保能找到 src 模块 (这行非常关键)
# 获取当前文件 (main.py) 的目录 -> src
current_file_path = Path(__file__).resolve()
src_dir = current_file_path.parent
project_root = src_dir.parent

# 将项目根目录加入 python path
sys.path.append(str(project_root))

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles # 必须导入这个

from src.api.routes import router as api_router
from src.services.chat_agent import CustomsChatAgent
from src.services.report_agent import ComplianceReporter

# ==========================================
# 🚀 生命周期管理
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n" + "="*50)
    print("🚀 [System] 服务正在启动...")
    
    # 1. 初始化 Chat Agent
    try:
        app.state.agent = CustomsChatAgent()
        print("✅ [System] Chat Agent 挂载成功")
    except Exception as e:
        print(f"❌ [System] Chat Agent 初始化失败: {e}")
        app.state.agent = None

    # 2. 初始化 Report Agent
    try:
        app.state.reporter = ComplianceReporter()
        print("✅ [System] Report Agent 挂载成功")
    except Exception as e:
        print(f"❌ [System] Report Agent 初始化失败: {e}")
        app.state.reporter = None
    
    # 3. 自动打开浏览器 (延迟执行，确保服务已就绪)
    async def open_browser():
        await asyncio.sleep(1.5)
        url = "http://localhost:8000"
        print(f"🌐 [System] 正在尝试打开浏览器: {url}")
        try:
            webbrowser.open(url)
        except Exception as e:
            print(f"⚠️ 无法自动打开浏览器: {e}")
            
    asyncio.create_task(open_browser())
    
    print("="*50 + "\n")
    yield
    print("🛑 [System] 服务正在关闭...")

app = FastAPI(
    title="Customs AI Risk Agent",
    version="2.1",
    lifespan=lifespan 
)

# --- 跨域配置 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 挂载 API 路由 ---
app.include_router(api_router, prefix="/api/v1")

# ==========================================
# 📂 前端静态文件挂载 (修复 404 的核心)
# ==========================================
web_dir = project_root / "web"

print(f"🔍 [Debug] 正在寻找前端目录: {web_dir}")

if web_dir.exists() and (web_dir / "index.html").exists():
    # html=True 表示访问 / 时自动寻找 index.html
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    print(f"✅ [System] 前端页面挂载成功！")
else:
    print(f"❌ [Error] 严重错误：找不到 web 目录或 index.html！")
    print(f"   请确认你的文件夹结构是否为：")
    print(f"   {project_root}")
    print(f"   └── web/")
    print(f"       └── index.html")

if __name__ == "__main__":
    # 启动服务
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)