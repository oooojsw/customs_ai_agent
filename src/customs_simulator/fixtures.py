from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class MockCaseFixtureLoader:
    def __init__(self, fixture_dir: str | Path):
        self.fixture_dir = Path(fixture_dir)

    def load(self, mock_case_id: str) -> dict[str, Any]:
        path = self.fixture_dir / f"{mock_case_id}.json"
        if not path.is_file():
            raise FileNotFoundError(f"MOCK_CASE_NOT_FOUND: {mock_case_id}")
        with path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)

    def list_ids(self) -> list[str]:
        return sorted(path.stem for path in self.fixture_dir.glob("*.json"))
