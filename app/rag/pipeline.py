"""Pipeline tanya-jawab: retrieve -> guardrail -> generate -> sumber -> log.

Guardrail berlapis:
1. Panjang pertanyaan dibatasi.
2. Skor hybrid terbaik harus >= SCORE_THRESHOLD, kalau tidak LLM tidak dipanggil sama sekali.
3. LLM diminta membalas TIDAK_DITEMUKAN bila konteks tidak memuat jawaban.
4. Kegagalan LLM (kuota, jaringan) menghasilkan pesan ramah, bukan error mentah.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field

from ..config import Settings
from ..db import db, get_index_version
from .llm import LLMClient, LLMError
from .prompt import NOT_FOUND_MESSAGE, NOT_FOUND_TOKEN, SYSTEM_PROMPT, build_prompt
from .search import Hit, Retriever

ERROR_MESSAGE = "Maaf, layanan jawaban sedang bermasalah. Coba lagi beberapa saat lagi."
_CITE_RE = re.compile(r"\[(\d+)\]")
_NORM_RE = re.compile(r"[^\w\s]", re.UNICODE)


@dataclass
class AskResult:
    query_id: int
    status: str  # answered | not_found | error
    answer: str
    sources: list[dict] = field(default_factory=list)
    top_score: float | None = None
    cached: bool = False
    hits: list[dict] = field(default_factory=list)

    def to_dict(self, include_debug: bool = False) -> dict:
        data = {
            "query_id": self.query_id,
            "status": self.status,
            "found": self.status == "answered",
            "answer": self.answer,
            "sources": self.sources,
            "top_score": self.top_score,
            "cached": self.cached,
        }
        if include_debug:
            data["hits"] = self.hits
        return data


def normalize_question(q: str) -> str:
    return " ".join(_NORM_RE.sub(" ", q.casefold()).split())


def _source_dict(n: int, h: Hit) -> dict:
    return {
        "n": n,
        "doc_id": h.doc_id,
        "title": h.doc_title,
        "heading": h.heading_path,
        "url": h.source_url,
        "effective_date": h.effective_date,
        "score": round(h.score, 4),
        "downloadable": h.downloadable,
    }


def _cited_sources(answer: str, hits: list[Hit]) -> list[dict]:
    cited = sorted({int(n) for n in _CITE_RE.findall(answer) if 1 <= int(n) <= len(hits)})
    if not cited:  # LLM lupa mencantumkan nomor: tampilkan tiga teratas
        cited = list(range(1, min(3, len(hits)) + 1))
    return [_source_dict(n, hits[n - 1]) for n in cited]


class Pipeline:
    def __init__(self, retriever: Retriever, llm: LLMClient, settings: Settings):
        self.retriever = retriever
        self.llm = llm
        self.settings = settings

    # -- cache --------------------------------------------------------------------------------

    def _cache_key(self, conn, question: str, category: str | None) -> str:
        raw = f"{get_index_version(conn)}|{category or ''}|{normalize_question(question)}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _cache_get(self, conn, key: str) -> dict | None:
        ttl = self.settings.cache_ttl_hours
        if ttl <= 0:
            return None
        row = conn.execute(
            """
            SELECT answer, sources_json, top_score FROM answer_cache
            WHERE key = ? AND created_at >= datetime('now', ?)
            """,
            (key, f"-{ttl} hours"),
        ).fetchone()
        return dict(row) if row else None

    def _cache_put(self, conn, key: str, answer: str, sources: list[dict], top: float | None) -> None:
        if self.settings.cache_ttl_hours <= 0:
            return
        conn.execute(
            """
            INSERT INTO answer_cache(key, answer, sources_json, top_score, created_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET answer = excluded.answer,
              sources_json = excluded.sources_json, top_score = excluded.top_score,
              created_at = excluded.created_at
            """,
            (key, answer, json.dumps(sources, ensure_ascii=False), top),
        )

    # -- log ----------------------------------------------------------------------------------

    def _log(self, *, question, category, channel, user_ref, status, answer, top_score,
             sources, latency_ms, cached=False, error=None) -> int:
        with db() as conn:
            cur = conn.execute(
                """
                INSERT INTO query_log(channel, user_ref, question, category, status, answer,
                                      top_score, sources_json, latency_ms, cached, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (channel, user_ref, question, category, status, answer, top_score,
                 json.dumps(sources, ensure_ascii=False), latency_ms, int(cached), error),
            )
            return int(cur.lastrowid)

    # -- inti -----------------------------------------------------------------------------------

    def ask(
        self,
        question: str,
        category: str | None = None,
        channel: str = "api",
        user_ref: str | None = None,
    ) -> AskResult:
        started = time.perf_counter()
        question = " ".join(question.split())[: self.settings.max_question_chars]
        category = category or None

        def finish(status, answer, sources=None, top=None, cached=False, error=None, hits=None):
            qid = self._log(
                question=question, category=category, channel=channel, user_ref=user_ref,
                status=status, answer=answer, top_score=top, sources=sources or [],
                latency_ms=int((time.perf_counter() - started) * 1000), cached=cached, error=error,
            )
            return AskResult(qid, status, answer, sources or [], top, cached, hits or [])

        if not question:
            return finish("not_found", NOT_FOUND_MESSAGE)

        # 1. cache jawaban untuk pertanyaan yang sama pada versi indeks yang sama
        with db() as conn:
            key = self._cache_key(conn, question, category)
            cached = self._cache_get(conn, key)
        if cached:
            return finish("answered", cached["answer"], json.loads(cached["sources_json"]),
                          cached["top_score"], cached=True)

        # 2. retrieval + ambang skor
        hits = self.retriever.search(question, category=category)
        debug_hits = [h.to_debug() for h in hits]
        top = hits[0].score if hits else None
        if not hits or top < self.settings.score_threshold:
            return finish("not_found", NOT_FOUND_MESSAGE, top=top, hits=debug_hits)

        # 3. generate
        try:
            raw = self.llm.generate(SYSTEM_PROMPT, build_prompt(question, hits))
        except LLMError as exc:
            return finish("error", ERROR_MESSAGE, top=top, error=str(exc), hits=debug_hits)

        if raw.strip().strip(".").upper() == NOT_FOUND_TOKEN or raw.strip().startswith(NOT_FOUND_TOKEN):
            return finish("not_found", NOT_FOUND_MESSAGE, top=top, hits=debug_hits)

        sources = _cited_sources(raw, hits)
        with db() as conn:
            self._cache_put(conn, key, raw, sources, top)
        return finish("answered", raw, sources, top, hits=debug_hits)
