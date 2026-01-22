import json
import os
from pathlib import Path

class PromptBuilder:
    def __init__(self, rule_config_path=None):
        """
        初始化：计算绝对路径，预备加载规则。
        """
        # 1. 计算项目根目录 (customs_ai_agent)
        # 当前文件在 src/core/prompt_builder.py
        current_dir = Path(__file__).resolve().parent
        self.project_root = current_dir.parent.parent
        
        # 2. 设定 config 目录路径 (用于后续加载 RAG txt)
        self.config_dir = self.project_root / "config"
        
        # 3. 设定规则 json 路径
        if rule_config_path:
            self.rule_path = Path(rule_config_path)
        else:
            self.rule_path = self.config_dir / "risk_rules.json"

        # 初始化默认配置
        self.config = {"rules": []}

        # 多语言 system_role 和 output_requirement
        self.system_roles = {
            "zh": "你是一名拥有20年经验的海关高级查验专家。你的任务是阅读报关案卷数据，并严格依据提供的【海关高级审查指导文件】（RAG CONTEXT）进行风险研判。",
            "vi": "Bạn là chuyên gia hải quan cao cấp với 20 năm kinh nghiệm. Nhiệm vụ của bạn là đọc dữ liệu tờ khai hải quan và đánh giá rủi ro dựa trên【Hướng dẫn kiểm tra hải quan cấp cao】(RAG CONTEXT) được cung cấp."
        }

        self.output_requirements = {
            "zh": "请严格返回一个JSON二元数组：[\"符号\", \"简短结论\"]。\n- 如果风险低/通过，符号为 \"√\"。\n- 如果风险高/存疑，符号为 \"x\"。\n示例：[\"√\", \"申报要素完整\"] 或 [\"x\", \"价格逻辑异常，疑似低报\"]",
            "vi": "Vui lòng trả về một mảng JSON bao gồm hai phần: [\"biểu tượng\", \"kết luận ngắn gọn\"].\n- Nếu rủi ro thấp/đạt, biểu tượng là \"√\"。\n- Nếu rủi ro cao/cần kiểm tra, biểu tượng là \"x\"。\nVí dụ: [\"√\", \"Các yếu tố khai báo đầy đủ\"] hoặc [\"x\", \"Logic giá bất thường, nghi ngờ khai báo thấp\"]"
        }

        # 默认使用中文
        self.system_role = self.system_roles["zh"]
        self.output_requirement = self.output_requirements["zh"]

        # 4. 加载主规则文件
        self._load_rule_config()

    def _load_rule_config(self):
        """加载 JSON 配置文件，带容错"""
        try:
            print(f" [PromptBuilder] 加载规则配置: {self.rule_path}")
            with open(self.rule_path, 'r', encoding='utf-8') as f:
                #加载文件规则文件内容，并赋值给实例变量config
                self.config = json.load(f)
                self.system_role = self.config.get('meta', {}).get('system_role_definition', self.system_role)
                self.output_requirement = self.config.get('global_output_requirement', self.output_requirement)
        except Exception as e:
            print(f"[Error] [PromptBuilder] 规则加载失败: {e}")
            # 保持默认空配置，防止崩溃

    def _load_specific_rag_context(self, filename: str) -> str:
        """
        动态加载指定的 RAG .txt 文件
        """
        if not filename:
            return "无"
            
        file_path = self.config_dir / filename
        try:
            # 每次读取都重新打开，方便你在不重启服务的情况下热修改txt内容
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            print(f"[Warning] [PromptBuilder] 警告: 找不到 RAG 文件 -> {filename}")
            return "无（未找到对应的参考指导文件）"
        except Exception as e:
            print(f"[Error] [PromptBuilder] 读取 RAG 文件出错: {e}")
            return "无（读取文件出错）"

    def build_system_prompt(self, language: str = "zh"):
        """构建系统提示词，支持多语言"""
        # 根据语言选择对应的 system_role
        system_role = self.system_roles.get(language, self.system_roles["zh"])
        language_instruction = self._get_language_instruction(language)
        return f"{system_role}\n\n{language_instruction}"

    def build_user_prompt(self, raw_data_context, rule_item, language: str = "zh"):
        """
        组装最终的 Prompt：指令 + RAG文件内容 + 数据
        """
        # 根据语言选择对应的 instruction
        if language == "vi" and 'instruction_vi' in rule_item:
            instruction = rule_item.get('instruction_vi', '')
        else:
            instruction = rule_item.get('instruction', '')

        rag_filename = rule_item.get('rag_file')

        # 动态加载对应的 txt 内容
        rag_content = self._load_specific_rag_context(rag_filename)

        # 根据语言选择对应的输出要求
        output_requirement = self.output_requirements.get(language, self.output_requirements["zh"])

        # 添加语言要求
        language_instruction = self._get_language_instruction(language)

        # 越南语模式下使用越南语的标签，中文模式使用中文标签
        if language == "vi":
            prompt = f"""
【Hướng dẫn审核】
{instruction}

【Yêu cầu ngôn ngữ / 语言要求】
{language_instruction}

【Tài liệu hướng dẫn kiểm tra hải quan cấp cao (Cơ sở tham khảo)】
Vui lòng đánh giá nghiêm ngặt dựa trên nội dung tài liệu sau:
================ BEGIN REFERENCE GUIDANCE ================
{rag_content}
================ END REFERENCE GUIDANCE ================

【Hồ sơ hải quan cần kiểm tra】
================ BEGIN DATA ================
{raw_data_context}
================ END DATA ================

【Yêu cầu输出】
{output_requirement}
"""
        else:
            prompt = f"""
【审核指令】
{instruction}

【语言要求】
{language_instruction}

【海关高级审查指导文件 (参考依据)】
请严格依据以下文件内容进行判断：
================ BEGIN REFERENCE GUIDANCE ================
{rag_content}
================ END REFERENCE GUIDANCE ================

【待审核报关案卷】
================ BEGIN DATA ================
{raw_data_context}
================ END DATA ================

【输出要求】
{output_requirement}
"""
        return prompt.strip()

    def _get_language_instruction(self, language: str) -> str:
        """生成语言输出指令"""
        # 语言代码映射到实际语言名称
        language_names = {
            "zh": "简体中文 (Chinese)",
            "vi": "Tiếng Việt (Vietnamese)"
        }
        language_name = language_names.get(language, language_names["zh"])

        # 根据语言生成对应的指令
        if language == "vi":
            return f"""【QUAN TRỌNG - CẤU HÌNH NGÔN NGỮ】
Ngôn ngữ giao diện người dùng là: {language_name} (Mã: {language})

【YÊU CẦU BẮT BUỘC - MANDATORY REQUIREMENT】
1. TẤT CẢ kết quả phân tích, nhận định rủi ro, lý do và đề xuất PHẢI được viết bằng {language_name}。
2. KHÔNG được sử dụng tiếng Trung Quốc trong kết quả, kể cả khi tài liệu tham khảo là tiếng Trung。
3. Chỉ được phép hiển thị tiếng Trung trong phần trích dẫn tài liệu tham khảo, mọi kết luận và giải thích PHẢI bằng {language_name}。

【TRỌNG VỤ - CRITICAL】
Kết quả của bạn sẽ HIỂN THỊ TRỰC TIẾP trên giao diện người dùng, vui lòng tôn trọng cài đặt ngôn ngữ của họ！"""
        else:
            return f"""【重要语言设置】当前用户设置的语言是 {language_name}，语言代码为 {language}。

【严格要求】你必须使用 {language_name} 输出所有分析结果和判断依据。
包括风险结论、分析理由、建议等所有内容必须是 {language_name}，这是用户界面语言设置，结果将直接显示给前端用户。"""

# --- 自测代码 ---
if __name__ == "__main__":
    builder = PromptBuilder()
    # 模拟测试一条规则
    mock_rule = {
        "instruction": "测试指令",
        "rag_file": "rag_r01_basic_info.txt" # 确保你真的创建了这个文件，否则会报警告
    }
    print(builder.build_user_prompt("测试数据...", mock_rule))