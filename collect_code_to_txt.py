#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
收集项目所有代码文件内容到一个txt文件中
排除知识库文件（config/目录下的txt文件）
"""

import os
import sys
from pathlib import Path

def is_code_file(file_path):
    """判断是否为代码文件"""
    # 排除知识库文件：config/目录下的txt文件
    if "config" in str(file_path) and file_path.suffix == ".txt":
        return False
    
    # 排除其他非代码文件
    if file_path.name in [".env", ".gitignore", "README.md", "requirements.txt"]:
        return False
    
    # 排除缓存目录
    if "UsersZhuanZnpm-cache" in str(file_path) or ".cursor" in str(file_path) or ".roo" in str(file_path):
        return False
    
    # 排除日志文件
    if file_path.suffix == ".log":
        return False
    
    # 只包含特定扩展名的文件
    code_extensions = {'.py', '.json', '.js', '.ts', '.html', '.css', '.java', '.cpp', '.c', '.go', '.rs', '.rb', '.php'}
    return file_path.suffix in code_extensions

def collect_code_files(root_dir):
    """收集所有代码文件"""
    code_files = []
    root_path = Path(root_dir)
    
    for file_path in root_path.rglob("*"):
        if file_path.is_file() and is_code_file(file_path):
            # 计算相对路径
            rel_path = file_path.relative_to(root_path)
            code_files.append((rel_path, file_path))
    
    # 按路径排序
    code_files.sort(key=lambda x: str(x[0]))
    return code_files

def read_file_content(file_path):
    """读取文件内容"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except UnicodeDecodeError:
        try:
            with open(file_path, 'r', encoding='gbk') as f:
                return f.read()
        except:
            return f"无法读取文件: {file_path} (编码问题)"
    except Exception as e:
        return f"读取文件失败: {file_path} - {str(e)}"

def main():
    # 获取当前目录
    current_dir = os.getcwd()
    print(f"当前目录: {current_dir}")
    
    # 收集代码文件
    print("正在收集代码文件...")
    code_files = collect_code_files(current_dir)
    
    if not code_files:
        print("未找到代码文件！")
        return
    
    print(f"找到 {len(code_files)} 个代码文件:")
    for rel_path, _ in code_files:
        print(f"  - {rel_path}")
    
    # 输出文件
    output_file = "all_code_content.txt"
    print(f"\n正在写入到: {output_file}")
    
    with open(output_file, 'w', encoding='utf-8') as out_f:
        # 写入文件头
        out_f.write("=" * 80 + "\n")
        out_f.write("项目所有代码文件内容汇总\n")
        out_f.write(f"生成时间: {sys.version}\n")
        out_f.write(f"文件总数: {len(code_files)}\n")
        out_f.write("=" * 80 + "\n\n")
        
        # 写入每个文件的内容
        for i, (rel_path, file_path) in enumerate(code_files, 1):
            out_f.write(f"\n{'=' * 60}\n")
            out_f.write(f"文件 {i}/{len(code_files)}: {rel_path}\n")
            out_f.write(f"{'=' * 60}\n\n")
            
            content = read_file_content(file_path)
            out_f.write(content)
            
            # 如果不是最后一个文件，添加一些空行
            if i < len(code_files):
                out_f.write("\n\n")
    
    print(f"\n完成！所有代码内容已保存到: {output_file}")
    print(f"总文件数: {len(code_files)}")
    
    # 显示文件大小
    output_size = os.path.getsize(output_file)
    print(f"输出文件大小: {output_size:,} 字节 ({output_size/1024:.2f} KB)")

if __name__ == "__main__":
    main()