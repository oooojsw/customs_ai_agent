from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from .models import (
    AgentError,
    AgentEvent,
    CreateRunRequest,
    EventType,
    RunSnapshot,
    RunStatus,
    utc_now,
)
from .store import InMemoryRunStore, TERMINAL_STATUSES, _RunRecord


class SQLiteRunStore(InMemoryRunStore):
    """Durable single-instance RunStore with an in-memory live event bus."""

    def __init__(self, database_path: str | Path) -> None:
        super().__init__()
        self.database_path = Path(database_path).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = asyncio.Lock()
        self._initialize()
        self._load()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_runs (
                    run_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    request_fingerprint TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    events_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(tenant_id, request_id)
                )
                """
            )

    def _load(self) -> None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT request_fingerprint, snapshot_json, events_json
                FROM agent_runs
                """
            ).fetchall()
        for fingerprint, snapshot_json, events_json in rows:
            snapshot = RunSnapshot.model_validate_json(snapshot_json)
            events = [
                AgentEvent.model_validate(item)
                for item in json.loads(events_json)
            ]
            if snapshot.status not in TERMINAL_STATUSES:
                error = AgentError(
                    error_code="RUN_INTERRUPTED_BY_RESTART",
                    message="服务重启导致未完成任务中断，请使用新的 request_id 重试",
                    retryable=True,
                    stage="run_recovery",
                )
                snapshot.status = RunStatus.FAILED
                snapshot.error = error
                snapshot.completed_at = utc_now()
                snapshot.last_sequence += 1
                events.append(
                    AgentEvent(
                        run_id=snapshot.run_id,
                        request_id=snapshot.request_id,
                        session_id=snapshot.session_id,
                        sequence=snapshot.last_sequence,
                        event=EventType.AGENT_FAILED,
                        data={
                            "status": RunStatus.FAILED.value,
                            "error": error.model_dump(
                                mode="json", exclude_none=True
                            ),
                        },
                    )
                )
            record = _RunRecord(
                snapshot=snapshot,
                request_fingerprint=fingerprint,
                events=events,
            )
            self._runs[snapshot.run_id] = record
            self._request_index[
                (snapshot.tenant_id, snapshot.request_id)
            ] = snapshot.run_id
            self._persist_sync(record)

    async def create(
        self, request: CreateRunRequest
    ) -> tuple[RunSnapshot, bool]:
        snapshot, created = await super().create(request)
        if created:
            await self._persist(snapshot.run_id)
        return snapshot, created

    async def set_status(self, run_id: str, status: RunStatus) -> RunSnapshot:
        snapshot = await super().set_status(run_id, status)
        await self._persist(run_id)
        return snapshot

    async def append_event(self, run_id, event_type, data=None):
        event = await super().append_event(run_id, event_type, data)
        await self._persist(run_id)
        return event

    async def complete_with_event(self, run_id: str, **kwargs) -> RunSnapshot:
        snapshot = await super().complete_with_event(run_id, **kwargs)
        await self._persist(run_id)
        return snapshot

    async def fail_with_event(
        self, run_id: str, error: AgentError
    ) -> RunSnapshot:
        snapshot = await super().fail_with_event(run_id, error)
        await self._persist(run_id)
        return snapshot

    async def cancel_with_event(self, run_id: str) -> RunSnapshot:
        snapshot = await super().cancel_with_event(run_id)
        await self._persist(run_id)
        return snapshot

    async def add_warning(self, run_id: str, warning: AgentError) -> None:
        await super().add_warning(run_id, warning)
        await self._persist(run_id)

    async def set_usage(self, run_id: str, usage: dict) -> None:
        await super().set_usage(run_id, usage)
        await self._persist(run_id)

    async def set_context_version(
        self, run_id: str, context_version: int | None
    ) -> None:
        await super().set_context_version(run_id, context_version)
        await self._persist(run_id)

    async def _persist(self, run_id: str) -> None:
        async with self._write_lock:
            record = self._get_record(run_id)
            await asyncio.to_thread(self._persist_sync, record)

    def _persist_sync(self, record: _RunRecord) -> None:
        snapshot = record.snapshot
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_runs (
                    run_id, tenant_id, request_id, request_fingerprint,
                    snapshot_json, events_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    snapshot_json=excluded.snapshot_json,
                    events_json=excluded.events_json,
                    updated_at=excluded.updated_at
                """,
                (
                    snapshot.run_id,
                    snapshot.tenant_id,
                    snapshot.request_id,
                    record.request_fingerprint,
                    snapshot.model_dump_json(exclude_none=True),
                    json.dumps(
                        [
                            event.model_dump(mode="json", exclude_none=True)
                            for event in record.events
                        ],
                        ensure_ascii=False,
                    ),
                    utc_now().isoformat(),
                ),
            )
