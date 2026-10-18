"""Entry point FastAPI.

Jalankan:  uvicorn app.main:app --reload --port 8001
Panel admin: http://127.0.0.1:8001/admin/
Dokumentasi API: http://127.0.0.1:8001/docs
"""
from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import admin, ask, auth, documents
from .config import get_settings
from .db import db, init_db
from .ingestion.converter import ConversionError
from .ingestion.service import DocumentNotFound, DuplicateDocument, IndexingError
from .maintenance import maintenance_loop, warm_up
from .security import hash_password, warn_if_insecure

log = logging.getLogger("tanya_kampus")
STATIC_DIR = Path(__file__).parent / "static" / "admin"


def bootstrap_admin() -> None:
    """Buat admin pertama dari ADMIN_USERNAME/ADMIN_PASSWORD bila belum ada admin sama sekali."""
    settings = get_settings()
    with db() as conn:
        if conn.execute("SELECT 1 FROM admins LIMIT 1").fetchone():
            return
        if not (settings.admin_username and settings.admin_password):
            log.warning(
                "Belum ada akun admin. Isi ADMIN_USERNAME dan ADMIN_PASSWORD di .env "
                "atau jalankan: python -m scripts.create_admin"
            )
            return
        conn.execute(
            "INSERT INTO admins(username, password_hash) VALUES (?, ?)",
            (settings.admin_username, hash_password(settings.admin_password)),
        )
        log.info("Akun admin '%s' dibuat dari .env.", settings.admin_username)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    init_db()
    bootstrap_admin()
    settings = get_settings()
    for w in warn_if_insecure(settings):
        log.warning(w)
    task = asyncio.create_task(maintenance_loop(settings))
    if settings.warmup and settings.embedding_backend in ("sentence-transformers", "st"):
        threading.Thread(target=warm_up, daemon=True, name="warmup").start()
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="Tanya Kampus API", version=__version__, lifespan=lifespan)

_origins = get_settings().cors_origins
if _origins:
    app.add_middleware(
        CORSMiddleware, allow_origins=list(_origins), allow_methods=["*"], allow_headers=["*"]
    )

app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(ask.router)
app.include_router(admin.router)


@app.exception_handler(ConversionError)
async def _conversion_error(_: Request, exc: ConversionError):
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.exception_handler(DuplicateDocument)
async def _duplicate(_: Request, exc: DuplicateDocument):
    return JSONResponse(
        {"detail": str(exc), "existing_id": exc.existing_id}, status_code=409
    )


@app.exception_handler(DocumentNotFound)
async def _not_found(_: Request, exc: DocumentNotFound):
    return JSONResponse({"detail": str(exc)}, status_code=404)


@app.exception_handler(IndexingError)
async def _indexing_error(_: Request, exc: IndexingError):
    return JSONResponse({"detail": f"Gagal meng-index: {exc}"}, status_code=500)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "version": __version__}


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/admin/")


if STATIC_DIR.exists():
    app.mount("/admin", StaticFiles(directory=STATIC_DIR, html=True), name="admin")
