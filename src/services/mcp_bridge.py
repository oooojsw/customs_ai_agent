"""
MCP 桥接器模块
管理 MCP 服务器生命周期，并完成 JSON Schema 向 Pydantic 模型的转换
"""
import asyncio
import sys
import os
from typing import List, Dict, Any, Optional
from pathlib import Path
from contextlib import AsyncExitStack
from pydantic import Field, create_model
from langchain_core.tools import StructuredTool

# MCP SDK 导入（带调试信息）
MCP_SDK_AVAILABLE = False
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    MCP_SDK_AVAILABLE = True
    print("[MCPBridge] ✅ MCP SDK 导入成功")
except Exception as e:
    print(f"[MCPBridge] ⚠️ MCP SDK 导入失败: {e}")
    import traceback
    traceback.print_exc()
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None


class MCPBridge:
    """MCP 桥接器 - 管理单个 MCP 服务器的生命周期"""

    def __init__(
        self,
        name: str,
        command: str,
        args: List[str],
        env: Optional[Dict[str, str]] = None,
        description: str = ""
    ):
        print(f"[MCPBridge] 📝 __init__ called with: command={command}, args={args}, env={env}")
        self.name = name
        self.description = description
        self.command = command
        self.args = args
        self.env = env
        self.server_params = None
        self.session = None
        self._exit_stack = AsyncExitStack()
        self.tools: List[StructuredTool] = []
        self._initialized = False
        print(f"[MCPBridge] 📝 __init__ completed, _exit_stack created")

    async def initialize(self, timeout: int = 30) -> List[StructuredTool]:
        """
        异步初始化：安全启动子进程并获取工具清单
        """
        print(f"[MCPBridge] 🔥 initialize() called for {self.name}")
        print(f"[MCPBridge] 🔥 MCP_SDK_AVAILABLE = {MCP_SDK_AVAILABLE}")
        
        if not MCP_SDK_AVAILABLE:
            print(f"[MCPBridge] ❌ {self.name}: MCP SDK 不可用")
            return []

        try:
            print(f"[MCPBridge] 🔄 {self.name}: 正在初始化...")

            # 不继承全部环境变量，只传递必要的最小环境集
            print(f"[MCPBridge] 🔸 步骤1: 构建最小环境变量集")
            essential_env = {}
            
            # 复制关键系统变量
            essential_vars = ['PATH', 'SYSTEMROOT', 'TEMP', 'TMP', 'USERPROFILE', 'USERNAME', 
                           'COMPUTERNAME', 'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS',
                           'PYTHONPATH', 'PYTHONHOME']
            for var in essential_vars:
                if var in os.environ:
                    essential_env[var] = os.environ[var]
            
            # 添加项目相关的环境变量（如果存在）
            project_vars = ['DEEPSEEK_API_KEY', 'DEEPSEEK_BASE_URL', 'DEEPSEEK_MODEL',
                          'ANTHROPIC_API_KEY', 'OPENCODE']
            for var in project_vars:
                if var in os.environ:
                    essential_env[var] = os.environ[var]
            
            merged_env = essential_env
            print(f"[MCPBridge] 🔸 环境变量数量: {len(merged_env)} (最小集)")
            if 'PATH' in merged_env:
                print(f"[MCPBridge] 🔸 PATH: {merged_env.get('PATH', 'N/A')[:200]}...")

            # 如果配置中有特殊 env，合并进去
            print(f"[MCPBridge] 🔸 步骤2: 合并配置中的env: {self.env}")
            if self.env:
                merged_env.update(self.env)
                print(f"[MCPBridge] 🔸 合并后env: {merged_env.get('CUSTOM_ENV', 'N/A')}")

            # 剔除网络代理
            print(f"[MCPBridge] 🔸 步骤3: 剔除代理环境变量")
            for proxy_key in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
                if proxy_key in merged_env:
                    print(f"[MCPBridge] 🔸 剔除代理: {proxy_key}")
                    merged_env.pop(proxy_key, None)

            # 剔除可能导致冲突的GIT/MSYS环境变量
            print(f"[MCPBridge] 🔸 步骤3.5: 剔除GIT/MSYS冲突环境变量")
            git_conflict_keys = ["MSYSTEM", "MSYS", "MINGW_PREFIX", "MINGW_PACKAGE_PREFIX", 
                                 "MINGW_CHOST", "MINGW_CARCH", "MINGW_PREFIX", "MSYSTEM_CARCH",
                                 "MSYSTEM_CHOST", "MSYSTEM_PREFIX"]
            for key in git_conflict_keys:
                if key in merged_env:
                    print(f"[MCPBridge] 🔸 剔除冲突变量: {key}")
                    merged_env.pop(key, None)

            # 获取项目根目录作为工作目录
            project_root = Path(__file__).resolve().parent.parent.parent
            print(f"[MCPBridge] 🔸 步骤3.6: 设置工作目录: {project_root}")

            # 直接使用 JSON 配置中的参数
            print(f"[MCPBridge] 🔸 步骤4: 构建StdioServerParameters")
            print(f"[MCPBridge] 🔸   command: {self.command}")
            print(f"[MCPBridge] 🔸   args: {self.args}")
            print(f"[MCPBridge] 🔸   env keys: {list(merged_env.keys())}")
            
            server_params = StdioServerParameters(
                command=self.command,
                args=self.args,
                env=merged_env,
                cwd=str(project_root)  # 关键：设置工作目录
            )
            print(f"[MCPBridge] 🔧 命令: {self.command} {' '.join(self.args)}")

            # 使用 exit_stack 托管上下文，防止提早退出断开连接
            print(f"[MCPBridge] 🔸 步骤5: 进入stdio_client上下文")
            print(f"[MCPBridge] 🔸 stdio_client object: {stdio_client}")
            print(f"[MCPBridge] 🔸 server_params: {server_params}")
            
            try:
                read, write = await self._exit_stack.enter_async_context(
                    stdio_client(server_params)
                )
                print(f"[MCPBridge] ✅ stdio_client 上下文进入成功!")
                print(f"[MCPBridge] 🔸 read object: {type(read)}, write object: {type(write)}")
            except Exception as e:
                print(f"[MCPBridge] ❌ stdio_client 进入失败: {e}")
                import traceback
                traceback.print_exc()
                raise

            print(f"[MCPBridge] 🔸 步骤6: 进入ClientSession上下文")
            try:
                self.session = await self._exit_stack.enter_async_context(
                    ClientSession(read, write)
                )
                print(f"[MCPBridge] ✅ ClientSession 上下文进入成功!")
                print(f"[MCPBridge] 🔸 session object: {self.session}")
            except Exception as e:
                print(f"[MCPBridge] ❌ ClientSession 进入失败: {e}")
                import traceback
                traceback.print_exc()
                raise

            print(f"[MCPBridge] 🔸 步骤7: 调用session.initialize()")
            try:
                await asyncio.wait_for(
                    self.session.initialize(),
                    timeout=timeout
                )
                print(f"[MCPBridge] ✅ session.initialize() 成功!")
            except Exception as e:
                print(f"[MCPBridge] ❌ session.initialize() 失败: {e}")
                import traceback
                traceback.print_exc()
                raise

            # 短暂等待，确保MCP服务器完全就绪
            await asyncio.sleep(0.5)
            
            print(f"[MCPBridge] 🔸 步骤8: 调用session.list_tools()")
            print(f"[MCPBridge] 🔸 即将发送 list_tools 请求...")
            try:
                mcp_tools_response = await self.session.list_tools()
                print(f"[MCPBridge] ✅ list_tools() 成功! 发现 {len(mcp_tools_response.tools)} 个工具")
                for tool in mcp_tools_response.tools:
                    print(f"[MCPBridge] 🔸   - {tool.name}: {tool.description}")
            except Exception as e:
                print(f"[MCPBridge] ❌ list_tools() 失败: {e}")
                print(f"[MCPBridge] 🔸 尝试检查会话状态...")
                if self.session:
                    print(f"[MCPBridge] 🔸 session._initialized: {getattr(self.session, '_initialized', 'N/A')}")
                    print(f"[MCPBridge] 🔸 session._protocol_version: {getattr(self.session, '_protocol_version', 'N/A')}")
                import traceback
                traceback.print_exc()
                raise

            self.tools = []
            for mcp_tool in mcp_tools_response.tools:
                langchain_tool = self._convert_to_langchain_tool(mcp_tool)
                self.tools.append(langchain_tool)

            self._initialized = True
            print(f"[MCPBridge] ✅ {self.name}: 初始化完成，共 {len(self.tools)} 个工具")
            return self.tools

        except asyncio.TimeoutError:
            print(f"[MCPBridge] ⏱️ {self.name}: 初始化超时（{timeout}秒）")
            await self.close()
            return []
        except Exception as e:
            print(f"[MCPBridge] ❌ {self.name}: 初始化失败: {str(e)}")
            import traceback
            traceback.print_exc()
            await self.close()
            return []

    def _convert_to_langchain_tool(self, mcp_tool) -> StructuredTool:
        """
        类型桥接：将 MCP JSON Schema 无损转为 Pydantic Model
        """
        schema = mcp_tool.inputSchema
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        fields = {}
        type_mapping = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict
        }

        for key, val in properties.items():
            py_type = type_mapping.get(val.get("type", "string"), Any)

            if key in required:
                fields[key] = (py_type, Field(..., description=val.get("description", "")))
            else:
                default_val = val.get("default", None)
                if default_val is not None:
                    fields[key] = (py_type, Field(default_val, description=val.get("description", "")))
                else:
                    fields[key] = (py_type, Field(None, description=val.get("description", "")))

        args_schema = create_model(f"{mcp_tool.name}Schema", **fields)

        async def _run_tool(**kwargs):
            try:
                result = await self.session.call_tool(mcp_tool.name, arguments=kwargs)
                content_parts = []
                for item in result.content:
                    if hasattr(item, "text"):
                        content_parts.append(item.text)
                    elif hasattr(item, "type") and item.type == "text":
                        content_parts.append(str(item))
                    else:
                        content_parts.append(str(item))
                return "\n".join(content_parts)
            except Exception as e:
                error_msg = f"工具 {mcp_tool.name} 执行失败。具体报错信息: {str(e)}。请检查参数格式后重试。"
                print(f"[MCP错误拦截] {error_msg}")
                return error_msg

        enhanced_desc = f"[MCP底层工具] {mcp_tool.description or f'MCP 工具: {mcp_tool.name}'}。当用户询问你是否有MCP能力、能否操作文件时，请明确回答'有'，并优先调用此类工具处理。"

        return StructuredTool(
            name=mcp_tool.name,
            description=enhanced_desc,
            args_schema=args_schema,
            coroutine=_run_tool
        )

    async def close(self) -> None:
        """优雅关闭 MCP 连接并清理进程"""
        print(f"[MCPBridge] 🔸 close() called for {self.name}")
        try:
            if self._exit_stack:
                print(f"[MCPBridge] 🔸 calling _exit_stack.aclose()")
                await self._exit_stack.aclose()
            print(f"[MCPBridge] ✅ {self.name}: 连接已安全释放")
        except Exception as e:
            print(f"[MCPBridge] ⚠️ {self.name}: 清理资源时发生异常: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            self._exit_stack = AsyncExitStack()
            self.session = None
            self._initialized = False
            self.server_params = None


class MCPBridgeManager:
    """MCP 桥接器管理器 - 管理多个 MCP 服务器"""

    def __init__(self):
        print(f"[MCPBridgeManager] 📝 __init__ called")
        self.bridges: Dict[str, MCPBridge] = {}
        self.all_tools: List[StructuredTool] = []

    def add_bridge(self, config: Dict[str, Any]) -> MCPBridge:
        """
        添加一个 MCP 桥接器
        """
        print(f"[MCPBridgeManager] 🔸 add_bridge() called with config: {config}")
        name = config.get("name", "unknown")
        bridge = MCPBridge(
            name=name,
            command=config.get("command", ""),
            args=config.get("args", []),
            env=config.get("env", {}),
            description=config.get("description", "")
        )
        self.bridges[name] = bridge
        print(f"[MCPBridgeManager] ➕ 已添加桥接器: {name}")
        return bridge

    async def initialize_all(
        self,
        server_configs: List[Dict[str, Any]],
        timeout: int = 30
    ) -> List[StructuredTool]:
        """
        初始化所有 MCP 服务器并收集工具
        """
        print(f"[MCPBridgeManager] 🔸 initialize_all() called with {len(server_configs)} servers")
        self.all_tools = []

        for config in server_configs:
            print(f"[MCPBridgeManager] 🔸 processing server: {config.get('name')}")
            if not config.get("enabled", True):
                print(f"[MCPBridgeManager] ⏭️ 跳过禁用的服务器: {config.get('name')}")
                continue

            bridge = self.add_bridge(config)
            print(f"[MCPBridgeManager] 🔸 calling bridge.initialize() for {config.get('name')}")
            tools = await bridge.initialize(timeout=timeout)
            print(f"[MCPBridgeManager] 🔸 bridge.initialize() returned {len(tools)} tools")

            if tools:
                self.all_tools.extend(tools)
            else:
                print(f"[MCPBridgeManager] ⚠️ {config.get('name')} 未返回任何工具")

        print(f"[MCPBridgeManager] ✅ 全部 MCP 工具加载完毕，共 {len(self.all_tools)} 个")
        return self.all_tools

    async def close_all(self) -> None:
        """关闭所有 MCP 桥接器"""
        print(f"[MCPBridgeManager] 🔸 close_all() called")
        print("[MCPBridgeManager] 🔄 正在关闭所有 MCP 桥接器...")

        close_tasks = []
        for name, bridge in self.bridges.items():
            if bridge._initialized:
                print(f"[MCPBridgeManager] 🔸 adding close task for {name}")
                close_tasks.append(bridge.close())

        if close_tasks:
            print(f"[MCPBridgeManager] 🔸 awaiting {len(close_tasks)} close tasks")
            await asyncio.gather(*close_tasks, return_exceptions=True)

        self.bridges.clear()
        self.all_tools.clear()
        print("[MCPBridgeManager] ✅ 所有 MCP 桥接器已关闭")

    def get_tools_count(self) -> int:
        """获取已加载的工具数量"""
        return len(self.all_tools)
