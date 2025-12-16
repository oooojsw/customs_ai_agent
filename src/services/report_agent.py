import json
import asyncio
import httpx
from typing import List, AsyncGenerator
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from pathlib import Path

# 导入配置
from src.config.loader import settings

class ComplianceReporter:
    def __init__(self):
        print("📑 [System] 初始化合规报告生成引擎 (DeepSeek Powered)...")
        
        # 1. 网络层配置 (修复点：区分 Sync 和 Async Transport)
        proxy_url = settings.HTTP_PROXY
        
        # ❌ 错误代码 (原): transport = httpx.HTTPTransport(...)
        # ✅ 修正代码 (新): 使用 AsyncHTTPTransport
        async_transport = httpx.AsyncHTTPTransport(proxy=proxy_url, verify=False)
        
        # 创建异步客户端
        self.async_client = httpx.AsyncClient(transport=async_transport, timeout=120.0)

        # 2. LLM 初始化 (DeepSeek)
        self.llm = ChatOpenAI(
            model=settings.DEEPSEEK_MODEL,
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            temperature=0.3, # 报告需要相对严谨
            # 关键：注入修复后的异步客户端
            http_async_client=self.async_client,
            streaming=True
        )

        # 3. 加载 SOP
        self.sop_content = self._load_sop()

    def _load_sop(self) -> str:
        """加载系统级 SOP 文件"""
        try:
            # 获取 config/sop_process.txt 的绝对路径
            base_dir = Path(__file__).resolve().parent.parent.parent
            sop_path = base_dir / "config" / "sop_process.txt"
            
            if sop_path.exists():
                with open(sop_path, "r", encoding="utf-8") as f:
                    return f.read()
            return "无系统SOP文件，请根据通用海关法规进行分析。"
        except Exception as e:
            print(f"⚠️ SOP 加载失败: {e}")
            return "无系统SOP文件。"

    async def generate_stream(self, raw_data: str) -> AsyncGenerator[str, None]:
        """
        核心生成流：规划 -> 执行循环 -> 完结
        yield: SSE 格式字符串
        """
        try:
            # --- 阶段 1: 规划 (Planning) ---
            yield self._sse_pack("planning", "正在分析数据并根据 SOP 规划报告目录...")
            
            # 调用 LLM 生成目录
            toc_list = await self._generate_toc(raw_data)
            
            # 推送目录给前端渲染
            yield self._sse_pack("toc_generated", {"steps": toc_list})
            await asyncio.sleep(0.5) 

            # --- 阶段 2: 执行 (Executing) ---
            # 维护对话历史 (Context Caching)
            history_messages = [
                SystemMessage(content=f"""你是一名资深海关合规审计专家。
依据以下 SOP 标准流程：
{self.sop_content}

你需要撰写一份专业的《进出口货物合规性审查报告》。
请保持语气客观、专业，重点指出风险点。不要使用 Markdown 代码块包裹整个回复。"""),
                HumanMessage(content=f"这是待审查的报关数据：\n{raw_data}\n\n请按照计划撰写报告。")
            ]

            # 循环生成每一章
            for index, section_title in enumerate(toc_list):
                # 2.1 推送状态：开始写这一章
                yield self._sse_pack("step_start", {"index": index, "title": section_title})
                
                # 2.2 构建当前章节的 Prompt
                step_prompt = f"请撰写报告的第 {index + 1} 部分：【{section_title}】。\n要求：内容详实，如果引用了法规请注明。直接输出 Markdown 内容，不要包含'好的'、'下面是...'等废话。"
                
                # 临时消息列表
                current_turn_messages = history_messages + [HumanMessage(content=step_prompt)]
                
                section_content = ""
                
                # 2.3 流式生成内容
                async for chunk in self.llm.astream(current_turn_messages):
                    if chunk.content:
                        content = chunk.content
                        section_content += content
                        yield self._sse_pack("step_stream", {"chunk": content})
                
                # 2.4 上下文缓存：将结果存入历史
                history_messages.append(HumanMessage(content=step_prompt))
                history_messages.append(AIMessage(content=section_content))
                
                # 2.5 推送状态：这一章完成
                yield self._sse_pack("step_done", {"index": index})
                
                await asyncio.sleep(0.5)

            # --- 阶段 3: 完结 ---
            yield self._sse_pack("done", {})
            
        except Exception as e:
            print(f"❌ 报告生成流中断: {e}")
            # 发送错误给前端
            yield f"data: {json.dumps({'type': 'error', 'payload': str(e)}, ensure_ascii=False)}\n\n"

    async def _generate_toc(self, raw_data: str) -> List[str]:
        """使用 LLM 生成目录结构 (JSON)"""
        prompt = f"""
分析以下报关数据和 SOP，列出合规审查报告的章节目录。
SOP摘要: {self.sop_content[:200]}...
数据摘要: {raw_data[:200]}...

要求：
1. 只返回一个 JSON 字符串数组。
2. 包含 3-5 个核心章节标题。
3. 必须包含“风险分析”和“改进建议”相关的章节。
4. 严禁输出 Markdown 代码块标记，只输出纯数组字符串。
"""
        messages = [
            SystemMessage(content="你是一个JSON生成器。只输出JSON数组，不要任何其他废话。"),
            HumanMessage(content=prompt)
        ]
        
        try:
            response = await self.llm.ainvoke(messages)
            content = response.content.strip()
            content = content.replace("```json", "").replace("```", "").strip()
            
            toc = json.loads(content)
            if isinstance(toc, list):
                return toc
            return ["1. 综合分析", "2. 风险提示", "3. 改进建议"]
        except Exception as e:
            print(f"❌ 目录生成失败: {e}")
            return ["1. 数据概览", "2. 详细审查", "3. 总结"]

    def _sse_pack(self, event_type: str, data: any) -> str:
        return f"data: {json.dumps({'type': event_type, 'payload': data}, ensure_ascii=False)}\n\n"