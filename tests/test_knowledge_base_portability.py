import json
from pathlib import Path

from langchain_core.documents import Document

from src.services.knowledge_base import KnowledgeBase


class _FakeIndex:
    ntotal = 3


class _FakeDocstore:
    def __init__(self) -> None:
        self._dict = {
            "1": Document(
                page_content="portable",
                metadata={"source": r"C:\old\project\data\knowledge\rule.txt"},
            )
        }


class _FakeVectorStore:
    def __init__(self) -> None:
        self.index = _FakeIndex()
        self.docstore = _FakeDocstore()

    def save_local(self, path: str) -> None:
        target = Path(path)
        target.mkdir(parents=True, exist_ok=True)
        (target / "index.faiss").write_bytes(b"faiss")
        (target / "index.pkl").write_bytes(b"pickle")


def _knowledge_base(tmp_path: Path) -> KnowledgeBase:
    kb = KnowledgeBase.__new__(KnowledgeBase)
    kb.base_dir = tmp_path
    kb.data_path = tmp_path / "data" / "knowledge"
    kb.vector_db_path = tmp_path / "config" / "faiss_index_local"
    kb.embedding_model_name = KnowledgeBase.DEFAULT_EMBEDDING_MODEL
    kb.embedding_model_revision = KnowledgeBase.DEFAULT_EMBEDDING_REVISION
    kb.auto_include_pdfs = True
    kb.vector_store = None
    kb.data_path.mkdir(parents=True)
    return kb


def test_scan_includes_extensionless_text_and_pdf(tmp_path: Path) -> None:
    kb = _knowledge_base(tmp_path)
    for name in ("rule.txt", "guide.md", "01-1", "manual.pdf", "rules.json"):
        (kb.data_path / name).write_bytes(b"content")

    names = [path.name for path in kb._scan_indexable_files(include_pdfs=True)]

    assert names == ["01-1", "guide.md", "manual.pdf", "rule.txt"]


def test_saved_manifest_and_metadata_are_portable(tmp_path: Path) -> None:
    kb = _knowledge_base(tmp_path)
    source = kb.data_path / "rule.txt"
    source.write_text("customs rule", encoding="utf-8")
    vector_store = _FakeVectorStore()

    kb._save_index(vector_store, [source])

    manifest = json.loads(
        (kb.vector_db_path / "manifest.json").read_text(encoding="utf-8")
    )
    document = vector_store.docstore._dict["1"]
    assert manifest["schema_version"] == KnowledgeBase.INDEX_SCHEMA_VERSION
    assert manifest["sources"] == ["data/knowledge/rule.txt"]
    assert manifest["vector_count"] == 3
    assert document.metadata["source"] == "data/knowledge/rule.txt"
    assert "C:" not in json.dumps(manifest)


def test_manifest_detects_changed_knowledge(tmp_path: Path) -> None:
    kb = _knowledge_base(tmp_path)
    source = kb.data_path / "rule.txt"
    source.write_text("version one", encoding="utf-8")
    kb._save_index(_FakeVectorStore(), [source])

    assert kb._manifest_is_current(kb._read_manifest()) is True
    source.write_text("version two", encoding="utf-8")
    assert kb._manifest_is_current(kb._read_manifest()) is False


def test_pdf_indexing_falls_back_to_ocr(monkeypatch, tmp_path: Path) -> None:
    kb = _knowledge_base(tmp_path)
    pdf_path = kb.data_path / "scan.pdf"
    pdf_path.write_bytes(b"pdf")

    monkeypatch.setattr(
        "src.services.knowledge_base.PDFService.extract_text",
        lambda *args, **kwargs: ("", 0.01),
    )
    monkeypatch.setattr(
        "src.services.rapidocr_service.RapidOCRService.extract_text",
        lambda *args, **kwargs: ("海关扫描文本" * 100, 1.0),
    )

    text, method = kb._extract_pdf_for_index(pdf_path)

    assert method == "rapidocr"
    assert "海关扫描文本" in text
