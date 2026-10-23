from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query

from ..config import Settings, get_settings
from ..db import db
from ..ingestion import ocr
from ..ingestion.service import DEFAULT_CATEGORIES
from ..security import require_admin, warn_if_insecure

router = APIRouter(prefix="/api", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/meta")
def meta(settings: Settings = Depends(get_settings)):
    with db() as conn:
        used = [r["category"] for r in conn.execute("SELECT DISTINCT category FROM documents")]
    ocr_ok, ocr_msg, _ = ocr.tesseract_status(settings)
    return {
        "categories": sorted(set(DEFAULT_CATEGORIES) | set(used)),
        "embedding": f"{settings.embedding_backend}:{settings.embedding_model}",
        "llm": {"gemini": settings.gemini_model, "groq": settings.groq_model}.get(settings.llm_provider, settings.llm_provider),
        "score_threshold": settings.score_threshold,
        "top_k": settings.top_k,
        "telegram_upload_enabled": bool(settings.bot_api_key),
        "ocr": {"ready": ocr_ok, "message": ocr_msg},
        "warnings": warn_if_insecure(settings),
    }


@router.get("/stats")
def stats():
    with db() as conn:
        one = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
        by_status = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) AS n FROM query_log GROUP BY status")}
        by_day = [dict(r) for r in conn.execute(
            """
            SELECT date(created_at) AS day, COUNT(*) AS total,
                   SUM(status = 'not_found') AS not_found
            FROM query_log WHERE created_at >= datetime('now', '-7 days')
            GROUP BY day ORDER BY day
            """
        )]
        return {
            "documents": one("SELECT COUNT(*) FROM documents"),
            "documents_indexed": one("SELECT COUNT(*) FROM documents WHERE status = 'indexed'"),
            "documents_need_index": one(
                "SELECT COUNT(*) FROM documents WHERE status != 'indexed' OR dirty = 1"
            ),
            "chunks": one("SELECT COUNT(*) FROM chunks"),
            "queries": one("SELECT COUNT(*) FROM query_log"),
            "answered": by_status.get("answered", 0),
            "not_found": by_status.get("not_found", 0),
            "errors": by_status.get("error", 0),
            "feedback_up": one("SELECT COUNT(*) FROM feedback WHERE rating = 1"),
            "feedback_down": one("SELECT COUNT(*) FROM feedback WHERE rating = -1"),
            "by_day": by_day,
        }


@router.get("/logs")
def logs(
    status: str | None = Query(default=None, pattern="^(answered|not_found|error)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    sql = """
        SELECT q.id, q.created_at, q.channel, q.user_ref, q.question, q.status, q.answer,
               q.top_score, q.sources_json, q.latency_ms, q.cached, q.error,
               f.rating AS feedback
        FROM query_log q LEFT JOIN feedback f ON f.query_id = q.id
    """
    params: list = []
    if status:
        sql += " WHERE q.status = ?"
        params.append(status)
    sql += " ORDER BY q.id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    with db() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["sources"] = json.loads(d.pop("sources_json") or "[]")
        d["cached"] = bool(d["cached"])
        out.append(d)
    return out
