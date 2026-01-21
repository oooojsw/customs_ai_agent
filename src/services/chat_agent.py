import os
import httpx
import asyncio
import json

# ============================================================
# ⬇️⬇️⬇️ 【环境配置】 ⬇️⬇️⬇️
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HUB_DISABLE_SSL_VERIFY'] = '1'
os.environ['CURL_CA_BUNDLE'] = ''
# ============================================================

# 修复 Windows 控制台编码问题
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from langgraph.prebuilt import create_react_agent 
from langchain_openai import ChatOpenAI
from langchain_core.tools import Tool
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from src.config.loader import settings

# 知识库容错
try:
    from src.services.knowledge_base import KnowledgeBase
    print("[ChatAgent] KnowledgeBase module loaded")
except ImportError as e:
    print(f"[Warning] KnowledgeBase import failed: {e}")
    KnowledgeBase = None

MEMORY = InMemorySaver()

class CustomsChatAgent:
    def __init__(self, kb=None, llm_config: dict = None):
        """
        初始化海关咨询对话Agent

        Args:
            kb: 可选的KnowledgeBase实例。如果不提供，将创建新实例。
               推荐从main.py传入全局共享的实例，避免重复初始化。
            llm_config: 可选的 LLM 配置字典 {
                'api_key': str,
                'base_url': str,
                'model': str,
                'temperature': float
            }
        """
        print("[System] Initializing Agent (DeepSeek compatible)...")

        # --- 1. 获取 LLM 配置 ---
        if llm_config:
            # 使用传入的配置
            config = llm_config
            print("[ChatAgent] 使用传入的 LLM 配置")
        else:
            # 使用默认 .env 配置
            config = {
                'api_key': settings.DEEPSEEK_API_KEY,
                'base_url': settings.DEEPSEEK_BASE_URL,
                'model': settings.DEEPSEEK_MODEL,
                'temperature': 0.3,
            }
            print("[ChatAgent] 使用 .env 默认配置")

        # --- 2. 网络客户端配置 ---
        proxy_url = settings.HTTP_PROXY if hasattr(settings, 'HTTP_PROXY') and settings.HTTP_PROXY else None

        # 创建客户端
        if proxy_url:
            async_transport = httpx.AsyncHTTPTransport(proxy=proxy_url, verify=False)
            async_client = httpx.AsyncClient(transport=async_transport, timeout=120.0)
        else:
            async_client = httpx.AsyncClient(verify=False, timeout=120.0)

        # --- 3. 初始化 LLM (关键配置) ---
        self.llm = ChatOpenAI(
            model=config['model'],
            api_key=config['api_key'],
            base_url=config['base_url'],
            temperature=config.get('temperature', 0.3),
            http_async_client=async_client,
            streaming=True,
            # 【核心修复】DeepSeek 绑定工具后必须禁用并行调用才能流式输出
            model_kwargs={
                "stream": True,
                "parallel_tool_calls": False,
                "stream_options": {"include_usage": False}
            }
        )

        # --- 3. 工具配置 ---
        tools = []
        self.retriever = None
        if KnowledgeBase:
            try:
                # 优先使用传入的kb实例
                if kb is not None:
                    self.kb = kb
                    print("[ChatAgent] [OK] 使用全局共享的KnowledgeBase实例")
                else:
                    # 回退方案：创建新实例（可能触发重建）
                    print("[ChatAgent] [WARNING] 未传入kb参数，将创建新的KnowledgeBase实例")
                    print("[ChatAgent] [TIP] 建议从main.py传入全局kb实例以避免重复初始化")
                    self.kb = KnowledgeBase()

                self.retriever = self.kb.get_retriever()

                def retrieve_docs(query: str) -> str:
                    if not self.retriever: return "知识库未初始化。"
                    try:
                        print(f"🔍 [RAG] 正在检索: {query}")
                        docs = self.retriever.invoke(query)
                        return "\n\n".join([doc.page_content for doc in docs]) if docs else "未找到相关内容。"
                    except Exception as e:
                        return f"检索失败: {str(e)}"

                retriever_tool = Tool(
                    name="search_customs_regulations",
                    func=retrieve_docs,
                    description="查询海关法规、政策、HS编码或报关流程。涉及此类问题必须使用此工具。"
                )
                tools.append(retriever_tool)
                print("[ChatAgent] Knowledge base tools loaded")
            except Exception as e:
                print(f"❌ 知识库加载失败: {e}")
                self.kb = None
        
        # --- 4. 保存系统提示词 (稍后在对话时注入) ---
        self.system_prompt_text = """
        你是一名专业、严谨的海关法规咨询专家。
        规则:
        1. 必须优先使用 `search_customs_regulations` 工具查询专业问题。
        2. 闲聊或普通问候可以直接回答，无需查库。
        3. 回答必须简洁、专业。
        """

        # --- 5. 创建 Agent (最简参数，避开版本冲突) ---
        # 我们不在这里传 system_prompt/state_modifier，避免报错
        self.agent = create_react_agent(
            model=self.llm,
            tools=tools,
            checkpointer=MEMORY,
        )
        print("[ChatAgent] Agent construction complete")

        # 预热
        if self.retriever:
            try:
                self.retriever.invoke("warm-up") 
            except: pass

    async def chat_stream(self, user_input: str, session_id: str = "default_session", language: str = "zh"):
        """
        执行 Agent 流式调用
        """
        try:
            print(f"\n👉 [Request] {user_input}")
            yield f"data: {json.dumps({'type': 'thinking', 'content': '智能体正在思考...'}, ensure_ascii=False)}\n\n"

            config = {"configurable": {"thread_id": session_id}}
            has_sent_content = False

            # 【构建消息列表】手动将 SystemPrompt 插在最前面，并注入语言指令
            language_instruction = self._get_language_instruction(language)
            enhanced_system_prompt = f"{self.system_prompt_text}\n\n{language_instruction}"

            input_messages = [
                SystemMessage(content=enhanced_system_prompt),
                HumanMessage(content=user_input)
            ]

            # 使用 astream_events v2 监听底层 Token
            async for event in self.agent.astream_events(
                {"messages": input_messages}, # 传入包含系统提示的消息列表
                config=config,
                version="v2" 
            ):
                event_type = event["event"]
                
                # 1. 监听 LLM 的流式输出
                if event_type == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    
                    # A. 捕获正文内容
                    if chunk.content:
                        has_sent_content = True
                        # 使用 json.dumps 自动处理转义，不要手动 replace
                        payload = {"type": "answer", "content": chunk.content}
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    
                    # B. 捕获 DeepSeek 的思考过程
                    reasoning = chunk.additional_kwargs.get('reasoning_content', '')
                    if reasoning:
                        payload = {"type": "thinking", "content": reasoning}
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

                    await asyncio.sleep(0.01)
                    
                # 2. 监听工具开始调用
                elif event_type == "on_tool_start":
                    tool_name = event["name"]
                    print(f"🛠️ [工具] {tool_name} 启动")
                    yield f"data: {json.dumps({'type': 'thinking', 'content': f'正在调用工具[{tool_name}]...'}, ensure_ascii=False)}\n\n"

                # 3. 监听工具结束
                elif event_type == "on_tool_end":
                    print(f"[ChatAgent] Tool complete")
                    yield f"data: {json.dumps({'type': 'thinking', 'content': '查询完成，正在生成回答...'}, ensure_ascii=False)}\n\n"

            # =======================================================
            # 保底逻辑
            # =======================================================
            if not has_sent_content:
                print("⚠️ [警告] 流式未触发，尝试获取最终状态...")
                final_state = await self.agent.aget_state(config)
                if final_state.values and "messages" in final_state.values:
                    last_msg = final_state.values["messages"][-1]
                    if isinstance(last_msg, AIMessage) and last_msg.content:
                        payload = {"type": "answer", "content": last_msg.content}
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

            print("[ChatAgent] Request complete")

        except Exception as e:
            print(f"❌ [Error] {e}")
            import traceback
            traceback.print_exc()
            payload = {"type": "error", "content": f"系统错误: {str(e)}"}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def _get_language_instruction(self, language: str) -> str:
        """
        根据语言代码生成对应的输出指令
        """
        # 语言代码映射到实际语言名称
        language_names = {
            "zh": "简体中文 (Chinese)",
            "vi": "Tiếng Việt (越南语)"
        }
        language_name = language_names.get(language, language_names["zh"])

        return f"""【重要语言设置】当前用户设置的语言是 {language_name}，语言代码为 {language}。
【严格要求】你必须使用 {language_name} 回答所有问题，所有输出必须是 {language_name}。
这是用户界面语言设置，你的回答将直接显示给前端用户，请务必使用 {language_name}。"""