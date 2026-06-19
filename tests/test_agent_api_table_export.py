from openpyxl import load_workbook

from src.agent_api.document_models import DocumentResult
from src.agent_api.table_export import TableWorkbookExporter


def test_table_export_preserves_values_merges_and_blocks_formulas(tmp_path):
    document = DocumentResult.model_validate(
        {
            "source_file_id": "file-001",
            "source_name": "declaration.png",
            "document_type": "table",
            "tables": [
                {
                    "rows": 3,
                    "columns": 2,
                    "metadata": {"name": "报关明细"},
                    "cells": [
                        {
                            "row": 0,
                            "column": 0,
                            "column_span": 2,
                            "text": "商品明细",
                            "confidence": 0.99,
                        },
                        {"row": 1, "column": 0, "text": "HS编码"},
                        {
                            "row": 1,
                            "column": 1,
                            "text": "85423100",
                            "normalized_value": 85423100,
                        },
                        {
                            "row": 2,
                            "column": 0,
                            "text": "=HYPERLINK(\"https://example.test\")",
                        },
                        {
                            "row": 2,
                            "column": 1,
                            "text": "待复核",
                            "review_status": "review_required",
                        },
                    ],
                }
            ],
        }
    )
    destination = tmp_path / "table.xlsx"

    TableWorkbookExporter().export(document, destination)

    workbook = load_workbook(destination, data_only=False)
    sheet = workbook["报关明细"]
    assert "A1:B1" in {str(item) for item in sheet.merged_cells.ranges}
    assert sheet["B2"].value == 85423100
    assert sheet["A3"].data_type != "f"
    assert sheet["A3"].value.startswith("'=")
    assert sheet["B3"].fill.fill_type == "solid"
