#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
依赖检查脚本

检查requirements.txt中的所有依赖是否已安装
验证项目运行所需的关键库

使用方法：
    python check_dependencies.py
"""

import sys
import subprocess
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))


def check_requirements_file():
    """检查requirements.txt文件是否存在"""
    print("\n" + "="*60)
    print("[Check 1] requirements.txt File")
    print("="*60)

    req_file = Path(__file__).parent / "requirements.txt"

    if not req_file.exists():
        print(f"[ERROR] requirements.txt not found: {req_file}")
        return False

    print(f"[OK] requirements.txt exists")

    # 统计依赖数量
    with open(req_file, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    print(f"[INFO] Total dependencies: {len(lines)}")
    return True


def check_installation_status():
    """检查关键依赖的安装状态"""
    print("\n" + "="*60)
    print("[Check 2] Key Dependencies Installation")
    print("="*60)

    # 定义关键依赖
    key_deps = {
        # Web框架
        'fastapi': 'Web framework',
        'uvicorn': 'ASGI server',

        # LangChain
        'langchain': 'LangChain core',
        'langchain_core': 'LangChain core',
        'langchain_community': 'LangChain community',
        'langchain_openai': 'LangChain OpenAI',
        'langchain_huggingface': 'Embeddings',
        'langchain_text_splitters': 'Text splitters',
        'langgraph': 'Agent orchestration',

        # LLM
        'openai': 'LLM client',

        # RAG
        'faiss': 'Vector database',
        'sentence_transformers': 'Sentence models',

        # PDF处理
        'pypdfium2': 'PDF text extraction',

        # 数据库
        'sqlalchemy': 'Database ORM',
        'aiosqlite': 'Async SQLite',

        # 工具
        'python_dotenv': 'Config management',
        'tiktoken': 'Token counting',
        'pydantic': 'Data validation',
        'httpx': 'HTTP client',
        'requests': 'HTTP requests',
    }

    all_ok = True
    missing_deps = []

    for module_name, description in key_deps.items():
        try:
            __import__(module_name)
            print(f"[OK] {module_name:25s} - {description}")
        except ImportError:
            print(f"[MISSING] {module_name:25s} - {description}")
            missing_deps.append(module_name)
            all_ok = False

    if all_ok:
        print(f"\n[OK] All key dependencies installed")
    else:
        print(f"\n[ERROR] Missing {len(missing_deps)} dependencies:")
        for dep in missing_deps:
            print(f"   - {dep}")
        print(f"\nFix: pip install -r requirements.txt")

    return all_ok


def check_pdf_dependencies():
    """检查PDF处理相关依赖"""
    print("\n" + "="*60)
    print("[Check 3] PDF Processing Dependencies")
    print("="*60)

    pdf_deps = {
        'pypdfium2': 'Fast PDF extraction (current)',
        'marker': 'Marker PDF library (backup)',
        'PIL': 'Pillow (image processing)',
        'torch': 'PyTorch (Marker dependency)',
        'transformers': 'HuggingFace Transformers',
    }

    all_ok = True

    for module_name, description in pdf_deps.items():
        try:
            __import__(module_name)
            print(f"[OK] {module_name:15s} - {description}")
        except ImportError:
            print(f"[WARNING] {module_name:15s} - {description}")
            all_ok = False

    if all_ok:
        print(f"\n[OK] All PDF dependencies installed")
    else:
        print(f"\n[WARNING] Some PDF dependencies missing")
        print(f"Note: pypdfium2 is the primary PDF library")

    return True  # PDF dependencies are optional


def check_version_compatibility():
    """检查版本兼容性"""
    print("\n" + "="*60)
    print("[Check 4] Version Compatibility")
    print("="*60)

    try:
        # 检查Python版本
        python_version = sys.version_info
        if python_version.major == 3 and python_version.minor >= 11:
            print(f"[OK] Python {python_version.major}.{python_version.minor}.{python_version.micro}")
        else:
            print(f"[WARNING] Python {python_version.major}.{python_version.minor}.{python_version.micro}")
            print(f"   Recommended: Python 3.11+")

        # 检查关键包版本
        import langchain
        print(f"[OK] langchain {langchain.__version__}")

        import fastapi
        print(f"[OK] fastapi {fastapi.__version__}")

        import sqlalchemy
        print(f"[OK] sqlalchemy {sqlalchemy.__version__}")

        return True

    except Exception as e:
        print(f"[ERROR] Version check failed: {e}")
        return False


def test_basic_functionality():
    """测试基本功能"""
    print("\n" + "="*60)
    print("[Check 5] Basic Functionality Test")
    print("="*60)

    try:
        # 测试导入
        from langchain_huggingface import HuggingFaceEmbeddings
        from langchain_community.vectorstores import FAISS
        from langchain_openai import ChatOpenAI
        from sqlalchemy import create_engine
        import pypdfium2

        print("[OK] All key imports successful")

        # 测试embedding模型加载
        print("[TEST] Loading embedding model...")
        embeddings = HuggingFaceEmbeddings(
            model_name="BAAI/bge-small-zh-v1.5"
        )
        print("[OK] Embedding model loaded")

        # 测试PDF库
        print("[TEST] Testing PDF library...")
        # pypdfium2不需要初始化
        print("[OK] PDF library ready")

        print(f"\n[OK] All functionality tests passed")
        return True

    except Exception as e:
        print(f"[ERROR] Functionality test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主函数"""
    print("\n" + "="*60)
    print("Dependency Check Tool")
    print("="*60)

    from datetime import datetime
    print(f"Check time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    results = {}

    # 运行所有检查
    results['requirements_file'] = check_requirements_file()
    results['installation'] = check_installation_status()
    results['pdf_deps'] = check_pdf_dependencies()
    results['versions'] = check_version_compatibility()

    if results['installation']:
        results['functionality'] = test_basic_functionality()

    # 总结
    print("\n" + "="*60)
    print("Check Summary")
    print("="*60)

    status_map = {
        True: "[OK] Pass",
        False: "[ERROR] Fail",
    }

    print(f"\nRequirements file:      {status_map.get(results['requirements_file'], '[WARNING] Unknown')}")
    print(f"Dependencies installed: {status_map.get(results['installation'], '[WARNING] Unknown')}")
    print(f"PDF dependencies:       {status_map.get(results['pdf_deps'], '[WARNING] Unknown')}")
    print(f"Version compatibility:   {status_map.get(results['versions'], '[WARNING] Unknown')}")

    if 'functionality' in results:
        print(f"Functionality test:     {status_map.get(results['functionality'], '[WARNING] Unknown')}")

    # 总体评估
    all_passed = all(v for v in results.values() if v is not None)

    if all_passed:
        print(f"\n[SUCCESS] All checks passed! Dependencies are complete.")
        print(f"\nNext steps:")
        print(f"   1. Run: python quick_rebuild.py  (if needed)")
        print(f"   2. Run: python src/main.py")
    else:
        print(f"\n[WARNING] Some checks failed.")
        print(f"\nFix: pip install -r requirements.txt")

    print("\n" + "="*60)


if __name__ == "__main__":
    main()
