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

from datetime import datetime

from ..config import Settings
from ..db import db, get_index_version
from .clock import describe_now, now_local, resolve_relative_days
from .llm import LLMClient, LLMError
from .prompt import (
    CHAT_PROMPT,
    NOT_FOUND_MESSAGE,
    NOT_FOUND_TOKEN,
    REWRITE_PROMPT,
    SYSTEM_PROMPT,
    build_prompt,
    build_rewrite_prompt,
)
from .search import Hit, Retriever

CHAT_MAX_WORDS = 30  # pesan lebih panjang langsung memakai pesan 'tidak ditemukan' baku (hemat kuota)
REWRITE_MAX_WORDS = 15  # pesan lebih panjang dianggap sudah berdiri sendiri (tanpa panggilan LLM tambahan)
HISTORY_MAX_TURNS = 3
HISTORY_MAX_CHARS = 300
# jawaban yang bergantung pada waktu sekarang tidak boleh dipakai ulang dari cache
_TIME_SENSITIVE_RE = re.compile(r"\b(selanjutnya|berikutnya|nanti|tanggal|jam\s+berapa|jam\s+\d{2}\.\d{2}|minggu\s+ini|bulan\s+ini)\b", re.I)
_CITATION_RE = re.compile(r"\[\d+\]")
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
    standalone_question: str | None = None  # hasil tulis ulang pesan lanjutan, bila ada

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
            data["standalone_question"] = self.standalone_question
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

    def _standalone(self, question: str, history: list[tuple[str, str]] | None) -> str:
        """Tulis ulang pesan lanjutan ("kalo hari kamis?") menjadi pertanyaan lengkap memakai riwayat chat.

        Satu panggilan LLM, hanya bila ada riwayat dan pesannya pendek. Gagal atau hasilnya janggal: pakai pesan asli.
        """
        if not history or len(question.split()) > REWRITE_MAX_WORDS:
            return question
        turns = [(q[:HISTORY_MAX_CHARS], a[:HISTORY_MAX_CHARS]) for q, a in history[-HISTORY_MAX_TURNS:]]
        try:
            raw = self.llm.generate(REWRITE_PROMPT, build_rewrite_prompt(turns, question))
        except LLMError:
            return question
        lines = raw.strip().splitlines()
        text = " ".join(lines[0].split()).strip(" \"'") if lines else ""
        if not text or text.startswith(NOT_FOUND_TOKEN) or _CITATION_RE.search(text):
            return question
        return text[: self.settings.max_question_chars]

    def _llm_fallback(self, question: str, now_text: str | None = None) -> tuple[str, str]:
        """Balasan LLM saat dokumen tidak menjawab: ("answered", obrolan ringan) atau ("not_found", pesan ramah)."""
        if len(question.split()) > CHAT_MAX_WORDS:
            return "not_found", NOT_FOUND_MESSAGE
        try:
            prompt = f"WAKTU SEKARANG: {now_text}\n\nPESAN: {question}" if now_text else question
            raw = self.llm.generate(CHAT_PROMPT, prompt).strip()
        except LLMError:
            return "not_found", NOT_FOUND_MESSAGE
        if raw.startswith(NOT_FOUND_TOKEN):
            text = raw[len(NOT_FOUND_TOKEN):].lstrip(" :.-\n").strip()
            if not text or _CITATION_RE.search(text):
                text = NOT_FOUND_MESSAGE
            return "not_found", text
        if not raw or _CITATION_RE.search(raw):
            return "not_found", NOT_FOUND_MESSAGE
        return "answered", raw

    # -- inti -----------------------------------------------------------------------------------

    def ask(
        self,
        question: str,
        category: str | None = None,
        channel: str = "api",
        user_ref: str | None = None,
        history: list[tuple[str, str]] | None = None,
        now: datetime | None = None,
    ) -> AskResult:
        started = time.perf_counter()
        question = " ".join(question.split())[: self.settings.max_question_chars]
        category = category or None

        standalone: str | None = None

        def finish(status, answer, sources=None, top=None, cached=False, error=None, hits=None):
            qid = self._log(
                question=question, category=category, channel=channel, user_ref=user_ref,
                status=status, answer=answer, top_score=top, sources=sources or [],
                latency_ms=int((time.perf_counter() - started) * 1000), cached=cached, error=error,
            )
            return AskResult(qid, status, answer, sources or [], top, cached, hits or [], standalone)

        if not question:
            return finish("not_found", NOT_FOUND_MESSAGE)

        # 0. pesan lanjutan dilengkapi dari riwayat chat; log tetap mencatat pesan asli
        search_q = self._standalone(question, history)
        if search_q != question:
            standalone = search_q
        # waktu server: "hari ini"/"besok"/"sekarang" diganti nama hari sebenarnya (baris jadwal memuat nama hari)
        now = now or now_local(self.settings.timezone)
        now_text = describe_now(now, self.settings.timezone)
        search_q = resolve_relative_days(search_q, now)

        # 1. cache jawaban untuk pertanyaan yang sama pada versi indeks yang sama
        time_sensitive = bool(_TIME_SENSITIVE_RE.search(search_q))
        with db() as conn:
            key = self._cache_key(conn, search_q, category)
            cached = None if time_sensitive else self._cache_get(conn, key)
        if cached:
            return finish("answered", cached["answer"], json.loads(cached["sources_json"]),
                          cached["top_score"], cached=True)

        # 2. retrieval + ambang skor
        hits = self.retriever.search(search_q, category=category)
        debug_hits = [h.to_debug() for h in hits]
        top = hits[0].score if hits else None
        if not hits or top < self.settings.score_threshold:
            status, text = self._llm_fallback(search_q, now_text)
            return finish(status, text, top=top, hits=debug_hits)

        # 3. generate
        try:
            raw = self.llm.generate(SYSTEM_PROMPT, build_prompt(search_q, hits, now_text))
        except LLMError as exc:
            return finish("error", ERROR_MESSAGE, top=top, error=str(exc), hits=debug_hits)

        if raw.strip().strip(".").upper() == NOT_FOUND_TOKEN or raw.strip().startswith(NOT_FOUND_TOKEN):
            status, text = self._llm_fallback(search_q, now_text)
            return finish(status, text, top=top, hits=debug_hits)

        sources = _cited_sources(raw, hits)
        with db() as conn:
            if not time_sensitive:
                self._cache_put(conn, key, raw, sources, top)
        return finish("answered", raw, sources, top, hits=debug_hits)
