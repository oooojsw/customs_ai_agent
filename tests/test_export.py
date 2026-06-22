#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
单独测试导出脚本
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

# 调用 L4 脚本
script_path = Path("data/skills/document_exporter/scripts/export_engine.py")
print(f"测试脚本: {script_path}")
print(f"参数: {json.dumps(args, ensure_ascii=False)}")

# 使用 encoding='utf-8' 来正确处理输出
result = subprocess.run(
    ["python", str(script_path), json.dumps(args, ensure_ascii=False)],
    capture_output=True,
    text=False,  # 不使用 text 模式，手动解码
    timeout=30
)

# 手动解码输出（使用 UTF-8）
stdout = result.stdout.decode('utf-8') if result.stdout else ''
stderr = result.stderr.decode('utf-8', errors='replace') if result.stderr else ''

print(f"\n返回码: {result.returncode}")
print(f"\n标准输出:\n{stdout}")
if stderr:
    print(f"\n标准错误:\n{stderr}")

# 解析输出
if result.returncode == 0 and stdout:
    try:
        output_data = json.loads(stdout.strip())
        if output_data.get('success'):
            print(f"\n导出成功!")
            print(f"文件路径: {output_data.get('file_path')}")
            print(f"文件名: {output_data.get('filename')}")

            # 验证文件是否存在
            file_path = Path(output_data.get('file_path'))
            if file_path.exists():
                print(f"文件已创建: {file_path}")
                print(f"文件大小: {file_path.stat().st_size} 字节")
            else:
                print(f"警告: 文件未找到")
        else:
            print(f"\n导出失败: {output_data.get('error')}")
    except json.JSONDecodeError as e:
        print(f"\nJSON 解析失败: {e}")
else:
    print("\n脚本执行失败")
