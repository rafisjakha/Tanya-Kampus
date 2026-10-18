"""Kualitas retrieval pada dokumen contoh, memakai embedding hashing (tanpa unduhan model).

Embedding hashing hanya menangkap kesamaan kata, jadi tes ini menjaga lapisan keyword + chunking
tetap sehat. Kualitas semantik model asli diukur lewat `python -m eval.run_eval`.
"""
import csv
from pathlib import Path

from app.config import BASE_DIR
from app.ingestion import service
from app.rag.embeddings import HashingEmbedder
from app.rag.search import Retriever, keywords
from scripts.seed_demo import SAMPLES, SAMPLE_DIR


def _seed(env):
    from app.db import init_db

    init_db()
    emb = HashingEmbedder()
    for filename, (title, category, date) in SAMPLES.items():
        doc_id = service.create_manual(
            title=title, markdown=(SAMPLE_DIR / filename).read_text(encoding="utf-8"), category=category,
            effective_date=date, source_url=None, created_by="tes",
        )
        service.index_document(doc_id, emb, env)
    return Retriever(emb, env)


def test_hit_at_k_pada_testset(env):
    retriever = _seed(env)
    rows = list(csv.DictReader((BASE_DIR / "eval" / "testset.csv").open(encoding="utf-8")))
    answerable = [r for r in rows if r["answerable"] == "yes"]
    hits_ok = 0
    for r in answerable:
        found = retriever.search(r["question"], top_k=5)
        if any(r["expected_title"] in h.doc_title and r["expected_keyword"].lower() in h.content.lower() for h in found):
            hits_ok += 1
    assert hits_ok / len(answerable) >= 0.8, f"hit@5 hanya {hits_ok}/{len(answerable)}"


def test_skor_terjawab_lebih_tinggi_dari_di_luar_topik(env):
    retriever = _seed(env)
    on_topic = retriever.search("Apa syarat mendaftar sidang tugas akhir?")[0].score
    off_topic = retriever.search("Apa resep nasi goreng yang enak?")
    off_score = off_topic[0].score if off_topic else 0.0
    assert on_topic > off_score + 0.1


def test_stopword_dibuang_dari_keyword():
    assert keywords("Bagaimana cara mengajukan cuti akademik?") == ["cara", "mengajukan", "cuti", "akademik"]
