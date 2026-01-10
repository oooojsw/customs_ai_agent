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
except ImportError:
    KnowledgeBase = None

class ComplianceReporter:
    def __init__(self):
        print("📑 [System] 初始化双模研判引擎 (Hybrid Deep Research Engine)...")
        
        # 1. 网络层配置
        proxy_url = settings.HTTP_PROXY
        async_transport = httpx.AsyncHTTPTransport(proxy=proxy_url, verify=False)
        self.async_client = httpx.AsyncClient(transport=async_transport, timeout=120.0)

        # 2. LLM 初始化 (R1 逻辑最强)
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
        if KnowledgeBase:
            try:
                self.kb = KnowledgeBase()
            except Exception as e:
                print(f"⚠️ 知识库加载失败: {e}")

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
        """
        简单高效的规则路由：判断是否为报关单
        """
        # 关键词命中 2 个以上即视为报关单
        keywords = ["报关单", "HS编码", "申报要素", "境内收货人", "成交方式", "提运单号", "毛重", "净重"]
        hit_count = sum(1 for k in keywords if k in text)
        
        if hit_count >= 2:
            return "CUSTOMS"
        return "RESEARCH"

    async def generate_stream(self, input_text: str) -> AsyncGenerator[str, None]:
        """
        智能双模生成流 (优化版：最后一章跳过 RAG)
        """
        # 1. 路由判断
        mode = self._detect_mode(input_text)
        
        if mode == "CUSTOMS":
            active_sop = self.sop_customs
            role_desc = "海关高级查验专家"
            task_desc = "进行进出口合规性审查"
            yield self._sse("thought", "🔍 检测到报关单据，已切换至【合规审计模式】...")
        else:
            active_sop = self.sop_research
            role_desc = "深度档案分析师"
            task_desc = "进行本地知识库深度挖掘与研判"
            yield self._sse("thought", "🧠 检测到通用问题，已切换至【深度研判模式 (DeepResearch)】...")
        
        await asyncio.sleep(0.5)

        # 初始化状态
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
            # 阶段 1: 动态规划 (Planning)
            # ==========================================
            yield self._sse("thought", f"正在基于[{role_desc}]视角构建大纲...")
            
            toc_list = await self._generate_toc(input_text, mode, active_sop)
            state["toc"] = toc_list
            yield self._sse("toc", toc_list)
            
            # ==========================================
            # 阶段 2: 章节循环 (Section Loop)
            # ==========================================
            for i, section_title in enumerate(toc_list):
                # 判断是否是最后一章
                is_last_chapter = (i == len(toc_list) - 1)
                
                yield self._sse("step_start", {"index": i, "title": section_title})
                
                section_search_history = []
                section_notes = []

                # --- 分支逻辑：如果是最后一章，跳过 RAG ---
                if is_last_chapter:
                    yield self._sse("thought", "正在回顾全文，进行逻辑收束与最终研判 (Skip RAG)...")
                    # 模拟一点思考时间，让前端体验更好
                    await asyncio.sleep(1.5)
                    section_notes.append("（本章为总结章节，基于前文所有分析得出结论，不再检索新证据）")
                
                else:
                    # --- 普通章节：正常进行 RAG 挖掘 ---
                    research_rounds = 2 if mode == "CUSTOMS" else 3
                    
                    for round_idx in range(1, research_rounds + 1):
                        # ... (这里保持原有的 RAG 逻辑不变) ...
                        previous_context = state["full_report_text"][-800:] if state["full_report_text"] else "（首章）"
                        
                        if mode == "CUSTOMS":
                            strategy_instruction = "请提取当前章节需要的法规依据、HS编码规则或监管要求作为检索词。"
                        else:
                            strategy_instruction = "请思考为了完善本章论点，还需要在本地文档中挖掘什么具体的证据或细节？"

                        strategy_prompt = f"""
你是一名{role_desc}。正在撰写：《{section_title}》。

【⚠️ 核心要求】
请提取一个简短的检索关键词（2-6个词），用于在本地知识库中查找相关法规或技术资料。

【限制条件】
1. **严禁输出分析过程**，直接输出关键词
2. 关键词长度：2-6个词
3. 不要输出完整句子或段落
4. 只输出关键词，不要引号、不要标点

【参考示例】
✅ 正确：HS编码8536 归类规则
✅ 正确：锂电池 联合国危险品分类
✅ 正确：贸易管制 出口许可证
❌ 错误：为了明确该产品的归类，我需要查找...
❌ 错误：该产品的物理接口细节包括...

【当前上下文】
章节：{section_title}
前文：{previous_context[:200]}
"""
                        q_res = await self.llm.ainvoke([HumanMessage(content=strategy_prompt)])
                        # 清理输出，只取第一行，去除标点和引号
                        query = q_res.content.strip().split('\n')[0].strip('"\'')
                        # 去除常见中文标点
                        for char in '。，、？！':
                            query = query.strip(char)
                        section_search_history.append(query)
                        
                        yield self._sse("thought", f"[Round {round_idx}] 正在知识库比对：'{query}'")
                        yield self._sse("rag_search", {"query": query})
                        
                        # 执行检索（使用真实相似度分数）
                        snippet = ""
                        score = 0.0
                        filename = "LocalDB"

                        if self.kb:
                            try:
                                # 调用新的带分数检索方法
                                results = await self.kb.search_with_score(query, k=6)

                                for doc, similarity in results:
                                    doc_hash = hash(doc.page_content[:30])
                                    if doc_hash not in state["used_doc_hashes"]:
                                        snippet = doc.page_content
                                        filename = Path(doc.metadata.get("source", "unknown")).name
                                        score = similarity  # 使用真实的相似度百分比 (0-100)
                                        state["used_doc_hashes"].add(doc_hash)
                                        break

                                # 如果所有文档都用过了，取第一个作为后备
                                if not snippet and results:
                                    snippet = results[0][0].page_content
                                    score = results[0][1] * 0.8  # 稍微降权，因为是重复使用

                            except Exception as e:
                                print(f"检索错: {e}")
                                import traceback
                                traceback.print_exc()

                        if not snippet:
                            snippet = "（未在本地知识库中找到直接对应条款，需依据通用专业知识判断）"
                            score = 0.0

                        yield self._sse("rag_result", {
                            "filename": filename,
                            "score": float(score),  # 确保 JSON 可序列化
                            "snippet": snippet[:100] + "..."
                        })

                        note_content = f"关键词[{query}] -> 发现：{snippet}"
                        section_notes.append(note_content)
                        state["notebook"].append(note_content)
                        await asyncio.sleep(0.5)

                # --- 子循环结束，撰写正文 ---
                
                # 动态调整写作 Prompt
                previous_context_full = state["full_report_text"][-1500:] if state["full_report_text"] else "无"
                
                if is_last_chapter:
                    yield self._sse("thought", "正在综合前文所有观点，生成最终结论...")
                    instruction_special = "这是报告的【最终章】。请不要引入新的事实证据，而是对【前文脉络】中提到的核心问题、风险点或发现进行高度概括和总结。给出明确的下一步建议。"
                else:
                    yield self._sse("thought", "证据链闭合，正在生成专业分析报告...")
                    instruction_special = f"请基于【核心证据】撰写本章。{role_desc}风格。承接前文，逻辑通顺。"

                write_prompt = f"""
你是一名{role_desc}。请撰写《{section_title}》。

【任务目标】
{task_desc}

【前文脉络 (基于此进行衔接/总结)】
...{previous_context_full}

【核心证据】
{json.dumps(section_notes, ensure_ascii=False)}

【原始输入】
{input_text}

【写作指令】
1. {instruction_special}
2. 直接输出 Markdown 正文。

【⚠️ 格式要求 - 重要】
- **严禁在正文开头重复章节标题**（如 "## 2. 价格审查"），因为系统已经自动显示了标题
- **直接从正文第一段开始写**，例如：

❌ 错误示例：
## 2. 价格真实性与逻辑审查
承接前文归类复核结论...

✅ 正确示例：
承接前文归类复核结论，HS编码8479.8962的适用性虽基本成立，但申报要素的简化描述...

"""
                current_section_content = ""
                async for chunk in self.llm.astream([HumanMessage(content=write_prompt)]):
                    if chunk.content:
                        current_section_content += chunk.content
                        yield self._sse("report_chunk", chunk.content)
                
                state["full_report_text"] += f"\n\n## {section_title}\n\n{current_section_content}"
                yield self._sse("step_done", {"index": i})

            # ==========================================
            # 阶段 3: 完结
            # ==========================================
            yield self._sse("thought", "报告生成完毕。")
            yield self._sse("done", {})

        except Exception as e:
            print(f"❌ 生成异常: {e}")
            import traceback
            traceback.print_exc()
            yield self._sse("error", str(e))

    async def _generate_toc(self, topic: str, mode: str, sop: str) -> List[str]:
        """
        双模目录生成器 (带清洗功能，修复乱码问题)
        """
        if mode == "CUSTOMS":
            advice_structure = """
            建议包含以下章节（请只返回标题字符串）：
            1. 申报要素与归类复核
            2. 价格真实性与逻辑审查
            3. 贸易管制与准入风险
            4. 综合结论与整改建议
            """
        else:
            advice_structure = """
            建议包含 4-6 个章节（请只返回标题字符串）：
            - 第一章必须是背景/现状概述
            - 中间章节按主题逻辑展开
            - 最后一章是结论与证据缺口说明
            """

        prompt = f"""
你是一名高级分析师。请根据用户输入和SOP设计目录。

【用户输入】
{topic}

【SOP】
{sop}

【结构建议】
{advice_structure}

【严格格式要求】
1. 必须返回一个纯 JSON 字符串数组，例如：["1. 章节名称", "2. 章节名称"]。
2. 严禁返回对象或字典（不要使用 key-value 结构）。
3. 不要 Markdown 标记。
"""
        try:
            res = await self.llm.ainvoke([HumanMessage(content=prompt)])
            # 1. 清洗 Markdown 标记
            text = res.content.replace("```json", "").replace("```", "").strip()
            
            # 2. 解析 JSON
            parsed = json.loads(text)
            
            # 3. 【核心修复】强制扁平化处理
            # 无论 LLM 返回的是 [{"title": "A"}, {"title": "B"}] 还是 ["A", "B"]
            # 我们都把它统一转成 ["1. A", "2. B"]
            clean_toc = []
            
            if isinstance(parsed, list):
                for idx, item in enumerate(parsed):
                    title = ""
                    if isinstance(item, str):
                        title = item
                    elif isinstance(item, dict):
                        # 如果模型不听话返回了对象，尝试提取 value 中看起来像标题的字段
                        # 优先找 'title', 'name', 'chapter'，找不到就取第一个 value
                        for key in ['title', 'chapterTitle', 'chapter_name', 'name', 'header']:
                            if key in item:
                                title = str(item[key])
                                break
                        if not title and item.values():
                            title = str(list(item.values())[0])
                    
                    # 移除已有的序号，重新编号，保证前端显示整齐
                    if title:
                        # 去掉开头的 "1.", "1 ", "Chapter 1" 等
                        clean_title = re.sub(r'^(\d+\.|Chapter\s*\d+|第.+章)\s*', '', title).strip()
                        clean_toc.append(f"{idx + 1}. {clean_title}")
            
            if not clean_toc:
                raise ValueError("Parsed TOC is empty")
                
            return clean_toc

        except Exception as e:
            print(f"❌ 目录生成解析失败: {e}, 启用兜底策略")
            # 兜底目录
            if mode == "CUSTOMS":
                return ["1. 申报要素复核", "2. 价格逻辑分析", "3. 监管证件筛查", "4. 结论建议"]
            return ["1. 背景概述", "2. 核心事实梳理", "3. 深度关联分析", "4. 结论与展望"]

    def _sse(self, type_str, payload):
        return f"data: {json.dumps({'type': type_str, 'payload': payload}, ensure_ascii=False)}\n\n"