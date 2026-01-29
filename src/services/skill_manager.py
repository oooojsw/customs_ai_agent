"""
技能插件管理器
===================
动态加载Markdown技能文件，支持热插拔扩展Agent能力
"""
import os
import yaml
from pathlib import Path
from typing import Dict, Optional


class SkillManager:
    """技能插件管理器 - 动态加载Markdown技能文件"""

    def __init__(self, skills_dir: str = "data/skills"):
        """
        初始化技能管理器
        :param skills_dir: 技能目录路径
        """
        self.skills_dir = Path(skills_dir)
        self.skills: Dict[str, dict] = {}
        self._discover_skills()

    def _discover_skills(self):
        """
        L1 加载层：扫描skills目录，只读取 YAML frontmatter
        每个技能子目录必须包含SKILL.md文件
        """
        if not self.skills_dir.exists():
            print(f"[SkillManager] 技能目录不存在: {self.skills_dir}")
            return

        for skill_path in self.skills_dir.iterdir():
            if not skill_path.is_dir():
                continue

            skill_file = skill_path / "SKILL.md"
            if not skill_file.exists():
                continue

            # L1 加载：只解析 YAML frontmatter，不读取正文
            try:
                metadata, resources = self._parse_skill_frontmatter_only(skill_file)
                skill_name = metadata.get('name')
                description = metadata.get('description', '')

                if skill_name:
                    self.skills[skill_name] = {
                        'path': skill_file,
                        'description': description,
                        'resources_dir': skill_path / 'resources',  # L3 资源目录
                        'resource_files': resources or [],           # 资源清单
                        'scripts_dir': skill_path / 'scripts'        # L4 脚本目录
                    }
                    print(f"[SkillManager] [OK] L1加载: {skill_name} - {description}")

            except Exception as e:
                print(f"[SkillManager] [ERROR] L1加载失败: {skill_path.name} - {str(e)}")

    def _parse_skill_frontmatter_only(self, file_path: Path) -> tuple:
        """
        L1 加载层：只解析 YAML frontmatter，不读取正文内容
        :return: (metadata_dict, resource_list)
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                # 只读取前20行，足够覆盖YAML头
                header_lines = []
                for i, line in enumerate(f):
                    if i >= 20:
                        break
                    header_lines.append(line)
                    if line.strip() == '---' and i > 0:
                        break

                header_text = ''.join(header_lines)

                if header_text.startswith('---'):
                    parts = header_text.split('---', 2)
                    if len(parts) >= 2:
                        yaml_content = parts[1]
                        metadata = yaml.safe_load(yaml_content)
                        resources = metadata.get('resources', [])
                        return metadata, resources
        except Exception as e:
            print(f"[SkillManager] Frontmatter解析失败: {e}")

        return {}, []

    def _parse_skill_md(self, file_path: Path) -> tuple:
        """
        解析SKILL.md文件，提取YAML frontmatter和正文
        :return: (metadata_dict, content_str)
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 提取YAML frontmatter（在---之间的部分）
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                yaml_content = parts[1]
                markdown_content = parts[2].strip()
                metadata = yaml.safe_load(yaml_content)
                return metadata, markdown_content

        # 如果没有frontmatter，整个文件作为content
        return {}, content

    def get_skill_registry_text(self) -> str:
        """
        生成技能清单文本，用于注入System Prompt
        :return: 格式化的技能列表字符串
        """
        if not self.skills:
            return "暂无可用扩展技能"

        lines = []
        for name, info in self.skills.items():
            lines.append(f"- {name}: {info['description']}")

        return "\n".join(lines)

    def load_skill_content(self, skill_name: str) -> Optional[str]:
        """
        L2 加载层：读取技能正文，并提示可用的资源
        :param skill_name: 技能名称
        :return: 技能手册正文（移除YAML头后的Markdown内容）+ 资源提示
        """
        if skill_name not in self.skills:
            return f"错误：技能 '{skill_name}' 不存在"

        skill_file = self.skills[skill_name]['path']
        resource_files = self.skills[skill_name].get('resource_files', [])

        try:
            _, content = self._parse_skill_md(skill_file)

            # 构建资源提示文本
            resource_hint = ""
            if resource_files:
                resource_list = "\n".join([f"  - {f}" for f in resource_files])
                resource_hint = f"\n\n【可用资源文件】\n{resource_list}\n如需读取这些文件，请调用 read_skill_resource 工具。"

            return content + resource_hint
        except Exception as e:
            return f"加载技能失败: {str(e)}"

    def list_resources(self, skill_name: str) -> dict:
        """
        列出技能的所有可用资源（含文件大小等元信息）
        :return: {
            'resources_dir': Path,
            'files': [
                {'name': 'tax_rates.csv', 'size': 1024, 'type': 'csv'},
                ...
            ]
        }
        """
        if skill_name not in self.skills:
            return {'error': f'技能 {skill_name} 不存在'}

        resources_dir = self.skills[skill_name]['resources_dir']

        if not resources_dir.exists():
            return {
                'resources_dir': str(resources_dir),
                'files': [],
                'message': '该技能无资源文件夹'
            }

        files_info = []
        for file_path in resources_dir.iterdir():
            if file_path.is_file():
                files_info.append({
                    'name': file_path.name,
                    'size': file_path.stat().st_size,
                    'type': file_path.suffix.lstrip('.'),
                    'path': str(file_path)
                })

        return {
            'resources_dir': str(resources_dir),
            'files': files_info
        }

    def get_resource_content(self, skill_name: str, file_name: str, max_lines: int = 100) -> str:
        """
        L3 加载层：按需读取资源文件内容
        :param skill_name: 技能名称
        :param file_name: 资源文件名（不含路径）
        :param max_lines: 最大读取行数（防止超大文件）
        :return: 文件内容或错误信息
        """
        # 安全校验：防止路径遍历攻击
        if '..' in file_name or '/' in file_name or '\\' in file_name:
            return "错误：非法的文件名（禁止路径遍历）"

        if skill_name not in self.skills:
            return f"错误：技能 '{skill_name}' 不存在"

        resources_dir = self.skills[skill_name]['resources_dir']
        file_path = resources_dir / file_name

        # 校验文件路径是否在允许的目录内
        if not file_path.resolve().is_relative_to(resources_dir.resolve()):
            return "错误：文件路径超出技能资源目录范围"

        if not file_path.exists():
            return f"错误：资源文件 '{file_name}' 不存在"

        try:
            # 根据文件类型选择读取策略
            file_ext = file_path.suffix.lower()

            if file_ext == '.json':
                with open(file_path, 'r', encoding='utf-8') as f:
                    import json
                    data = json.load(f)
                    return json.dumps(data, ensure_ascii=False, indent=2)

            elif file_ext in ['.csv', '.txt', '.md']:
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = []
                    for i, line in enumerate(f):
                        if i >= max_lines:
                            lines.append(f"\n... (文件过大，仅显示前{max_lines}行)")
                            break
                        lines.append(line.rstrip())
                    return '\n'.join(lines)

            else:
                # 二进制文件返回提示
                size_kb = file_path.stat().st_size / 1024
                return f"二进制文件（{file_ext}），大小: {size_kb:.2f} KB，暂不支持预览"

        except Exception as e:
            return f"读取资源文件失败: {str(e)}"

    def get_script_path(self, skill_name: str, script_name: str) -> str:
        """
        获取技能脚本的绝对路径（含安全检查）
        :param skill_name: 技能名称
        :param script_name: 脚本文件名（不含路径）
        :return: 脚本的绝对路径
        :raises: ValueError 如果路径非法或文件不存在
        """
        # 安全校验：防止路径遍历攻击
        if '..' in script_name or '/' in script_name or '\\' in script_name:
            raise ValueError("错误：非法的脚本文件名（禁止路径遍历）")

        if skill_name not in self.skills:
            raise ValueError(f"错误：技能 '{skill_name}' 不存在")

        scripts_dir = self.skills[skill_name]['scripts_dir']
        script_path = scripts_dir / script_name

        # 校验文件路径是否在允许的目录内
        if not script_path.resolve().is_relative_to(scripts_dir.resolve()):
            raise ValueError("错误：脚本路径超出技能脚本目录范围")

        if not script_path.exists():
            raise ValueError(f"错误：脚本文件 '{script_name}' 不存在")

        return str(script_path)
