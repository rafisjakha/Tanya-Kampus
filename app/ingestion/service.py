"""Operasi dokumen: buat, ubah, index, hapus. Dipanggil dari API (dan skrip seed)."""
from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from ..config import Settings
from ..db import bump_index_version, db, embedding_to_blob
from ..rag.chunker import chunk_markdown
from ..rag.embeddings import Embedder
from .converter import ConversionError, convert_file, url_to_markdown

# Kategori bawaan di panel admin, mengikuti scope rapat Kaprodi 23 Oktober 2026 (lihat docs/).
# Kategori lain yang sudah dipakai dokumen lama tetap muncul di panel.
DEFAULT_CATEGORIES = [
    "magang", "kp", "mbkm", "innovillage", "tak", "template", "tugas_akhir", "layanan", "akademik", "umum",
]
_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


class DocumentNotFound(LookupError):
    pass


class IndexingError(RuntimeError):
    pass


class DuplicateDocument(ValueError):
    """Isi dokumen identik dengan dokumen yang sudah ada."""

    def __init__(self, existing_id: int, existing_title: str):
        super().__init__(f"Isi dokumen ini sama dengan dokumen yang sudah ada: \"{existing_title}\" (#{existing_id}).")
        self.existing_id = existing_id
        self.existing_title = existing_title


def content_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.strip().encode("utf-8")).hexdigest()


def _row_to_dict(row, with_markdown: bool = False) -> dict:
    d = dict(row)
    if not with_markdown:
        d.pop("markdown", None)
    d["dirty"] = bool(d.get("dirty"))
    d["downloadable"] = bool(d.get("downloadable"))
    d.pop("content_hash", None)
    # path di server tidak perlu keluar lewat API
    d["has_original"] = bool(d.pop("original_path", None))
    return d


def _get_row(conn, doc_id: int):
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if not row:
        raise DocumentNotFound(f"Dokumen {doc_id} tidak ditemukan.")
    return row


def save_upload(settings: Settings, filename: str, data: bytes) -> Path:
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    safe = _SAFE_RE.sub("_", Path(filename).name) or "file"
    path = settings.raw_dir / f"{uuid.uuid4().hex[:12]}_{safe}"
    path.write_bytes(data)
    return path


def _remove_file(path: str | None) -> None:
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass


# --- buat -------------------------------------------------------------------------------------

def _insert(**f) -> int:
    f.setdefault("note", None)
    f.setdefault("downloadable", 0)
    f["content_hash"] = content_hash(f["markdown"])
    with db() as conn:
        dup = conn.execute(
            "SELECT id, title FROM documents WHERE content_hash = ? LIMIT 1", (f["content_hash"],)
        ).fetchone()
        if dup:
            raise DuplicateDocument(dup["id"], dup["title"])
        cur = conn.execute(
            """
            INSERT INTO documents(title, category, source_type, source_name, source_url,
                                  original_path, markdown, effective_date, status, created_by,
                                  note, content_hash, downloadable)
            VALUES (:title, :category, :source_type, :source_name, :source_url,
                    :original_path, :markdown, :effective_date, 'draft', :created_by,
                    :note, :content_hash, :downloadable)
            """,
            f,
        )
        return int(cur.lastrowid)


def create_from_file(settings: Settings, *, filename: str, data: bytes, title: str | None,
                     category: str, effective_date: str | None, created_by: str,
                     downloadable: bool = False) -> int:
    path = save_upload(settings, filename, data)
    try:
        result = convert_file(path)
        return _insert(
            title=(title or Path(filename).stem).strip(), category=category, source_type="file",
            source_name=filename, source_url=None, original_path=str(path), markdown=result.markdown,
            effective_date=effective_date or None, created_by=created_by, note=result.note,
            downloadable=int(downloadable),
        )
    except (ConversionError, DuplicateDocument):
        _remove_file(str(path))
        raise


def create_from_url(*, url: str, title: str | None, category: str,
                    effective_date: str | None, created_by: str) -> int:
    markdown, page_title = url_to_markdown(url)
    return _insert(
        title=(title or page_title or url).strip(), category=category, source_type="url",
        source_name=None, source_url=url, original_path=None, markdown=markdown,
        effective_date=effective_date or None, created_by=created_by,
    )


def create_manual(*, title: str, markdown: str, category: str,
                  effective_date: str | None, source_url: str | None, created_by: str) -> int:
    if not markdown.strip():
        raise ConversionError("Isi dokumen tidak boleh kosong.")
    return _insert(
        title=title.strip(), category=category, source_type="manual", source_name=None,
        source_url=source_url or None, original_path=None, markdown=markdown,
        effective_date=effective_date or None, created_by=created_by,
    )


# --- baca / ubah ----------------------------------------------------------------------------------

# Semua kolom documents kecuali markdown: daftar dokumen tidak perlu memuat isi lengkap ke memori.
_LIST_COLUMNS = (
    "id, title, category, source_type, source_name, source_url, original_path, effective_date, status, "
    "dirty, error, note, downloadable, chunk_count, created_by, created_at, updated_at, indexed_at"
)


def list_documents() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            f"SELECT {_LIST_COLUMNS} FROM documents ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_document(doc_id: int) -> dict:
    with db() as conn:
        return _row_to_dict(_get_row(conn, doc_id), with_markdown=True)


