from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from .models import BusinessCaseSnapshot


class CaseNotFoundError(KeyError):
    pass


class CaseVersionConflictError(ValueError):
    pass


class SQLiteCustomsCaseRepository:
    schema_version = 1

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mock_customs_schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mock_customs_cases (
                    business_case_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    mock_case_id TEXT NOT NULL,
                    case_version INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_mock_customs_session
                ON mock_customs_cases (tenant_id, session_id, updated_at)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mock_customs_action_results (
                    business_case_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (business_case_id, request_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mock_customs_case_requests (
                    tenant_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    business_case_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (tenant_id, request_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mock_customs_declaration_versions (
                    version_id TEXT PRIMARY KEY,
                    business_case_id TEXT NOT NULL,
                    version_no INTEGER NOT NULL,
                    source_version_id TEXT,
                    reason TEXT NOT NULL,
                    declaration_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (business_case_id, version_no)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mock_customs_documents (
                    document_id TEXT NOT NULL,
                    business_case_id TEXT NOT NULL,
                    document_version INTEGER NOT NULL,
                    document_type TEXT NOT NULL,
                    document_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (
                        business_case_id, document_id, document_version
                    )
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mock_customs_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    business_case_id TEXT NOT NULL,
                    receipt_type TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mock_customs_timeline_events (
                    event_id TEXT PRIMARY KEY,
                    business_case_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (business_case_id, sequence)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mock_customs_tax_assessments (
                    business_case_id TEXT PRIMARY KEY,
                    assessment_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mock_customs_inspections (
                    business_case_id TEXT PRIMARY KEY,
                    inspection_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS mock_customs_agent_decisions (
                    event_id TEXT PRIMARY KEY,
                    business_case_id TEXT NOT NULL,
                    model_version TEXT,
                    prompt_version TEXT,
                    model_invoked INTEGER NOT NULL,
                    fallback_used INTEGER NOT NULL,
                    decision_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO mock_customs_schema_migrations (version)
                VALUES (?)
                """,
                (self.schema_version,),
            )

    def create(self, snapshot: BusinessCaseSnapshot) -> BusinessCaseSnapshot:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO mock_customs_cases (
                    business_case_id, tenant_id, session_id, mock_case_id,
                    case_version, stage, snapshot_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.business_case_id,
                    snapshot.tenant_id,
                    snapshot.session_id,
                    snapshot.mock_case_id,
                    snapshot.case_version,
                    snapshot.stage.value,
                    snapshot.model_dump_json(),
                    snapshot.updated_at,
                ),
            )
            self._sync_audit_tables(connection, snapshot)
        return snapshot.model_copy(deep=True)

    def get_case_id_for_request(
        self,
        tenant_id: str,
        request_id: str,
    ) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT business_case_id FROM mock_customs_case_requests
                WHERE tenant_id = ? AND request_id = ?
                """,
                (tenant_id, request_id),
            ).fetchone()
        return str(row[0]) if row else None

    def save_case_request(
        self,
        tenant_id: str,
        request_id: str,
        business_case_id: str,
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO mock_customs_case_requests (
                    tenant_id, request_id, business_case_id
                ) VALUES (?, ?, ?)
                """,
                (tenant_id, request_id, business_case_id),
            )

    def get(self, business_case_id: str) -> BusinessCaseSnapshot:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT snapshot_json FROM mock_customs_cases
                WHERE business_case_id = ?
                """,
                (business_case_id,),
            ).fetchone()
        if row is None:
            raise CaseNotFoundError(business_case_id)
        return BusinessCaseSnapshot.model_validate(json.loads(row[0]))

    def save(
        self, snapshot: BusinessCaseSnapshot, expected_version: int
    ) -> BusinessCaseSnapshot:
        next_snapshot = snapshot.model_copy(deep=True)
        next_snapshot.case_version = expected_version + 1
        next_snapshot.context_version = snapshot.context_version + 1
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE mock_customs_cases
                SET case_version = ?, stage = ?, snapshot_json = ?, updated_at = ?
                WHERE business_case_id = ? AND case_version = ?
                """,
                (
                    next_snapshot.case_version,
                    next_snapshot.stage.value,
                    next_snapshot.model_dump_json(),
                    next_snapshot.updated_at,
                    next_snapshot.business_case_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise CaseVersionConflictError(next_snapshot.business_case_id)
            self._sync_audit_tables(connection, next_snapshot)
        return next_snapshot

    @staticmethod
    def _sync_audit_tables(
        connection: sqlite3.Connection,
        snapshot: BusinessCaseSnapshot,
    ) -> None:
        for version in snapshot.declaration_versions:
            connection.execute(
                """
                INSERT OR IGNORE INTO mock_customs_declaration_versions (
                    version_id, business_case_id, version_no,
                    source_version_id, reason, declaration_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version.version_id,
                    snapshot.business_case_id,
                    version.version_no,
                    version.source_version_id,
                    version.reason,
                    version.declaration.model_dump_json(),
                    version.created_at,
                ),
            )
        for document in snapshot.documents:
            connection.execute(
                """
                INSERT OR IGNORE INTO mock_customs_documents (
                    document_id, business_case_id, document_version,
                    document_type, document_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    document.document_id,
                    snapshot.business_case_id,
                    document.document_version,
                    document.document_type,
                    document.model_dump_json(),
                    document.created_at,
                ),
            )
        for receipt in snapshot.receipts:
            connection.execute(
                """
                INSERT OR IGNORE INTO mock_customs_receipts (
                    receipt_id, business_case_id, receipt_type,
                    decision, receipt_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.receipt_id,
                    snapshot.business_case_id,
                    receipt.receipt_type,
                    receipt.decision,
                    receipt.model_dump_json(),
                    receipt.created_at,
                ),
            )
        for event in snapshot.timeline:
            connection.execute(
                """
                INSERT OR IGNORE INTO mock_customs_timeline_events (
                    event_id, business_case_id, sequence, stage,
                    event_type, event_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    snapshot.business_case_id,
                    event.sequence,
                    event.stage.value,
                    event.event_type,
                    event.model_dump_json(),
                    event.created_at,
                ),
            )
            if event.event_type == "customs_decision":
                connection.execute(
                    """
                    INSERT OR IGNORE INTO mock_customs_agent_decisions (
                        event_id, business_case_id, model_version,
                        prompt_version, model_invoked, fallback_used,
                        decision_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        snapshot.business_case_id,
                        event.data.get("model_version"),
                        event.data.get("prompt_version"),
                        int(bool(event.data.get("model_invoked"))),
                        int(bool(event.data.get("fallback_used"))),
                        event.model_dump_json(),
                        event.created_at,
                    ),
                )
        if snapshot.tax_assessment:
            connection.execute(
                """
                INSERT INTO mock_customs_tax_assessments (
                    business_case_id, assessment_json
                ) VALUES (?, ?)
                ON CONFLICT(business_case_id) DO UPDATE SET
                    assessment_json=excluded.assessment_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    snapshot.business_case_id,
                    snapshot.tax_assessment.model_dump_json(),
                ),
            )
        if snapshot.inspection:
            connection.execute(
                """
                INSERT INTO mock_customs_inspections (
                    business_case_id, inspection_json
                ) VALUES (?, ?)
                ON CONFLICT(business_case_id) DO UPDATE SET
                    inspection_json=excluded.inspection_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    snapshot.business_case_id,
                    snapshot.inspection.model_dump_json(),
                ),
            )

    def list_for_session(
        self, tenant_id: str, session_id: str
    ) -> list[BusinessCaseSnapshot]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT snapshot_json FROM mock_customs_cases
                WHERE tenant_id = ? AND session_id = ?
                ORDER BY updated_at DESC
                """,
                (tenant_id, session_id),
            ).fetchall()
        return [
            BusinessCaseSnapshot.model_validate(json.loads(row[0]))
            for row in rows
        ]

    def get_action_result(
        self, business_case_id: str, request_id: str
    ) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT result_json FROM mock_customs_action_results
                WHERE business_case_id = ? AND request_id = ?
                """,
                (business_case_id, request_id),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def save_action_result(
        self,
        business_case_id: str,
        request_id: str,
        result: dict,
    ) -> dict:
        serialized = json.dumps(result, ensure_ascii=False)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO mock_customs_action_results (
                    business_case_id, request_id, result_json
                ) VALUES (?, ?, ?)
                """,
                (business_case_id, request_id, serialized),
            )
            row = connection.execute(
                """
                SELECT result_json FROM mock_customs_action_results
                WHERE business_case_id = ? AND request_id = ?
                """,
                (business_case_id, request_id),
            ).fetchone()
        return json.loads(row[0])
