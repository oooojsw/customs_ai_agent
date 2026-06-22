#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
深度研究工具链简单测试
验证核心功能是否正常工作
"""
import asyncio
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.integration]

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def test_tool_registration():
    """测试工具是否正确注册"""
    print("\n" + "="*60)
    print("【测试】验证深度研究工具注册")
    print("="*60)

    try:
        from src.services.chat_agent import CustomsChatAgent

        agent = CustomsChatAgent()

        # 检查工具列表
        tool_names = [t.name for t in agent.tools]

        print("\n已注册的工具列表:")
        for name in tool_names:
            print(f"  - {name}")

        # 验证三个深度研究工具是否存在
        required_tools = [
            "generate_compliance_report",
            "export_document_file",
            "read_report_buffer"
        ]

        missing_tools = []
        for tool_name in required_tools:
            if tool_name in tool_names:
                print(f"✅ {tool_name} 已注册")
            else:
                print(f"❌ {tool_name} 未注册")
                missing_tools.append(tool_name)

        if missing_tools:
            print(f"\n❌ 测试失败：缺少工具: {missing_tools}")
            return False
        else:
            print("\n✅ 所有深度研究工具已正确注册")
            return True

    except Exception as e:
        print(f"❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_export_engine():
    """测试 L4 导出脚本"""
    print("\n" + "="*60)
    print("【测试】L4 导出脚本（Markdown → Word）")
    print("="*60)

    try:
        import subprocess
        import json
        from pathlib import Path

        # 准备测试数据
        test_markdown = """# 测试报告

## 第一章：测试内容

这是一个测试报告。

- 测试项1
- 测试项2

## 第二章：结论

测试通过。
"""

        args = {
            "markdown": test_markdown,
            "output_dir": "data/exports"
        }

        # 调用 L4 脚本
        script_path = Path("data/skills/document_exporter/scripts/export_engine.py")
        if not script_path.exists():
            print(f"❌ 导出脚本不存在: {script_path}")
            return False

        print(f"📄 执行导出脚本: {script_path}")
        result = subprocess.run(
            ["python", str(script_path), json.dumps(args, ensure_ascii=False)],
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=30
        )

        if result.returncode != 0:
            print(f"❌ 脚本执行失败:")
            print(f"  错误: {result.stderr}")
            return False

        # 检查输出
        if not result.stdout:
            print(f"❌ 脚本无输出")
            return False

        # 解析输出
        output = result.stdout.strip()
        try:
            result_data = json.loads(output)
        except json.JSONDecodeError:
            print(f"❌ 输出不是有效的 JSON: {output}")
            return False

        if result_data.get('success'):
            print(f"✅ {result_data.get('message')}")
            print(f"📁 文件路径: {result_data.get('file_path')}")
            print(f"📄 文件名: {result_data.get('filename')}")
            return True
        else:
            print(f"❌ 导出失败: {result_data.get('error')}")
            return False

    except Exception as e:
        print(f"❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_report_buffer():
    """测试报告缓冲区"""
    print("\n" + "="*60)
    print("【测试】报告缓冲区（数据隧道机制）")
    print("="*60)

    try:
        from src.services.chat_agent import CustomsChatAgent

        agent = CustomsChatAgent()

        # 检查是否有报告生成器
        if not hasattr(agent, 'reporter') or agent.reporter is None:
            print("❌ 报告生成器未初始化")
            return False

        print("✅ 报告生成器已初始化")

        # 检查导出目录
        if not hasattr(agent, 'export_dir'):
            print("❌ 导出目录未初始化")
            return False

        print(f"✅ 导出目录: {agent.export_dir}")

        # 检查目录是否存在
        if not agent.export_dir.exists():
            print(f"❌ 导出目录不存在: {agent.export_dir}")
            return False

        print(f"✅ 导出目录存在")

        return True

    except Exception as e:
        print(f"❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主测试函数"""
    print("\n" + "="*60)
    print("深度研究工具链基础功能测试")
    print("="*60)

    results = []

    # 测试 1：工具注册
    try:
        result1 = await test_tool_registration()
        results.append(("工具注册测试", result1))
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        results.append(("工具注册测试", False))

    # 测试 2：L4 导出脚本
    try:
        result2 = await test_export_engine()
        results.append(("L4导出脚本测试", result2))
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        results.append(("L4导出脚本测试", False))

    # 测试 3：报告缓冲区
    try:
        result3 = await test_report_buffer()
        results.append(("报告缓冲区测试", result3))
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        results.append(("报告缓冲区测试", False))

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
        print("🎉 所有基础测试通过！")
        print("\n💡 下一步：")
        print("   1. 启动服务: python src/main.py")
        print("   2. 打开浏览器: http://localhost:8000")
        print("   3. 在功能二对话框中测试：")
        print("      '写一份关于二手挖掘机进口的合规建议书，直接给我 Word 版'")
    else:
        print("⚠️ 部分测试失败，请检查错误日志")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
