"""Dependency FastAPI. Objek berat (model embedding, klien LLM) dibuat sekali lalu dipakai ulang.

Di tes, fungsi-fungsi ini di-override lewat `app.dependency_overrides`.
"""
from __future__ import annotations

from functools import lru_cache

from fastapi import HTTPException

from .config import get_settings
from .rag.embeddings import Embedder, build_embedder
from .rag.llm import LLM_CHOICES, SwitchableLLM, build_llm
from .rag.pipeline import Pipeline
from .rag.search import Retriever


@lru_cache(maxsize=1)
def _embedder() -> Embedder:
    return build_embedder(get_settings())


def get_embedder() -> Embedder:
    try:
        return _embedder()
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(503, str(exc))


@lru_cache(maxsize=1)
def _llm():
    """Groq/Gemini bisa diganti dari panel admin. Mode tes (extractive) tidak punya pilihan."""
    settings = get_settings()
    return SwitchableLLM(settings) if settings.llm_provider in LLM_CHOICES else build_llm(settings)


def get_llm_switch() -> SwitchableLLM:
    try:
        llm = _llm()
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(503, str(exc))
    if not isinstance(llm, SwitchableLLM):
        raise HTTPException(409, "Pilihan LLM tidak tersedia pada mode tes (LLM_PROVIDER=extractive).")
    return llm


@lru_cache(maxsize=1)
def _pipeline() -> Pipeline:
    settings = get_settings()
    return Pipeline(Retriever(_embedder(), settings), _llm(), settings)


def get_pipeline() -> Pipeline:
    try:
        return _pipeline()
    except (ValueError, RuntimeError) as exc:
        # mis. GROQ_API_KEY / GEMINI_API_KEY belum diset. Jangan di-cache supaya langsung pulih setelah .env diperbaiki.
        raise HTTPException(503, str(exc))
