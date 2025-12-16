import time
import json
import asyncio
from datetime import datetime
from typing import AsyncGenerator

# 导入我们之前写好的模块
from src.core.prompt_builder import PromptBuilder
from src.services.llm_service import LLMService

class RiskAnalysisOrchestrator:
    def __init__(self):
        # 初始化各个组件
        self.prompt_builder = PromptBuilder()
        self.llm_service = LLMService()
        
        # 获取所有已启用的规则
        # 过滤掉 enabled: false 的规则
        self.active_rules = [r for r in self.prompt_builder.config['rules'] if r.get('enabled', True)]

    async def analyze_stream(self, raw_data_context: str) -> AsyncGenerator[str, None]:
        """
        核心流式分析函数。
        这是一个异步生成器 (Async Generator)，专门配合 FastAPI 的 StreamingResponse 使用。
        
        Yields:
            str: 符合 SSE (Server-Sent Events) 格式的字符串
            格式示例: "data: {...json...}\n\n"
        """
        
        # --- 阶段 1: 初始化握手 ---
        # 告诉前端：我们要开始干活了，一共有多少步。
        # 前端收到这个后，可以先画出 5 个灰色的步骤条。
        init_payload = {
            "type": "init",
            "timestamp": datetime.now().isoformat(),
            "total_steps": len(self.active_rules),
            "steps_info": [
                {
                    "id": rule['id'],
                    "title": rule['display']['title'],
                    "icon": rule['display']['icon']
                } for rule in self.active_rules
            ]
        }
        yield self._format_sse(init_payload)
        
        # 稍微停顿一下，给前端渲染初始界面的时间
        await asyncio.sleep(0.5)

        # 收集最终的风险计数，用于最后生成总结报告
        risk_count = 0
        risk_details = []

        # --- 阶段 2: 逐条规则执行循环 ---
        for index, rule in enumerate(self.active_rules):
            rule_id = rule['id']
            rule_name = rule['display']['title']
            
            # 2.1 [状态推送] 开始处理当前步骤
            # 前端收到这个，对应的步骤条开始转圈圈 (Loading)
            yield self._format_sse({
                "type": "step_start",
                "rule_id": rule_id,
                "loading_text": rule['display']['loading_text']
            })
            
            # --- 模拟 AI 思考的“呼吸感” ---
            # 真实请求可能很快，但为了演示效果，我们强制让它至少“思考”1秒
            # 这样领导能看清“正在比对国家禁止目录...”这几个字
            start_time = time.time()
            
            # 2.2 [核心逻辑] 构建 Prompt + 调用 LLM
            # 这里最好用 await 异步调用，防止阻塞主线程
            # (注：requests 是同步的，如果并发高需换 httpx，但演示够用了，这里用 asyncio.to_thread 包装一下)
            system_prompt = self.prompt_builder.build_system_prompt()
            user_prompt = self.prompt_builder.build_user_prompt(raw_data_context, rule)
            
            # 在线程池中执行同步的 LLM 调用，不阻塞 Event Loop
            llm_result = await asyncio.to_thread(
                self.llm_service.call_llm, system_prompt, user_prompt
            )
            
            # 解构结果：["符号", "理由"]
            status_symbol, message = llm_result[0], llm_result[1]
            
            # 判断是否风险（x 为风险）
            is_risk = "x" in status_symbol.lower() or "fail" in status_symbol.lower()
            if is_risk:
                risk_count += 1
                risk_details.append(f"{rule_name}: {message}")

            # --- 节奏控制 ---
            # 如果 LLM 响应太快(<1.5s)，强行补足剩余时间
            elapsed = time.time() - start_time
            if elapsed < 1.5:
                await asyncio.sleep(1.5 - elapsed)
            
            # 2.3 [状态推送] 推送当前步骤结果
            # 前端收到这个，步骤条停止转圈，变绿(√)或变红(x)，并展开文字
            yield self._format_sse({
                "type": "step_result",
                "rule_id": rule_id,
                "status": "risk" if is_risk else "pass",
                "icon": status_symbol,  # √ 或 x
                "message": message,
                "color": "red" if is_risk else "green" # 覆盖默认颜色
            })
            
            # 步骤之间稍微喘口气
            await asyncio.sleep(1)

        # --- 阶段 3: 最终总结 ---
        # 所有步骤跑完，给出一个总结论
        final_conclusion = "✅ 建议放行：未发现明显风险点。"
        final_status = "pass"
        
        if risk_count > 0:
            final_conclusion = f"⚠️ 建议转人工查验：共发现 {risk_count} 项风险指标。\n" + "\n".join(risk_details)
            final_status = "risk"

        yield self._format_sse({
            "type": "complete",
            "final_status": final_status,
            "summary": final_conclusion
        })

    def _format_sse(self, data: dict) -> str:
        """
        格式化为 Server-Sent Events 标准协议字符串。
        格式：data: <json_string>\n\n
        """
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

# --- 单元测试 (Async 运行) ---
if __name__ == "__main__":
    async def test_run():
        orchestrator = RiskAnalysisOrchestrator()
        print("开始模拟流式输出...")
        
        # 模拟一段数据
        mock_data = "货物：废旧电池，单价：0.1美元"
        
        async for event in orchestrator.analyze_stream(mock_data):
            print(event.strip()) # 打印出来看看格式对不对

    asyncio.run(test_run())