from __future__ import annotations

import re
import hashlib

from .models import (
    BusinessCaseSnapshot,
    CustomsStage,
    DeclarationData,
    RuleFinding,
)
from .knowledge_rules import KnowledgeRulePackLoader


REQUIRED_DOCUMENTS = {"contract", "invoice", "packing_list", "bill_of_lading"}


class CustomsRuleEngine:
    version = "mock-rules-1.0"

    def __init__(
        self,
        knowledge_rules: KnowledgeRulePackLoader | None = None,
    ):
        self.knowledge_rules = knowledge_rules or KnowledgeRulePackLoader()

    @property
    def effective_version(self) -> str:
        return f"{self.version}+{self.knowledge_rules.version}"

    def validate_documents(
        self, declaration: DeclarationData, document_types: set[str]
    ) -> list[RuleFinding]:
        findings: list[RuleFinding] = []
        missing = sorted(REQUIRED_DOCUMENTS - document_types)
        if missing:
            findings.append(
                RuleFinding(
                    code="DOCUMENT_SET_INCOMPLETE",
                    severity="high",
                    stage="document_validation",
                    message=f"缺少必要单证: {', '.join(missing)}",
                    blocking=True,
                )
            )
        invoice_total = sum(item.total_price for item in declaration.goods)
        for item in declaration.goods:
            expected = round(item.quantity * item.unit_price, 2)
            if abs(expected - item.total_price) > 0.01:
                findings.append(
                    RuleFinding(
                        code="GOODS_AMOUNT_MISMATCH",
                        severity="high",
                        stage="document_validation",
                        field=f"goods[{item.item_no}].total_price",
                        message="商品数量乘单价与总价不一致",
                        blocking=True,
                    )
                )
        if invoice_total <= 0:
            findings.append(
                RuleFinding(
                    code="INVALID_INVOICE_TOTAL",
                    severity="high",
                    stage="document_validation",
                    message="发票总金额必须大于零",
                    blocking=True,
                )
            )
        for document in declaration.goods:
            if document.gross_weight <= 0 or document.net_weight <= 0:
                findings.append(
                    RuleFinding(
                        code="INVALID_WEIGHT",
                        severity="high",
                        stage="document_validation",
                        message="商品毛重和净重必须大于零",
                        blocking=True,
                    )
                )
        return findings

    def validate_acceptance(self, declaration: DeclarationData) -> list[RuleFinding]:
        findings: list[RuleFinding] = []
        required_header_fields = {
            "consignee": declaration.consignee,
            "overseas_consignor": declaration.overseas_consignor,
            "transport_mode": declaration.transport_mode,
            "bill_of_lading_no": declaration.bill_of_lading_no,
            "invoice_no": declaration.invoice_no,
            "contract_no": declaration.contract_no,
            "packing_list_no": declaration.packing_list_no,
        }
        for field_name, value in required_header_fields.items():
            if not str(value).strip():
                findings.append(
                    RuleFinding(
                        code="MISSING_REQUIRED_FIELD",
                        severity="high",
                        stage="acceptance",
                        field=field_name,
                        message=f"申报表头字段 {field_name} 未填写",
                        blocking=True,
                    )
                )
        if not re.fullmatch(r"\d{4}", declaration.trade_mode):
            findings.append(
                RuleFinding(
                    code="INVALID_TRADE_MODE",
                    severity="high",
                    stage="acceptance",
                    field="trade_mode",
                    message="贸易方式代码必须为 4 位数字",
                    blocking=True,
                )
            )
        for index, item in enumerate(declaration.goods):
            prefix = f"goods[{index}]"
            if not re.fullmatch(r"\d{8,10}", item.hs_code):
                findings.append(
                    RuleFinding(
                        code="INVALID_HS_CODE",
                        severity="high",
                        stage="acceptance",
                        field=f"{prefix}.hs_code",
                        message="HS 编码格式不正确",
                        blocking=True,
                    )
                )
            for field_name in ("model", "usage"):
                if not getattr(item, field_name).strip():
                    findings.append(
                        RuleFinding(
                            code="MISSING_DECLARATION_ELEMENT",
                            severity="medium",
                            stage="acceptance",
                            field=f"{prefix}.{field_name}",
                            message=f"申报要素 {field_name} 未填写",
                            blocking=True,
                        )
                    )
            if item.net_weight > item.gross_weight:
                findings.append(
                    RuleFinding(
                        code="WEIGHT_LOGIC_ERROR",
                        severity="high",
                        stage="acceptance",
                        field=f"{prefix}.net_weight",
                        message="净重不能大于毛重",
                        blocking=True,
                    )
                )
            if "PROHIBITED" in item.regulatory_codes:
                findings.append(
                    RuleFinding(
                        code="PROHIBITED_IMPORT",
                        severity="high",
                        stage="acceptance",
                        field=f"{prefix}.regulatory_codes",
                        message="商品命中 Mock 禁止进口监管代码",
                        blocking=True,
                    )
                )
        return findings

    def review(self, declaration: DeclarationData) -> list[RuleFinding]:
        findings: list[RuleFinding] = []
        for index, item in enumerate(declaration.goods):
            prefix = f"goods[{index}]"
            if item.currency != declaration.currency:
                findings.append(
                    RuleFinding(
                        code="CURRENCY_MISMATCH",
                        severity="medium",
                        stage="customs_review",
                        field=f"{prefix}.currency",
                        message="商品币种与申报表头币种不一致",
                    )
                )
            if (
                item.reference_unit_price_min is not None
                and item.unit_price < item.reference_unit_price_min
            ):
                findings.append(
                    RuleFinding(
                        code="PRICE_BELOW_REFERENCE",
                        severity="high",
                        stage="customs_review",
                        field=f"{prefix}.unit_price",
                        message="申报单价低于 Mock 参考价格区间",
                    )
                )
            if (
                item.reference_unit_price_max is not None
                and item.unit_price > item.reference_unit_price_max
            ):
                findings.append(
                    RuleFinding(
                        code="PRICE_ABOVE_REFERENCE",
                        severity="medium",
                        stage="customs_review",
                        field=f"{prefix}.unit_price",
                        message="申报单价高于 Mock 参考价格区间",
                    )
                )
            if item.regulatory_codes and not declaration.licenses:
                findings.append(
                    RuleFinding(
                        code="LICENSE_REQUIRED",
                        severity="high",
                        stage="customs_review",
                        field=f"{prefix}.regulatory_codes",
                        message="商品涉及监管条件，但未提供许可证",
                        blocking=True,
                    )
                )
            if item.total_price >= 100_000 and item.net_weight < 10:
                findings.append(
                    RuleFinding(
                        code="HIGH_VALUE_LOW_WEIGHT",
                        severity="high",
                        stage="customs_review",
                        field=f"{prefix}.net_weight",
                        message="商品呈现高价值低重量风险特征",
                    )
                )
        if declaration.freight == 0 and declaration.incoterm.upper() == "CIF":
            findings.append(
                RuleFinding(
                    code="CIF_FREIGHT_MISSING",
                    severity="medium",
                    stage="customs_review",
                    field="freight",
                    message="CIF 成交方式下运费为零，需复核完税价格组成",
                )
            )
        findings.extend(
            self.knowledge_rules.evaluate(declaration, "customs_review")
        )
        return findings

    @staticmethod
    def requires_inspection(
        findings: list[RuleFinding], force_inspection: bool = False
    ) -> bool:
        return force_inspection or any(
            finding.severity == "high"
            and finding.code
            in {
                "PRICE_BELOW_REFERENCE",
                "WEIGHT_LOGIC_ERROR",
                "HIGH_VALUE_LOW_WEIGHT",
            }
            for finding in findings
        )

    @staticmethod
    def deterministic_random_inspection(
        business_case_id: str,
        rate: float,
    ) -> bool:
        if rate <= 0:
            return False
        threshold = max(0, min(rate, 1))
        digest = hashlib.sha256(business_case_id.encode("utf-8")).hexdigest()
        sample = int(digest[:8], 16) / 0xFFFFFFFF
        return sample < threshold

    @staticmethod
    def validate_release(case: BusinessCaseSnapshot) -> list[RuleFinding]:
        findings: list[RuleFinding] = []
        if case.stage != CustomsStage.TAX_PAID:
            findings.append(
                RuleFinding(
                    code="TAX_PAYMENT_REQUIRED",
                    severity="high",
                    stage="release",
                    message="当前案件尚未进入税款已缴状态",
                    blocking=True,
                )
            )
        if not case.tax_assessment or case.tax_assessment.status != "PAID":
            findings.append(
                RuleFinding(
                    code="TAX_PAYMENT_REQUIRED",
                    severity="high",
                    stage="release",
                    message="税单尚未确认支付",
                    blocking=True,
                )
            )
        if case.inspection and case.inspection.result not in {
            "MATCHED",
            "PASSED",
        }:
            findings.append(
                RuleFinding(
                    code="INSPECTION_REQUIRED",
                    severity="high",
                    stage="release",
                    message="查验尚未完成或查验结果不允许放行",
                    blocking=True,
                )
            )
        return findings