def get_original(doc_id: int) -> tuple[Path, str] | None:
    """Path file asli dan nama unduhannya, atau None bila dokumen tidak punya file asli."""
    with db() as conn:
        row = _get_row(conn, doc_id)
    if not row["original_path"] or not Path(row["original_path"]).exists():
        return None
    return Path(row["original_path"]), row["source_name"] or Path(row["original_path"]).name


def list_chunks(doc_id: int) -> list[dict]:
    with db() as conn:
        _get_row(conn, doc_id)
        rows = conn.execute(
            "SELECT id, chunk_index, heading_path, content, embedding_model "
            "FROM chunks WHERE doc_id = ? ORDER BY chunk_index",
            (doc_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_document(doc_id: int, fields: dict) -> dict:
    allowed = {"title", "category", "effective_date", "source_url", "markdown", "downloadable"}
    with db() as conn:
        current = _get_row(conn, doc_id)
        changes = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if "effective_date" in changes and not changes["effective_date"]:
            changes["effective_date"] = None
        if not changes:
            return _row_to_dict(current, with_markdown=True)
        dirty = bool(current["dirty"]) or any(
            k in changes and changes[k] != current[k] for k in ("title", "markdown")
        )
        changes["dirty"] = int(dirty)
        if "downloadable" in changes:
            changes["downloadable"] = int(bool(changes["downloadable"]))
        if "markdown" in changes:
            changes["content_hash"] = content_hash(changes["markdown"])
        sets = ", ".join(f"{k} = :{k}" for k in changes)
        conn.execute(
            f"UPDATE documents SET {sets}, updated_at = datetime('now') WHERE id = :id",
            {**changes, "id": doc_id},
        )
        # kategori dan izin unduh ikut tersimpan di cache jawaban/retrieval, jadi cache harus dibuang
        if ("category" in changes and changes["category"] != current["category"]) or (
            "downloadable" in changes and changes["downloadable"] != current["downloadable"]
        ):
            bump_index_version(conn)
        return _row_to_dict(_get_row(conn, doc_id), with_markdown=True)


def replace_file(settings: Settings, doc_id: int, *, filename: str, data: bytes) -> dict:
    with db() as conn:
        current = _get_row(conn, doc_id)
    path = save_upload(settings, filename, data)
    try:
        result = convert_file(path)
    except ConversionError:
        _remove_file(str(path))
        raise
    with db() as conn:
        conn.execute(
            """
            UPDATE documents SET markdown = ?, content_hash = ?, original_path = ?, source_name = ?,
                   source_type = 'file', note = ?, dirty = 1, updated_at = datetime('now') WHERE id = ?
            """,
            (result.markdown, content_hash(result.markdown), str(path), filename, result.note, doc_id),
        )
    _remove_file(current["original_path"])
    return get_document(doc_id)


# --- index ----------------------------------------------------------------------------------------

def index_document(doc_id: int, embedder: Embedder, settings: Settings) -> dict:
    """Chunk + embed + simpan. Chunk lama baru dibuang setelah embedding baru siap."""
    with db() as conn:
        doc = _get_row(conn, doc_id)
    title, markdown = doc["title"], doc["markdown"]

    chunks = chunk_markdown(markdown, title, settings.chunk_max_chars, settings.chunk_overlap_chars)
    try:
        if not chunks:
            raise IndexingError("Dokumen tidak menghasilkan chunk (isi kosong).")
        vectors = embedder.embed_passages([c.embed_text for c in chunks])
    except Exception as exc:  # noqa: BLE001
        with db() as conn:
            conn.execute(
                "UPDATE documents SET status = 'error', error = ?, updated_at = datetime('now') WHERE id = ?",
                (str(exc), doc_id),
            )
        raise IndexingError(str(exc)) from exc

    with db() as conn:
        conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        conn.executemany(
            """
            INSERT INTO chunks(doc_id, chunk_index, heading_path, content, embedding, embedding_model)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (doc_id, c.index, c.heading_path, c.content, embedding_to_blob(v), embedder.name)
                for c, v in zip(chunks, vectors)
            ],
        )
        conn.execute(
            """
            UPDATE documents SET status = 'indexed', dirty = 0, error = NULL, chunk_count = ?,
                   indexed_at = datetime('now'), updated_at = datetime('now') WHERE id = ?
            """,
            (len(chunks), doc_id),
        )
        bump_index_version(conn)
    return get_document(doc_id)


def reindex_all(embedder: Embedder, settings: Settings) -> dict:
    """Index ulang semua dokumen yang pernah di-index (mis. setelah ganti model embedding)."""
    with db() as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM documents WHERE status IN ('indexed', 'error') OR chunk_count > 0 ORDER BY id"
        )]
    ok, failed = 0, []
    for doc_id in ids:
        try:
            index_document(doc_id, embedder, settings)
            ok += 1
        except IndexingError as exc:
            failed.append({"doc_id": doc_id, "error": str(exc)})
    return {"total": len(ids), "ok": ok, "failed": failed}


# --- hapus ------------------------------------------------------------------------------------------

def delete_document(doc_id: int) -> None:
    with db() as conn:
        doc = _get_row(conn, doc_id)
        conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        bump_index_version(conn)
    _remove_file(doc["original_path"])
