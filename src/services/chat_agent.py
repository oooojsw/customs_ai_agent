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

        self.system_prompt_text = f"""
你是一名智慧口岸AI专家，负责报关咨询和自动审单。

【核心工作守则】
1. 审计：用户粘贴报关单后，主动调用 `audit_declaration`。
2. 咨询：法律疑问调用 `search_customs_regulations`。
3. 协同：审单发现风险后，可检索法规条文来支撑你的解释。
4. 语言：严禁跳出用户当前使用的语言（中文或越南语）。

{skills_section}
{deep_research_section}
{mcp_section}
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