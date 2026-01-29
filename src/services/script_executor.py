"""
Python 脚本沙箱执行器（L4 层）
====================
安全执行技能包中的 Python 脚本，使用独立子进程模式
"""
import subprocess
import json
from pathlib import Path
from typing import Dict, Any


class ScriptExecutor:
    """Python 脚本沙箱执行器"""

    def __init__(self, timeout: int = 10):
        """
        初始化执行器
        :param timeout: 默认超时时间（秒），防止死循环
        """
        self.timeout = timeout

    def execute(self, script_path: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行 Python 脚本并返回结果
        :param script_path: 脚本的绝对路径
        :param args: 传递给脚本的参数字典
        :return: {'success': bool, 'result': Any, 'error': str}
        """
        try:
            # 1. 将参数字典序列化为 JSON 字符串
            args_json = json.dumps(args, ensure_ascii=False)

            # 2. 使用 subprocess 执行脚本
            result = subprocess.run(
                ['python', str(script_path), args_json],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                encoding='utf-8'
            )

            # 3. 检查执行是否成功
            if result.returncode != 0:
                return {
                    'success': False,
                    'error': result.stderr,
                    'stdout': result.stdout
                }

            # 4. 尝试解析 stdout 为 JSON
            try:
                parsed_result = json.loads(result.stdout)
                return {
                    'success': True,
                    'result': parsed_result,
                    'raw_output': result.stdout
                }
            except json.JSONDecodeError:
                # 如果不是 JSON，返回原始文本
                return {
                    'success': True,
                    'result': result.stdout,
                    'raw_output': result.stdout
                }

        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': f'脚本执行超时（超过 {self.timeout} 秒）'
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'执行异常: {str(e)}'
            }
