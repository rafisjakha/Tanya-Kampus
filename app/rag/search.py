"""Hybrid search: semantik (embedding) + keyword (FTS5 BM25) + cakupan kata.

Skor akhir per chunk:

    lex   = 0.5 * bm25_relatif + 0.5 * cakupan_kata
    skor  = w_sem * cosine + (1 - w_sem) * lex

- cosine        : kemiripan makna (embedding sudah ternormalisasi, jadi dot product).
- bm25_relatif  : skor BM25 FTS5 dibagi skor terbaik pada query yang sama (0..1).
- cakupan_kata  : porsi kata kunci pertanyaan (tanpa stopword) yang muncul di chunk (0..1).
                  Ini yang membuat istilah seperti "KRS" atau "cuti" tetap berpengaruh
                  dan menahan skor chunk yang hanya mirip secara semantik umum.

Matriks embedding disimpan di memori dan dimuat ulang hanya bila `index_version` di DB berubah,
jadi query tidak perlu membaca semua BLOB dari SQLite setiap kali.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

import numpy as np

from ..config import Settings
from ..db import blob_to_embedding, db, get_index_version
from .embeddings import Embedder

_WORD_RE = re.compile(r"\w+", re.UNICODE)

STOPWORDS = frozenset(
    """
    yang dan di ke dari untuk pada dengan atau adalah itu ini apa apakah bagaimana berapa kapan
    dimana mana siapa kenapa mengapa saja sih dong kah lah nya ya yg dgn utk dlm tidak bisa dapat
    harus ada akan sudah belum saya aku kamu kita kami mereka bisakah boleh gimana gmn kalau jika
    bila agar supaya oleh sebagai para sebuah suatu ingin mau tolong mohon minta info informasi
    """.split()
)


def tokenize(text: str) -> list[str]:
    return [t.casefold() for t in _WORD_RE.findall(text)]


def keywords(text: str) -> list[str]:
    seen: list[str] = []
    for t in tokenize(text):
        if len(t) >= 2 and t not in STOPWORDS and t not in seen:
            seen.append(t)
    return seen


def build_fts_query(terms: list[str]) -> str:
    if not terms:
        return '""'
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)


@dataclass
class Hit:
    chunk_id: int
    doc_id: int
    doc_title: str
    category: str
    heading_path: str
    content: str
    effective_date: str | None
    source_url: str | None
    semantic: float
    lexical: float
    score: float
    downloadable: bool = False  # file asli boleh dikirim bot

    def to_debug(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "title": self.doc_title,
            "heading": self.heading_path,
            "semantic": round(self.semantic, 4),
            "lexical": round(self.lexical, 4),
            "score": round(self.score, 4),
            "snippet": self.content[:220],
        }


@dataclass
class _Matrix:
    version: int
    model: str
    ids: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    vectors: np.ndarray = field(default_factory=lambda: np.zeros((0, 0), dtype=np.float32))
    categories: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=object))


class Retriever:
    def __init__(self, embedder: Embedder, settings: Settings):
        self.embedder = embedder
        self.settings = settings
        self._cache: _Matrix | None = None

    # -- cache matriks embedding -----------------------------------------------------------

    def _matrix(self, conn: sqlite3.Connection) -> _Matrix:
        version = get_index_version(conn)
        cached = self._cache
        if cached and cached.version == version and cached.model == self.embedder.name:
            return cached
        rows = conn.execute(
            """
            SELECT c.id, c.embedding, d.category
            FROM chunks c JOIN documents d ON d.id = c.doc_id
            WHERE c.embedding IS NOT NULL AND c.embedding_model = ?
            """,
            (self.embedder.name,),
        ).fetchall()
        if rows:
            ids = np.array([r["id"] for r in rows], dtype=np.int64)
            # satu buffer lalu reshape: tanpa ribuan array kecil sementara seperti np.vstack
            vectors = blob_to_embedding(b"".join(r["embedding"] for r in rows)).reshape(len(rows), -1)
            categories = np.array([r["category"] for r in rows], dtype=object)
            matrix = _Matrix(version, self.embedder.name, ids, vectors, categories)
        else:
            matrix = _Matrix(version, self.embedder.name)
        self._cache = matrix
        return matrix

    def invalidate(self) -> None:
        self._cache = None

    # -- pencarian -------------------------------------------------------------------------

    def _semantic(self, conn, query: str, category: str | None, limit: int) -> dict[int, float]:
        m = self._matrix(conn)
        if len(m.ids) == 0:
            return {}
        qvec = self.embedder.embed_query(query)
        sims = m.vectors @ qvec
        if category:
            mask = m.categories == category
            sims = np.where(mask, sims, -np.inf)
        if limit < len(sims):  # ambil kandidat teratas dalam O(n), bukan mengurutkan semua chunk
            order = np.argpartition(-sims, limit - 1)[:limit]
        else:
            order = np.arange(len(sims))
        return {int(m.ids[i]): float(max(sims[i], 0.0)) for i in order if np.isfinite(sims[i])}

    def _bm25(self, conn, terms: list[str], category: str | None, limit: int) -> dict[int, float]:
        if not terms:
            return {}
        sql = """
            SELECT c.id AS id, bm25(chunks_fts) AS score
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.rowid
            JOIN documents d ON d.id = c.doc_id
            WHERE chunks_fts MATCH ?
        """
        params: list = [build_fts_query(terms)]
        if category:
            sql += " AND d.category = ?"
            params.append(category)
        sql += " ORDER BY score LIMIT ?"
        params.append(limit)
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return {}
        if not rows:
            return {}
        best = max(abs(r["score"]) for r in rows) or 1.0
        return {int(r["id"]): abs(r["score"]) / best for r in rows}

    def search(self, query: str, category: str | None = None, top_k: int | None = None) -> list[Hit]:
        top_k = top_k or self.settings.top_k
        terms = keywords(query)
        w_sem = self.settings.semantic_weight
        pool = max(top_k * 4, 20)

        with db() as conn:
            sem = self._semantic(conn, query, category, pool)
            bm = self._bm25(conn, terms, category, pool)
            ids = list(set(sem) | set(bm))
            if not ids:
                return []
            placeholders = ",".join("?" for _ in ids)
            rows = conn.execute(
                f"""
                SELECT c.id, c.doc_id, c.heading_path, c.content,
                       d.title, d.category, d.effective_date, d.source_url,
                       (d.downloadable = 1 AND d.original_path IS NOT NULL) AS downloadable
                FROM chunks c JOIN documents d ON d.id = c.doc_id
                WHERE c.id IN ({placeholders})
                """,
                ids,
            ).fetchall()

        hits: list[Hit] = []
        for r in rows:
            haystack = f"{r['heading_path']} {r['content']}".casefold()
            coverage = (
                sum(1 for t in terms if t in haystack) / len(terms) if terms else 0.0
            )
            lex = 0.5 * bm.get(r["id"], 0.0) + 0.5 * coverage
            s = sem.get(r["id"], 0.0)
            hits.append(
                Hit(
                    chunk_id=r["id"],
                    doc_id=r["doc_id"],
                    doc_title=r["title"],
                    category=r["category"],
                    heading_path=r["heading_path"],
                    content=r["content"],
                    effective_date=r["effective_date"],
                    source_url=r["source_url"],
                    semantic=s,
                    lexical=lex,
                    score=w_sem * s + (1 - w_sem) * lex,
                    downloadable=bool(r["downloadable"]),
                )
            )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]
