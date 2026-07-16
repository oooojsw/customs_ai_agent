"""Rebuild the portable FAISS index, including PDFs and text sources."""

import asyncio
import io
import json
import sys


if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

from src.services.knowledge_base import KnowledgeBase


async def rebuild() -> int:
    # Build in memory first. The old index remains usable until the new index,
    # metadata and manifest have all been generated successfully.
    kb = await asyncio.to_thread(KnowledgeBase, False, True)
    health = kb.get_index_health()
    print(json.dumps(health, ensure_ascii=False, indent=2))
    if not health["ready"]:
        print("索引重建完成，但健康检查未通过。", file=sys.stderr)
        return 1

    print(
        f"索引重建完成：{health['indexed_source_count']} 个来源，"
        f"{health['vector_count']} 个向量片段。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(rebuild()))
