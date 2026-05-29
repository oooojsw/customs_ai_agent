import json
import asyncio
import httpx
import random
import re
from typing import List, AsyncGenerator, Set, Tuple
from dataclasses import dataclass
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
    print("[System] KnowledgeBase module not found, running without knowledge base")

# ==================== AI 决策系统数据结构 ====================

@dataclass
class SearchRecord:
    """单次检索记录"""
    round: int
    query: str
    snippet: str
    score: float


@dataclass
class ResearchContext:
    """检索上下文"""
    # 章节信息
    chapter_index: int           # 当前章节序号 (1-based)
    chapter_title: str           # 章节标题
    total_chapters: int          # 总章节数

    # 轮次信息
    current_round: int           # 当前轮次 (1-based)
    min_rounds: int              # 最小轮数
    max_rounds: int              # 最大轮数
    mode: str                    # "CUSTOMS" 或 "RESEARCH"

    # 检索历史 (每轮的记录)
    search_history: List[SearchRecord]

    # 当前检索结果
    current_query: str
    current_snippet: str
    current_score: float


@dataclass
class QualityMetrics:
    """质量指标"""
    # 基础评分 (0-1)
    score_component: float      # 相似度 × 40%
    richness_component: float   # 丰富度 × 30%
    dedup_component: float      # 去重 × 20%
    evidence_component: float   # 累积证据 × 10%

    # 综合评分
    total_quality: float        # 总分 (0-1)

    # 质量等级
    quality_level: str          # "优秀"/"中等"/"较差"
    quality_stars: str          # "⭐⭐⭐"/"⭐⭐"/"⭐"

    # 趋势分析
    trend_indicator: str        # "↑0.05"/"↓0.08"/"→持平"

    # 内容特征
    has_numbers: bool
    has_punctuation: bool
    has_citation: bool

    # 证据分析
    coverage_areas: Set[str]    # 已覆盖的领域
    sufficiency_percent: float  # 充分性百分比
    duplication_percent: float  # 重复度百分比


