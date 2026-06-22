"""
测试 ComplianceReporter 热重载修复

验证 Reporter 的 async_client 属性命名一致性
"""
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def test_reporter_async_client_attribute():
    """测试 Reporter 是否有正确的 async_client 属性"""
    from src.services.report_agent import ComplianceReporter
    
    # 创建测试配置
    test_config = {
        'api_key': 'test-key',
        'base_url': 'https://api.test.com/v1',
        'model': 'test-model',
        'temperature': 0.3
    }
    
    # 初始化 Reporter
    reporter = ComplianceReporter(kb=None, llm_config=test_config)
    
    # 验证属性存在
    assert hasattr(reporter, 'async_client'), "Reporter 缺少 async_client 属性"
    assert not hasattr(reporter, '_async_client'), "Reporter 不应该有 _async_client 属性（命名不一致）"
    
    print("✅ Reporter async_client 属性验证通过")
    print(f"   - async_client 类型: {type(reporter.async_client)}")
    
    # 清理
    import asyncio
    asyncio.run(reporter.async_client.aclose())

if __name__ == "__main__":
    test_reporter_async_client_attribute()
    print("\n✅ 所有测试通过")
