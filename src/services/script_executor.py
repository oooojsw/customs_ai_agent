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
        执行 Python 脚本并返回结果（文件传参版本）

        通过临时 JSON 文件绕过 Windows 8KB 命令行限制
        :param script_path: 脚本的绝对路径
        :param args: 传递给脚本的参数字典
        :return: {'success': bool, 'result': Any, 'error': str}
        """
        try:
            import tempfile
            import sys

            # 1. 将参数写入临时 JSON 文件
            temp_dir = Path(tempfile.gettempdir())
            temp_file = temp_dir / f"temp_args_{id(args)}.json"

            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(args, f, ensure_ascii=False)

            # 2. 通过命令行传递临时文件路径
            result = subprocess.run(
                [sys.executable, str(script_path), str(temp_file)],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                encoding='utf-8'
            )

            # 3. 自动清理临时文件
            try:
                temp_file.unlink()
            except:
                pass

            # 4. 返回结果
            if result.returncode != 0:
                # 尝试从 stdout 解析错误（脚本可能打印了 JSON 错误信息）
                try:
                    stdout_error = json.loads(result.stdout)
                    if isinstance(stdout_error, dict) and 'error' in stdout_error:
                        return {
                            'success': False,
                            'error': stdout_error['error'],
                            'stdout': result.stdout,
                            'stderr': result.stderr
                        }
                except:
                    pass

                # 如果 stdout 不是 JSON，返回 stderr 和 stdout
                error_msg = result.stderr if result.stderr else result.stdout
                return {
                    'success': False,
                    'error': error_msg,
                    'stdout': result.stdout,
                    'stderr': result.stderr
                }

            # 5. 尝试解析 stdout 为 JSON
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
