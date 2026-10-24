"""Dokumen dari sumber resmi (data/knowledge) siap dimuat lewat seed_demo --knowledge."""
from app.rag.pipeline import DIRECTORY_CATEGORY, DIRECTORY_MAX_CHARS
from scripts.seed_demo import KNOWLEDGE, KNOWLEDGE_DIR


def test_semua_file_knowledge_ada_dan_mencantumkan_sumber():
    for filename in KNOWLEDGE:
        text = (KNOWLEDGE_DIR / filename).read_text(encoding="utf-8")
        assert "Sumber" in text, f"{filename} tidak mencantumkan sumber"


def test_direktori_kontak_muat_dalam_batas_prompt():
    kontak = [f for f, (_, category, _, _) in KNOWLEDGE.items() if category == DIRECTORY_CATEGORY]
    assert kontak, "harus ada satu dokumen berkategori kontak"
    total = sum(len((KNOWLEDGE_DIR / f).read_text(encoding="utf-8")) for f in kontak)
    assert total <= DIRECTORY_MAX_CHARS
