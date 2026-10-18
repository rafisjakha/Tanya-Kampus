"""Embedding yang bisa ditukar (pluggable).

Backend:
- sentence-transformers : model asli, berjalan lokal di CPU. Default untuk pemakaian nyata.
- hashing               : embedding berbasis hash kata, deterministik dan tanpa unduhan model.
                          Hanya untuk tes dan pengembangan offline. Kualitas semantiknya rendah.

Nama embedder (`name`) disimpan per chunk. Kalau model diganti, chunk lama dikenali
sebagai tidak kompatibel dan harus di-index ulang (lihat tombol "Re-index semua").
"""
from __future__ import annotations

import re
import zlib
from typing import Protocol

import numpy as np

from ..config import Settings

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


class Embedder(Protocol):
    name: str

    def embed_passages(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, query_prefix: str = "", passage_prefix: str = ""):
        self.model_name = model_name
        self.name = f"st:{model_name}"
        self.query_prefix = query_prefix
        self.passage_prefix = passage_prefix
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "sentence-transformers belum terpasang. Jalankan: pip install -r requirements.txt"
                ) from exc
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        model = self._load()
        vecs = model.encode(
            [self.passage_prefix + t for t in texts],
            normalize_embeddings=True,
            batch_size=16,
            show_progress_bar=False,
        )
        return np.asarray(vecs, dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        model = self._load()
        vec = model.encode(self.query_prefix + text, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vec, dtype=np.float32)


class HashingEmbedder:
    """Bag-of-words (unigram + bigram) yang di-hash ke vektor berdimensi tetap."""

    def __init__(self, dim: int = 384):
        self.dim = dim
        self.name = f"hashing:{dim}"

    def _embed(self, text: str) -> np.ndarray:
        tokens = [t.casefold() for t in _TOKEN_RE.findall(text)]
        vec = np.zeros(self.dim, dtype=np.float32)
        grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
        for g in grams:
            h = zlib.crc32(g.encode("utf-8"))
            idx = h % self.dim
            sign = 1.0 if (h >> 16) & 1 else -1.0
            vec[idx] += sign
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack([self._embed(t) for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed(text)


def build_embedder(settings: Settings) -> Embedder:
    backend = settings.embedding_backend
    if backend in ("hashing", "hash", "dummy"):
        return HashingEmbedder()
    if backend in ("sentence-transformers", "st"):
        return SentenceTransformerEmbedder(
            settings.embedding_model,
            query_prefix=settings.embedding_query_prefix,
            passage_prefix=settings.embedding_passage_prefix,
        )
    raise ValueError(f"EMBEDDING_BACKEND tidak dikenal: {backend!r}")
