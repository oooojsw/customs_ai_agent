import os
import httpx
import asyncio
import json
import sys
import io
import requests
import time
import re
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

# 技能管理器模块容错处理
try:
    from src.services.skill_manager import SkillManager
    print("[ChatAgent] 成功加载技能管理器模块")
except ImportError as e:
    print(f"[Warning] 技能管理器模块加载失败: {e}")
    SkillManager = None

# 脚本执行器模块容错处理
try:
    from src.services.script_executor import ScriptExecutor
    print("[ChatAgent] 成功加载脚本执行器模块")
except ImportError as e:
    print(f"[Warning] 脚本执行器模块加载失败: {e}")
    ScriptExecutor = None

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

        # ========== 货币代码映射表（用于汇率查询工具） ==========
        self.CURRENCY_MAP = {
            # 中文常见货币名称
            "美元": "USD", "人民币": "CNY", "欧元": "EUR", "英镑": "GBP", "日元": "JPY",
            "港币": "HKD", "澳元": "AUD", "加元": "CAD", "瑞郎": "CHF", "卢布": "RUB",
            "韩元": "KRW", "新币": "SGD", "纽元": "NZD", "越南盾": "VND",

            # 英文货币名称
            "dollar": "USD", "usd": "USD",
            "yuan": "CNY", "cny": "CNY", "rmb": "CNY",
            "euro": "EUR", "eur": "EUR",
            "pound": "GBP", "gbp": "GBP",
            "yen": "JPY", "jpy": "JPY",
            "hkd": "HKD", "aud": "AUD", "cad": "CAD", "chf": "CHF",
            "vnd": "VND",

            # ISO代码
            "USD": "USD", "CNY": "CNY", "EUR": "EUR", "GBP": "GBP", "JPY": "JPY",
            "HKD": "HKD", "AUD": "AUD", "CAD": "CAD", "CHF": "CHF", "KRW": "KRW",
            "SGD": "SGD", "NZD": "NZD", "VND": "VND"
        }

        # ========== 汇率查询辅助函数 ==========
        def _fetch_exchange_rate(from_currency: str, to_currency: str) -> dict:
            """调用每刻报销API查询汇率"""
            url = 'https://openapi-ng.maycur.com/api/openapi/currency/sys-exchange-rate'

            # 获取当前时间戳（毫秒级）
            timestamp_ms = int(time.time() * 1000)

            payload = {
                'data': {
                    'from': from_currency,
                    'to': to_currency,
                    'effectiveDate': timestamp_ms
                }
            }

            # 使用代理（如果配置了）
            proxies = None
            if hasattr(settings, 'HTTP_PROXY') and settings.HTTP_PROXY:
                proxies = {
                    'http': settings.HTTP_PROXY,
                    'https': settings.HTTP_PROXY
                }

            try:
                print(f"🌐 [汇率API] 正在调用: {from_currency} → {to_currency}")
                response = requests.post(
                    url,
                    json=payload,
                    headers={'Content-Type': 'application/json'},
                    proxies=proxies,
                    timeout=10
                )
                print(f"🌐 [汇率API] 响应状态: {response.status_code}")

                if response.status_code == 404:
                    return {
                        'success': False,
                        'error': '汇率查询服务暂时不可用（API返回404），请稍后重试'
                    }

                result = response.json()
                print(f"🌐 [汇率API] 响应内容: {str(result)[:200]}")

                if result.get('success') and result.get('data'):
                    rate_data = result['data'][0]
                    return {
                        'success': True,
                        'rate': rate_data['exchangeRate'],
                        'from': rate_data['fromCurrency'],
                        'to': rate_data['toCurrency'],
                        'source': '中国银行' if rate_data['rateType'] == 'SYSTEM' else '自定义',
                        'timestamp': rate_data['startedAt']
                    }
                else:
                    return {'success': False, 'error': result.get('message', '未找到汇率数据')}

            except requests.exceptions.Timeout:
                return {'success': False, 'error': '汇率查询超时，请稍后重试'}
            except requests.exceptions.ConnectionError:
                return {'success': False, 'error': '无法连接到汇率服务，请检查网络连接'}
            except Exception as e:
                print(f"❌ [汇率API] 异常: {str(e)}")
                return {'success': False, 'error': f'汇率查询失败: {str(e)}'}

        def _format_exchange_rate_result(data: dict, amount: float = None) -> str:
            """格式化汇率查询结果为易读的字符串"""
            if not data['success']:
                return f"❌ 汇率查询失败：{data.get('error', '未知错误')}"

            rate = data['rate']
            from_curr = data['from']
            to_curr = data['to']
            source = data['source']

            # 基础汇率信息
            lines = [
                f"💱 汇率查询结果",
                f"{'─' * 20}",
                f"货币对: {from_curr} → {to_curr}",
                f"汇率: 1 {from_curr} = {rate:.4f} {to_curr}",
                f"数据来源: {source}",
            ]

            # 如果提供了金额，计算兑换结果
            if amount is not None:
                converted = amount * rate
                lines.append(f"\n💰 换算结果:")
                lines.append(f"{amount:.2f} {from_curr} = {converted:.2f} {to_curr}")

            return "\n".join(lines)

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

        # --- 4.5 初始化技能管理器 ---
        if SkillManager:
            self.skill_manager = SkillManager()
            skills_registry = self.skill_manager.get_skill_registry_text()
            print(f"[ChatAgent] 技能清单已加载:\n{skills_registry}")
        else:
            self.skill_manager = None
            skills_registry = "技能系统未就绪"

        # --- 4.6 初始化脚本执行器（L4 层） ---
        if ScriptExecutor:
            self.script_executor = ScriptExecutor(timeout=10)
            print("[ChatAgent] L4脚本执行器已就绪")
        else:
            self.script_executor = None

        # ========== 汇率查询工具 ==========
        def query_exchange_rate_tool(query: str) -> str:
            """
            查询中国银行实时汇率（数据来源：每刻报销API）

            支持的自然语言输入示例：
            - "USD到CNY的汇率"
            - "100美元等于多少人民币"
            - "欧元兑人民币汇率"
            """
            # 1. 提取货币代码
            from_curr = None
            to_curr = None
            amount = None

            # 提取金额（数字）
            amount_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:元|美元|欧元|英镑|日元|人民币|USD|EUR|GBP|JPY|CNY|HKD|AUD|CAD)', query)
            if amount_match:
                amount = float(amount_match.group(1))

            # 提取货币代码
            query_lower = query.lower()
            for name, code in self.CURRENCY_MAP.items():
                if name.lower() in query_lower:
                    if from_curr is None:
                        from_curr = code
                    elif to_curr is None and code != from_curr:
                        to_curr = code

            # 如果只找到一种货币，默认兑CNY
            if from_curr and not to_curr:
                to_curr = "CNY" if from_curr != "CNY" else "USD"

            # 如果都没找到，返回提示
            if not from_curr:
                return "❌ 无法识别货币类型，请明确说明要查询的货币（如：美元、欧元、人民币等）"

            # 2. 调用API查询汇率
            print(f"💱 [Tool Call] 正在查询汇率: {from_curr} → {to_curr}")
            result = _fetch_exchange_rate(from_curr, to_curr)

            # 3. 格式化结果
            return _format_exchange_rate_result(result, amount)

        # 汇率查询工具（暂时禁用 - 需要API认证信息）
        # self.tools.append(Tool(
        #     name="query_exchange_rate",
        #     func=query_exchange_rate_tool,
        #     description="查询实时汇率信息（数据来源：中国银行）。当用户询问货币汇率、货币兑换、汇率换算等问题时必须调用此工具。支持中英文货币名称输入，如'USD到CNY'、'美元兑人民币'、'100美元等于多少人民币'。"
        # ))

        # ========== 技能调用工具（三级加载架构） ==========
        async def use_skill_tool(skill_name: str, query: str = "") -> str:
            """
            激活特定技能以获取详细操作指导（L2 加载）
            :param skill_name: 技能名称（必须精确匹配技能列表）
            :param query: 用户的具体问题
            """
            if not self.skill_manager:
                return "技能系统未就绪"

            print(f"🔧 [Tool Call] L2加载: {skill_name}")

            # L2 加载：读取技能手册 + 资源列表提示
            skill_content = self.skill_manager.load_skill_content(skill_name)

            if skill_content.startswith("错误") or skill_content.startswith("加载技能失败"):
                return skill_content

            response = f"""你已激活【{skill_name}】技能。

请根据以下操作手册处理用户问题：

---
{skill_content}
---

用户问题: {query}

【重要】如果上述手册中提到需要参考某些数据文件，请调用 read_skill_resource 工具。"""

            return response

        # L3 资源读取工具
        async def read_skill_resource_tool(input_str: str) -> str:
            """
            读取技能关联的资源文件（L3 加载）

            使用场景：
            - 已通过 use_skill 激活某个技能
            - 技能手册中提到"参考 XX 数据文件"
            - 需要查看具体数据以回答用户问题

            输入格式："<skill_name>|<file_name>"
            """
            if not self.skill_manager:
                return "技能系统未就绪"

            try:
                parts = input_str.split('|')
                if len(parts) != 2:
                    return "错误：参数格式应为 'skill_name|file_name'"

                skill_name, file_name = parts
                print(f"📄 [Tool Call] L3加载资源: {skill_name}/{file_name}")

                # L3 加载：读取资源文件
                resource_content = self.skill_manager.get_resource_content(skill_name, file_name)
                return resource_content

            except Exception as e:
                return f"读取资源文件失败: {str(e)}"

        # 资源列表查询工具
        async def list_skill_resources_tool(skill_name: str) -> str:
            """
            列出技能的所有可用资源文件

            输入格式：技能名称（如 "tax_calculator"）
            """
            if not self.skill_manager:
                return "技能系统未就绪"

            result = self.skill_manager.list_resources(skill_name)

            if 'error' in result:
                return result['error']

            if not result['files']:
                return f"技能【{skill_name}】无资源文件"

            # 格式化输出
            lines = [f"📁 技能【{skill_name}】的资源文件夹: {result['resources_dir']}", "\n可用文件:"]
            for file_info in result['files']:
                size_kb = file_info['size'] / 1024
                lines.append(f"  - {file_info['name']} ({file_info['type']}, {size_kb:.2f} KB)")

            return "\n".join(lines)

        self.tools.append(Tool(
            name="use_skill",
            func=lambda x: "此工具仅支持异步环境运行",
            coroutine=use_skill_tool,
            description=f"""激活特定技能以获取详细操作指导。

可用技能列表：
{skills_registry}

使用时机：当用户问题与上述某个技能的描述高度匹配时，调用此工具。

参数说明：
- skill_name: 技能名称（必须精确匹配上述列表）
- query: 用户的具体问题或上下文
"""
        ))

        self.tools.append(Tool(
            name="read_skill_resource",
            func=lambda x: "此工具仅支持异步环境运行",
            coroutine=read_skill_resource_tool,
            description="""读取技能关联的资源文件（CSV/JSON/TXT等）。

使用时机：当通过 use_skill 激活技能后，技能手册中提到需要参考某个数据文件时。

参数格式："<技能名称>|<文件名>"
示例："tax_calculator|tax_rates.csv"

注意：技能名称和文件名用竖线"|"分隔，不要使用空格或其他分隔符。
"""
        ))

        self.tools.append(Tool(
            name="list_skill_resources",
            func=lambda x: "此工具仅支持异步环境运行",
            coroutine=list_skill_resources_tool,
            description="""列出某个技能的所有可用资源文件。

使用时机：在激活技能后，想了解该技能有哪些辅助数据时。

参数说明：
- skill_name: 技能名称
"""
        ))

        # ========== L4 脚本执行工具 ==========
        async def run_skill_script_tool(input_str: str) -> str:
            """
            执行技能包中的 Python 脚本进行复杂计算或处理

            使用场景：
            - 技能手册中明确提到需要"运行脚本"或"调用计算程序"
            - 需要进行复杂的数学计算（如关税、汇率换算）
            - 需要处理数据转换或格式化

            输入格式："<skill_name>|<script_name>|<args_json>"
            示例："tax_calculator|calculate_duty.py|{\"cif_price\": 10000, \"hs_code\": \"85423100\"}"
            """
            if not self.skill_manager or not self.script_executor:
                return "脚本执行系统未就绪"

            try:
                parts = input_str.split('|')
                if len(parts) != 3:
                    return "错误：参数格式应为 'skill_name|script_name|args_json'"

                skill_name, script_name, args_json = parts

                # 解析参数 JSON
                try:
                    args = json.loads(args_json)
                except json.JSONDecodeError:
                    return f"错误：参数 JSON 格式无效: {args_json}"

                print(f"🐍 [Tool Call] L4执行脚本: {skill_name}/{script_name}")
                print(f"   参数: {args}")

                # 获取脚本路径
                script_path = self.skill_manager.get_script_path(skill_name, script_name)

                # 执行脚本
                result = self.script_executor.execute(script_path, args)

                if result['success']:
                    # 格式化返回结果
                    if isinstance(result['result'], dict):
                        return json.dumps(result['result'], ensure_ascii=False, indent=2)
                    else:
                        return str(result['result'])
                else:
                    return f"❌ 脚本执行失败:\n{result.get('error', '未知错误')}"

            except ValueError as e:
                return str(e)
            except Exception as e:
                return f"执行异常: {str(e)}"

        self.tools.append(Tool(
            name="run_skill_script",
            func=lambda x: "此工具仅支持异步环境运行",
            coroutine=run_skill_script_tool,
            description="""执行技能包中的 Python 脚本进行复杂计算或数据处理。

使用时机：当技能手册中明确提到需要"运行脚本"、"调用计算程序"或需要进行复杂数学运算时。

参数格式："<技能名称>|<脚本文件名>|<参数JSON>"
示例："tax_calculator|calculate_duty.py|{\"cif_price\": 10000, \"hs_code\": \"85423100\"}"

注意：三个字段用竖线"|"分隔，参数必须是有效的 JSON 格式。
"""
        ))

        # --- 5. 构建图智能体 ---
        # 构建扩展能力提示（四级加载架构说明）
        skills_section = f"""
【扩展能力中心 - 四级加载架构】
L1层（技能清单）- 当前已加载以下技能：
{skills_registry}

【技能调度策略】
1. L2加载：当用户问题与上述技能描述匹配时，调用 use_skill(skill_name, query)
2. L3加载：阅读技能手册后，如需参考数据文件，调用 read_skill_resource(skill_name, file_name)
3. 资源探测：不确定有哪些资源时，先调用 list_skill_resources(skill_name)
4. L4计算：如需执行复杂计算或数据处理，调用 run_skill_script(skill_name, script_name, args_json)

示例流程：
用户: "这批货要交多少税？"
→ 调用 use_skill("tax_calculator", "这批货要交多少税")
→ 手册提示"参考 tax_rates.csv 或运行 calculate_duty.py"
→ 调用 run_skill_script("tax_calculator", "calculate_duty.py", {{"cif_price": 10000, "hs_code": "85423100"}})
→ 返回计算结果: {{duty: 0, vat: 1300}}
""" if self.skill_manager else ""

        self.system_prompt_text = f"""
你是一名智慧口岸AI专家，负责报关咨询和自动审单。
工作守则：
1. 审计：用户粘贴报关单后，主动调用 `audit_declaration`。
2. 咨询：法律疑问调用 `search_customs_regulations`。
3. 协同：审单发现风险后，可检索法规条文来支撑你的解释。
4. 语言：严禁跳出用户当前使用的语言（中文或越南语）。
{skills_section}
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
                    yield f"data: {json.dumps({'type': 'tool_start', 'tool_name': t_name, 'content': f'正在调用工具 [{t_name}]...'}, ensure_ascii=False)}\n\n"

                elif event_type == "on_tool_end":
                    t_name = event["name"]
                    # 获取工具执行结果
                    tool_output = event["data"].get("output", "")
                    # 格式化工具结果（限制长度，避免过长）
                    if isinstance(tool_output, str):
                        tool_result = tool_output[:2000] + "..." if len(tool_output) > 2000 else tool_output
                    else:
                        tool_result = str(tool_output)[:2000]
                    yield f"data: {json.dumps({'type': 'tool_end', 'tool_name': t_name, 'content': f'工具 [{t_name}] 调用完毕', 'tool_result': tool_result}, ensure_ascii=False)}\n\n"

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