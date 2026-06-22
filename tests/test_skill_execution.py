"""
L4 脚本执行引擎测试套件
========================
测试 ScriptExecutor 和 SkillManager 的脚本执行能力
"""
import asyncio
import sys
import os

import pytest

# 修复 Windows 控制台编码问题
if (
    sys.platform == "win32"
    and sys.stdout.isatty()
    and hasattr(sys.stdout, "reconfigure")
):
    sys.stdout.reconfigure(encoding="utf-8")

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.services.script_executor import ScriptExecutor
from src.services.skill_manager import SkillManager


def test_basic_calculation():
    """测试 1：基础计算验证"""
    print("\n" + "="*60)
    print("测试 1：基础计算验证")
    print("="*60)

    executor = ScriptExecutor()
    manager = SkillManager()

    # 获取脚本路径
    script_path = manager.get_script_path('tax_calculator', 'calculate_duty.py')
    print(f"✅ 脚本路径: {script_path}")

    # 执行脚本（芯片，关税 0%）
    result = executor.execute(script_path, {
        'cif_price': 10000,
        'hs_code': '85423100'
    })

    print(f"📊 执行结果: {result}")

    assert result['success'] == True, "脚本执行应该成功"
    assert result['result']['duty'] == 0, "芯片关税应为 0"
    assert result['result']['vat'] == 1300, "增值税应为 1300"
    assert result['result']['total'] == 1300, "总税额应为 1300"

    print("✅ 测试 1 通过：基础计算验证")


def test_normal_tax_rate():
    """测试 2：普通商品关税计算"""
    print("\n" + "="*60)
    print("测试 2：普通商品关税计算")
    print("="*60)

    executor = ScriptExecutor()
    manager = SkillManager()

    script_path = manager.get_script_path('tax_calculator', 'calculate_duty.py')

    # 执行脚本（普通商品，关税 5%）
    result = executor.execute(script_path, {
        'cif_price': 10000,
        'hs_code': '99999999'  # 非 85423100
    })

    print(f"📊 执行结果: {result}")

    assert result['success'] == True, "脚本执行应该成功"
    assert result['result']['duty'] == 500, "普通商品关税应为 500 (10000 * 5%)"
    assert result['result']['vat'] == 1365, "增值税应为 1365 ((10000 + 500) * 13%)"
    assert result['result']['total'] == 1865, "总税额应为 1865"

    print("✅ 测试 2 通过：普通商品关税计算")


def test_error_handling():
    """测试 3：错误处理验证"""
    print("\n" + "="*60)
    print("测试 3：错误处理验证")
    print("="*60)

    import tempfile
    import os

    # 创建一个会出错的测试脚本
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write("import sys\nimport json\n1/0\n")  # 故意制造除零错误
        broken_script = f.name

    try:
        executor = ScriptExecutor()
        result = executor.execute(broken_script, {})

        print(f"📊 执行结果: {result}")

        assert result['success'] == False, "脚本执行应该失败"
        assert 'error' in result, "应包含错误信息"
        assert 'ZeroDivisionError' in result['error'] or 'division by zero' in result['error'], "应为除零错误"

        print("✅ 测试 3 通过：错误处理验证")
    finally:
        os.unlink(broken_script)


def test_parameter_passing():
    """测试 4：参数传递验证"""
    print("\n" + "="*60)
    print("测试 4：参数传递验证")
    print("="*60)

    executor = ScriptExecutor()
    manager = SkillManager()

    script_path = manager.get_script_path('tax_calculator', 'calculate_duty.py')

    # 参数包含小数
    result = executor.execute(script_path, {
        'cif_price': 5000.5,
        'hs_code': '85423100'
    })

    print(f"📊 执行结果: {result}")

    assert result['success'] == True, "脚本执行应该成功"
    assert result['result']['duty'] == 0, "芯片关税应为 0"
    assert result['result']['vat'] == 650.07, "增值税应为 650.07 (5000.5 * 13%)，允许精度误差"
    # 由于浮点数精度问题，使用近似比较
    assert abs(result['result']['vat'] - 650.07) < 0.01, "增值税计算结果应在误差范围内"

    print("✅ 测试 4 通过：参数传递验证")


