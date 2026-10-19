from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..config import Settings, get_settings
from ..db import db
from ..deps import get_pipeline
from ..ingestion import service
from ..rag.pipeline import Pipeline
from ..security import bot_or_open, bot_required, require_admin
from .documents import read_upload
from .schemas import AskIn, FeedbackIn, normalize_category

router = APIRouter(prefix="/api", tags=["ask"])


@router.post("/ask", dependencies=[Depends(bot_or_open)])
def ask(body: AskIn, pipeline: Pipeline = Depends(get_pipeline)):
    """Dipakai bot Telegram. Kalau BOT_API_KEY diset, kirim lewat header X-API-Key."""
    result = pipeline.ask(
        body.question,
        category=normalize_category(body.category) if body.category else None,
        channel=body.channel,
        user_ref=body.user_ref,
        history=[(t.question, t.answer) for t in body.history],
    )
    return result.to_dict()


@router.post("/admin/ask")
def admin_ask(
    body: AskIn,
    username: str = Depends(require_admin),
    pipeline: Pipeline = Depends(get_pipeline),
):
    """Tes dari panel admin. Sama dengan /ask, ditambah detail skor per chunk."""
    result = pipeline.ask(
        body.question,
        category=normalize_category(body.category) if body.category else None,
        channel="admin-test",
        user_ref=username,
        history=[(t.question, t.answer) for t in body.history],
    )
    return result.to_dict(include_debug=True)


@router.post("/feedback", dependencies=[Depends(bot_or_open)])
def feedback(body: FeedbackIn):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM query_log WHERE id = ?", (body.query_id,)).fetchone():
            raise HTTPException(404, "query_id tidak ditemukan.")
        conn.execute(
            """
            INSERT INTO feedback(query_id, rating, comment) VALUES (?, ?, ?)
            ON CONFLICT(query_id) DO UPDATE SET rating = excluded.rating, comment = excluded.comment,
                                                created_at = datetime('now')
            """,
            (body.query_id, body.rating, body.comment),
        )
    return {"ok": True}


@router.post("/bot/ingest", status_code=201, dependencies=[Depends(bot_required)])
def bot_ingest(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    user_ref: str = Form(default="unknown"),
    category: str = Form(default="akademik"),
    settings: Settings = Depends(get_settings),
):
    """Upload dari admin Telegram. Selalu menjadi DRAFT; admin meninjau dan meng-index lewat panel."""
    data = read_upload(file, settings)
    doc_id = service.create_from_file(
        settings, filename=file.filename or "file", data=data, title=title or None,
        category=normalize_category(category), effective_date=None,
        created_by=f"telegram:{user_ref}",
    )
    doc = service.get_document(doc_id)
    return {"id": doc["id"], "title": doc["title"], "status": doc["status"]}


@router.get("/files/{doc_id}", dependencies=[Depends(bot_or_open)])
def download_file(doc_id: int):
    """File asli untuk bot. Hanya dokumen yang ditandai admin sebagai 'boleh diunduh'."""
    doc = service.get_document(doc_id)
    original = service.get_original(doc_id)
    if not doc["downloadable"] or original is None:
        raise HTTPException(404, "File tidak tersedia untuk diunduh.")
    path, name = original
    return FileResponse(path, filename=name)
