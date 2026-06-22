import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio


TEST_DATABASE_PATH = (
    Path(tempfile.gettempdir())
    / f"customs_ai_agent_pytest_{os.getpid()}.db"
)
os.environ.setdefault(
    "CUSTOMS_AUDIT_DB_PATH",
    str(TEST_DATABASE_PATH),
)


def pytest_addoption(parser):
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="run tests marked as slow",
    )
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="run tests marked as live_model",
    )
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run tests marked as integration",
    )


def pytest_collection_modifyitems(config, items):
    gated_markers = {
        "slow": ("--run-slow", config.getoption("--run-slow")),
        "live_model": ("--run-live", config.getoption("--run-live")),
        "integration": ("--run-integration", config.getoption("--run-integration")),
    }

    for item in items:
        missing_flags = [
            option
            for marker, (option, enabled) in gated_markers.items()
            if item.get_closest_marker(marker) and not enabled
        ]
        if not missing_flags:
            continue
        item.add_marker(
            pytest.mark.skip(
                reason=(
                    "requires explicit pytest option(s): "
                    + ", ".join(sorted(set(missing_flags)))
                )
            )
        )


@pytest_asyncio.fixture(scope="session", autouse=True)
async def isolate_global_async_database():
    """Keep tests off the developer DB and close aiosqlite worker threads."""
    from src.database.connection import init_db

    await init_db()
    yield

    try:
        from src.database.connection import engine

        await engine.dispose()
    except ImportError:
        pass

    for suffix in ("", "-shm", "-wal"):
        path = Path(f"{TEST_DATABASE_PATH}{suffix}")
        try:
            path.unlink(missing_ok=True)
        except PermissionError:
            pass
