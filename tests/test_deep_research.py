#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
深度研究工具链测试脚本
测试场景：
A. 全自动链路：生成报告 + 导出 Word
B. 按需感知：生成报告 → 查询细节 → 导出
"""
import asyncio
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.live_model, pytest.mark.integration]

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.chat_agent import CustomsChatAgent


async def test_full_chain():
    """测试场景 A：全自动链路测试"""
    print("\n" + "="*60)
    print("【测试场景 A】全自动链路：生成报告 + 导出 Word")
    print("="*60)

    agent = CustomsChatAgent()

    # 模拟用户对话
    user_input = "帮我写一份关于二手挖掘机进口的合规建议书，直接给我 Word 版"
    print(f"\n👤 用户: {user_input}")

    response = ""
    print("\n🤖 Agent 响应:")
    async for msg in agent.chat_stream(
        user_input,
        session_id="test_full_chain"
    ):
        if msg.startswith('data: '):
            data_str = msg[6:]
            import json
            try:
                data = json.loads(data_str)
                if data.get('type') == 'answer':
                    content = data.get('content', '')
                    response += content
                    print(content, end='', flush=True)
            except:
                pass

    print("\n")
    # 验证
    success = True
    if "报告已生成" not in response and "✅" not in response:
        print("❌ 测试失败：未检测到报告生成成功")
        success = False

    if "/downloads/" not in response:
        print("❌ 测试失败：未检测到下载链接")
        success = False

    if ".docx" not in response:
        print("❌ 测试失败：未检测到 Word 文件")
        success = False

    if success:
        print("✅ 测试通过：全自动链路")

    return success


async def test_on_demand_reading():
    """测试场景 B：按需感知测试"""
    print("\n" + "="*60)
    print("【测试场景 B】按需感知：生成报告 → 查询细节 → 导出")
    print("="*60)

    agent = CustomsChatAgent()

    # 第一轮：生成报告
    user_input1 = "写一份关于废旧电池进口的风险分析报告"
    print(f"\n👤 用户 (第一轮): {user_input1}")

    response1 = ""
    print("\n🤖 Agent 响应:")
    async for msg in agent.chat_stream(
        user_input1,
        session_id="test_on_demand_1"
    ):
        if msg.startswith('data: '):
            data_str = msg[6:]
            import json
            try:
                data = json.loads(data_str)
                if data.get('type') == 'answer':
                    content = data.get('content', '')
                    response1 += content
                    print(content, end='', flush=True)
            except:
                pass

    print("\n")
    if "报告已生成" not in response1:
        print("❌ 第一轮失败：未生成报告")
        return False

    # 第二轮：查询细节
    user_input2 = "报告里提到的第二项风险，具体的法律依据是哪一条？"
    print(f"\n👤 用户 (第二轮): {user_input2}")

    response2 = ""
    print("\n🤖 Agent 响应:")
    async for msg in agent.chat_stream(
        user_input2,
        session_id="test_on_demand_2"
    ):
        if msg.startswith('data: '):
            data_str = msg[6:]
            import json
            try:
                data = json.loads(data_str)
                if data.get('type') == 'answer':
                    content = data.get('content', '')
                    response2 += content
                    print(content, end='', flush=True)
            except:
                pass

    print("\n")
    if "海关法" not in response2 and "法律" not in response2:
        print("❌ 第二轮失败：未查询到法律依据")
        return False

    # 第三轮：导出 Word
    user_input3 = "把这个报告导出成 Word 文档"
    print(f"\n👤 用户 (第三轮): {user_input3}")

    response3 = ""
    print("\n🤖 Agent 响应:")
    async for msg in agent.chat_stream(
        user_input3,
        session_id="test_on_demand_3"
    ):
        if msg.startswith('data: '):
            data_str = msg[6:]
            import json
            try:
                data = json.loads(data_str)
                if data.get('type') == 'answer':
                    content = data.get('content', '')
                    response3 += content
                    print(content, end='', flush=True)
            except:
                pass

    print("\n")
    if "/downloads/" not in response3 or ".docx" not in response3:
        print("❌ 第三轮失败：未生成下载链接")
        return False

    print("✅ 测试通过：按需感知")
    return True


async def main():
    """主测试函数"""
    print("\n" + "="*60)
    print("深度研究工具链测试")
    print("="*60)

    results = []

    # 运行测试 A
    try:
        result_a = await test_full_chain()
        results.append(("场景A（全自动链路）", result_a))
    except Exception as e:
        print(f"❌ 场景A测试异常: {e}")
        import traceback
        traceback.print_exc()
        results.append(("场景A（全自动链路）", False))

    # 运行测试 B
    try:
        result_b = await test_on_demand_reading()
        results.append(("场景B（按需感知）", result_b))
    except Exception as e:
        print(f"❌ 场景B测试异常: {e}")
        import traceback
        traceback.print_exc()
        results.append(("场景B（按需感知）", False))

    # 输出测试总结
    print("\n" + "="*60)
    print("测试总结")
    print("="*60)
    for name, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"{name}: {status}")

    all_passed = all(success for _, success in results)
    print("\n" + "="*60)
    if all_passed:
        print("🎉 所有测试通过！")
    else:
        print("⚠️ 部分测试失败，请检查日志")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
