import os
import httpx
import asyncio
import json
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain_core.tools import Tool
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

# 引入 create_react_agent (LangGraph 推荐方式)
from langgraph.prebuilt import create_react_agent

from src.config.loader import settings

# --- 环境配置 ---
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HUB_DISABLE_SSL_VERIFY'] = '1'
os.environ['CURL_CA_BUNDLE'] = ''

# 知识库容错
try:
    from src.services.knowledge_base import KnowledgeBase
except ImportError:
    KnowledgeBase = None

MEMORY = InMemorySaver()

class CustomsChatAgent:
    def __init__(self):
        print("🔗 [System] 初始化 Agent (DeepSeek 深度优化版)...")
        
        # 1. 网络配置
        proxy_url = settings.HTTP_PROXY if hasattr(settings, 'HTTP_PROXY') and settings.HTTP_PROXY else None
        
        if proxy_url:
            async_transport = httpx.AsyncHTTPTransport(proxy=proxy_url, verify=False)
            async_client = httpx.AsyncClient(transport=async_transport, timeout=120.0)
        else:
            async_client = httpx.AsyncClient(verify=False, timeout=120.0)

        # 2. LLM 初始化 (严格遵循 DeepSeek 文档)
        self.llm = ChatOpenAI(
            model=settings.DEEPSEEK_MODEL,
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            temperature=0.3,
            http_async_client=async_client,
            streaming=True, # 必须开启
            model_kwargs={
                # 显式开启流式，防止被 Agent 覆盖
                "stream": True,
                # 【关键】禁用并行工具调用，DeepSeek 文档虽未明说，但实测能减少服务端缓冲
                "parallel_tool_calls": False,
                # 减少不必要的数据传输
                "stream_options": {"include_usage": False} 
            }
        )

        # 3. 工具
        tools = []
        self.retriever = None
        if KnowledgeBase:
            try:
                self.kb = KnowledgeBase()
                self.retriever = self.kb.get_retriever()
                
                def retrieve_docs(query: str) -> str:
                    if not self.retriever: return "知识库不可用。"
                    try:
                        docs = self.retriever.invoke(query)
                        return "\n\n".join([doc.page_content for doc in docs]) if docs else "未找到。"
                    except Exception as e:
                        return f"检索错: {e}"

                tools.append(Tool(
                    name="search_customs_regulations",
                    func=retrieve_docs,
                    description="查询海关法规、政策、HS编码或报关流程。"
                ))
            except: pass
        
        # 4. Agent 构建 (使用 LangGraph)
        self.agent = create_react_agent(
            model=self.llm,
            tools=tools,
            # prompt="你是一名海关专家...", # 新版 LangGraph 这里用 state_modifier
            checkpointer=MEMORY,
        )

    async def chat_stream(self, user_input: str, session_id: str = "default_session"):
        """
        使用 astream_events 监听底层 LLM 事件，绕过 Agent 的缓冲
        """
        print(f"\n👉 [Request] {user_input}")
        yield f"data: {{\"type\": \"thinking\", \"content\": \"连接建立...\"}}\n\n"
        
        config = {"configurable": {"thread_id": session_id}}
        has_sent_content = False

        try:
            # 【核心修改】使用 astream_events (v2)
            # 它可以穿透 Graph 的层级，直接捕获最底层的 on_chat_model_stream 事件
            # 无论 Agent 逻辑怎么卡，只要 LLM 吐字，这里就能收到！
            async for event in self.agent.astream_events(
                {"messages": [HumanMessage(content=user_input)]},
                config=config,
                version="v2"
            ):
                event_type = event["event"]
                
                # 1. 监听 LLM 的流式输出 (最核心的部分)
                if event_type == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    
                    # A. 捕获正文内容 (Content)
                    if chunk.content:
                        has_sent_content = True
                        safe_content = chunk.content.replace("\n", "\\n").replace('"', '\\"')
                        yield f"data: {{\"type\": \"answer\", \"content\": \"{safe_content}\"}}\n\n"
                    
                    # B. 捕获 DeepSeek 的思考过程 (Reasoning)
                    # DeepSeek 的 thinking 通常在 additional_kwargs 里
                    reasoning = chunk.additional_kwargs.get('reasoning_content', '')
                    if reasoning:
                        safe_reason = reasoning.replace("\n", "\\n").replace('"', '\\"')
                        yield f"data: {{\"type\": \"thinking\", \"content\": \"{safe_reason}\"}}\n\n"
                    
                    # 极短休眠，确保 I/O 不阻塞
                    await asyncio.sleep(0)

                # 2. 监听工具开始调用 (用于前端显示状态)
                elif event_type == "on_tool_start":
                    tool_name = event["name"]
                    yield f"data: {{\"type\": \"thinking\", \"content\": \"正在调用工具: {tool_name}...\"}}\n\n"

                # 3. 监听工具结束
                elif event_type == "on_tool_end":
                    yield f"data: {{\"type\": \"thinking\", \"content\": \"工具调用完成，正在生成回复...\"}}\n\n"

            # 保底逻辑 (如果事件流没有捕获到任何内容)
            if not has_sent_content:
                print("⚠️ 事件流未捕获内容，尝试读取最终状态...")
                state = await self.agent.aget_state(config)
                if state.values.get("messages"):
                    last = state.values["messages"][-1]
                    if isinstance(last, AIMessage) and last.content:
                        safe = last.content.replace("\n", "\\n").replace('"', '\\"')
                        yield f"data: {{\"type\": \"answer\", \"content\": \"{safe}\"}}\n\n"

        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback
            traceback.print_exc()
            yield f"data: {{\"type\": \"error\", \"content\": \"{str(e)}\"}}\n\n"