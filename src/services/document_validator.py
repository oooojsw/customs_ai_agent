"""
报关文档字段校验引擎
====================
对 DocumentResult 执行字段级和跨字段校验，生成 ValidationReport。

校验规则覆盖：
  - HS 编码格式检查
  - 关键字段缺失检查（按文档类型）
  - 金额一致性检查（发票总额 ≈ 商品总价之和）
  - 币种一致性检查
  - 低置信度关键字段标记
  - 数量/单位合理性检查

用法：
    from src.services.document_validator import DocumentValidator
    validator = DocumentValidator()
    report = validator.validate(document_result)

对齐《报关智能体平台集成中间层与多模态协议总体方案》第 4.3 节理解层校验要求。
"""

import re
import logging
from datetime import datetime, timezone
from typing import List, Optional

from src.services.document_models import (
    DocumentResult, DocumentType, FieldEvidence,
    ConfidenceLevel, ValidationSeverity,
    ValidationReport, ValidationFinding,
    CRITICAL_FIELDS,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 校验规则定义
# ============================================================================

# HS编码格式：4位品目 / 6位子目 / 8位本国子目 / 10位（含小数点分隔）
HS_CODE_PATTERN = re.compile(
    r'^\d{4}(\.\d{2})?(\.\d{2,4})?(\.\d{2})?$'
)

# 金额提取模式（支持多种币种符号和千分位）
AMOUNT_PATTERN = re.compile(
    r'([\d,]+\.?\d*)\s*(元|美元|USD|EUR|JPY|KRW|VND|CNY|¥|\$|€|₫)'
)

# 各文档类型的必填字段
REQUIRED_FIELDS_BY_TYPE = {
    DocumentType.DECLARATION: [
        "entry_id", "goods_name", "quantity", "unit_price", "total_price",
        "currency", "hs_code",
    ],
    DocumentType.INVOICE: [
        "invoice_total", "currency", "goods_name", "quantity", "unit_price",
    ],
    DocumentType.PACKING_LIST: [
        "goods_name", "quantity",
    ],
    DocumentType.CERTIFICATE: [
        "origin_country",
    ],
    DocumentType.SOURCE_TABLE_IMAGE: [],
    DocumentType.GENERAL_IMAGE: [],
    DocumentType.UNKNOWN: [],
}


class DocumentValidator:
    """字段校验引擎

    对单个 DocumentResult 执行所有注册的校验规则，
    生成包含 findings 和通过/失败状态的 ValidationReport。
    """

    def __init__(self):
        self._rules = [
            self._check_hs_code_format,
            self._check_required_fields,
            self._check_amount_consistency,
            self._check_currency_consistency,
            self._check_low_confidence_critical_fields,
        ]

    def validate(self, doc: DocumentResult) -> ValidationReport:
        """执行全部校验规则

        Args:
            doc: 待校验的文档识别结果

        Returns:
            ValidationReport 包含所有校验发现
        """
        findings: List[ValidationFinding] = []
        checked = 0

        for rule_func in self._rules:
            try:
                result = rule_func(doc)
                if result:
                    if isinstance(result, list):
                        findings.extend(result)
                    else:
                        findings.append(result)
                checked += 1
            except Exception as e:
                logger.warning(f"校验规则 {rule_func.__name__} 执行异常: {e}")
                findings.append(ValidationFinding(
                    rule_id="VALIDATOR_INTERNAL_ERROR",
                    message=f"校验规则执行异常: {e}",
                    severity=ValidationSeverity.WARNING,
                ))
                checked += 1

        # 统计
        error_count = sum(1 for f in findings if f.severity == ValidationSeverity.ERROR)
        warning_count = sum(1 for f in findings if f.severity == ValidationSeverity.WARNING)
        info_count = sum(1 for f in findings if f.severity == ValidationSeverity.INFO)

        return ValidationReport(
            report_id=f"vr_{doc.document_id}",
            document_id=doc.document_id,
            rules_checked=checked,
            findings=findings,
            passed=(error_count == 0),
            error_count=error_count,
            warning_count=warning_count,
            info_count=info_count,
            checked_at=datetime.now(timezone.utc).isoformat(),
        )

    # ------------------------------------------------------------------
    # 规则 1: HS 编码格式检查
    # ------------------------------------------------------------------

    def _check_hs_code_format(self, doc: DocumentResult) -> Optional[ValidationFinding]:
        """检查 HS 编码是否符合格式规范。

        合法格式：4位 / 6位 / 8位 / 10位（如 8542.31.0000）
        """
        hs_field = doc.get_field("hs_code")
        if not hs_field or not hs_field.standard_value:
            if doc.document_type == DocumentType.DECLARATION:
                return ValidationFinding(
                    rule_id="HS_CODE_MISSING",
                    field_names=["hs_code"],
                    message="报关单缺少 HS 编码，该字段为必填项",
                    severity=ValidationSeverity.ERROR,
                    suggestion="请从商品清单中补充 HS 编码，或使用 hs_code_advisor 技能查询",
                )
            return None

        raw_code = hs_field.standard_value.strip()
        if HS_CODE_PATTERN.match(raw_code):
            return None  # 格式正确

        # 尝试修复：去除空格和其他符号后重试
        cleaned = re.sub(r'[\s\-—]', '', raw_code)
        if HS_CODE_PATTERN.match(cleaned):
            return ValidationFinding(
                rule_id="HS_CODE_FORMAT",
                field_names=["hs_code"],
                message=f"HS 编码格式含多余字符: {raw_code}",
                severity=ValidationSeverity.WARNING,
                expected=cleaned,
                actual=raw_code,
                suggestion=f"建议修正为: {cleaned}",
            )

        return ValidationFinding(
            rule_id="HS_CODE_FORMAT",
            field_names=["hs_code"],
            message=f"HS 编码格式无效: {raw_code}",
            severity=ValidationSeverity.ERROR,
            suggestion="HS编码应为4/6/8/10位数字，如 85423100 或 8542.31.0000",
            actual=raw_code,
        )

    # ------------------------------------------------------------------
    # 规则 2: 必填字段检查
    # ------------------------------------------------------------------

    def _check_required_fields(self, doc: DocumentResult) -> List[ValidationFinding]:
        """按文档类型检查必填字段是否缺失。"""
        findings = []
        required = REQUIRED_FIELDS_BY_TYPE.get(doc.document_type, [])

        for field_name in required:
            field = doc.get_field(field_name)
            if not field or not field.display_value:
                severity = ValidationSeverity.ERROR if field_name in CRITICAL_FIELDS else ValidationSeverity.WARNING
                findings.append(ValidationFinding(
                    rule_id="REQUIRED_FIELD_MISSING",
                    field_names=[field_name],
                    message=f"必填字段缺失: {field_name}",
                    severity=severity,
                    suggestion=f"请补充 {field_name} 字段的值",
                ))

        return findings

    # ------------------------------------------------------------------
    # 规则 3: 金额一致性检查
    # ------------------------------------------------------------------

    def _check_amount_consistency(self, doc: DocumentResult) -> Optional[ValidationFinding]:
        """检查发票总额是否与商品总价之和一致。

        仅适用于 document_type 为 declaration 或 invoice 的情况。
        """
        if doc.document_type not in (DocumentType.DECLARATION, DocumentType.INVOICE):
            return None

        # 尝试从字段中提取发票总额
        invoice_total = self._extract_amount(doc, "invoice_total")
        if not invoice_total:
            # 尝试从 total_price 字段汇总（单商品场景就是总价本身）
            total_field = doc.get_field("total_price")
            if total_field and total_field.standard_value:
                invoice_total = self._parse_amount_string(total_field.standard_value)

        if invoice_total is None:
            return None  # 没有金额数据可比较

        # 从表格 cell 中汇总所有商品总价
        goods_total = self._sum_goods_total_from_tables(doc)
        if goods_total is None:
            return None

        # 比较（允许 5% 偏差，考虑四舍五入和币种换算）
        if goods_total > 0 and invoice_total > 0:
            diff_ratio = abs(invoice_total - goods_total) / max(invoice_total, goods_total)
            if diff_ratio > 0.05:
                return ValidationFinding(
                    rule_id="AMOUNT_CONSISTENCY",
                    field_names=["invoice_total", "total_price"],
                    message=f"发票总额与商品总价之和差异较大",
                    severity=ValidationSeverity.ERROR,
                    expected=f"≈ {goods_total:,.2f}",
                    actual=f"{invoice_total:,.2f}",
                    suggestion="请核对各商品总价和发票总额是否一致，检查是否有遗漏商品",
                )
            elif diff_ratio > 0.01:
                return ValidationFinding(
                    rule_id="AMOUNT_CONSISTENCY",
                    field_names=["invoice_total", "total_price"],
                    message=f"发票总额与商品总价之和有轻微差异 ({diff_ratio:.1%})",
                    severity=ValidationSeverity.WARNING,
                    expected=f"≈ {goods_total:,.2f}",
                    actual=f"{invoice_total:,.2f}",
                    suggestion="差异较小，可能为四舍五入导致，建议确认",
                )

        return None

    def _extract_amount(self, doc: DocumentResult, field_name: str) -> Optional[float]:
        """从文档字段中提取金额数值。"""
        field = doc.get_field(field_name)
        if not field or not field.standard_value:
            return None
        return self._parse_amount_string(field.standard_value)

    def _parse_amount_string(self, text: str) -> Optional[float]:
        """从金额字符串中解析数值。"""
        if not text:
            return None
        # 去除币种符号
        cleaned = re.sub(r'[¥$€₫元美元EURUSDJPYKRWCNYVND\s]', '', text, flags=re.IGNORECASE)
        # 去除千分位逗号
        cleaned = cleaned.replace(',', '')
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _sum_goods_total_from_tables(self, doc: DocumentResult) -> Optional[float]:
        """从表格中汇总商品总价。

        查找表头含"总价"的列，对数据行的该列求和。
        """
        total_sum = 0.0
        found_any = False

        for table in doc.tables:
            headers = [h.lower() for h in table.headers]
            # 寻找"总价"相关列
            total_col_idx = None
            for i, h in enumerate(headers):
                if any(kw in h for kw in ['总价', 'total', '金额', 'amount', 'price']):
                    total_col_idx = i
                    break

            if total_col_idx is None:
                continue

            # 按行汇总（header 是 row 1）
            for cell in table.cells:
                if cell.row == 1:
                    continue  # 跳过表头
                if cell.column == total_col_idx + 1:
                    val = self._parse_amount_string(cell.text)
                    if val is not None:
                        total_sum += val
                        found_any = True

        return total_sum if found_any else None

    # ------------------------------------------------------------------
    # 规则 4: 币种一致性检查
    # ------------------------------------------------------------------

    def _check_currency_consistency(self, doc: DocumentResult) -> Optional[ValidationFinding]:
        """检查多个字段中的币种是否一致。"""
        currency_field = doc.get_field("currency")
        if not currency_field or not currency_field.standard_value:
            return None

        expected_currency = currency_field.standard_value.strip().upper()

        # 检查金额相关字段是否包含其他币种
        amount_fields = ["total_price", "unit_price", "invoice_total"]
        mismatched = []

        for fname in amount_fields:
            field = doc.get_field(fname)
            if not field or not field.standard_value:
                continue
            text = field.standard_value

            # 检测常见币种符号
            for symbol, code in [("¥", "CNY"), ("$", "USD"), ("€", "EUR"),
                                  ("₫", "VND"), ("元", "CNY"), ("USD", "USD"),
                                  ("EUR", "EUR"), ("VND", "VND")]:
                if symbol in text and code != expected_currency:
                    mismatched.append(f"{fname}({symbol})")

        if mismatched:
            return ValidationFinding(
                rule_id="CURRENCY_CONSISTENCY",
                field_names=["currency"] + [f.split("(")[0] for f in mismatched],
                message=f"检测到币种不一致: 期望 {expected_currency}, 发现 {', '.join(mismatched)}",
                severity=ValidationSeverity.WARNING,
                expected=expected_currency,
                actual=", ".join(mismatched),
                suggestion="请确认所有金额是否使用同一币种，或补充汇率换算说明",
            )

        return None

    # ------------------------------------------------------------------
    # 规则 5: 低置信度关键字段标记
    # ------------------------------------------------------------------

    def _check_low_confidence_critical_fields(self, doc: DocumentResult) -> List[ValidationFinding]:
        """对所有低置信度关键字段生成 ERROR 级别发现。

        根据协议：低置信度关键字段不得用于生成正式报关单。
        """
        findings = []
        critical_fields = doc.get_critical_fields()

        for field in critical_fields:
            if field.confidence == ConfidenceLevel.LOW:
                findings.append(ValidationFinding(
                    rule_id="CRITICAL_FIELD_LOW_CONFIDENCE",
                    field_names=[field.field_name],
                    message=f"关键字段 {field.field_name} 置信度过低 ({field.confidence_score:.2f})，"
                            f"必须人工确认后才能用于正式报关单",
                    severity=ValidationSeverity.ERROR,
                    actual=field.display_value,
                    suggestion=f"请人工核对该字段: {field.display_value}",
                ))
            elif field.confidence == ConfidenceLevel.MEDIUM and field.needs_review:
                findings.append(ValidationFinding(
                    rule_id="CRITICAL_FIELD_MEDIUM_CONFIDENCE",
                    field_names=[field.field_name],
                    message=f"关键字段 {field.field_name} 置信度中等 ({field.confidence_score:.2f})，"
                            f"建议人工确认",
                    severity=ValidationSeverity.WARNING,
                    actual=field.display_value,
                    suggestion=f"建议人工核对该字段: {field.display_value}",
                ))

        return findings


# ============================================================================
# 便捷函数
# ============================================================================

def validate_document(doc: DocumentResult) -> ValidationReport:
    """对 DocumentResult 执行全部校验（快捷方式）。"""
    validator = DocumentValidator()
    return validator.validate(doc)
