from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import deps
from ..config import Settings, get_settings
from ..db import db
from ..ingestion import ocr
from ..ingestion.service import DEFAULT_CATEGORIES
from ..rag.llm import KEY_VARS, LLM_CHOICES, LLM_LABELS, SwitchableLLM
from .schemas import LlmChoiceIn
from ..security import require_admin, warn_if_insecure

router = APIRouter(prefix="/api", tags=["admin"], dependencies=[Depends(require_admin)])


def _active_model_label(settings: Settings) -> str:
    try:
        llm = deps._llm()
        return llm.name if isinstance(llm, SwitchableLLM) else settings.llm_model
    except Exception:  # noqa: BLE001 - kunci LLM belum diisi: tampilkan nilai dari .env
        return settings.llm_model


@router.get("/meta")
def meta(settings: Settings = Depends(get_settings)):
    with db() as conn:
        used = [r["category"] for r in conn.execute("SELECT DISTINCT category FROM documents")]
    ocr_ok, ocr_msg, _ = ocr.tesseract_status(settings)
    return {
        "categories": sorted(set(DEFAULT_CATEGORIES) | set(used)),
        "embedding": f"{settings.embedding_backend}:{settings.embedding_model}",
        "llm": _active_model_label(settings),
        "score_threshold": settings.score_threshold,
        "top_k": settings.top_k,
        "telegram_upload_enabled": bool(settings.bot_api_key),
        "ocr": {"ready": ocr_ok, "message": ocr_msg},
        "warnings": warn_if_insecure(settings),
    }


def _llm_state(llm: SwitchableLLM) -> dict:
    active = llm.active()
    return {
        "active": active,
        "source": "panel" if llm.override() else "env",
        "providers": [
            {
                "id": p,
                "label": LLM_LABELS[p],
                "model": llm.model(p),
                "available": llm.has_key(p),
                "hint": None if llm.has_key(p) else f"{KEY_VARS[p]} belum diisi di .env",
            }
            for p in LLM_CHOICES
        ],
    }


@router.get("/llm")
def get_llm(llm: SwitchableLLM = Depends(deps.get_llm_switch)):
    """Penyedia LLM yang sedang dipakai dan pilihan yang tersedia."""
    return _llm_state(llm)


@router.put("/llm")
def set_llm(body: LlmChoiceIn, llm: SwitchableLLM = Depends(deps.get_llm_switch)):
    """Ganti penyedia LLM (berlaku langsung untuk panel dan bot, dan tetap setelah restart)."""
    try:
        llm.set_active(body.provider.strip().lower())
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    return _llm_state(llm)


@router.get("/pulse")
def pulse():
    """Penanda perubahan data yang murah dihitung. Panel admin memeriksanya tiap beberapa detik dan hanya memuat
    ulang bagian yang penandanya berubah (log, dokumen, pilihan LLM)."""
    with db() as conn:
        one = lambda sql: tuple(conn.execute(sql).fetchone())  # noqa: E731
        logs = one("SELECT COALESCE(MAX(id), 0), COUNT(*) FROM query_log")
        feedback = one("SELECT COUNT(*), COALESCE(SUM(rating), 0) FROM feedback")
        docs = one(
            """
            SELECT COUNT(*), COALESCE(MAX(updated_at), ''), COALESCE(SUM(status = 'indexed'), 0), COALESCE(SUM(dirty), 0),
                   (SELECT value FROM meta WHERE key = 'index_version')
            FROM documents
            """
        )
    try:
        llm = deps._llm()
        active = llm.active() if isinstance(llm, SwitchableLLM) else None
    except Exception:  # noqa: BLE001 - kunci LLM belum diisi
        active = None
    return {"logs": [*logs, *feedback], "docs": list(docs), "llm": active}


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
               q.top_score, q.sources_json, q.latency_ms, q.cached, q.error, q.llm,
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
