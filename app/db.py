"""Lapisan SQLite.

Satu file .db menyimpan semuanya: admin, dokumen, chunk beserta embedding (BLOB float32),
indeks keyword FTS5, log tanya-jawab, feedback, dan cache jawaban.

Modul ini sengaja tipis supaya mudah diganti ke PostgreSQL nanti.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

import numpy as np

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'akademik',
    source_type TEXT NOT NULL DEFAULT 'file',        -- file | url | manual
    source_name TEXT,                                 -- nama file asli
    source_url TEXT,
    original_path TEXT,                               -- file asli di data/raw
    markdown TEXT NOT NULL DEFAULT '',                -- sumber kebenaran isi dokumen
    effective_date TEXT,                              -- tanggal berlaku (YYYY-MM-DD)
    status TEXT NOT NULL DEFAULT 'draft',             -- draft | indexed | error
    dirty INTEGER NOT NULL DEFAULT 0,                 -- 1 = markdown/judul berubah, perlu index ulang
    error TEXT,
    note TEXT,                                        -- catatan konversi (mis. hasil OCR, periksa kembali)
    content_hash TEXT,                                -- sha256 markdown, untuk deteksi duplikat
    downloadable INTEGER NOT NULL DEFAULT 0,          -- 1 = bot boleh mengirim file asli ke mahasiswa
    chunk_count INTEGER NOT NULL DEFAULT 0,
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    indexed_at TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    heading_path TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    embedding BLOB,
    embedding_model TEXT
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    heading_path, content, content='chunks', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, heading_path, content)
    VALUES (new.id, new.heading_path, new.content);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, heading_path, content)
    VALUES ('delete', old.id, old.heading_path, old.content);
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, heading_path, content)
    VALUES ('delete', old.id, old.heading_path, old.content);
    INSERT INTO chunks_fts(rowid, heading_path, content)
    VALUES (new.id, new.heading_path, new.content);
END;

CREATE TABLE IF NOT EXISTS query_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    channel TEXT NOT NULL DEFAULT 'api',
    user_ref TEXT,
    question TEXT NOT NULL,
    category TEXT,
    status TEXT NOT NULL,                             -- answered | not_found | error
    answer TEXT,
    top_score REAL,
    sources_json TEXT,
    latency_ms INTEGER,
    cached INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_log_status ON query_log(status);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id INTEGER NOT NULL REFERENCES query_log(id) ON DELETE CASCADE,
    rating INTEGER NOT NULL,                          -- 1 = membantu, -1 = tidak membantu
    comment TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(query_id)
);

CREATE TABLE IF NOT EXISTS answer_cache (
    key TEXT PRIMARY KEY,
    answer TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    top_score REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO meta(key, value) VALUES ('index_version', '0');
"""


def connect() -> sqlite3.Connection:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    """Buka koneksi, commit kalau sukses, rollback kalau error, selalu ditutup."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Kolom yang ditambahkan setelah rilis awal. Database lama otomatis di-upgrade saat startup.
_DOCUMENT_COLUMNS = {
    "note": "TEXT",
    "content_hash": "TEXT",
    "downloadable": "INTEGER NOT NULL DEFAULT 0",
}


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(documents)")}
    for name, decl in _DOCUMENT_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE documents ADD COLUMN {name} {decl}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_hash ON documents(content_hash)")


def init_db() -> None:
    settings = get_settings()
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


# --- versi indeks: dipakai untuk invalidasi cache retrieval dan cache jawaban -------------

def get_index_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM meta WHERE key = 'index_version'").fetchone()
    return int(row["value"]) if row else 0


def bump_index_version(conn: sqlite3.Connection) -> None:
    conn.execute(
        "UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key = 'index_version'"
    )


# --- embedding <-> BLOB ---------------------------------------------------------------------

def embedding_to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def blob_to_embedding(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)
