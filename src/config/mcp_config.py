"""
MCP 服务器配置加载器
支持从 JSON 文件加载 MCP 服务器配置
"""
import json
from pathlib import Path
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field


class MCPServerConfig(BaseModel):
    """MCP 服务器配置模型"""
    name: str = Field(..., description="服务器名称")
    enabled: bool = Field(True, description="是否启用")
    description: str = Field("", description="服务器描述")
    command: str = Field(..., description="启动命令，如 npx, python, node 等")
    args: List[str] = Field(default_factory=list, description="命令参数列表")
    env: Dict[str, str] = Field(default_factory=dict, description="环境变量")


class MCPConfigSettings(BaseModel):
    """MCP 全局配置"""
    auto_start: bool = Field(True, description="服务启动时自动加载 MCP")
    timeout: int = Field(30, description="初始化超时时间（秒）")
    retry_count: int = Field(3, description="重试次数")


class MCPConfigLoader:
    """MCP 配置加载器 (单例)"""

    _instance = None
    _config: Optional[Dict[str, Any]] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._config is None:
            self._load_config()

    def _load_config(self) -> None:
        """从 JSON 文件加载 MCP 配置"""
        config_path = Path("data/mcp_servers.json")

        if not config_path.exists():
            print(f"[MCPConfig] 配置文件不存在: {config_path}, 使用默认配置")
            self._config = {
                "servers": [],
                "config": {"auto_start": True, "timeout": 30, "retry_count": 3}
            }
            return

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                raw_config = json.load(f)

            servers = [MCPServerConfig(**s) for s in raw_config.get("servers", [])]
            settings = MCPConfigSettings(**raw_config.get("config", {}))

            self._config = {
                "servers": [s.model_dump() for s in servers],
                "config": settings.model_dump()
            }

            print(f"[MCPConfig] 成功加载 {len(servers)} 个 MCP 服务器配置")

        except Exception as e:
            print(f"[MCPConfig] 配置加载失败: {e}, 使用默认配置")
            self._config = {
                "servers": [],
                "config": {"auto_start": True, "timeout": 30, "retry_count": 3}
            }

    def get_servers(self) -> List[Dict[str, Any]]:
        """获取所有启用的 MCP 服务器配置"""
        if not self._config:
            self._load_config()

        return [
            s for s in self._config.get("servers", [])
            if s.get("enabled", True)
        ]

    def get_settings(self) -> MCPConfigSettings:
        """获取 MCP 全局配置"""
        if not self._config:
            self._load_config()

        return MCPConfigSettings(**self._config.get("config", {}))

    def reload(self) -> None:
        """重新加载配置"""
        self._config = None
        self._load_config()


mcp_config_loader = MCPConfigLoader()
