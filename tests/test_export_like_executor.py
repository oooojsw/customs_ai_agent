#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
使用与 ScriptExecutor 相同的方式测试导出脚本
"""
import sys
import subprocess
import json
from pathlib import Path

# 修复 Windows 控制台编码问题
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream.isatty() and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

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

# 调用 L4 脚本（使用与 ScriptExecutor 相同的方式）
script_path = Path("data/skills/document_exporter/scripts/export_engine.py")
print(f"测试脚本: {script_path}")

# 与 ScriptExecutor 完全相同的方式
args_json = json.dumps(args, ensure_ascii=False)

result = subprocess.run(
    ['python', str(script_path), args_json],
    capture_output=True,
    text=True,
    timeout=30,
    encoding='utf-8'
)

print(f"\n返回码: {result.returncode}")
print(f"\n标准输出:\n{result.stdout}")
if result.stderr:
    print(f"\n标准错误:\n{result.stderr}")

# 检查执行是否成功
if result.returncode != 0:
    print(f"\n脚本执行失败")
else:
    print(f"\n脚本执行成功")
    # 尝试解析 stdout 为 JSON
    try:
        parsed_result = json.loads(result.stdout)
        print(f"解析成功: {parsed_result}")

        if parsed_result.get('success'):
            print(f"\n导出成功!")
            print(f"文件路径: {parsed_result.get('file_path')}")
            print(f"文件名: {parsed_result.get('filename')}")

            # 验证文件是否存在
            file_path = Path(parsed_result.get('file_path'))
            if file_path.exists():
                print(f"文件已创建: {file_path}")
                print(f"文件大小: {file_path.stat().st_size} 字节")
            else:
                print(f"警告: 文件未找到")
        else:
            print(f"\n导出失败: {parsed_result.get('error')}")
    except json.JSONDecodeError as e:
        print(f"JSON 解析失败: {e}")
        print(f"原始输出: {result.stdout}")
