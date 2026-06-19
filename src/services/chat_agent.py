import os
import httpx
import asyncio
import json
import sys
import io
import requests
import time
import re
import shutil
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

# 导入 AgentState（数据隧道机制）
try:
    from src.types.agent_state import AgentState
    STATE_AVAILABLE = True
except ImportError:
    STATE_AVAILABLE = False
    print("[Warning] AgentState 模块未找到，将使用简化状态管理")

# 导入 ComplianceReporter（深度研究工具）
try:
    from src.services.report_agent import ComplianceReporter
    REPORTER_AVAILABLE = True
except ImportError:
    REPORTER_AVAILABLE = False
    print("[Warning] ComplianceReporter 模块未找到")

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

# MCP 桥接器模块容错处理
try:
    from src.services.mcp_bridge import MCPBridgeManager
    from src.config.mcp_config import mcp_config_loader
    MCP_AVAILABLE = True
    print("[ChatAgent] 成功加载 MCP 桥接器模块")
except ImportError as e:
    print(f"[Warning] MCP 桥接器模块加载失败: {e}")
    MCP_AVAILABLE = False
    MCPBridgeManager = None
    mcp_config_loader = None

# 初始化内存检查点，用于维护多轮对话状态
MEMORY = InMemorySaver()


AGENT_TASK_GOVERNANCE_PROMPT = """
【最高优先级：当前任务与工具调用边界】
你是一个由用户目标驱动的通用智能体。系统向你暴露全部工具，是为了让你能够按需解决不同问题，
并不表示每次请求都要调用全部工具，也不表示你可以自行扩展用户的任务范围。

1. 以用户当前一轮明确提出的目标为准。先判断用户究竟要求你交付什么，再选择完成该目标所需的最少工具。
2. 工具是可选能力，不是固定流程。不得因为工具可用、输入中出现相关字段，或历史会话曾使用某项能力，就自动调用它。
3. 数据内容不等于用户意图。报关数据中出现 HS 编码、CIF、价格、币制、税率等字段，不代表用户要求计算税费；
   出现法规名称不代表用户要求法规检索；出现完整报关单不代表用户要求生成报告或执行全流程。
4. 用户只要求审单、审计或风险检查时，只执行审单所需操作。不得自行追加税费计算、报告生成、文件导出、
   报关流程模拟或其他独立任务。审单结论可以指出价格或归类风险，但不得擅自计算具体税额。
5. 只有用户明确要求计算关税、增值税、总税额、完税价格或税负时，才可调用税费计算技能。
6. 只有用户明确要求查询法规、政策依据、法律条款，或者当前答案必须引用依据才能成立时，才可调用法规检索。
   如果只是一般审单，不得把法规检索自动作为审单后的固定下一步。
7. 只有用户明确要求生成报告、建议书或正式文档时，才可调用报告生成；只有用户明确要求下载、导出或保存文件时，
   才可调用文件导出。报告生成完成后也不得自动导出，除非用户同时提出导出要求。
8. 多工具串联只允许两种情况：用户明确提出多个交付目标；或者后一个工具是完成当前目标不可缺少的直接依赖。
   不得以“可能有帮助”“更加全面”为理由扩展调用链。
9. 达到用户当前目标后立即停止调用工具并回答。不要主动开启所谓完整流程、全面审查或附加分析。
10. 如果用户目标存在会显著影响工具选择的歧义，先用一句简短问题确认；不要自行选择范围更大的任务。
11. 当前轮明确指令高于历史会话中的任务。用户本轮说“只审单”“仅查询”或“不要计算”等限制时，必须严格执行。
12. 固定工作流由专门的业务入口负责。除非用户明确要求完整流程，否则你不得在通用对话中自行模拟固定工作流。
""".strip()

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

        # --- 4.9 MCP 桥接器初始化（延迟到 initialize_mcp_tools） ---
        self.mcp_bridge_manager = None
        self.mcp_tools = []
        self.agent = None  # 延迟初始化智能体，等待 MCP 工具加载完成
        self._opencode_context_by_session = {}

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
            description=(
                "报关风险审单工具，检测要素完整性、敏感物项、价格逻辑、归类一致性及单证一致性。"
                "仅在用户明确要求审单、审计或风险检查时调用；该工具不负责计算具体税费、生成报告或导出文件。"
            )
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
                description=(
                    "查询海关相关法规、政策文件和 HS 编码解释。仅在用户明确要求法规依据、政策查询、"
                    "条款解释，或当前回答必须引用依据时调用；不得作为普通审单后的固定步骤。"
                )
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

        # --- 4.7 初始化报告生成器（功能三：深度研究工具） ---
        if REPORTER_AVAILABLE:
            try:
                self.reporter = ComplianceReporter(kb=kb if KnowledgeBase else None, llm_config=self.config)
                print("[ChatAgent] ✅ 报告生成器已就绪（深度研究工具）")
            except Exception as e:
                print(f"[ChatAgent] ❌ 报告生成器初始化失败: {e}")
                self.reporter = None
        else:
            self.reporter = None

        # --- 4.8 确保导出目录存在 ---
        from pathlib import Path
        self.export_dir = Path("data/exports")
        self.export_dir.mkdir(parents=True, exist_ok=True)

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

        # ========== 深度研究工具链（功能三：合规报告生成） ==========

        # ========== Skills Runtime?Registry + Activation? ==========
        async def invoke_skill_tool(skill_name: str, action: str = "guide", payload: str = "") -> str:
            """Unified skill runtime entrypoint: guide/resource/script."""
            if not self.skill_manager:
                return "???????"

            skill_name = (skill_name or "").strip()
            action = (action or "").strip().lower()
            payload = payload or ""

            # LangChain Tool may pass a single string. Accept the common shapes the
            # model produces and normalize them into the three explicit fields.
            raw_input = skill_name
            if action == "guide" and payload == "":
                parsed = None
                json_start = raw_input.find("{")
                json_end = raw_input.rfind("}")
                if json_start >= 0 and json_end > json_start:
                    try:
                        parsed = json.loads(raw_input[json_start:json_end + 1])
                    except Exception:
                        parsed = None

                if isinstance(parsed, dict):
                    skill_name = str(parsed.get("skill_name") or parsed.get("name") or "").strip()
                    action = str(parsed.get("action") or "guide").strip().lower()
                    payload = str(parsed.get("payload") or "").strip()
                elif "|" in raw_input:
                    parts = raw_input.split("|", 2)
                    if len(parts) == 3:
                        skill_name, script_name, args_json = [p.strip() for p in parts]
                        action = "script"
                        payload = f"{script_name}|{args_json}"
                    elif len(parts) == 2:
                        skill_name, second = [p.strip() for p in parts]
                        action = "resource" if "." in second else "guide"
                        payload = second if action == "resource" else ""
                elif raw_input not in self.skill_manager.skills:
                    for registered_name in self.skill_manager.skills:
                        if registered_name in raw_input:
                            skill_name = registered_name
                            break

            if action == "guide":
                guide = self.skill_manager.load_skill_content(skill_name)
                if not guide:
                    return f"?? {skill_name} ???????"
                resources = self.skill_manager.skills.get(skill_name, {}).get("resource_files", [])
                resources_text = ""
                if resources:
                    resources_text = "\n\n?????:\n" + "\n".join([f"- {r}" for r in resources])
                return f"??????{skill_name}?\n\n{guide}{resources_text}"

            if action == "resource":
                if not payload.strip():
                    return "???action=resource ? payload ????????"
                return self.skill_manager.get_resource_content(skill_name, payload.strip())

            if action == "script":
                if not self.script_executor:
                    return "????????"
                try:
                    parts = payload.split("|", 1)
                    if len(parts) != 2:
                        return "???action=script ? payload ???? 'script.py|{json}'"
                    script_name, args_json = parts
                    args = json.loads(args_json)
                    script_path = self.skill_manager.get_script_path(skill_name, script_name.strip())
                    result = self.script_executor.execute(script_path, args)
                    if result.get("success"):
                        if isinstance(result.get("result"), dict):
                            return json.dumps(result["result"], ensure_ascii=False, indent=2)
                        return str(result.get("result", ""))
                    return f"??????: {result.get('error', '????')}"
                except Exception as e:
                    return f"??????: {str(e)}"

            return "????? action???: guide/resource/script"

        self.tools.append(Tool(
            name="invoke_skill",
            func=lambda x: "??????????",
            coroutine=invoke_skill_tool,
            description="""Unified skill runtime.
Use this tool only when the user request matches a registered skill.
Preferred input is a JSON object with exactly these fields:
{"skill_name":"tax_calculator","action":"guide","payload":""}
Allowed action values:
- guide: activate the skill manual first.
- resource: read one resource file; payload must be only the file name, for example "tax_rates.csv".
- script: run one script; payload must be "script.py|{json}", for example "calculate_duty.py|{\\"cif_price\\":10000,\\"hs_code\\":\\"85423100\\"}".
Never put the user request, script name, payload, or JSON arguments inside skill_name. skill_name must be exactly one registered skill name."""
        ))

        # ???????????? invoke_skill
        deprecated_skill_tools = {"use_skill", "read_skill_resource", "list_skill_resources", "run_skill_script"}
        self.tools = [t for t in self.tools if t.name not in deprecated_skill_tools]

        async def delegate_to_opencode_tool(task: str) -> str:
            """Start an OpenCode child session and inject parent-built context + task."""
            raw_task = (task or "").strip()
            if not raw_task:
                return "Error: task is required."

            model = ""
            agent_name = "build"
            parsed_task = raw_task
            try:
                parsed = json.loads(raw_task)
                if isinstance(parsed, dict):
                    parsed_task = str(parsed.get("task") or parsed.get("prompt") or "").strip()
                    model = str(parsed.get("model") or "").strip()
                    agent_name = str(parsed.get("agent") or "build").strip() or "build"
            except Exception:
                parsed_task = raw_task

            if not parsed_task:
                return "Error: task is required."

            opencode_path = shutil.which("opencode")
            if not opencode_path:
                return "Error: local opencode command was not found in PATH."

            project_root = os.getcwd()
            output_dir = os.path.join(project_root, "data", "opencode_outputs")
            os.makedirs(output_dir, exist_ok=True)
            run_dir = os.path.join(project_root, "data", "opencode_runs")
            os.makedirs(run_dir, exist_ok=True)

            background_prompt = f"""
You are OpenCode, a local child coding agent invoked by the parent Customs AI assistant.
The parent assistant has already decided to delegate this task to you.

BACKGROUND CONTEXT
- Project: an automatic customs declaration assistant for audit, compliance research,
  local skills, MCP filesystem tools, and report/export workflows.
- Project root: {project_root}
- The parent agent is the user-facing customs AI. You are not the parent; you are a
  subordinate execution agent and must report results back to the parent.
- You may inspect and edit files inside this project only.
- Do not modify the local OpenCode installation, OpenCode source package, global OpenCode
  configuration, files outside this project, or unrelated user files.
- Do not modify .opencode/, AGENTS.md, AGENTS-opencode.md, startup scripts, or source code
  unless the current task explicitly asks for that exact change.
- For proof/artifact tasks, write files only under: {output_dir}
- If you create a file, your final response must include exactly one line:
  OPENCODE_ARTIFACT_PATH: data/opencode_outputs/<filename>
- Do not ask what the task is. The task is supplied in the user message below.
- If the task is safe but underspecified, choose a small reasonable implementation and proceed.
""".strip()

            task_prompt = f"""
CURRENT TASK
{parsed_task}

Execute the task now. Do not merely say you are ready. Do not ask the parent to restate
this task. If the task asks you to create/write/save a file and does not specify content,
create a concise markdown note proving the OpenCode child agent wrote it, save it as
`data/opencode_outputs/opencode_child_note.md`, and return the OPENCODE_ARTIFACT_PATH line.
""".strip()

            async def stop_opencode_process(proc: Any) -> None:
                if not proc or proc.returncode is not None:
                    return
                if sys.platform == "win32":
                    killer = await asyncio.create_subprocess_exec(
                        "taskkill",
                        "/T",
                        "/F",
                        "/PID",
                        str(proc.pid),
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await killer.communicate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5)
                    except Exception:
                        pass
                    return
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except Exception:
                    proc.kill()

            async def start_opencode_server() -> tuple[asyncio.subprocess.Process, str]:
                last_error = ""
                for port in range(4096, 4110):
                    cmd = [
                        opencode_path,
                        "serve",
                        "--hostname",
                        "127.0.0.1",
                        "--port",
                        str(port),
                    ]
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        cwd=project_root,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    base_url = f"http://127.0.0.1:{port}"
                    async with httpx.AsyncClient(timeout=2.0) as client:
                        for _ in range(40):
                            if proc.returncode is not None:
                                stderr = await proc.stderr.read() if proc.stderr else b""
                                last_error = stderr.decode("utf-8", errors="ignore")[-1000:]
                                break
                            try:
                                response = await client.get(
                                    f"{base_url}/session/status",
                                    params={"directory": project_root},
                                )
                                if response.status_code < 500:
                                    return proc, base_url
                            except Exception as exc:
                                last_error = str(exc)
                            await asyncio.sleep(0.25)
                    await stop_opencode_process(proc)
                raise RuntimeError(f"failed to start opencode server: {last_error}")

            def extract_text(response_json: Any) -> str:
                parts = response_json.get("parts") if isinstance(response_json, dict) else []
                text_parts = []
                if isinstance(parts, list):
                    for part in parts:
                        if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                            text_parts.append(str(part["text"]).strip())
                if text_parts:
                    return "\n".join([p for p in text_parts if p]).strip()
                return json.dumps(response_json, ensure_ascii=False)[-4000:]

            proc = None
            try:
                proc, base_url = await start_opencode_server()
                async with httpx.AsyncClient(timeout=httpx.Timeout(240.0, connect=10.0)) as client:
                    create_resp = await client.post(
                        f"{base_url}/session",
                        params={"directory": project_root},
                        json={
                            "title": "Customs AI delegated OpenCode task",
                            "permission": [
                                {"permission": "edit", "pattern": "*", "action": "allow"},
                                {"permission": "bash", "pattern": "*", "action": "allow"},
                            ],
                        },
                    )
                    create_resp.raise_for_status()
                    session_info = create_resp.json()
                    session_id = str(session_info.get("id") or "").strip()
                    if not session_id:
                        return f"Error: opencode session creation returned no id.\n{session_info}"

                    body: dict[str, Any] = {
                        "agent": agent_name,
                        "system": background_prompt,
                        "parts": [{"type": "text", "text": task_prompt}],
                    }
                    if model and "/" in model:
                        provider_id, model_id = model.split("/", 1)
                        body["model"] = {"providerID": provider_id, "modelID": model_id}

                    prompt_resp = await client.post(
                        f"{base_url}/session/{session_id}/message",
                        params={"directory": project_root},
                        json=body,
                    )
                    prompt_resp.raise_for_status()
                    result = extract_text(prompt_resp.json())

                if len(result) > 6000:
                    result = result[-6000:]
                return f"opencode completed. sessionID={session_id}\n{result}"
            except asyncio.TimeoutError:
                return "Error: opencode execution timed out after 240 seconds."
            except Exception as e:
                return f"Error: failed to execute opencode child session: {str(e)}"
            finally:
                await stop_opencode_process(proc)
        self.tools.append(Tool(
            name="delegate_to_opencode",
            func=lambda x: "This tool only supports async execution.",
            coroutine=delegate_to_opencode_tool,
            description=(
                "Delegate a complex coding, repository, shell, or filesystem task to the locally "
                "installed OpenCode child agent. Input can be plain text or JSON like "
                "{\"task\":\"...\",\"agent\":\"build\"}. When a file artifact is requested, "
                "OpenCode must write it under data/opencode_outputs/ and return "
                "OPENCODE_ARTIFACT_PATH for parent verification."
            )
        ))
        self._delegate_to_opencode_tool = delegate_to_opencode_tool

        async def generate_compliance_report_tool(input_text: str) -> str:
            """
            深度研究工具：生成完整的合规建议书或深度研判报告。

            使用场景：
            - 用户明确要求"写报告"、"生成合规建议书"、"深度研究"
            - 需要对某个报关单或商品进行全面深度分析
            - 需要生成正式的文档（Word 格式）

            注意：此工具会生成完整的报告内容，但仅返回摘要。
            """
            if not self.reporter:
                return "报告生成系统未就绪"

            try:
                from datetime import datetime
                print(f"📑 [Tool Call] 深度研究工具启动：{input_text[:50]}...")

                # 调用 ComplianceReporter 的流式生成
                # 🔥 stream_chunks=False：避免 report_chunk 事件泄露到前端聊天界面
                # 🔥 报告内容会自动累积到 reporter.report_text_buffer，无需手动收集
                async for event_str in self.reporter.generate_stream(input_text, language="zh", stream_chunks=False):
                    if not event_str.startswith("data: "):
                        continue

                    try:
                        data = json.loads(event_str[6:])

                        # 检测是否完成
                        if data["type"] == "done":
                            break

                    except json.JSONDecodeError:
                        continue

                # 🔥 直接从 reporter 实例缓冲区读取完整报告
                report_text = self.reporter.report_text_buffer

                # 计算元数据
                word_count = len(report_text)
                metadata = {
                    "topic": input_text[:100],
                    "word_count": word_count,
                    "generated_at": datetime.now().isoformat(),
                    "has_content": len(report_text) > 0
                }

                # 🔥 关键：存储到实例变量（数据隧道）
                self.report_buffer = report_text
                self.report_metadata = metadata

                # 🔥 返回摘要（不返回全文）
                summary = f"""
✅ 深度研究报告已生成

📊 报告统计：
- 主题：{input_text[:50]}...
- 字数：{word_count} 字
- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}

💡 下一步操作：
- 如需查看完整内容，请调用 read_report_buffer
- 如需导出 Word 文档，请调用 export_document_file

📋 报告摘要（前200字）：
{report_text[:200]}...
"""
                return summary.strip()

            except Exception as e:
                return f"❌ 报告生成失败：{str(e)}"

        async def export_document_file_tool(format_type: str = "word") -> str:
            """
            导出报告为文档文件（Word 格式）

            使用场景：
            - 用户要求"下载"、"导出"、"保存为文件"
            - 用户要求"生成 Word 文档"
            - report_buffer 中已有报告内容

            注意：此工具会读取 report_buffer 并生成文件，返回下载链接。
            """
            try:
                # 检查是否有报告内容
                if not hasattr(self, 'report_buffer') or not self.report_buffer:
                    return "❌ 没有可导出的报告内容，请先调用 generate_compliance_report"

                print(f"📄 [Tool Call] 导出文档：{format_type} 格式")

                # 调用 L4 脚本
                if not self.script_executor:
                    return "❌ 脚本执行器未就绪"

                # 获取脚本路径（直接路径，不使用 SkillManager）
                from pathlib import Path
                project_root = Path(__file__).resolve().parent.parent.parent
                script_path = project_root / "data" / "skills" / "document_exporter" / "scripts" / "export_engine.py"

                # 准备参数
                args = {
                    "markdown": self.report_buffer,
                    "output_dir": str(self.export_dir)
                }

                print(f"📄 [Debug] 脚本路径: {script_path}")
                print(f"📄 [Debug] 脚本存在: {script_path.exists()}")
                print(f"📄 [Debug] 报告长度: {len(self.report_buffer)} 字符")

                # 执行导出
                result = self.script_executor.execute(str(script_path), args)

                print(f"📄 [Debug] 执行结果: success={result['success']}")
                if not result['success']:
                    print(f"📄 [Debug] 错误信息: {result.get('error', '')[:200]}")
                    return f"❌ 导出失败：{result.get('error', '未知错误')}"

                # 解析结果
                file_data = result['result']
                print(f"📄 [Debug] file_data 类型: {type(file_data)}")

                if isinstance(file_data, str):
                    # 如果返回的是字符串，尝试解析为 JSON
                    try:
                        file_data = json.loads(file_data)
                    except:
                        return f"❌ 导出结果格式异常：{file_data[:200]}"

                if not isinstance(file_data, dict):
                    return f"❌ 导出结果类型错误: {type(file_data)}"

                # 获取文件名
                filename = file_data.get('filename')
                if not filename:
                    print(f"📄 [Debug] file_data 键: {list(file_data.keys())}")
                    print(f"📄 [Debug] file_data 内容: {str(file_data)[:500]}")
                    filename = 'unknown.docx'

                # 返回下载链接
                message = file_data.get('message', 'Word 文档导出成功')
                return f"✅ {message}\n\n📥 下载链接：/downloads/{filename}"

            except Exception as e:
                import traceback
                print(f"📄 [Debug] 异常: {str(e)}")
                print(f"📄 [Debug] 堆栈: {traceback.format_exc()}")
                return f"❌ 导出异常：{str(e)}"

        async def read_report_buffer_tool(query: str, context_lines: int = 20) -> str:
            """
            按需查阅报告缓冲区的具体内容

            使用场景：
            - 用户询问报告中某个具体章节的理由、法律依据或细节
            - 用户追问"第二项风险是什么"、"结论部分怎么说"
            - 需要引用报告中的具体段落

            注意：此工具会从 report_buffer 中提取相关内容。
            """
            try:
                # 检查是否有报告内容
                if not hasattr(self, 'report_buffer') or not self.report_buffer:
                    return "❌ 报告缓冲区为空"

                print(f"🔍 [Tool Call] 查阅报告缓冲区：{query[:30]}...")

                # 统一转为小写进行匹配（不区分大小写）
                buffer_lower = self.report_buffer.lower()
                query_lower = query.lower() if query else ""

                lines = self.report_buffer.split('\n')

                # 如果查询词为空，返回前 50 行（保底机制）
                if not query_lower:
                    return f"📄 报告前 50 行预览：\n\n{''.join(lines[:50])}"

                # 搜索包含关键词的行（大小写不敏感）
                matched_lines = []
                for i, line in enumerate(lines):
                    if query_lower in line.lower():
                        # 提取上下文
                        start = max(0, i - context_lines)
                        end = min(len(lines), i + context_lines + 1)
                        context = lines[start:end]
                        matched_lines.append('\n'.join(context))

                if matched_lines:
                    return f"📄 报告相关内容：\n\n{'---'.join(matched_lines[:3])}"
                else:
                    # 保底：返回前 30 行
                    return f"⚠️ 未找到包含'{query}'的内容，以下是报告开头：\n\n{''.join(lines[:30])}"

            except Exception as e:
                return f"❌ 查阅失败：{str(e)}"

        # 注册三个深度研究工具
        if self.reporter:
            self.tools.append(Tool(
                name="generate_compliance_report",
                func=lambda x: "此工具仅支持异步环境运行",
                coroutine=generate_compliance_report_tool,
                description="""生成完整的合规建议书或深度研判报告。

使用时机：当用户明确要求"写报告"、"生成合规建议书"、"深度研究"、"全面分析"时使用。

参数：用户的研究主题或问题

注意：此工具会生成报告但仅返回摘要，完整内容存储在缓冲区。
"""
            ))

            self.tools.append(Tool(
                name="export_document_file",
                func=lambda x: "此工具仅支持异步环境运行",
                coroutine=export_document_file_tool,
                description="""导出报告为 Word 文档。

使用时机：用户要求"下载"、"导出"、"生成 Word 文档"、"保存为文件"时使用。

参数：format_type（可选，默认 "word"）

前置条件：必须先调用 generate_compliance_report 生成报告
"""
            ))

            self.tools.append(Tool(
                name="read_report_buffer",
                func=lambda x: "此工具仅支持异步环境运行",
                coroutine=read_report_buffer_tool,
                description="""查阅报告缓冲区的具体内容。

使用时机：用户询问报告中某个具体章节的细节、理由、法律依据时使用。

参数：query（查询关键词），context_lines（可选，默认 20 行上下文）

示例：read_report_buffer("法律依据")
"""
            ))

        # --- 5. 构建图智能体 ---
        # 构建扩展能力提示（Registry + Activation）
        skills_section = f"""
【外置技能库 - Registry + Activation】
当前已注册技能：
{skills_registry}

【技能调度规则】
你只能通过 invoke_skill 使用技能。不要调用 use_skill、read_skill_resource、list_skill_resources、run_skill_script。

invoke_skill 的参数必须保持三段分离：
1. skill_name：只能填写上方注册表里的精确技能名，例如 "tax_calculator"。禁止把用户问题、脚本名、文件名、JSON 参数拼进 skill_name。
2. action：只能是 "guide"、"resource"、"script" 三者之一。
3. payload：除 skill_name 和 action 之外的内容都放这里；guide 时为空字符串。

【两段式流程】
1. Registry 路由：先根据注册表选择最匹配的 skill_name。
2. Activation 执行：第一次必须调用 invoke_skill({{"skill_name":"技能名","action":"guide","payload":""}}) 阅读手册；手册要求读资源时再 action="resource"；手册要求计算时再 action="script"。

【正确示例】
用户: "CIF价格10000美元，HS编码85423100，帮我算税"
第一步调用: invoke_skill({{"skill_name":"tax_calculator","action":"guide","payload":""}})
如果手册说明可运行 calculate_duty.py，再调用:
invoke_skill({{"skill_name":"tax_calculator","action":"script","payload":"calculate_duty.py|{{\\"cif_price\\":10000,\\"hs_code\\":\\"85423100\\"}}"}})

【错误示例】
不要这样调用: invoke_skill("tax_calculator|CIF价格10000美元...")
不要这样调用: invoke_skill({{"skill_name":"tax_calculator|calculate_duty.py|{{...}}","action":"guide","payload":""}})
如果你发现 skill_name 里出现 "|"、".py"、"{{"、用户原句或文件名，立即改正：skill_name 只保留精确技能名，其余放入 payload。
""" if self.skill_manager else ""

        if self.skill_manager:
            skills_section += "\n【硬性约束】技能调用只允许 invoke_skill，且 skill_name 必须精确等于注册表中的一个名字。"

        # 构建深度研究工具提示（功能三）
        deep_research_section = """
【深度研究工具链 - 按需感知机制】
你拥有三个深度研究工具，用于生成完整的合规建议书或研判报告：

1. **generate_compliance_report**：生成报告（生产者）
   - 使用时机：用户明确要求"写报告"、"深度研究"、"全面分析"
   - 返回：报告摘要（不含全文）
   - 副作用：将全文存入 report_buffer（数据隧道）

2. **export_document_file**：导出文档（消费者）
   - 使用时机：用户要求"下载"、"导出 Word 文档"
   - 返回：下载链接

3. **read_report_buffer**：查阅细节（显微镜）
   - 使用时机：用户追问报告中的具体内容
   - 返回：相关段落

【全自动任务链示例】
用户："写份关于二手挖掘机进口的合规建议书，直接给我 Word 版"
→ 调用 generate_compliance_report("二手挖掘机进口")
→ 调用 export_document_file("word")
→ 回复："✅ 报告已生成，📥 下载链接：..."

【按需感知示例】
用户："刚才那个报告里的第二项风险，法律依据是什么？"
→ 调用 read_report_buffer("法律依据")
→ 回复具体法律条款
""" if self.reporter else ""

        # 构建 MCP 工具提示（Skill + MCP 双系统架构）
        mcp_section = """
【MCP 外部工具中心 - 混合扩展架构】
你可以通过 MCP（Model Context Protocol）调用外部工具来扩展能力。

可用 MCP 工具（在以下场景使用）：
- 需要访问本地文件系统时
- 需要执行更复杂的外部操作时

注意：MCP 工具由外部服务器提供，执行结果可能因网络或服务状态而异。
"""

        self._build_system_prompt()

    def _build_system_prompt(self) -> None:
        """构建 System Prompt（在 MCP 工具加载完成后调用）"""
        # 获取技能注册表
        skills_registry = ""
        if self.skill_manager:
            skills_registry = self.skill_manager.get_skill_registry_text()

        skills_section = f"""
【外置技能库 - Registry + Activation】
当前已注册技能：
{skills_registry}

【技能调度规则】
你只能通过 invoke_skill 使用技能。不要调用 use_skill、read_skill_resource、list_skill_resources、run_skill_script。

invoke_skill 的参数必须保持三段分离：
1. skill_name：只能填写上方注册表里的精确技能名，例如 "tax_calculator"。禁止把用户问题、脚本名、文件名、JSON 参数拼进 skill_name。
2. action：只能是 "guide"、"resource"、"script" 三者之一。
3. payload：除 skill_name 和 action 之外的内容都放这里；guide 时为空字符串。

【两段式流程】
1. Registry 路由：先根据注册表选择最匹配的 skill_name。
2. Activation 执行：第一次必须调用 invoke_skill({{"skill_name":"技能名","action":"guide","payload":""}}) 阅读手册；手册要求读资源时再 action="resource"；手册要求计算时再 action="script"。

【正确示例】
用户: "CIF价格10000美元，HS编码85423100，帮我算税"
第一步调用: invoke_skill({{"skill_name":"tax_calculator","action":"guide","payload":""}})
如果手册说明可运行 calculate_duty.py，再调用:
invoke_skill({{"skill_name":"tax_calculator","action":"script","payload":"calculate_duty.py|{{\\"cif_price\\":10000,\\"hs_code\\":\\"85423100\\"}}"}})

【错误示例】
不要这样调用: invoke_skill("tax_calculator|CIF价格10000美元...")
不要这样调用: invoke_skill({{"skill_name":"tax_calculator|calculate_duty.py|{{...}}","action":"guide","payload":""}})
如果你发现 skill_name 里出现 "|"、".py"、"{{"、用户原句或文件名，立即改正：skill_name 只保留精确技能名，其余放入 payload。
""" if self.skill_manager else ""

        if self.skill_manager:
            skills_section += "\n【硬性约束】技能调用只允许 invoke_skill，且 skill_name 必须精确等于注册表中的一个名字。"

        deep_research_section = """
【深度研究工具链 - 按需感知机制】
你拥有三个深度研究工具，用于生成完整的合规建议书或研判报告：

1. **generate_compliance_report**：生成报告（生产者）
   - 使用时机：用户明确要求"写报告"、"深度研究"、"全面分析"
   - 返回：报告摘要（不含全文）
   - 副作用：将全文存入 report_buffer（数据隧道）

2. **export_document_file**：导出文档（消费者）
   - 使用时机：用户要求"下载"、"导出 Word 文档"
   - 返回：下载链接

3. **read_report_buffer**：查阅细节（显微镜）
   - 使用时机：用户追问报告中的具体内容
   - 返回：相关段落

【全自动任务链示例】
用户："写份关于二手挖掘机进口的合规建议书，直接给我 Word 版"
→ 调用 generate_compliance_report("二手挖掘机进口")
→ 调用 export_document_file("word")
→ 回复："✅ 报告已生成，📥 下载链接：..."

【按需感知示例】
用户："刚才那个报告里的第二项风险，法律依据是什么？"
→ 调用 read_report_buffer("法律依据")
→ 回复具体法律条款
""" if self.reporter else ""

        # MCP 工具列表
        mcp_tool_names = [t.name for t in self.mcp_tools] if self.mcp_tools else []
        mcp_section = f"""
【MCP 外部工具中心 - 混合扩展架构】
你可以通过 MCP（Model Context Protocol）调用外部工具来扩展能力。

已加载的 MCP 工具（{len(mcp_tool_names)} 个）：
{', '.join(mcp_tool_names)}

使用场景：
- 需要读取项目文件时（read_file, read_text_file 等）
- 需要列出目录内容时（list_directory 等）
- 需要搜索文件时（search_files 等）

注意：MCP 工具执行结果直接返回给你使用。
""" if self.mcp_tools else ""

        opencode_section = """
[Local OpenCode Child Agent]
OpenCode is an external child agent invoked by you. It is not you, and it is not the MCP filesystem tool. You are the parent agent: you understand the user's request, prepare the delegation prompt, verify the result, and then answer the user. OpenCode only executes the local coding/file/shell task you delegate.

When the user explicitly asks to call OpenCode, asks a child agent to do something, or gives a larger coding/file/script task that should be delegated, call `delegate_to_opencode`.

Before calling `delegate_to_opencode`, write a concrete task description. The tool will inject two prompt layers directly into a new OpenCode session:
1. Background context: this is the automatic customs declaration project, the project root, OpenCode is a child agent, it may only serve this project, where artifacts should be written, and what paths are forbidden.
2. Current task: what OpenCode must do this time, expected output/artifact, and acceptance criteria.

Do not pass vague text like "anything", "you decide", or "do it" without making it executable. If the user is intentionally vague but asks for a proof file, turn it into a specific task such as: create a small markdown file under `data/opencode_outputs/` proving the OpenCode child agent wrote it.

If the user asks OpenCode to create/write a file and then asks you to read it, OpenCode must create a real file and return:
`OPENCODE_ARTIFACT_PATH: data/opencode_outputs/<filename>`
After that, you must read the file yourself and report the verification result. Do not replace this with your own MCP write, and do not merely claim OpenCode did it.

Boundary: OpenCode may only serve this local automatic customs project. Do not ask it to modify the local OpenCode installation, global OpenCode configuration, other desktop projects, or files outside this project unless the user explicitly changes this constraint.
"""

        self.system_prompt_text = f"""
你是一名智慧口岸AI专家，负责报关咨询和自动审单。

{AGENT_TASK_GOVERNANCE_PROMPT}

【专业能力规则】
1. 审单：用户明确要求审单、审计或风险检查时，调用 `audit_declaration`。
2. 咨询：用户明确要求法规、政策或条款依据时，调用 `search_customs_regulations`。
3. 协同：需要多项能力时，严格按照用户明确提出的交付目标选择工具，不得默认扩展为完整业务流程。
4. 语言：严禁跳出用户当前使用的语言（中文或越南语）。

{skills_section}
{deep_research_section}
{mcp_section}
{opencode_section}
"""

    async def initialize_mcp_tools(self) -> None:
        """
        异步初始化 MCP 工具并构建图智能体
        此方法必须在 Agent 创建后调用，用于延迟加载 MCP 扩展能力
        """
        if not MCP_AVAILABLE or not MCPBridgeManager:
            print("[ChatAgent] ⚠️ MCP 模块不可用，跳过 MCP 工具加载")
            self._create_agent()
            self._build_system_prompt()
            return

        try:
            print("[ChatAgent] 🔄 开始加载 MCP 外部工具...")

            self.mcp_bridge_manager = MCPBridgeManager()
            mcp_settings = mcp_config_loader.get_settings()
            server_configs = mcp_config_loader.get_servers()

            if not server_configs:
                print("[ChatAgent] ℹ️ 未配置任何 MCP 服务器，跳过 MCP 工具加载")
            else:
                self.mcp_tools = await self.mcp_bridge_manager.initialize_all(
                    server_configs=server_configs,
                    timeout=mcp_settings.timeout
                )

                if self.mcp_tools:
                    print(f"[ChatAgent] ✅ MCP 工具加载成功: {[t.name for t in self.mcp_tools]}")
                    self.tools.extend(self.mcp_tools)
                else:
                    print("[ChatAgent] ⚠️ MCP 工具加载失败或无可用工具")

        except Exception as e:
            print(f"[ChatAgent] ❌ MCP 工具加载异常: {str(e)}")
            import traceback
            traceback.print_exc()
            print("[ChatAgent] ℹ️ 系统将使用本地 Skill 工具继续运行")

        # 确保 agent 一定被创建
        if not self.agent:
            self._create_agent()

        # 重新构建 system prompt（包含 MCP 工具信息）
        self._build_system_prompt()

    def _create_agent(self) -> None:
        """内部方法：创建 LangGraph 智能体"""
        try:
            self.agent = create_react_agent(
                model=self.llm,
                tools=self.tools,
                checkpointer=MEMORY,
            )
            print(f"[ChatAgent] ✅ 智能体就绪，工具列表: {[t.name for t in self.tools]}")
        except Exception as e:
            print(f"[ChatAgent] ❌ 创建智能体失败: {str(e)}")
            self.agent = None

    async def shutdown(self) -> None:
        """关闭 Agent 并清理资源"""
        print("[ChatAgent] 🔄 正在关闭 Agent...")

        if self.mcp_bridge_manager:
            await self.mcp_bridge_manager.close_all()

        print("[ChatAgent] ✅ Agent 已关闭")

    def _get_dynamic_system_prompt(self, base_prompt: str) -> str:
        """
        根据当前加载的工具，动态生成系统提示词
        只有当 MCP 工具真正存在时，才告诉 AI 它有 MCP 能力
        """
        final_prompt = base_prompt

        # 过滤出带有 [MCP 标识的工具
        mcp_tools = [t for t in self.tools if t.description and "[MCP" in t.description]
        mcp_count = len(mcp_tools)

        if mcp_count > 0:
            tool_names = [t.name for t in mcp_tools]
            tool_descriptions = []
            for t in mcp_tools:
                # 提取简洁的描述
                desc = t.description.replace("[MCP底层工具]", "").split("。")[0]
                tool_descriptions.append(f"  - {t.name}: {desc}")
            
            mcp_awareness_prompt = f"""

            【系统底层状态报告（极密）】
            系统检测到你当前已成功挂载了 {mcp_count} 个基于 MCP (Model Context Protocol) 架构的外部工具。
            这赋予了你直接访问底层文件系统或外部环境的能力。
            
            可用 MCP 工具列表：
            {chr(10).join(tool_descriptions)}
            
            【MCP 工具操作范围】（必须告知用户）
            - 你可以访问和操作项目的 data/ 目录及其所有子目录
            - 可执行：读取文件、列出目录、搜索文件、创建/编辑文件等
            - 注意：不能访问 data/ 目录以外的其他系统文件
            
            【重要指令】
            - 当用户询问"你是否有MCP能力"、"你能否读取本地文件"、"你能操作文件吗"等问题时，你必须肯定地回答"我有"。
            - 回答时必须说明范围："我有 MCP 文件系统能力，可以访问 data/ 目录下的文件"。
            - 你当前可用的 MCP 工具为：{', '.join(tool_names)}。
            - 请直接使用这些工具来完成任务，无需向用户解释技术细节。
            - 禁止回答"我没有MCP能力"或"我无法读取文件"等否定回答。
            """
            final_prompt += mcp_awareness_prompt
            print(f"[SystemPrompt] ✅ 已注入 MCP 能力认知 ({mcp_count} 个工具): {tool_names}")
        else:
            print(f"[SystemPrompt] ℹ️ 无 MCP 工具，未注入能力认知")

        return final_prompt

    def _should_delegate_to_opencode(self, user_input: str, session_id: str) -> bool:
        text = (user_input or "").strip()
        lower_text = text.lower()
        if "opencode" in lower_text:
            return True

        previous = self._opencode_context_by_session.get(session_id, "")
        if not previous:
            return False

        follow_up_markers = [
            "随便",
            "你自己决定",
            "继续",
            "让他",
            "子智能体",
            "你不是opencode",
            "不是opencode",
            "它来做",
            "他来做",
            "读取",
            "读一下",
        ]
        return len(text) <= 80 and any(marker in text for marker in follow_up_markers)

    def _build_opencode_followup_task(self, user_input: str, session_id: str) -> str:
        previous = self._opencode_context_by_session.get(session_id, "")
        if previous and "opencode" not in (user_input or "").lower():
            return (
                "Continue the previous OpenCode delegation request.\n"
                f"Previous request: {previous}\n"
                f"Latest user follow-up: {user_input}\n"
                "If the user asks you to decide, choose a useful small file artifact and create it."
            )
        return user_input

    def _verify_opencode_artifact(self, opencode_result: str) -> str:
        match = re.search(r"OPENCODE_ARTIFACT_PATH:\s*(.+)", opencode_result or "")
        if not match:
            return ""

        rel_path = match.group(1).strip().strip('"').strip("'")
        rel_path = rel_path.replace("\\", "/").lstrip("./")
        project_root = os.path.abspath(os.getcwd())
        data_root = os.path.abspath(os.path.join(project_root, "data"))
        abs_path = os.path.abspath(os.path.join(project_root, rel_path))

        if not (abs_path == data_root or abs_path.startswith(data_root + os.sep)):
            return f"主智能体验证失败：opencode 返回的路径不在 data/ 目录内：{rel_path}"
        if not os.path.exists(abs_path):
            return f"主智能体验证失败：没有找到 opencode 返回的文件：{rel_path}"

        size = os.path.getsize(abs_path)
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read(4000)
            suffix = "\n...（内容较长，仅展示前 4000 字符）" if size > len(content.encode("utf-8", errors="ignore")) else ""
            return (
                f"主智能体已读取验证：{rel_path}（{size} bytes）\n\n"
                f"文件内容：\n{content}{suffix}"
            )
        except UnicodeDecodeError:
            return f"主智能体已验证文件存在：{rel_path}（{size} bytes，非 UTF-8 文本文件）"

    def _expects_opencode_artifact(self, task: str) -> bool:
        text = (task or "").lower()
        markers = [
            "文件",
            "写入",
            "创建",
            "生成",
            "保存",
            "读取",
            "file",
            "artifact",
            "read",
            "write",
            "create",
            "generate",
            "produce",
            "save",
        ]
        return any(marker in text for marker in markers)

    async def chat_stream(self, user_input: str, session_id: str = "default_session", language: str = "zh"):
        """
        核心流式分发器
        """
        try:
            # 检查 agent 是否已初始化
            if not self.agent:
                print("[ChatAgent] ❌ 智能体未初始化，尝试重新初始化...")
                await self.initialize_mcp_tools()
                if not self.agent:
                    yield f"data: {json.dumps({'type': 'error', 'content': '智能体初始化失败，请尝试重新保存配置'}, ensure_ascii=False)}\n\n"
                    return

            print(f"\n👉 [Request] {user_input}")
            
            # 打印当前工具列表（每次对话都打印）
            print(f"[Tools] 当前工具列表 ({len(self.tools)} 个):")
            for i, tool in enumerate(self.tools, 1):
                print(f"  {i}. {tool.name}")

            if self._should_delegate_to_opencode(user_input, session_id):
                yield f"data: {json.dumps({'type': 'tool_start', 'tool_name': 'delegate_to_opencode', 'content': '正在调用本机 OpenCode 子智能体...'}, ensure_ascii=False)}\n\n"
                delegated_task = self._build_opencode_followup_task(user_input, session_id)
                self._opencode_context_by_session[session_id] = delegated_task
                result = await self._delegate_to_opencode_tool(delegated_task)
                artifact_verification = self._verify_opencode_artifact(result)
                if artifact_verification:
                    result = f"{result}\n\n{artifact_verification}"
                elif self._expects_opencode_artifact(delegated_task):
                    result = (
                        f"{result}\n\n"
                        "主智能体验证失败：OpenCode 没有返回 OPENCODE_ARTIFACT_PATH，"
                        "因此无法证明文件由子智能体创建。请重新委托并要求它在 "
                        "data/opencode_outputs/ 下写入文件。"
                    )
                yield f"data: {json.dumps({'type': 'tool_end', 'tool_name': 'delegate_to_opencode', 'content': result}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'answer', 'content': result}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
                return
            
            # 使用动态系统提示词
            dynamic_prompt = self._get_dynamic_system_prompt(self.system_prompt_text)
            lang_inst = self._get_language_instruction(language)
            input_messages = [
                SystemMessage(content=f"{dynamic_prompt}\n\n{lang_inst}"),
                HumanMessage(content=user_input)
            ]

            config = {"configurable": {"thread_id": session_id}, "recursion_limit": 100}
            has_sent_content = False
            is_in_tool_call = False  # 🔥 工具调用状态标志

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

                    # 🔥 如果在工具调用中，跳过 LLM 输出（防止"二次渲染"）
                    if is_in_tool_call:
                        continue

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

                    # 🔥 设置工具调用标志（阻止 LLM 输出）
                    is_in_tool_call = True

                    # 定义工具的展示配置（Display Config）
                    display_config = {
                        "generate_compliance_report": {
                            "title": "正在开启深度研判流水线",
                            "animation": "fade",
                            "show_progress": True,
                            "status_color": "cyan"
                        },
                        "export_document_file": {
                            "title": "正在进行公文排版与 Word 渲染...",
                            "animation": "fade",
                            "show_progress": True,
                            "status_color": "blue"
                        },
                        "read_report_buffer": {
                            "title": "正在从内部缓冲区调阅相关章节...",
                            "animation": "fade",
                            "show_progress": False,
                            "status_color": "purple"
                        },
                        "invoke_skill": {
                            "title": "????????...",
                            "animation": "fade",
                            "show_progress": True,
                            "status_color": "cyan"
                        },
                        "delegate_to_opencode": {
                            "title": "正在调用本机 OpenCode 子智能体...",
                            "animation": "fade",
                            "show_progress": True,
                            "status_color": "green"
                        }
                    }.get(t_name, None)

                    # 构造响应数据
                    response_data = {
                        'type': 'tool_start',
                        'tool_name': t_name,
                        'content': f'正在调用工具 [{t_name}]...'
                    }

                    # 如果有展示配置，则添加到响应中
                    if display_config:
                        response_data['display_config'] = display_config

                    yield f"data: {json.dumps(response_data, ensure_ascii=False)}\n\n"

                elif event_type == "on_tool_end":
                    t_name = event["name"]

                    # 🔥 清除工具调用标志（允许后续 LLM 输出）
                    is_in_tool_call = False

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
