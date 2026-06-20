"""
统一报关文档识别数据模型
===========================
定义文档识别（OCR/VLM）的统一数据结构，覆盖提取层和理解层的核心模型。

对齐《报关智能体平台集成中间层与多模态协议总体方案》第 4.3 节三层视觉引擎：
  1. 提取层 — DocumentResult, TableResult, CellResult
  2. 理解层 — FieldEvidence, 字段映射与校验
  3. 生成层 — 模板定义（后续实现）

所有枚举和 dataclass 均支持 JSON 序列化/反序列化，可直接用于 Skill 脚本输出和 Agent 协议 Event。
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, List, Dict, Any


# ============================================================================
# 枚举定义
# ============================================================================

class DocumentType(str, Enum):
    """文档/图片类型分类 — 对应协议 Attachment purpose + 识别结果分类"""
    DECLARATION = "declaration"               # 报关单
    INVOICE = "invoice"                       # 发票
    PACKING_LIST = "packing_list"             # 装箱单
    CERTIFICATE = "certificate"               # 原产地证等证明
    SOURCE_TABLE_IMAGE = "source_table_image" # 需要转换为结构化表格或Excel的图片
    DECLARATION_TEMPLATE = "declaration_template"  # 报关单模板
    DOCUMENT_TEMPLATE = "document_template"    # 通用模板
    REFERENCE = "reference"                   # 普通参考材料
    GENERAL_IMAGE = "general_image"           # 普通图片（非单证：货物照片/场景/物品）
    UNKNOWN = "unknown"                       # 待识别


class ConfidenceLevel(str, Enum):
    """识别置信度 — 决定字段采用策略"""
    HIGH = "high"       # ≥0.85：自动采用
    MEDIUM = "medium"   # 0.50–0.85：标黄建议确认
    LOW = "low"         # <0.50：标红必须人工确认


class ReviewStatus(str, Enum):
    """字段人工复核状态"""
    PENDING = "pending"         # 待确认
    CONFIRMED = "confirmed"     # 已确认
    CORRECTED = "corrected"     # 已修正
    REJECTED = "rejected"       # 已驳回


class OutputKind(str, Enum):
    """Output 类型 — 对应协议第 10.1 节"""
    STRUCTURED_DATA = "structured_data"     # OCR JSON / 审单 JSON
    TABLE = "table"                         # 平台可直接渲染的表格数据
    SPREADSHEET = "spreadsheet"             # XLSX / CSV
    DOCUMENT = "document"                   # DOCX / PDF / TXT / Markdown
    IMAGE = "image"                         # PNG / JPEG / 标注图
    VALIDATION_REPORT = "validation_report" # 字段校验与人工复核结果
    CITATION_SET = "citation_set"           # 法规与证据引用集合
    ARCHIVE = "archive"                     # 多文件 ZIP
    TEMPLATE_DEFINITION = "template_definition"  # 模板版本与字段映射


# ============================================================================
# 提取层数据类
# ============================================================================

@dataclass
class CellResult:
    """单个单元格识别结果（方案要求的最小单元）

    字段对齐方案第 4.3 节："单元格中间结果至少包含 row、column、
    row_span、column_span、text、confidence 和 bbox"
    """
    row: int
    column: int
    text: str
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    row_span: int = 1
    column_span: int = 1
    bbox: Optional[List[float]] = None   # [x1, y1, x2, y2] 归一化或像素坐标
    confidence_score: float = 0.80       # 数值置信度 0.0–1.0
    cell_id: str = ""                    # 唯一标识，如 "R1C1"

    def to_dict(self) -> dict:
        d = {
            "row": self.row,
            "column": self.column,
            "row_span": self.row_span,
            "column_span": self.column_span,
            "text": self.text,
            "confidence": self.confidence.value,
            "confidence_score": round(self.confidence_score, 4),
            "cell_id": self.cell_id or f"R{self.row}C{self.column}",
        }
        if self.bbox:
            d["bbox"] = self.bbox
        return d


@dataclass
class TableResult:
    """表格识别结果

    包含完整的行列结构、单元格列表和表头语义映射。
    """
    table_id: str                                    # 唯一标识
    caption: str = ""                                # 表格标题/名称
    rows: int = 0                                    # 总行数
    columns: int = 0                                 # 总列数
    cells: List[CellResult] = field(default_factory=list)
    headers: List[str] = field(default_factory=list) # 表头列表
    merged_regions: List[dict] = field(default_factory=list)  # 合并区域 [{r1,c1,r2,c2}]
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    raw_markdown: str = ""                           # 原始 Markdown（保留证据）
    sheet_name: str = ""                             # 多 Sheet 时的 Sheet 名
    page_number: int = 1                             # 多页时的页码

    def to_dict(self) -> dict:
        return {
            "table_id": self.table_id,
            "caption": self.caption,
            "rows": self.rows,
            "columns": self.columns,
            "headers": self.headers,
            "cells": [c.to_dict() for c in self.cells],
            "merged_regions": self.merged_regions,
            "confidence": self.confidence.value,
            "raw_markdown": self.raw_markdown,
            "sheet_name": self.sheet_name,
            "page_number": self.page_number,
        }


# ============================================================================
# 理解层数据类
# ============================================================================

# 关键字段列表 — 使用更严格阈值
CRITICAL_FIELDS = {
    "entry_id", "declaration_id", "报关单号",
    "hs_code", "HS编码", "hs_code",
    "total_price", "总价", "amount",
    "currency", "币种",
    "quantity", "数量",
}

# 统一报关字段名映射
FIELD_NAME_MAP = {
    "entry_id": "报关单号",
    "declaration_id": "报关单号",
    "declaration_number": "报关单号",
    "goods_name": "货物名称",
    "hs_code": "HS编码",
    "quantity": "数量",
    "unit": "单位",
    "unit_price": "单价",
    "total_price": "总价",
    "currency": "币种",
    "origin_country": "原产国",
    "declaration_elements": "申报要素",
    "invoice_total": "发票总额",
    "goods_category": "商品类别",
}


@dataclass
class FieldEvidence:
    """单字段识别证据 — 保留完整追溯链

    对齐方案第 4.3 节："每个字段保留原文、标准值、页码、坐标、
    置信度、来源附件和人工确认状态"
    """
    field_name: str                              # 统一字段名（使用 FIELD_NAME_MAP）
    original_text: str = ""                      # OCR 原始文本
    standard_value: str = ""                     # 标准化后的值
    cell_refs: List[str] = field(default_factory=list)  # 引用的 cell_id 列表
    page_number: int = 1
    bbox: Optional[List[float]] = None           # [x1, y1, x2, y2]
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    confidence_score: float = 0.80
    source_attachment_id: Optional[str] = None   # 来源附件 file_id
    source_table_id: Optional[str] = None        # 来源表格 table_id
    needs_review: bool = False                   # 是否需要人工复核
    review_status: ReviewStatus = ReviewStatus.PENDING
    is_critical: bool = False                    # 是否为关键字段（使用更严格阈值）
    corrected_value: Optional[str] = None        # 人工修正后的值
    notes: str = ""                              # 补充说明

    def __post_init__(self):
        if not self.is_critical:
            self.is_critical = self.field_name in CRITICAL_FIELDS

    def to_dict(self) -> dict:
        d = {
            "field_name": self.field_name,
            "original_text": self.original_text,
            "standard_value": self.standard_value,
            "cell_refs": self.cell_refs,
            "page_number": self.page_number,
            "confidence": self.confidence.value,
            "confidence_score": round(self.confidence_score, 4),
            "source_attachment_id": self.source_attachment_id,
            "source_table_id": self.source_table_id,
            "needs_review": self.needs_review,
            "review_status": self.review_status.value,
            "is_critical": self.is_critical,
            "notes": self.notes,
        }
        if self.bbox:
            d["bbox"] = self.bbox
        if self.corrected_value is not None:
            d["corrected_value"] = self.corrected_value
        return d

    @property
    def display_value(self) -> str:
        """获取当前有效值（人工修正优先）"""
        return self.corrected_value or self.standard_value or self.original_text


# ============================================================================
# 文档结果（顶层）
# ============================================================================

@dataclass
class DocumentResult:
    """单张图片/文档的完整识别结果

    顶层数据类，包含文档分类、表格集合、字段集合和元信息。
    可直接序列化为 JSON 作为 Skill 脚本输出或 Agent 协议 Output.data。
    """
    document_id: str                             # 唯一标识
    document_type: DocumentType = DocumentType.UNKNOWN
    file_name: str = ""                          # 原始文件名
    tables: List[TableResult] = field(default_factory=list)
    fields: List[FieldEvidence] = field(default_factory=list)
    raw_text: str = ""                           # 保留原始识别文本（证据）
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    source_attachment_id: Optional[str] = None   # 来源附件
    page_count: int = 1
    model_used: str = ""                         # 识别模型
    processing_time_ms: int = 0                  # 处理耗时
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # 下层协议字段
    schema_version: str = "1.0"

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "document_id": self.document_id,
            "document_type": self.document_type.value,
            "file_name": self.file_name,
            "tables": [t.to_dict() for t in self.tables],
            "fields": [f.to_dict() for f in self.fields],
            "raw_text": self.raw_text,
            "confidence": self.confidence.value,
            "source_attachment_id": self.source_attachment_id,
            "page_count": self.page_count,
            "model_used": self.model_used,
            "processing_time_ms": self.processing_time_ms,
            "warnings": self.warnings,
            "metadata": self.metadata,
        }

    def get_field(self, field_name: str) -> Optional[FieldEvidence]:
        """按统一字段名查找"""
        for f in self.fields:
            if f.field_name == field_name:
                return f
        return None

    def get_fields_by_confidence(self, level: ConfidenceLevel) -> List[FieldEvidence]:
        """按置信度筛选字段"""
        return [f for f in self.fields if f.confidence == level]

    def get_fields_needing_review(self) -> List[FieldEvidence]:
        """获取所有需要人工复核的字段"""
        return [f for f in self.fields if f.needs_review]

    def get_critical_fields(self) -> List[FieldEvidence]:
        """获取关键字段"""
        return [f for f in self.fields if f.is_critical]

    def validation_summary(self) -> dict:
        """生成校验摘要"""
        total = len(self.fields)
        high = len(self.get_fields_by_confidence(ConfidenceLevel.HIGH))
        medium = len(self.get_fields_by_confidence(ConfidenceLevel.MEDIUM))
        low = len(self.get_fields_by_confidence(ConfidenceLevel.LOW))
        needs_review = len(self.get_fields_needing_review())
        return {
            "total_fields": total,
            "high_confidence": high,
            "medium_confidence": medium,
            "low_confidence": low,
            "fields_needing_review": needs_review,
            "auto_adoption_rate": round(high / total, 3) if total > 0 else 0,
        }


# ============================================================================
# 置信度阈值与判定
# ============================================================================

# 通用阈值
CONFIDENCE_THRESHOLD_HIGH = 0.85    # ≥ 此值为 HIGH
CONFIDENCE_THRESHOLD_MEDIUM = 0.50  # ≥ 此值为 MEDIUM，低于为 LOW

# 关键字段使用更严格阈值
CRITICAL_FIELD_THRESHOLD_HIGH = 0.90
CRITICAL_FIELD_THRESHOLD_MEDIUM = 0.65


def classify_confidence(score: float, is_critical: bool = False) -> ConfidenceLevel:
    """根据数值分数和字段重要性判定置信度等级

    Args:
        score: 0.0–1.0 的置信度分数
        is_critical: 是否为关键字段

    Returns:
        ConfidenceLevel 枚举值
    """
    if is_critical:
        if score >= CRITICAL_FIELD_THRESHOLD_HIGH:
            return ConfidenceLevel.HIGH
        elif score >= CRITICAL_FIELD_THRESHOLD_MEDIUM:
            return ConfidenceLevel.MEDIUM
        return ConfidenceLevel.LOW
    else:
        if score >= CONFIDENCE_THRESHOLD_HIGH:
            return ConfidenceLevel.HIGH
        elif score >= CONFIDENCE_THRESHOLD_MEDIUM:
            return ConfidenceLevel.MEDIUM
        return ConfidenceLevel.LOW


def needs_review(confidence: ConfidenceLevel, is_critical: bool = False) -> bool:
    """判断字段是否需要人工复核

    规则：
    - HIGH: 不需要复核（自动采用）
    - MEDIUM: 建议复核（标黄）
    - LOW: 必须复核（标红），关键字段 LOW 不得用于正式报关单
    """
    if confidence == ConfidenceLevel.HIGH:
        return False
    if confidence == ConfidenceLevel.LOW:
        return True
    # MEDIUM
    return is_critical  # 关键字段 MEDIUM 也建议复核


# ============================================================================
# JSON 序列化工具
# ============================================================================

def document_result_to_json(result: DocumentResult) -> dict:
    """将 DocumentResult 转为可 JSON 序列化的 dict"""
    return result.to_dict()


def json_to_document_result(data: dict) -> DocumentResult:
    """从 JSON dict 反序列化为 DocumentResult

    容错处理：缺失字段使用默认值。
    """
    tables = []
    for t in data.get("tables", []):
        cells = []
        for c in t.get("cells", []):
            cells.append(CellResult(
                row=c.get("row", 0),
                column=c.get("column", 0),
                text=c.get("text", ""),
                confidence=ConfidenceLevel(c.get("confidence", "medium")),
                row_span=c.get("row_span", 1),
                column_span=c.get("column_span", 1),
                bbox=c.get("bbox"),
                confidence_score=c.get("confidence_score", 0.80),
                cell_id=c.get("cell_id", ""),
            ))
        tables.append(TableResult(
            table_id=t.get("table_id", ""),
            caption=t.get("caption", ""),
            rows=t.get("rows", 0),
            columns=t.get("columns", 0),
            cells=cells,
            headers=t.get("headers", []),
            merged_regions=t.get("merged_regions", []),
            confidence=ConfidenceLevel(t.get("confidence", "medium")),
            raw_markdown=t.get("raw_markdown", ""),
            sheet_name=t.get("sheet_name", ""),
            page_number=t.get("page_number", 1),
        ))

    fields = []
    for f in data.get("fields", []):
        fields.append(FieldEvidence(
            field_name=f.get("field_name", ""),
            original_text=f.get("original_text", ""),
            standard_value=f.get("standard_value", ""),
            cell_refs=f.get("cell_refs", []),
            page_number=f.get("page_number", 1),
            bbox=f.get("bbox"),
            confidence=ConfidenceLevel(f.get("confidence", "medium")),
            confidence_score=f.get("confidence_score", 0.80),
            source_attachment_id=f.get("source_attachment_id"),
            source_table_id=f.get("source_table_id"),
            needs_review=f.get("needs_review", False),
            review_status=ReviewStatus(f.get("review_status", "pending")),
            is_critical=f.get("is_critical", False),
            corrected_value=f.get("corrected_value"),
            notes=f.get("notes", ""),
        ))

    return DocumentResult(
        document_id=data.get("document_id", ""),
        document_type=DocumentType(data.get("document_type", "unknown")),
        file_name=data.get("file_name", ""),
        tables=tables,
        fields=fields,
        raw_text=data.get("raw_text", ""),
        confidence=ConfidenceLevel(data.get("confidence", "medium")),
        source_attachment_id=data.get("source_attachment_id"),
        page_count=data.get("page_count", 1),
        model_used=data.get("model_used", ""),
        processing_time_ms=data.get("processing_time_ms", 0),
        warnings=data.get("warnings", []),
        metadata=data.get("metadata", {}),
        schema_version=data.get("schema_version", "1.0"),
    )


# ============================================================================
# 校验报告数据类
# ============================================================================

class ValidationSeverity(str, Enum):
    """校验发现严重程度"""
    ERROR = "error"        # 必须修正：关键字段缺失/格式错误/金额不一致
    WARNING = "warning"    # 建议修正：中置信度字段/非关键字段问题
    INFO = "info"          # 信息提示：低风险提示/统计信息


@dataclass
class ValidationFinding:
    """单条校验发现"""
    rule_id: str
    field_names: List[str] = field(default_factory=list)
    message: str = ""
    severity: ValidationSeverity = ValidationSeverity.INFO
    expected: Optional[str] = None
    actual: Optional[str] = None
    suggestion: str = ""

    def to_dict(self) -> dict:
        d = {
            "rule_id": self.rule_id,
            "field_names": self.field_names,
            "message": self.message,
            "severity": self.severity.value,
            "suggestion": self.suggestion,
        }
        if self.expected is not None:
            d["expected"] = self.expected
        if self.actual is not None:
            d["actual"] = self.actual
        return d


@dataclass
class ValidationReport:
    """字段校验报告 — 对应协议 Output kind=validation_report"""
    report_id: str
    document_id: str
    rules_checked: int = 0
    findings: List[ValidationFinding] = field(default_factory=list)
    passed: bool = True
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    checked_at: str = ""  # ISO timestamp

    def has_errors(self) -> bool:
        return self.error_count > 0

    def has_warnings(self) -> bool:
        return self.warning_count > 0

    def is_clean(self) -> bool:
        return len(self.findings) == 0

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "document_id": self.document_id,
            "rules_checked": self.rules_checked,
            "findings": [f.to_dict() for f in self.findings],
            "passed": self.passed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "checked_at": self.checked_at,
        }


# ============================================================================
# 字段映射辅助函数
# ============================================================================

def map_field_name(raw_name: str) -> str:
    """将原始字段名映射到统一字段名

    Args:
        raw_name: OCR 或用户传入的原始字段名（中/英/混合）

    Returns:
        统一字段名（如果无匹配则返回原始值）
    """
    # 精确匹配
    if raw_name in FIELD_NAME_MAP:
        return raw_name

    # 中文值匹配
    chinese_to_key = {v: k for k, v in FIELD_NAME_MAP.items()}
    if raw_name in chinese_to_key:
        return chinese_to_key[raw_name]

    # 模糊匹配（包含关系）
    raw_lower = raw_name.lower().strip()
    for key, cn_name in FIELD_NAME_MAP.items():
        if raw_lower == key.lower() or raw_lower == cn_name:
            return key

    return raw_name
