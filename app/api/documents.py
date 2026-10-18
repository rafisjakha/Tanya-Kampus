from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from ..config import Settings, get_settings
from ..deps import get_embedder
from ..ingestion import service
from ..ingestion.converter import SUPPORTED_EXTENSIONS
from ..rag.embeddings import Embedder
from ..security import require_admin
from .schemas import (
    DocUpdateIn,
    ManualDocIn,
    UrlDocIn,
    normalize_category,
    validate_date,
)

router = APIRouter(prefix="/api", tags=["documents"], dependencies=[Depends(require_admin)])


def read_upload(upload: UploadFile, settings: Settings) -> bytes:
    limit = settings.max_upload_mb * 1024 * 1024
    data = upload.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File melebihi batas {settings.max_upload_mb} MB.")
    if not data:
        raise HTTPException(422, "File kosong.")
    ext = Path(upload.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            422, f"Format {ext or '(tanpa ekstensi)'} belum didukung. Didukung: " + ", ".join(sorted(SUPPORTED_EXTENSIONS))
        )
    return data


def _date_or_422(value: str | None) -> str | None:
    try:
        return validate_date(value)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/documents")
def list_documents():
    return service.list_documents()


@router.post("/documents/upload", status_code=201)
def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    category: str = Form(default="akademik"),
    effective_date: str | None = Form(default=None),
    downloadable: bool = Form(default=False),
    username: str = Depends(require_admin),
    settings: Settings = Depends(get_settings),
):
    data = read_upload(file, settings)
    doc_id = service.create_from_file(
        settings, filename=file.filename or "file", data=data, title=title or None,
        category=normalize_category(category), effective_date=_date_or_422(effective_date),
        created_by=username, downloadable=downloadable,
    )
    return service.get_document(doc_id)


@router.post("/documents/url", status_code=201)
def add_url_document(body: UrlDocIn, username: str = Depends(require_admin)):
    doc_id = service.create_from_url(
        url=body.url, title=body.title, category=normalize_category(body.category),
        effective_date=body.effective_date, created_by=username,
    )
    return service.get_document(doc_id)


@router.post("/documents/manual", status_code=201)
def add_manual_document(body: ManualDocIn, username: str = Depends(require_admin)):
    doc_id = service.create_manual(
        title=body.title, markdown=body.markdown, category=normalize_category(body.category),
        effective_date=body.effective_date, source_url=body.source_url, created_by=username,
    )
    return service.get_document(doc_id)


@router.get("/documents/{doc_id}")
def get_document(doc_id: int):
    return service.get_document(doc_id)


@router.put("/documents/{doc_id}")
def update_document(doc_id: int, body: DocUpdateIn):
    fields = body.model_dump(exclude_unset=True)
    if "category" in fields:
        fields["category"] = normalize_category(fields["category"])
    if "effective_date" in fields and fields["effective_date"] is None:
        fields["effective_date"] = ""
    return service.update_document(doc_id, fields)


@router.post("/documents/{doc_id}/replace")
def replace_document_file(
    doc_id: int,
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
):
    data = read_upload(file, settings)
    return service.replace_file(settings, doc_id, filename=file.filename or "file", data=data)


@router.post("/documents/{doc_id}/index")
def index_document(
    doc_id: int,
    embedder: Embedder = Depends(get_embedder),
    settings: Settings = Depends(get_settings),
):
    return service.index_document(doc_id, embedder, settings)


@router.get("/documents/{doc_id}/chunks")
def document_chunks(doc_id: int):
    return service.list_chunks(doc_id)


@router.get("/documents/{doc_id}/original")
def download_original(doc_id: int):
    original = service.get_original(doc_id)
    if original is None:
        raise HTTPException(404, "Dokumen ini tidak punya file asli.")
    path, name = original
    return FileResponse(path, filename=name)


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: int):
    service.delete_document(doc_id)


@router.post("/reindex")
def reindex_all(
    embedder: Embedder = Depends(get_embedder),
    settings: Settings = Depends(get_settings),
):
    return service.reindex_all(embedder, settings)
