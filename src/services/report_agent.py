import json
import asyncio
import httpx
import random
import re
from typing import List, AsyncGenerator, Set
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from pathlib import Path

# 导入配置
from src.config.loader import settings

# 知识库容错导入
try:
    from src.services.knowledge_base import KnowledgeBase
    KB_AVAILABLE = True
except ImportError:
    KnowledgeBase = None
    KB_AVAILABLE = False
    print("⚠️ [System] KnowledgeBase 模块未找到，将以无知识库模式运行")

class ComplianceReporter:
    def __init__(self):
        print("📑 [System] 初始化 ComplianceReporter...")
        
        # 1. 网络层配置
        proxy_url = settings.HTTP_PROXY
        # 强制关闭 SSL 验证
        if proxy_url:
            async_transport = httpx.AsyncHTTPTransport(proxy=proxy_url, verify=False)
            self.async_client = httpx.AsyncClient(transport=async_transport, timeout=120.0)
        else:
            self.async_client = httpx.AsyncClient(verify=False, timeout=120.0)

        # 2. LLM 初始化
        self.llm = ChatOpenAI(
            model=settings.DEEPSEEK_MODEL,
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            temperature=0.3,
            http_async_client=self.async_client,
            streaming=True,
            model_kwargs={"stream": True}
        )

        # 3. 知识库检索器
        self.kb = None
        if KB_AVAILABLE:
            try:
                self.kb = KnowledgeBase()
            except Exception as e:
                print(f"   ❌ 知识库加载失败 (跳过): {e}")

        # 4. 加载双模 SOP
        self.sop_customs = self._load_specific_sop("sop_process.txt", "标准海关合规审查SOP")
        self.sop_research = self._load_specific_sop("sop_deep_research.txt", "通用深度研判SOP")

    def _load_specific_sop(self, filename: str, default_text: str) -> str:
        try:
            base_dir = Path(__file__).resolve().parent.parent.parent
            sop_path = base_dir / "config" / filename
            if sop_path.exists():
                with open(sop_path, "r", encoding="utf-8") as f:
                    return f.read()
            return default_text
        except:
            return default_text

    def _detect_mode(self, text: str) -> str:
        keywords = ["报关单", "HS编码", "申报要素", "境内收货人", "成交方式", "提运单号", "毛重", "净重"]
        hit_count = sum(1 for k in keywords if k in text)
        return "CUSTOMS" if hit_count >= 2 else "RESEARCH"

    async def generate_stream(self, input_text: str, language: str = "zh") -> AsyncGenerator[str, None]:
        """
        核心生成流
        """
        # 0. 立即握手
        engine_start = self._get_ui_text("engine_start", language)
        yield self._sse("thought", f"🚀 {engine_start}")
        await asyncio.sleep(0.1)

        # 1. 路由判断
        mode = self._detect_mode(input_text)
        
        if mode == "CUSTOMS":
            active_sop = self.sop_customs
            role_desc = self._get_ui_text("role_customs", language)
            task_desc = self._get_ui_text("task_customs", language)
            yield self._sse("thought", f"🔍 {self._get_ui_text('audit_mode', language)}")
        else:
            active_sop = self.sop_research
            role_desc = self._get_ui_text("role_research", language)
            task_desc = self._get_ui_text("task_research", language)
            yield self._sse("thought", f"🧠 {self._get_ui_text('research_mode', language)}")
        
        state = {
            "topic": input_text,
            "mode": mode,
            "toc": [],
            "notebook": [],
            "used_doc_hashes": set(), 
            "full_report_text": "",
        }

        try:
            # ==========================================
            # 阶段 1: 动态规划
            # ==========================================
            building_outline = self._get_ui_text("building_outline", language)
            yield self._sse("thought", f"{building_outline}[{role_desc}]视角构建大纲...")

            # 确保这里传了 4 个参数（包括 language）
            toc_list = await self._generate_toc(input_text, mode, active_sop, language)

            state["toc"] = toc_list
            yield self._sse("toc", toc_list)

            # ==========================================
            # 阶段 2: 章节循环
            # ==========================================
            for i, section_title in enumerate(toc_list):
                is_last_chapter = (i == len(toc_list) - 1)
                yield self._sse("step_start", {"index": i, "title": section_title})

                section_search_history = []
                section_notes = []

                if is_last_chapter:
                    reviewing_full_text = self._get_ui_text("reviewing_full_text", language)
                    yield self._sse("thought", f"{reviewing_full_text}...")
                    await asyncio.sleep(1.0)
                else:
                    research_rounds = 2 if mode == "CUSTOMS" else 3
                    for round_idx in range(1, research_rounds + 1):
                        previous_context = state["full_report_text"][-800:] if state["full_report_text"] else "（首章）"

                        # 改进的搜索策略：确保每轮搜索不同角度
                        if round_idx == 1:
                            # 第一轮：从章节标题直接提取关键词
                            strategy_prompt = f"你是一名{role_desc}。正在撰写：《{section_title}》。请生成一个简短搜索关键词(2-6字)，直接从章节标题中提取核心概念。"
                        elif round_idx == 2:
                            # 第二轮：从不同角度补充搜索（避免重复）
                            strategy_prompt = f"你是一名{role_desc}。正在撰写：《{section_title}》。\n"
                            if section_search_history:
                                strategy_prompt += f"已搜索过：{section_search_history}（这些角度已覆盖）。\n"
                            strategy_prompt += f"请从**完全不同**的角度（如：风险点、审核方法、常见问题、监管要求等）生成一个新的简短搜索关键词(2-6字)。必须与已搜索关键词不同！"
                        else:
                            # 第三轮：深度关联搜索
                            strategy_prompt = f"你是一名{role_desc}。正在撰写：《{section_title}》。\n"
                            if section_search_history:
                                strategy_prompt += f"已搜索过：{section_search_history}。\n"
                            strategy_prompt += f"请从**深层关联**角度（如：法律依据、处罚案例、操作规程等）生成一个新的简短搜索关键词(2-6字)。必须避免重复！"

                        try:
                            q_res = await self.llm.ainvoke([HumanMessage(content=strategy_prompt)])
                            query = q_res.content.strip().split('\n')[0].replace('"', '')
                            # 确保不重复
                            if query in section_search_history:
                                query = f"{section_title.split(' ')[0]}检查" if round_idx == 2 else f"{section_title.split(' ')[0]}风险"
                        except Exception:
                            query = self._get_ui_text("default_query", language)

                        section_search_history.append(query)
                        search_keyword = self._get_ui_text("search_keyword", language)
                        yield self._sse("thought", f"[Round {round_idx}] {search_keyword}：'{query}'")
                        yield self._sse("rag_search", {"query": query})
                        
                        snippet = "（无本地依据）"
                        score = 0.0
                        filename = "System"
                        
                        if self.kb:
                            try:
                                # 安全调用，防止方法不存在
                                search_func = getattr(self.kb, "search_with_score", None)
                                if search_func:
                                    results = await asyncio.wait_for(search_func(query, k=3), timeout=10.0)
                                    if results:
                                        doc, similarity = results[0]
                                        snippet = doc.page_content
                                        filename = Path(doc.metadata.get("source", "unknown")).name
                                        score = similarity
                            except asyncio.TimeoutError:
                                pass # 超时忽略
                            except Exception as e:
                                print(f"检索异常: {e}")

                        yield self._sse("rag_result", {"filename": filename, "score": float(score), "snippet": snippet[:100] + "..."})
                        section_notes.append(f"关键词[{query}] -> {snippet}")
                        state["notebook"].append(f"关键词[{query}] -> {snippet}")
                        
                        yield self._sse("take_note", {"content": f"{query}: {snippet[:20]}..."})
                        await asyncio.sleep(0.1)

                # 撰写正文
                language_instruction = self._get_language_instruction(language)
                write_prompt = f"""
你是一名{role_desc}。请撰写《{section_title}》。
【前文】...{state["full_report_text"][-1000:] if state["full_report_text"] else "无"}
【证据】{json.dumps(section_notes, ensure_ascii=False)}
【语言要求】{language_instruction}
【指令】直接输出Markdown正文，不要重复标题。
"""
                async for chunk in self.llm.astream([HumanMessage(content=write_prompt)]):
                    if chunk.content:
                        yield self._sse("report_chunk", chunk.content)
                        state["full_report_text"] += chunk.content
                
                state["full_report_text"] += "\n\n"
                yield self._sse("step_done", {"index": i})

            yield self._sse("done", {})

        except Exception as e:
            # 捕捉任何错误并发送给前端
            yield self._sse("error", str(e))

    async def _generate_toc(self, topic: str, mode: str, sop: str, language: str = "zh") -> List[str]:
        """双模目录生成器"""
        if mode == "CUSTOMS":
            advice = "建议包含（需要注意的是，不是一定要包含这些，你需要根据具体单据来确定）：1.申报要素复核 2.价格逻辑审查 3.贸易管制风险 4.综合结论"
        else:
            advice = "建议包含（需要注意的是，不是一定要包含这些，你需要根据具体单据来确定）：1.背景概述 2.核心事实梳理 3.深度关联分析 4.结论与展望"

        language_instruction = self._get_language_instruction(language)
        prompt = f"""
你是一名高级分析师。请根据用户输入设计目录。
输入：{topic[:200]}
建议结构：{advice}
【语言要求】{language_instruction}
【严格要求】
1. 只返回一个纯 JSON 字符串数组，如 ["1. 标题A", "2. 标题B"]
2. 目录标题使用对应的语言（中文/越南语）
3. 不要 Markdown，不要解释。
"""
        try:
            res = await self.llm.ainvoke([HumanMessage(content=prompt)])
            text = re.sub(r'```json\s*|\s*```', '', res.content).strip()
            parsed = json.loads(text)
            clean_toc = []
            if isinstance(parsed, list):
                for idx, item in enumerate(parsed):
                    title = str(item) if not isinstance(item, dict) else str(list(item.values())[0])
                    clean_title = re.sub(r'^(\d+\.|Chapter\s*\d+|第.+章)\s*', '', title).strip()
                    clean_toc.append(f"{idx + 1}. {clean_title}")
            return clean_toc if clean_toc else self._fallback_toc(mode, language)
        except Exception:
            return self._fallback_toc(mode, language)

    def _fallback_toc(self, mode, language: str = "zh"):
        if mode == "CUSTOMS":
            if language == "vi":
                return ["1. Kiểm tra các yếu tố khai báo", "2. Phân tích logic giá", "3. Sàng lọc giấy phép giám sát", "4. Kết luận và khuyến nghị"]
            return ["1. 申报要素复核", "2. 价格逻辑分析", "3. 监管证件筛查", "4. 结论与建议"]
        if language == "vi":
            return ["1. Tổng quan về bối cảnh", "2. Phân tích các sự kiện cốt lõi", "3. Phân tích liên kết sâu", "4. Kết luận và triển vọng"]
        return ["1. 背景概述", "2. 核心事实梳理", "3. 深度关联分析", "4. 结论与展望"]

    def _sse(self, type_str, payload):
        return f"data: {json.dumps({'type': type_str, 'payload': payload}, ensure_ascii=False)}\n\n"

    def _get_language_instruction(self, language: str) -> str:
        """生成语言输出指令"""
        # 语言代码映射到实际语言名称
        language_names = {
            "zh": "简体中文 (Chinese)",
            "vi": "Tiếng Việt (越南语)"
        }
        language_name = language_names.get(language, language_names["zh"])

        return f"""【重要语言设置】当前用户设置的语言是 {language_name}，语言代码为 {language}。
【严格要求】你必须使用 {language_name} 撰写报告内容，包括标题、正文、结论等所有部分。
报告的所有输出必须是 {language_name}，这是用户界面语言设置，报告将直接显示给前端用户。"""

    def _get_ui_text(self, key: str, language: str = "zh") -> str:
        """获取UI显示文字"""
        ui_texts = {
            "zh": {
                "building_outline": "正在基于",
                "reviewing_full_text": "正在回顾全文，进行逻辑收束与最终研判",
                "search_keyword": "检索关键词",
                "searching": "正在搜索",
                "writing": "正在撰写",
                "default_query": "通用风险",
                "engine_start": "研判引擎已启动，正在分析任务意图...",
                "role_customs": "海关高级查验专家",
                "task_customs": "进行进出口合规性审查",
                "audit_mode": "检测到报关单据，已切换至【合规审计模式】...",
                "role_research": "深度档案分析师",
                "task_research": "进行本地知识库深度挖掘与研判",
                "research_mode": "检测到通用问题，已切换至【深度研判模式】..."
            },
            "vi": {
                "building_outline": "Đang xây dựng",
                "reviewing_full_text": "Đang xem lại toàn văn, thực hiện kết luận logic cuối cùng",
                "search_keyword": "Từ khóa tìm kiếm",
                "searching": "Đang tìm kiếm",
                "writing": "Đang viết",
                "default_query": "Rủi ro chung",
                "engine_start": "Động cơ phân tích đã khởi động, đang phân tích ý định nhiệm vụ...",
                "role_customs": "Chuyên gia kiểm tra hải quan cấp cao",
                "task_customs": "Thực hiện xem xét tuân thủ xuất nhập khẩu",
                "audit_mode": "Phát hiện tờ khai hải quan, đã chuyển sang【Chế độ kiểm toán tuân thủ】...",
                "role_research": "Chuyên gia phân tích hồ sơ sâu",
                "task_research": "Thực hiện khai thác và nghiên cứu sâu cơ sở dữ liệu địa phương",
                "research_mode": "Phát hiện vấn đề chung, đã chuyển sang【Chế độ nghiên cứu sâu】..."
            }
        }
        return ui_texts.get(language, ui_texts["zh"]).get(key, ui_texts["zh"][key])