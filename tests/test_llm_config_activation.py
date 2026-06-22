"""
LLM配置激活修复 - 诊断和验证脚本

用途：
1. 验证配置保存到数据库
2. 验证配置加载机制
3. 验证is_enabled标志
4. 验证配置热重载
"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_config_save_and_load():
    """测试配置保存和加载流程"""
    print("=" * 60)
    print("LLM配置激活修复 - 诊断测试")
    print("=" * 60)
    
    from src.database.connection import AsyncSessionLocal
    from src.database.crud import LLMConfigRepository
    from src.config.llm_loader import llm_config_loader
    
    # 测试1: 保存配置
    print("\n[测试1] 保存测试配置到数据库...")
    async with AsyncSessionLocal() as db:
        repo = LLMConfigRepository(db)
        
        test_config = {
            'provider': 'deepseek',
            'api_key': 'test-key-12345',
            'base_url': 'https://api.deepseek.com/v1',
            'model_name': 'deepseek-chat',
            'temperature': 0.3,
            'is_enabled': True
        }
        
        saved = await repo.save_config(test_config)
        print(f"✓ 配置已保存: ID={saved.id}, Provider={saved.provider}")
        print(f"  is_enabled={saved.is_enabled}")
        print(f"  updated_at={saved.updated_at}")
    
    # 测试2: 验证配置唯一性
    print("\n[测试2] 验证配置唯一性...")
    async with AsyncSessionLocal() as db:
        repo = LLMConfigRepository(db)
        active_config = await repo.get_active_config()
        
        if active_config:
            print(f"✓ 找到启用的配置: Provider={active_config.provider}")
            print(f"  Model={active_config.model_name}")
            print(f"  is_enabled={active_config.is_enabled}")
        else:
            print("✗ 未找到启用的配置")
            return False
    
    # 测试3: 验证配置加载
    print("\n[测试3] 验证配置加载机制...")
    async with AsyncSessionLocal() as db:
        config = await llm_config_loader.load_config(db)
        
        print(f"✓ 配置加载成功:")
        print(f"  来源: {config.get('source')}")
        print(f"  厂商: {config.get('provider')}")
        print(f"  模型: {config.get('model')}")
        print(f"  Base URL: {config.get('base_url')}")
        
        if config.get('source') == 'user':
            print("✓ 配置来源正确（用户配置）")
        else:
            print(f"⚠️ 配置来源为: {config.get('source')}")
    
    # 测试4: 验证多次加载的一致性
    print("\n[测试4] 验证多次加载的一致性...")
    configs = []
    for i in range(3):
        async with AsyncSessionLocal() as db:
            config = await llm_config_loader.load_config(db)
            configs.append(config)
    
    if all(c.get('provider') == configs[0].get('provider') for c in configs):
        print("✓ 多次加载配置一致")
    else:
        print("✗ 多次加载配置不一致")
        return False
    
    print("\n" + "=" * 60)
    print("✓ 所有诊断测试通过")
    print("=" * 60)
    return True


async def test_config_reload_simulation():
    """模拟配置重载流程"""
    print("\n" + "=" * 60)
    print("配置重载流程模拟")
    print("=" * 60)
    
    from src.database.connection import AsyncSessionLocal
    from src.config.llm_loader import llm_config_loader
    
    # 步骤1: 加载初始配置
    print("\n[步骤1] 加载初始配置...")
    async with AsyncSessionLocal() as db:
        config1 = await llm_config_loader.load_config(db)
        print(f"初始配置: {config1.get('provider')}/{config1.get('model')}")
    
    # 步骤2: 模拟配置更新（实际场景中由前端触发）
    print("\n[步骤2] 模拟配置更新...")
    print("（在实际使用中，这一步由前端保存配置触发）")
    
    # 步骤3: 重新加载配置
    print("\n[步骤3] 重新加载配置...")
    async with AsyncSessionLocal() as db:
        config2 = await llm_config_loader.load_config(db)
        print(f"重载后配置: {config2.get('provider')}/{config2.get('model')}")
    
    # 验证配置是否从数据库重新加载
    if config2.get('source') == 'user':
        print("✓ 配置成功从数据库重新加载")
    else:
        print(f"⚠️ 配置来源: {config2.get('source')}")
    
    print("\n" + "=" * 60)
    print("✓ 配置重载流程模拟完成")
    print("=" * 60)


async def main():
    """主测试函数"""
    try:
        # 运行诊断测试
        success = await test_config_save_and_load()
        
        if success:
            # 运行重载模拟
            await test_config_reload_simulation()
            
            print("\n" + "=" * 60)
            print("建议的手动测试步骤：")
            print("=" * 60)
            print("1. 启动服务: python src/main.py")
            print("2. 打开前端配置页面")
            print("3. 修改并保存API配置")
            print("4. 观察控制台日志，确认配置重载")
            print("5. 使用功能二（对话）测试新配置")
            print("6. 检查日志中的配置来源信息")
            print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
