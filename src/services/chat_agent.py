import os
import httpx
import asyncio
import json
import sys
import io
from typing import List, Optional, Any

# ============================================================
# ⬇️⬇️⬇️ 【环境配置 - 遵从 1222.txt 修复经验】 ⬇️⬇️⬇️
# ============================================================
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
os.environ['HF_HUB_DISABLE_SSL_VERIFY'] = '1'
os.environ['CURL_CA_BUNDLE'] = ''

# 修复 Windows 控制台编码问题，确保控制台输出中文不乱码
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from langgraph.prebuilt import create_react_agent 
from langchain_openai import ChatOpenAI
from langchain_core.tools import Tool
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

# 导入项目配置和业务组件
from src.config.loader import settings
from src.core.orchestrator import RiskAnalysisOrchestrator

# 知识库模块容错处理
try:
    from src.services.knowledge_base import KnowledgeBase
    print("[ChatAgent] 成功加载知识库模块 (RAG System Ready)")
except ImportError as e:
    print(f"[Warning] 知识库模块加载失败: {e}")
    KnowledgeBase = None

# 初始化内存检查点，用于维护多轮对话状态
MEMORY = InMemorySaver()

class CustomsChatAgent:
    def __init__(self, kb=None, llm_config: dict = None):
        """
        初始化海关智能对话代理 (v3.1.3 深度集成版)
        已修复 Tool.__init__ 缺失 func 参数导致的 500 错误。
        """
        print("[System] 正在初始化全能智能体 (DeepSeek Streaming + Audit Tool)...")

        # --- 1. 获取并格式化 LLM 配置 ---
        if llm_config:
            self.config = llm_config
            print(f"[ChatAgent] 使用动态 LLM 配置: {self.config.get('model')}")
        else:
            self.config = {
                'api_key': settings.DEEPSEEK_API_KEY,
                'base_url': settings.DEEPSEEK_BASE_URL,
                'model': settings.DEEPSEEK_MODEL,
                'temperature': 0.3,
            }
            print("[ChatAgent] 使用 .env 默认配置")

        # --- 2. 网络客户端配置 ---
        proxy_url = settings.HTTP_PROXY if hasattr(settings, 'HTTP_PROXY') and settings.HTTP_PROXY else None
        if proxy_url:
            async_transport = httpx.AsyncHTTPTransport(proxy=proxy_url, verify=False)
            self._async_client = httpx.AsyncClient(transport=async_transport, timeout=120.0)
        else:
            self._async_client = httpx.AsyncClient(verify=False, timeout=120.0)

        # --- 3. 初始化核心 LLM ---
        self.llm = ChatOpenAI(
            model=self.config['model'],
            api_key=self.config['api_key'],
            base_url=self.config['base_url'],
            temperature=self.config.get('temperature', 0.3),
            http_async_client=self._async_client,
            streaming=True,
            model_kwargs={
                "stream": True,
                "parallel_tool_calls": False, # DeepSeek 专用流式补丁
            }
        )

        # --- 4. 构建工具集 ---
        self.tools = []

        # 定义异步审单函数
        async def audit_declaration_tool(raw_data: str) -> str:
            """
            当用户提供一段报关单数据并要求审核风险时，必须调用此工具。输入应为完整的报关单原文。
            """
            print(f"🚀 [Tool Call] 智能审单引擎正在执行...")
            orch = RiskAnalysisOrchestrator(llm_config=self.config)
            findings = []
            
            async for event_str in orch.analyze_stream(raw_data, language="zh"):
                if not event_str.startswith("data: "): continue
                try:
                    data = json.loads(event_str[6:])
                    if data["type"] == "step_result":
                        status_symbol = "✅" if data["status"] == "pass" else "❌"
                        findings.append(f"{status_symbol} {data['rule_id']}: {data['message']}")
                    elif data["type"] == "complete":
                        findings.append(f"\n【审计最终评估】\n{data['summary']}")
                except: continue
            
            return "\n".join(findings) if findings else "审单引擎未产生有效结论。"

        # 【修复点】使用 Tool 时显式提供 func (同步占位) 和 coroutine (异步实现)
        self.tools.append(Tool(
            name="audit_declaration",
            func=lambda x: "此工具仅支持异步环境运行", # 占位，防止初始化报错
            coroutine=audit_declaration_tool,      # 实际异步逻辑
            description="全自动报关风险扫描工具。能检测要素完整性、敏感物项、价格逻辑、归类一致性及单证一致性。"
        ))

        # RAG 知识库检索工具
        if KnowledgeBase:
            self.kb = kb if kb else KnowledgeBase()
            self.retriever = self.kb.get_retriever()

            def retrieve_docs(query: str) -> str:
                if not self.retriever: return "知识库未就绪。"
                try:
                    print(f"🔍 [Tool Call] 正在检索知识库: {query}")
                    docs = self.retriever.invoke(query)
                    if not docs: return "本地法规库中未找到直接相关的依据。"
                    return "\n\n".join([doc.page_content for doc in docs])
                except Exception as e:
                    return f"知识库检索异常: {str(e)}"

            self.tools.append(Tool(
                name="search_customs_regulations",
                func=retrieve_docs, 
                description="查询海关相关法规、政策文件、HS编码解释。遇到专业名词或法律疑问时必须使用。"
            ))

        # --- 5. 构建图智能体 ---
        self.system_prompt_text = """
        你是一名智慧口岸AI专家，负责报关咨询和自动审单。
        工作守则：
        1. 审计：用户粘贴报关单后，主动调用 `audit_declaration`。
        2. 咨询：法律疑问调用 `search_customs_regulations`。
        3. 协同：审单发现风险后，可检索法规条文来支撑你的解释。
        4. 语言：严禁跳出用户当前使用的语言（中文或越南语）。
        """

        self.agent = create_react_agent(
            model=self.llm,
            tools=self.tools,
            checkpointer=MEMORY,
        )
        print(f"[ChatAgent] 智能体就绪，工具列表: {[t.name for t in self.tools]}")

    async def chat_stream(self, user_input: str, session_id: str = "default_session", language: str = "zh"):
        """
        核心流式分发器
        """
        try:
            print(f"\n👉 [Request] {user_input}")
            
            lang_inst = self._get_language_instruction(language)
            input_messages = [
                SystemMessage(content=f"{self.system_prompt_text}\n\n{lang_inst}"),
                HumanMessage(content=user_input)
            ]

            config = {"configurable": {"thread_id": session_id}}
            has_sent_content = False

            # 使用 astream_events v2 实现极致打字机效果
            async for event in self.agent.astream_events(
                {"messages": input_messages},
                config=config,
                version="v2" 
            ):
                event_type = event["event"]
                
                if event_type == "on_chat_model_stream":
                    chunk = event["data"].get("chunk")
                    if not chunk: continue
                    
                    # 提取正文
                    content = getattr(chunk, 'content', '')
                    if content:
                        has_sent_content = True
                        yield f"data: {json.dumps({'type': 'answer', 'content': content}, ensure_ascii=False)}\n\n"
                    
                    # 提取思考流
                    add_kwargs = getattr(chunk, 'additional_kwargs', {})
                    reasoning = add_kwargs.get('reasoning_content', '')
                    if reasoning:
                        yield f"data: {json.dumps({'type': 'thinking', 'content': reasoning}, ensure_ascii=False)}\n\n"

                elif event_type == "on_tool_start":
                    t_name = event["name"]
                    yield f"data: {json.dumps({'type': 'thinking', 'content': f'专家正在使用工具 [{t_name}] 深度分析中...'}, ensure_ascii=False)}\n\n"

            if not has_sent_content:
                # 保底
                state = await self.agent.aget_state(config)
                if state.values and "messages" in state.values:
                    last_msg = state.values["messages"][-1]
                    if isinstance(last_msg, AIMessage) and last_msg.content:
                        yield f"data: {json.dumps({'type': 'answer', 'content': last_msg.content}, ensure_ascii=False)}\n\n"

        except Exception as e:
            print(f"💥 [Fatal] {str(e)}")
            import traceback
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'content': f'系统异常: {str(e)}'}, ensure_ascii=False)}\n\n"

    def _get_language_instruction(self, language: str) -> str:
        names = {"zh": "简体中文", "vi": "Tiếng Việt"}
        target = names.get(language, "简体中文")
        return f"【重要设置】当前语言为 {target}。你必须以此语言进行回复。"

if __name__ == "__main__":
    print("Chat Agent Service defined.")