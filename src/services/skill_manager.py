"""
技能插件管理器
===================
对齐官方两段式模型：Registry + Activation
"""
import json
from pathlib import Path
from typing import Dict, Optional, Tuple, List

import yaml


class SkillManager:
    """技能管理器（官方风格：Registry + Activation）"""

    def __init__(self, skills_dir: str = "data/skills"):
        self.skills_dir = Path(skills_dir)
        self.skills: Dict[str, dict] = {}
        self._discover_skills()

    def _discover_skills(self) -> None:
        """Registry 阶段：扫描目录并注册技能元数据。"""
        if not self.skills_dir.exists():
            print(f"[SkillManager] 技能目录不存在: {self.skills_dir}")
            return

        for skill_path in self.skills_dir.iterdir():
            if not skill_path.is_dir():
                continue

            skill_file = skill_path / "SKILL.md"
            if not skill_file.exists():
                continue

            try:
                metadata, resources = self._parse_skill_frontmatter_only(skill_file)
                skill_name = (metadata.get("name") or "").strip()
                description = (metadata.get("description") or "").strip()

                if not skill_name:
                    print(f"[SkillManager] [Registry] 跳过无 name 技能: {skill_file}")
                    continue

                self.skills[skill_name] = {
                    "path": skill_file,
                    "description": description,
                    "resources_dir": skill_path / "resources",
                    "resource_files": resources or [],
                    "scripts_dir": skill_path / "scripts",
                    "metadata": metadata,
                }
                print(f"[SkillManager] [Registry] 注册成功: {skill_name} - {description}")
            except Exception as e:
                print(f"[SkillManager] [Registry Error] 注册失败 {skill_path.name}: {e}")

    def _parse_skill_frontmatter_only(self, file_path: Path) -> Tuple[dict, List[str]]:
        """安全解析完整 frontmatter（读到第二个 --- 为止）。"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            if not lines or lines[0].strip() != "---":
                return {}, []

            yaml_lines: List[str] = []
            for line in lines[1:]:
                if line.strip() == "---":
                    break
                yaml_lines.append(line)

            metadata = yaml.safe_load("".join(yaml_lines)) or {}
            resources = metadata.get("resources", [])
            if not isinstance(resources, list):
                resources = []
            return metadata, resources
        except Exception as e:
            print(f"[SkillManager] Frontmatter 解析失败: {e}")
            return {}, []

    def _parse_skill_md(self, file_path: Path) -> Tuple[dict, str]:
        """解析 SKILL.md，提取 metadata 与正文。"""
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                metadata = yaml.safe_load(parts[1]) or {}
                return metadata, parts[2].strip()

        return {}, content

    def get_skill_registry_text(self) -> str:
        """生成供 System Prompt 使用的技能注册表。"""
        if not self.skills:
            return "无可用技能"
        return "\n".join([f"- {name}: {info['description']}" for name, info in self.skills.items()])

    def load_skill_content(self, skill_name: str) -> Optional[str]:
        """Activation 阶段：按需加载技能正文。"""
        if skill_name not in self.skills:
            return f"错误：技能 '{skill_name}' 未注册"

        try:
            _, content = self._parse_skill_md(self.skills[skill_name]["path"])
            return content
        except Exception as e:
            return f"激活技能失败: {e}"

    def list_resources(self, skill_name: str) -> dict:
        if skill_name not in self.skills:
            return {"error": f"技能 {skill_name} 不存在"}

        resources_dir = self.skills[skill_name]["resources_dir"]
        if not resources_dir.exists():
            return {"resources_dir": str(resources_dir), "files": [], "message": "该技能无资源文件夹"}

        files_info = []
        for file_path in resources_dir.iterdir():
            if file_path.is_file():
                files_info.append(
                    {
                        "name": file_path.name,
                        "size": file_path.stat().st_size,
                        "type": file_path.suffix.lstrip("."),
                        "path": str(file_path),
                    }
                )

        return {"resources_dir": str(resources_dir), "files": files_info}

    def get_resource_content(self, skill_name: str, file_name: str, max_lines: int = 150) -> str:
        """安全读取资源内容。"""
        if ".." in file_name or "/" in file_name or "\\" in file_name:
            return "错误：禁止路径遍历"

        if skill_name not in self.skills:
            return f"错误：技能 '{skill_name}' 未注册"

        resources_dir = self.skills[skill_name]["resources_dir"]
        file_path = resources_dir / file_name

        if not file_path.resolve().is_relative_to(resources_dir.resolve()):
            return "错误：非法越界访问"

        if not file_path.exists():
            return f"错误：资源文件 '{file_name}' 不存在"

        try:
            ext = file_path.suffix.lower()
            if ext == ".json":
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.dumps(json.load(f), ensure_ascii=False, indent=2)

            if ext in [".csv", ".txt", ".md"]:
                lines: List[str] = []
                with open(file_path, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f):
                        if i >= max_lines:
                            lines.append(f"... (仅展示前 {max_lines} 行)")
                            break
                        lines.append(line.rstrip("\n"))
                return "\n".join(lines)

            size_kb = file_path.stat().st_size / 1024
            return f"二进制文件({ext})，大小: {size_kb:.2f}KB，暂不支持预览"
        except Exception as e:
            return f"读取失败: {e}"

    def get_script_path(self, skill_name: str, script_name: str) -> str:
        """获取脚本绝对路径（含越界防护）。"""
        if ".." in script_name or "/" in script_name or "\\" in script_name:
            raise ValueError("错误：禁止路径遍历")

        if skill_name not in self.skills:
            raise ValueError(f"错误：技能 '{skill_name}' 未注册")

        scripts_dir = self.skills[skill_name]["scripts_dir"]
        script_path = scripts_dir / script_name

        if not script_path.resolve().is_relative_to(scripts_dir.resolve()):
            raise ValueError("错误：非法越界访问脚本")

        if not script_path.exists():
            raise ValueError(f"错误：脚本 '{script_name}' 不存在")

        return str(script_path)
