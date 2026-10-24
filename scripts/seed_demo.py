"""Muat dokumen dan index, supaya bot bisa langsung dicoba.

    python -m scripts.seed_demo               # dokumen contoh fiktif (data/sample)
    python -m scripts.seed_demo --knowledge   # dokumen dari sumber resmi publik (data/knowledge)

Aman dijalankan berulang: dokumen dengan judul yang sama dilewati.
"""
from __future__ import annotations

import argparse
import sys

from app.config import BASE_DIR, get_settings
from app.db import db, init_db
from app.ingestion import service
from app.rag.embeddings import build_embedder

SAMPLE_DIR = BASE_DIR / "data" / "sample"
KNOWLEDGE_DIR = BASE_DIR / "data" / "knowledge"

# nama file -> (judul, kategori, tanggal berlaku, URL sumber)
SAMPLES = {
    "panduan-akademik-contoh.md": ("Panduan Akademik (CONTOH)", "akademik", "2026-01-01", None),
    "panduan-tugas-akhir-contoh.md": ("Panduan Tugas Akhir (CONTOH)", "tugas_akhir", "2026-02-01", None),
}

# Disusun dari sumber resmi publik, diakses 24 Oktober 2026. Rincian sumber ada di bagian akhir tiap file.
KNOWLEDGE = {
    "direktori-kontak-tel-u-jakarta.md": (
        "Direktori Kontak Layanan Telkom University Jakarta", "kontak", "2026-10-24",
        "https://jakarta.telkomuniversity.ac.id/",
    ),
    "pedoman-tak-telkom-university.md": (
        "Pedoman TAK Telkom University", "tak", "2022-08-02",
        "https://bolif.telkomuniversity.ac.id/wp-content/uploads/2023/06/SK-TAK-2022.pdf",
    ),
    "kerja-praktik-s1-ti-jakarta.md": (
        "Kerja Praktik, Tugas Akhir, dan Kelulusan S1 Teknologi Informasi Jakarta", "kp", "2026-10-24",
        "https://bpa.telkomuniversity.ac.id/wp-content/uploads/2024/11/Pedoman-Akademik-Tel-U-2024.pdf",
    ),
    "mbkm-s1-ti-jakarta.md": (
        "MBKM, WRAP, dan Magang S1 Teknologi Informasi Jakarta", "mbkm", "2026-10-24",
        "https://bit-jkt.telkomuniversity.ac.id/kurikulum-mbkm-wrap/",
    ),
    "innovillage.md": ("Innovillage", "innovillage", "2026-10-24", "https://innovillage.id/"),
    "profil-prodi-s1-ti-jakarta.md": (
        "Profil Prodi S1 Teknologi Informasi Telkom University Jakarta", "umum", "2026-10-24",
        "https://bit-jkt.telkomuniversity.ac.id/informasi/",
    ),
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--knowledge", action="store_true", help="muat dokumen dari sumber resmi (data/knowledge)")
    args = ap.parse_args(argv)
    folder, docs = (KNOWLEDGE_DIR, KNOWLEDGE) if args.knowledge else (SAMPLE_DIR, SAMPLES)

    settings = get_settings()
    init_db()
    embedder = build_embedder(settings)
    print(f"Embedding: {embedder.name} (unduhan model pertama kali bisa beberapa menit)")

    for filename, (title, category, date, url) in docs.items():
        path = folder / filename
        if not path.exists():
            print(f"- lewati {filename}: file tidak ada")
            continue
        with db() as conn:
            if conn.execute("SELECT 1 FROM documents WHERE title = ?", (title,)).fetchone():
                print(f"- lewati '{title}': sudah ada")
                continue
        doc_id = service.create_manual(
            title=title, markdown=path.read_text(encoding="utf-8"), category=category,
            effective_date=date, source_url=url, created_by="seed",
        )
        doc = service.index_document(doc_id, embedder, settings)
        print(f"- '{title}': {doc['chunk_count']} chunk")
    print("Selesai. Jalankan: uvicorn app.main:app --reload --port 8001")
    return 0


if __name__ == "__main__":
    sys.exit(main())