class ComplianceReporter:
    def __init__(self, kb=None, llm_config: dict = None):
        """
        初始化合规报告Agent

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
        print("📑 [System] 初始化 ComplianceReporter...")

        # --- 1. 获取 LLM 配置 ---
        if llm_config:
            # 使用传入的配置
            config = llm_config
            print("[Reporter] 使用传入的 LLM 配置")
        else:
            # 使用默认 .env 配置
            config = {
                'api_key': settings.DEEPSEEK_API_KEY,
                'base_url': settings.DEEPSEEK_BASE_URL,
                'model': settings.DEEPSEEK_MODEL,
                'temperature': 0.3,
            }
            print("[Reporter] 使用 .env 默认配置")

        # 2. 网络层配置
        proxy_url = settings.HTTP_PROXY
        # 强制关闭 SSL 验证
        if proxy_url:
            async_transport = httpx.AsyncHTTPTransport(proxy=proxy_url, verify=False)
            self.async_client = httpx.AsyncClient(transport=async_transport, timeout=120.0)
        else:
            self.async_client = httpx.AsyncClient(verify=False, timeout=120.0)

        # 3. LLM 初始化
        self.llm = ChatOpenAI(
            model=config['model'],
            api_key=config['api_key'],
            base_url=config['base_url'],
            temperature=config.get('temperature', 0.3),
            http_async_client=self.async_client,
            streaming=True,
            model_kwargs={"stream": True}
        )

        # 3. 知识库检索器（使用传入的kb或创建新实例）
        if kb is not None:
            # ✅ 使用传入的全局kb实例（推荐方式）
            self.kb = kb
            print("   [OK] 使用全局共享的KnowledgeBase实例")
        elif KB_AVAILABLE:
            try:
                # ⚠️ 回退方案：创建新的kb实例（可能触发索引重建）
                print("   [WARNING] 未传入kb参数，将创建新的KnowledgeBase实例")
                print("   [TIP] 建议从main.py传入全局kb实例以避免重复初始化")
                self.kb = KnowledgeBase()
            except Exception as e:
                print(f"   ❌ 知识库加载失败 (跳过): {e}")
                self.kb = None
        else:
            self.kb = None
            print("   [INFO] KnowledgeBase未安装，将以无知识库模式运行")

        # 4. 加载双模 SOP
        self.sop_customs = self._load_specific_sop("sop_process.txt", "标准海关合规审查SOP")
        self.sop_research = self._load_specific_sop("sop_deep_research.txt", "通用深度研判SOP")

        # 5. 报告文本缓冲区（用于工具调用时存储完整报告）
        self.report_text_buffer = ""

    def _load_research_config(self) -> dict:
        """加载智能检索配置"""
        try:
            base_dir = Path(__file__).resolve().parent.parent.parent
            config_path = base_dir / "config" / "research_config.json"

            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            else:
                # 默认配置
                return {
                    "version": "1.0",
                    "rules": {
                        "CUSTOMS": {"min_rounds": 1, "max_rounds": 4, "early_stop_threshold": 0.75, "force_continue_threshold": 0.4},
                        "RESEARCH": {"min_rounds": 2, "max_rounds": 5, "early_stop_threshold": 0.7, "force_continue_threshold": 0.45}
                    },
                    "quality_metrics": {
                        "score_weight": 0.4, "content_weight": 0.3, "dedup_weight": 0.2, "evidence_weight": 0.1,
                        "min_content_length": 50, "dedup_threshold": 0.85
                    }
                }
        except Exception as e:
            print(f"⚠️ 加载检索配置失败: {e}, 使用默认配置")
            return {"rules": {"CUSTOMS": {"min_rounds": 1, "max_rounds": 3, "early_stop_threshold": 0.7},
                             "RESEARCH": {"min_rounds": 2, "max_rounds": 4, "early_stop_threshold": 0.7}},
                    "quality_metrics": {"score_weight": 0.4, "content_weight": 0.3, "dedup_weight": 0.2, "evidence_weight": 0.1}}

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

    def _validate_and_fix_filename(self, raw_filename: str) -> str:
        """
        验证从 FAISS metadata 提取的文件名，确保其确实存在于 knowledge 目录。
        如果不存在，尝试修复文件名。
        """
        from pathlib import Path

        # 获取 knowledge 目录
        base_dir = Path(__file__).resolve().parent.parent.parent
        knowledge_dir = base_dir / "data" / "knowledge"

        # 如果文件名为空或异常，返回默认值
        if not raw_filename or raw_filename in ["unknown", "System"]:
            return raw_filename

        # 策略1: 检查原始文件名是否存在
        possible_names = [
            raw_filename,
            raw_filename + ".txt",
            raw_filename.replace('.txt', ''),
        ]

        for name in possible_names:
            file_path = knowledge_dir / name
            if file_path.exists() and file_path.is_file():
                return name  # 返回找到的文件名

        # 策略2: 如果精确匹配失败，尝试模糊匹配
        try:
            # 列出所有文件
            all_files = list(knowledge_dir.glob('*'))

            # 优先级1: 完全匹配（忽略大小写和扩展名）
            for file_path in all_files:
                if file_path.is_file():
                    file_name = file_path.name
                    # 移除扩展名后比较
                    raw_no_ext = Path(raw_filename).stem
                    file_no_ext = file_path.stem

                    if raw_no_ext.lower() == file_no_ext.lower():
                        return file_name

            # 优先级2: 包含匹配
            raw_lower = raw_filename.lower()
            for file_path in all_files:
                if file_path.is_file():
                    file_name = file_path.name
                    file_lower = file_name.lower()

                    # 检查是否互相包含
                    if raw_lower in file_lower or file_lower in raw_lower:
                        return file_name

        except Exception as e:
            print(f"⚠️ 文件名验证时出错: {e}")

        # 如果所有策略都失败，返回原始文件名（让前端 API 去处理）
        return raw_filename

    def _detect_mode(self, text: str) -> str:
        keywords = ["报关单", "HS编码", "申报要素", "境内收货人", "成交方式", "提运单号", "毛重", "净重"]
        hit_count = sum(1 for k in keywords if k in text)
        return "CUSTOMS" if hit_count >= 2 else "RESEARCH"

    def _compute_content_similarity(self, text1: str, text2: str) -> float:
        """计算两个文本的相似度（用于去重）"""
        # 使用字符级别的 Jaccard 相似度
        def get_chinese_chars(text):
            return set(c for c in text if '\u4e00' <= c <= '\u9fff')

        chars1 = get_chinese_chars(text1)
        chars2 = get_chinese_chars(text2)

        if not chars1 or not chars2:
            return 0.0

        intersection = chars1 & chars2
        union = chars1 | chars2
        return len(intersection) / len(union) if union else 0.0

    def _evaluate_content_richness(self, snippet: str) -> float:
        """评估内容丰富度 (0-1)"""
        if not snippet or snippet == "（无本地依据）":
            return 0.0

        score = 0.0
        length = len(snippet)

        # 长度评分
        if length >= 200: score += 0.4
        elif length >= 100: score += 0.3
        elif length >= 50: score += 0.2
        else: score += 0.1

        # 信息密度
        if re.search(r'\d+', snippet): score += 0.2  # 包含数字
        if re.search(r'[：:、,，]', snippet): score += 0.2  # 包含结构化标点
        if re.search(r'(\d+\.|[-•])', snippet): score += 0.2  # 包列举标记

        return min(score, 1.0)

    def _evaluate_cumulative_evidence(self, section_notes: List[str]) -> float:
        """评估累积证据的充分度 (0-1)"""
        if not section_notes:
            return 0.0

        combined_text = " ".join(section_notes)
        score = 0.0

        # 总信息量
        total_length = len(combined_text)
        if total_length >= 500: score += 0.4
        elif total_length >= 300: score += 0.3
        elif total_length >= 150: score += 0.2
        else: score += 0.1

        # 关键词多样性
        unique_keywords = set(re.findall(r'关键词\[([^\]]+)\]', combined_text))
        if len(unique_keywords) >= 3: score += 0.3
        elif len(unique_keywords) >= 2: score += 0.2
        else: score += 0.1

        # 内容重复度（越低越好）
        if len(section_notes) > 1:
            similarities = []
            for i in range(len(section_notes)):
                for j in range(i+1, len(section_notes)):
                    sim = self._compute_content_similarity(section_notes[i], section_notes[j])
                    similarities.append(sim)
            if similarities:
                avg_sim = sum(similarities) / len(similarities)
                score += (1 - avg_sim) * 0.3

        return min(score, 1.0)

    def _should_continue_research(
        self, current_round: int, snippet: str, score: float,
        section_notes: List[str], mode: str, config: dict
    ) -> tuple[bool, str]:
        """智能决策是否继续检索"""
        mode_config = config["rules"][mode]
        min_rounds = mode_config["min_rounds"]
        max_rounds = mode_config["max_rounds"]
        early_stop_threshold = mode_config["early_stop_threshold"]
        force_continue_threshold = mode_config.get("force_continue_threshold", 0.4)

        # 强制边界条件
        if current_round < min_rounds:
            return True, f"未达到最小轮数 ({min_rounds})"
        if current_round >= max_rounds:
            return False, f"已达到最大轮数限制 ({max_rounds})"

        # 计算质量评分
        metrics = config["quality_metrics"]

        score_component = score * metrics["score_weight"]
        richness = self._evaluate_content_richness(snippet)
        richness_component = richness * metrics["content_weight"]

        # 去重评估
        if section_notes:
            max_sim = max(self._compute_content_similarity(snippet, note) for note in section_notes)
            dedup_threshold = metrics.get("dedup_threshold", 0.85)
            dedup_score = 0.0 if max_sim > dedup_threshold else 1.0
        else:
            dedup_score = 1.0

        dedup_component = dedup_score * metrics["dedup_weight"]

        # 累积证据度
        evidence_score = self._evaluate_cumulative_evidence(section_notes)
        evidence_component = evidence_score * metrics["evidence_weight"]

        # 综合评分
        total_quality_score = score_component + richness_component + dedup_component + evidence_component

        # 决策逻辑
        if total_quality_score >= early_stop_threshold:
            reason = f"质量评分 {total_quality_score:.2f} ≥ 阈值 {early_stop_threshold}"
            return False, reason

        if total_quality_score < force_continue_threshold and current_round >= min_rounds + 1:
            reason = f"连续质量评分过低 ({total_quality_score:.2f}), 停止以节省资源"
            return False, reason

        continue_reason = f"质量评分 {total_quality_score:.2f} < 阈值 {early_stop_threshold}, 继续深度检索"
        return True, continue_reason

    # ==================== AI 决策系统辅助函数 ====================

    def _get_quality_rating(self, score: float) -> str:
        """根据相似度返回星级评级"""
        if score >= 0.75: return "⭐⭐⭐"
        elif score >= 0.55: return "⭐⭐"
        else: return "⭐"

    def _build_history_table(self, search_history: List[SearchRecord]) -> str:
        """生成检索历史 Markdown 表格"""
        if not search_history:
            return "无检索历史"

        # 表头
        header = "轮次 | 关键词 | 相似度 | 内容摘要 | 评级\n"
        separator = "---|---|---|---|---\n"

        # 表行 (最多显示前3轮)
        rows = []
        for record in search_history[:3]:
            query_short = record.query[:12] + "..." if len(record.query) > 15 else record.query
            snippet_short = record.snippet[:12] + "..." if len(record.snippet) > 15 else record.snippet
            rating = self._get_quality_rating(record.score)

            row = f"{record.round} | {query_short} | {record.score:.2f} | {snippet_short} | {rating}"
            rows.append(row)

        return header + separator + "\n".join(rows)

    def _calculate_trend(self, current_score: float, history: List[SearchRecord]) -> str:
        """计算质量变化趋势"""
        if not history:
            return ""

        prev_score = history[-1].score
        diff = current_score - prev_score

        if abs(diff) < 0.03:
            return "→持平"
        elif diff > 0:
            return f"↑{diff:.2f}"
        else:
            return f"↓{abs(diff):.2f}"

    def _calculate_coverage(self, snippets: List[str]) -> Set[str]:
        """计算证据覆盖的关键领域"""
        coverage_keywords = {
            "审核标准": ["审核", "检查", "标准", "要求", "规范"],
            "风险分析": ["风险", "问题", "隐患", "注意"],
            "违规案例": ["案例", "查处", "违规", "违法"],
            "处罚依据": ["处罚", "条例", "法律", "规定"],
            "行业基准": ["市场价", "基准", "参考", "行业"]
        }

        covered = set()
        all_text = " ".join(snippets)

        for area, keywords in coverage_keywords.items():
            if any(kw in all_text for kw in keywords):
                covered.add(area)

        return covered

    def _build_coverage_checklist(self, covered: Set[str]) -> str:
        """生成覆盖度检查清单"""
        all_areas = ["审核标准", "风险分析", "违规案例", "处罚依据", "行业基准"]

        items = []
        for area in all_areas:
            if area in covered:
                items.append(f"✅{area}")
            else:
                items.append(f"❌{area}")

        return " ".join(items)

    def _calculate_sufficiency(self, coverage: Set[str]) -> Tuple[float, str]:
        """计算证据充分性"""
        total_areas = 5  # 总共5个领域
        covered_count = len(coverage)

        percent = covered_count / total_areas

        if percent >= 0.7:
            level = "充分"
        elif percent >= 0.5:
            level = "中等"
        else:
            level = "不足"

        return percent, level

    def _build_feature_checklist(self, snippet: str) -> str:
        """生成内容特征检查清单"""
        checks = []
        if re.search(r'\d+', snippet):
            checks.append("数字✓")
        if re.search(r'[：:、,，]', snippet):
            checks.append("标点✓")
        if re.search(r'[条例]{2}|第[一二三四\d]+条', snippet):
            checks.append("法规✓")

        return " ".join(checks) if checks else "基础文本"

    def _calculate_quality_metrics(
        self, context: ResearchContext, config: dict
    ) -> QualityMetrics:
        """计算完整的质量指标"""
        metrics = config["quality_metrics"]

        # 1. 相似度分量
        score_component = context.current_score * metrics["score_weight"]

        # 2. 内容丰富度
        richness = self._evaluate_content_richness(context.current_snippet)
        richness_component = richness * metrics["content_weight"]

        # 3. 去重分量
        if context.search_history:
            max_sim = max(
                self._compute_content_similarity(context.current_snippet, record.snippet)
                for record in context.search_history
            )
            dedup_threshold = metrics.get("dedup_threshold", 0.85)
            dedup_score = 0.0 if max_sim > dedup_threshold else 1.0
        else:
            dedup_score = 1.0

        dedup_component = dedup_score * metrics["dedup_weight"]
        duplication_percent = 1.0 - dedup_score

        # 4. 累积证据度
        all_snippets = [record.snippet for record in context.search_history] + [context.current_snippet]
        evidence_score = self._evaluate_cumulative_evidence(all_snippets)
        evidence_component = evidence_score * metrics["evidence_weight"]

        # 综合评分
        total_quality = score_component + richness_component + dedup_component + evidence_component

        # 质量等级
        if total_quality >= 0.7:
            quality_level = "优秀"
            quality_stars = "⭐⭐⭐"
        elif total_quality >= 0.5:
            quality_level = "中等"
            quality_stars = "⭐⭐"
        else:
            quality_level = "较差"
            quality_stars = "⭐"

        # 趋势指示器
        trend_indicator = self._calculate_trend(context.current_score, context.search_history)

        # 内容特征
        has_numbers = bool(re.search(r'\d+', context.current_snippet))
        has_punctuation = bool(re.search(r'[：:、,，]', context.current_snippet))
        has_citation = bool(re.search(r'[条例]{2}|第[一二三四\d]+条', context.current_snippet))

        # 证据覆盖度
        coverage_areas = self._calculate_coverage(all_snippets)
        sufficiency_percent, _ = self._calculate_sufficiency(coverage_areas)

        return QualityMetrics(
            score_component=score_component,
            richness_component=richness_component,
            dedup_component=dedup_component,
            evidence_component=evidence_component,
            total_quality=total_quality,
            quality_level=quality_level,
            quality_stars=quality_stars,
            trend_indicator=trend_indicator,
            has_numbers=has_numbers,
            has_punctuation=has_punctuation,
            has_citation=has_citation,
            coverage_areas=coverage_areas,
            sufficiency_percent=sufficiency_percent,
            duplication_percent=duplication_percent
        )

    def _build_decision_prompt(
        self, context: ResearchContext, metrics: QualityMetrics
    ) -> str:
        """构建 AI 决策 Prompt"""
        # 准备章节信息
        chapter_title_short = context.chapter_title[:20] + "..." if len(context.chapter_title) > 20 else context.chapter_title

        # 构建检索历史表格
        history_table = self._build_history_table(context.search_history)

        # 准备当前检索信息
        current_query_short = context.current_query[:20] + "..." if len(context.current_query) > 20 else context.current_query
        current_snippet_preview = context.current_snippet[:30] + "..." if len(context.current_snippet) > 30 else context.current_snippet
        feature_checklist = self._build_feature_checklist(context.current_snippet)
        content_length = len(context.current_snippet)

        # 构建证据充分性分析
        coverage_checklist = self._build_coverage_checklist(metrics.coverage_areas)
        sufficiency_percent, sufficiency_level = self._calculate_sufficiency(metrics.coverage_areas)
        evidence_count = len(context.search_history) + 1  # 包括当前
        total_chars = sum(len(r.snippet) for r in context.search_history) + len(context.current_snippet)

        # 构建 Prompt
        prompt = f"""你是【检索决策助手】。判断是否继续检索知识库。

