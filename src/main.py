import sys
import os
from contextlib import asynccontextmanager

# 路径修正
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import router as api_router
from src.services.chat_agent import CustomsChatAgent
# 【新增】导入 Reporter 类
from src.services.report_agent import ComplianceReporter
from src.config.loader import settings

# ==========================================
# 🚀 生命周期管理 (单例模式的核心)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n🚀 [System] 服务正在启动，初始化全局 AI 引擎...")
    
    # 1. 初始化 Chat Agent
    try:
        app.state.agent = CustomsChatAgent()
        print("✅ [System] Chat Agent 挂载成功！")
    except Exception as e:
        print(f"❌ [System] Chat Agent 初始化失败: {e}")
        app.state.agent = None

    # 2. 【新增】初始化 Report Agent
    try:
        app.state.reporter = ComplianceReporter()
        print("✅ [System] Report Agent 挂载成功！")
    except Exception as e:
        print(f"❌ [System] Report Agent 初始化失败: {e}")
        app.state.reporter = None
    
    yield  # 服务运行中...
    
    print("🛑 [System] 服务正在关闭...")

# 初始化 FastAPI 应用
app = FastAPI(
    title="Customs AI Risk Agent",
    description="基于大模型的海关智能审单与风险决策系统",
    version="2.1",
    lifespan=lifespan 
)

# --- 跨域配置 (CORS) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 挂载路由 ---
app.include_router(api_router, prefix="/api/v1")

if __name__ == "__main__":
    print("🚀 海关AI决策系统正在启动...")
    print("📄 API 文档地址: http://localhost:8000/docs")
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)