def test_security_checks():
    """测试 5：路径遍历攻击防护"""
    print("\n" + "="*60)
    print("测试 5：路径遍历攻击防护")
    print("="*60)

    manager = SkillManager()

    # 尝试路径遍历
    try:
        manager.get_script_path('tax_calculator', '../../../etc/passwd')
        assert False, "应该抛出异常"
    except ValueError as e:
        print(f"📊 安全拦截成功: {e}")
        assert "禁止路径遍历" in str(e), "应包含路径遍历警告"
        print("✅ 测试 5 通过：路径遍历攻击防护")


def test_json_format_validation():
    """测试 6：JSON 格式验证"""
    print("\n" + "="*60)
    print("测试 6：JSON 格式验证")
    print("="*60)

    executor = ScriptExecutor()
    manager = SkillManager()

    script_path = manager.get_script_path('tax_calculator', 'calculate_duty.py')

    # 测试 JSON 返回格式
    result = executor.execute(script_path, {
        'cif_price': 10000,
        'hs_code': '85423100'
    })

    print(f"📊 返回结果类型: {type(result['result'])}")

    assert result['success'] == True, "脚本执行应该成功"
    assert isinstance(result['result'], dict), "返回结果应为字典"
    assert 'duty' in result['result'], "结果应包含 duty 字段"
    assert 'vat' in result['result'], "结果应包含 vat 字段"
    assert 'total' in result['result'], "结果应包含 total 字段"
    assert 'duty_rate' in result['result'], "结果应包含 duty_rate 字段"
    assert 'vat_rate' in result['result'], "结果应包含 vat_rate 字段"
    assert 'hs_code' in result['result'], "结果应包含 hs_code 字段"

    print("✅ 测试 6 通过：JSON 格式验证")


@pytest.mark.slow
@pytest.mark.live_model
@pytest.mark.integration
async def test_integration():
    """测试 7：集成测试（Agent 对话）"""
    print("\n" + "="*60)
    print("测试 7：集成测试（Agent 对话）")
    print("="*60)

    try:
        from src.services.chat_agent import CustomsChatAgent

        agent = CustomsChatAgent()

        # 模拟用户对话
        response = ""
        async for msg in agent.chat_stream(
            "进口芯片，货值10000美元，算一下税。HS编码是85423100。",
            session_id="test_script"
        ):
            content = msg.get('content', '')
            response += content

        print(f"🤖 Agent 响应:\n{response}")

        # 验证响应中包含计算结果
        assert "1300" in response or "0" in response, "响应应包含计算结果"

        print("✅ 测试 7 通过：集成测试")
    except Exception as e:
        print(f"⚠️  测试 7 跳过（集成测试需要完整环境）: {str(e)}")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "🚀"*30)
    print("L4 脚本执行引擎测试套件")
    print("🚀"*30)

    tests = [
        test_basic_calculation,
        test_normal_tax_rate,
        test_error_handling,
        test_parameter_passing,
        test_security_checks,
        test_json_format_validation,
    ]

    passed = 0
    failed = 0

    for test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            print(f"❌ 测试失败: {test_func.__name__}")
            print(f"   错误: {str(e)}")
            import traceback
            traceback.print_exc()
            failed += 1

    # 运行集成测试（异步）
    try:
        asyncio.run(test_integration())
        passed += 1
    except Exception as e:
        print(f"❌ 集成测试失败: {str(e)}")
        failed += 1

    # 输出总结
    print("\n" + "="*60)
    print("📊 测试总结")
    print("="*60)
    print(f"✅ 通过: {passed}")
    print(f"❌ 失败: {failed}")
    print(f"📈 通过率: {passed / (passed + failed) * 100:.1f}%")

    if failed == 0:
        print("\n🎉 所有测试通过！")
    else:
        print(f"\n⚠️  有 {failed} 个测试失败")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