【当前状态】
- 章节: 第{context.chapter_index}章"{chapter_title_short}" (共{context.total_chapters}章)
- 轮次: 第{context.current_round}轮 / 最小{context.min_rounds}轮 / 最大{context.max_rounds}轮
- 模式: {context.mode}

【检索历史】
{history_table}

【当前检索】第{context.current_round}轮
- 关键词: "{current_query_short}"
- 相似度: {context.current_score:.2f} ({metrics.quality_level}{metrics.trend_indicator})
- 内容: "{current_snippet_preview}"
- 长度: {content_length}字
- 含: {feature_checklist}
- 质量: {metrics.quality_stars}

【证据充分性】
已收集{evidence_count}条证据 (约{total_chars}字)
覆盖: {coverage_checklist}
重复度: {metrics.duplication_percent:.0%}
充分性: {sufficiency_percent:.0%} ({sufficiency_level})

【决策标准】
✅ 停止检索: 充分性≥70% 或 (达到最大轮数) 或 (连续质量<0.5且重复度>30%)
❌ 继续检索: 充分性<50% 或 质量评分≥0.7且有明显提升趋势

返回JSON:
{{
  "decision": "continue" | "stop",
  "confidence": 0.0-1.0,
  "reason": "简短理由 (20-30字)",
  "missing_aspects": ["缺失方面1", "缺失方面2"]
}}"""
        return prompt

    async def _ask_llm_for_decision(self, prompt: str) -> dict:
        """调用 LLM 进行决策"""
        try:
            response = await self.llm.ainvoke([
                SystemMessage(content="你是检索决策助手，返回纯JSON，不要其他格式。"),
                HumanMessage(content=prompt)
            ])

            content = response.content.strip()

            # 尝试提取 JSON（处理 markdown 代码块格式）
            json_str = content

            # 如果响应包含 markdown 代码块，提取其中的 JSON
            if "```" in content:
                import re
                json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    # 尝试直接匹配 JSON 对象
                    json_match = re.search(r'\{.*\}', content, re.DOTALL)
                    if json_match:
                        json_str = json_match.group(0)

            # 解析 JSON
            decision = json.loads(json_str)
            return {
                "decision": decision.get("decision", "continue"),
                "confidence": decision.get("confidence", 0.5),
                "reason": decision.get("reason", ""),
                "missing_aspects": decision.get("missing_aspects", [])
            }
        except json.JSONDecodeError as e:
            print(f"⚠️ AI 响应 JSON 解析失败: {e}")
            print(f"   原始响应: {response.content[:200]}")
            return {
                "decision": "continue",
                "confidence": 0.0,
                "reason": "AI 响应解析失败，采用保守策略",
                "missing_aspects": []
            }
        except Exception as e:
            print(f"⚠️ AI 决策调用失败: {e}")
            return {
                "decision": "continue",
                "confidence": 0.0,
                "reason": f"AI 调用异常: {str(e)[:30]}",
                "missing_aspects": []
            }

    async def _should_continue_with_ai(
        self, context: ResearchContext, config: dict
    ) -> Tuple[bool, str, str]:
        """
        使用 AI 决策是否继续检索（带降级策略）

        Returns:
            (should_continue, reason, source)
            source: "ai" 或 "rule" (表示降级到规则)
        """
        try:
            # 计算质量指标
            metrics = self._calculate_quality_metrics(context, config)

            # 构建 Prompt
            prompt = self._build_decision_prompt(context, metrics)

            # 调用 AI 决策
            decision_result = await self._ask_llm_for_decision(prompt)

            should_continue = decision_result["decision"] == "continue"
            reason = decision_result["reason"]

            return should_continue, reason, "ai"

        except Exception as e:
            # 降级到规则决策
            print(f"⚠️ AI 决策失败: {e}, 降级到规则决策")

            should_continue, reason = self._should_continue_research(
                current_round=context.current_round,
                snippet=context.current_snippet,
                score=context.current_score,
                section_notes=[r.snippet for r in context.search_history],
                mode=context.mode,
                config=config
            )

            return should_continue, reason + " (规则降级)", "rule"

    async def generate_stream(self, input_text: str, language: str = "zh", stream_chunks: bool = True) -> AsyncGenerator[str, None]:
        """
        核心生成流

        Args:
            input_text: 输入文本
            language: 语言 (zh/vi)
            stream_chunks: 是否发送 report_chunk 事件（工具调用时应设为 False）
        """
        # 0. 立即握手
        engine_start = self._get_ui_text("engine_start", language)
        yield self._sse("thought", f"🚀 {engine_start}")
        await asyncio.sleep(0.1)

        # 🔥 清空报告缓冲区（为新的生成做准备）
        self.report_text_buffer = ""

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
                    # 加载智能检索配置
                    research_config = self._load_research_config()
                    max_possible_rounds = research_config["rules"][mode]["max_rounds"]

                    round_idx = 0
                    continue_research = True

                    while continue_research and round_idx < max_possible_rounds:
                        round_idx += 1
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

                                        # 🔥 新增：从 metadata 提取文件名并验证
                                        raw_filename = Path(doc.metadata.get("source", "unknown")).name

                                        # 验证文件名是否确实存在，如果不存在则尝试修复
                                        filename = self._validate_and_fix_filename(raw_filename)

                                        score = similarity
                            except asyncio.TimeoutError:
                                pass # 超时忽略
                            except Exception as e:
                                print(f"检索异常: {e}")

                        # 🔥 改进：返回完整的 RAG 匹配片段（而不是截断）
                        # FAISS 返回的 page_content 已经是一个 chunk（约1500字符）
                        # 这些内容是与查询最相关的部分，应该完整展示

                        # 调试日志：查看实际发送的内容
                        print(f"\n🔍 [RAG_DEBUG] 查询: {query}")
                        print(f"📄 [RAG_DEBUG] 文件: {filename}")
                        print(f"📏 [RAG_DEBUG] snippet 长度: {len(snippet)} 字符")
                        print(f"📝 [RAG_DEBUG] snippet 内容（前200字）:")
                        print(snippet[:200])
                        print(f"📝 [RAG_DEBUG] snippet 内容（后200字）:")
                        print(snippet[-200:] if len(snippet) > 200 else snippet)
                        print("-" * 80)

                        yield self._sse("rag_result", {
                            "filename": filename,
                            "score": float(score),
                            "snippet": snippet  # 完整的 chunk，不截断
                        })
                        section_notes.append(f"关键词[{query}] -> {snippet[:200]}...")
                        state["notebook"].append(f"关键词[{query}] -> {snippet[:200]}...")

                        yield self._sse("take_note", {"content": f"{query}: {snippet[:20]}..."})

                        # 🔥 AI 决策系统：构建检索上下文
                        # 构建 SearchRecord 列表
                        search_records = []
                        for hist_round, hist_query in enumerate(section_search_history, 1):
                            # 从 section_notes 中提取对应的 snippet
                            hist_note = f"关键词[{hist_query}] ->"
                            for note in section_notes:
                                if note.startswith(hist_note):
                                    hist_snippet = note.replace(hist_note, "")
                                    # 从 state["notebook"] 中找对应的 score
                                    # 简化处理：使用估算的相似度
                                    hist_score = score if hist_round == round_idx else 0.65
                                    search_records.append(SearchRecord(
                                        round=hist_round,
                                        query=hist_query,
                                        snippet=hist_snippet,
                                        score=hist_score
                                    ))
                                    break

                        # 构建当前检索的 SearchRecord（不包括在 search_records 中）
                        current_record = SearchRecord(
                            round=round_idx,
                            query=query,
                            snippet=snippet,
                            score=score
                        )

                        # 构建 ResearchContext
                        context = ResearchContext(
                            chapter_index=i + 1,
                            chapter_title=section_title,
                            total_chapters=len(toc_list),
                            current_round=round_idx,
                            min_rounds=research_config["rules"][mode]["min_rounds"],
                            max_rounds=research_config["rules"][mode]["max_rounds"],
                            mode=mode,
                            search_history=search_records,
                            current_query=query,
                            current_snippet=snippet,
                            current_score=score
                        )

                        # 🔥 调用 AI 决策（带降级策略）
                        should_continue, reason, source = await self._should_continue_with_ai(
                            context=context,
                            config=research_config
                        )

                        # 计算质量指标用于前端展示
                        metrics = self._calculate_quality_metrics(context, research_config)

                        # 向前端发送决策事件（增强版，包含 source 和 confidence）
                        yield self._sse("research_decision", {
                            "round": round_idx,
                            "decision": "continue" if should_continue else "stop",
                            "reason": reason,
                            "source": source,  # "ai" 或 "rule"
                            "confidence": 0.8 if source == "ai" else 1.0,  # 简化处理
                            "metrics": {
                                "score": metrics.score_component / 0.4,  # 反推原始分数
                                "richness": metrics.richness_component / 0.3,
                                "dedup": metrics.dedup_component / 0.2,
                                "evidence": metrics.evidence_component / 0.1,
                                "total_quality": metrics.total_quality
                            }
                        })

                        continue_research = should_continue

                        if should_continue:
                            source_badge = "[AI决策]" if source == "ai" else "[规则]"
                            yield self._sse("thought", f"[继续] {source_badge} {reason}")
                            await asyncio.sleep(0.3)
                        else:
                            source_badge = "[AI决策]" if source == "ai" else "[规则]"
                            yield self._sse("thought", f"[停止] {source_badge} {reason}")
                            await asyncio.sleep(0.5)

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
                        # 🔥 同时累积到 state 和实例缓冲区
                        state["full_report_text"] += chunk.content
                        self.report_text_buffer += chunk.content  # 实例缓冲区（工具可读取）

                        # 🔥 只有在 stream_chunks=True 时才发送 report_chunk 事件
                        # 工具调用时应设为 False，避免内容泄露到聊天界面
                        if stream_chunks:
                            yield self._sse("report_chunk", chunk.content)
                
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