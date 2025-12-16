import os
import httpx
import asyncio # 引入 asyncio 用于细微控制
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain_core.tools import Tool
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, AIMessageChunk

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
        print("🔗 [System] 初始化 Agent (原生架构 + 网络修正)...")
        
        # 1. 网络配置 (唯一修改的地方：使用 Transport 解决异步流式卡死)
        proxy_url = settings.HTTP_PROXY if hasattr(settings, 'HTTP_PROXY') and settings.HTTP_PROXY else None
        
        # 同步客户端 (保持不变，但建议用 Transport 以防万一)
        if proxy_url:
            sync_transport = httpx.HTTPTransport(proxy=proxy_url, verify=False)
            sync_client = httpx.Client(transport=sync_transport, timeout=60.0)
        else:
            sync_client = httpx.Client(verify=False, timeout=60.0)

        # 异步客户端 (核心修复：必须用 AsyncHTTPTransport，否则 astream 会卡死)
        if proxy_url:
            async_transport = httpx.AsyncHTTPTransport(proxy=proxy_url, verify=False)
            async_client = httpx.AsyncClient(transport=async_transport, timeout=120.0)
        else:
            async_client = httpx.AsyncClient(verify=False, timeout=120.0)

        # 2. LLM (开启流式)
        self.llm = ChatOpenAI(
            model=settings.DEEPSEEK_MODEL,
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            temperature=0.3,
            http_client=sync_client,
            http_async_client=async_client,
            streaming=True
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
                print("✅ 知识库加载成功")
            except: pass
        
        # 4. Agent (完全保留你原本的 create_agent 写法)
        system_prompt = "你是一名海关专家。遇到业务问题必须查库。闲聊直接回。"
        self.agent = create_agent(
            model=self.llm,
            tools=tools,
            system_prompt=system_prompt,
            checkpointer=MEMORY,
        )

        if self.retriever:
            try: self.retriever.invoke("warm-up") 
            except: pass

    async def chat_stream(self, user_input: str, session_id: str = "default_session"):
        """
        最终流式逻辑：兼容 DeepSeek 思考过程 (完全保留原逻辑)
        """
        try:
            print(f"\n👉 [Request] {user_input}")
            yield f"data: {{\"type\": \"thinking\", \"content\": \"连接建立，准备生成...\"}}\n\n"
            
            config = {"configurable": {"thread_id": session_id}}
            has_sent_content = False

            # 使用 stream_mode="messages"
            async for msg, metadata in self.agent.astream(
                {"messages": [HumanMessage(content=user_input)]},
                config=config,
                stream_mode="messages"
            ):
                # -------------------------------------------------
                # 1. 捕捉 AI 消息 (包括思考过程 + 正文)
                # -------------------------------------------------
                if isinstance(msg, AIMessageChunk):
                    # --- A. 尝试获取 DeepSeek 的思考内容 (Reasoning) ---
                    # DeepSeek 的思考内容通常在 additional_kwargs 中
                    reasoning = msg.additional_kwargs.get('reasoning_content', '')
                    if reasoning:
                        # 这是一个思考片段
                        safe_reason = reasoning.replace("\n", "\\n").replace('"', '\\"')
                        # 推送给前端，类型为 'thinking'
                        yield f"data: {{\"type\": \"thinking\", \"content\": \"{safe_reason}\"}}\n\n"
                    
                    # --- B. 尝试获取工具调用 (Tool Calls) ---
                    if msg.tool_call_chunks:
                        # 只要有工具调用的意图，就发一个信号保持连接活跃
                        yield f"data: {{\"type\": \"thinking\", \"content\": \"正在规划工具调用...\"}}\n\n"

                    # --- C. 捕捉正文内容 (Content) ---
                    if msg.content:
                        has_sent_content = True
                        safe_content = msg.content.replace("\n", "\\n").replace('"', '\\"')
                        yield f"data: {{\"type\": \"answer\", \"content\": \"{safe_content}\"}}\n\n"
                    
                    # 关键：手动让出控制权，防止 asyncio 循环过紧导致 buffer
                    await asyncio.sleep(0)

                # -------------------------------------------------
                # 2. 捕捉工具执行结果
                # -------------------------------------------------
                elif isinstance(msg, ToolMessage):
                    print(f"✅ 工具 {msg.name} 返回")
                    yield f"data: {{\"type\": \"thinking\", \"content\": \"查询完毕，正在整理...\"}}\n\n"

            # -------------------------------------------------
            # 3. 保底
            # -------------------------------------------------
            if not has_sent_content:
                print("⚠️ 启用保底...")
                state = await self.agent.aget_state(config)
                if state.values.get("messages"):
                    last = state.values["messages"][-1]
                    if isinstance(last, AIMessage) and last.content:
                        safe = last.content.replace("\n", "\\n").replace('"', '\\"')
                        yield f"data: {{\"type\": \"answer\", \"content\": \"{safe}\"}}\n\n"

        except Exception as e:
            print(f"❌ Error: {e}")
            yield f"data: {{\"type\": \"error\", \"content\": \"{str(e)}\"}}\n\n"