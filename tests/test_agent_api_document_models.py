import pytest
from pydantic import ValidationError

from src.agent_api.document_models import (
    BoundingBox,
    CellResult,
    DocumentResult,
    TableResult,
    TemplateDefinition,
)


def test_document_result_preserves_table_structure_and_evidence_shape():
    document = DocumentResult.model_validate(
        {
            "source_file_id": "file-001",
            "source_name": "table.png",
            "document_type": "table",
            "full_text": "HS编码 85423100",
            "tables": [
                {
                    "rows": 2,
                    "columns": 2,
                    "cells": [
                        {
                            "row": 0,
                            "column": 0,
                            "text": "HS编码",
                            "confidence": 0.99,
                        },
                        {
                            "row": 0,
                            "column": 1,
                            "text": "85423100",
                            "confidence": 0.96,
                        },
                    ],
                }
            ],
            "fields": [
                {
                    "field_key": "goods.0.hs_code",
                    "raw_text": "85423100",
                    "normalized_value": "85423100",
                    "source_file_id": "file-001",
                    "confidence": 0.96,
                    "review_status": "auto_accepted",
                }
            ],
        }
    )

    assert document.tables[0].cells[1].normalized_value is None
    assert document.fields[0].normalized_value == "85423100"
    assert document.fields[0].source_file_id == "file-001"


def test_bounding_box_rejects_inverted_coordinates():
    with pytest.raises(ValidationError):
        BoundingBox(x1=100, y1=10, x2=50, y2=20)


def test_table_rejects_cell_outside_declared_dimensions():
    with pytest.raises(ValidationError):
        TableResult(
            rows=1,
            columns=1,
            cells=[CellResult(row=1, column=0, text="outside")],
        )


def test_table_rejects_span_outside_declared_dimensions():
    with pytest.raises(ValidationError):
        TableResult(
            rows=1,
            columns=1,
            cells=[
                CellResult(
                    row=0,
                    column=0,
                    column_span=2,
                    text="outside",
                )
            ],
        )


def test_table_rejects_overlapping_cells():
    with pytest.raises(ValidationError):
        TableResult(
            rows=2,
            columns=2,
            cells=[
                CellResult(row=0, column=0, column_span=2, text="merged"),
                CellResult(row=0, column=1, text="overlap"),
            ],
        )


def test_excel_template_requires_cell_mapping():
    with pytest.raises(ValidationError):
        TemplateDefinition.model_validate(
            {
                "template_id": "declaration-v1",
                "version": "1.0",
                "kind": "excel",
                "source_file_id": "template-file-001",
                "mappings": [
                    {
                        "field_key": "entry_id",
                        "target": {"kind": "excel", "sheet": "Sheet1"},
                    }
                ],
            }
        )


def test_image_template_requires_page_and_bbox():
    template = TemplateDefinition.model_validate(
        {
            "template_id": "declaration-image-v1",
            "version": "1.0",
            "kind": "image",
            "source_file_id": "template-file-001",
            "mappings": [
                {
                    "field_key": "entry_id",
                    "target": {
                        "kind": "image",
                        "page": 1,
                        "bbox": {"x1": 10, "y1": 10, "x2": 100, "y2": 30},
                    },
                }
            ],
        }
    )
    assert template.mappings[0].target.page == 1
