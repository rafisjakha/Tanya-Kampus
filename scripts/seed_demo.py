"""Muat dokumen contoh (data/sample/*.md) dan index, supaya demo bisa langsung dicoba.

    python -m scripts.seed_demo

Aman dijalankan berulang: dokumen dengan judul yang sama dilewati.
"""
from __future__ import annotations

import sys

from app.config import BASE_DIR, get_settings
from app.db import db, init_db
from app.ingestion import service
from app.rag.embeddings import build_embedder

SAMPLE_DIR = BASE_DIR / "data" / "sample"

# nama file -> (judul, kategori, tanggal berlaku)
SAMPLES = {
    "panduan-akademik-contoh.md": ("Panduan Akademik (CONTOH)", "akademik", "2026-01-01"),
    "panduan-tugas-akhir-contoh.md": ("Panduan Tugas Akhir (CONTOH)", "tugas_akhir", "2026-02-01"),
}


def main() -> int:
    settings = get_settings()
    init_db()
    embedder = build_embedder(settings)
    print(f"Embedding: {embedder.name} (unduhan model pertama kali bisa beberapa menit)")

    for filename, (title, category, date) in SAMPLES.items():
        path = SAMPLE_DIR / filename
        if not path.exists():
            print(f"- lewati {filename}: file tidak ada")
            continue
        with db() as conn:
            if conn.execute("SELECT 1 FROM documents WHERE title = ?", (title,)).fetchone():
                print(f"- lewati '{title}': sudah ada")
                continue
        doc_id = service.create_manual(
            title=title, markdown=path.read_text(encoding="utf-8"), category=category,
            effective_date=date, source_url=None, created_by="seed",
        )
        doc = service.index_document(doc_id, embedder, settings)
        print(f"- '{title}': {doc['chunk_count']} chunk")
    print("Selesai. Jalankan: uvicorn app.main:app --reload")
    return 0


if __name__ == "__main__":
    sys.exit(main())
