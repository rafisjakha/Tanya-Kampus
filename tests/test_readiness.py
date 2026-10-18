"""Tes fitur kesiapan pakai: duplikat, file asli untuk bot, catatan konversi, migrasi, backup, doctor, sapaan."""
import sqlite3
import zipfile

import pytest

from app.db import db, init_db
from tests.conftest import SAMPLE_MD

BOT = {"X-API-Key": "bot-key-tes"}


def upload(client, auth, name="panduan.md", content=SAMPLE_MD.encode(), **data):
    return client.post("/api/documents/upload", headers=auth, files={"file": (name, content, "text/markdown")},
                       data={"title": "Panduan", **data})


# --- duplikat ---------------------------------------------------------------------------------------

def test_dokumen_duplikat_ditolak_dengan_rujukan(client, auth):
    first = upload(client, auth)
    assert first.status_code == 201
    dup = upload(client, auth, name="salinan.md", title="Judul Lain")
    assert dup.status_code == 409
    body = dup.json()
    assert body["existing_id"] == first.json()["id"] and "sama" in body["detail"]
    assert len(client.get("/api/documents", headers=auth).json()) == 1


def test_duplikat_tidak_meninggalkan_file_yatim(client, auth, env):
    upload(client, auth)
    upload(client, auth, name="salinan.md")
    assert len(list(env.raw_dir.iterdir())) == 1


def test_duplikat_manual_dan_edit_menghitung_ulang_hash(client, auth):
    a = client.post("/api/documents/manual", headers=auth, json={"title": "A", "markdown": "# A\n\nIsi dokumen pertama yang cukup."}).json()
    again = client.post("/api/documents/manual", headers=auth, json={"title": "B", "markdown": "# A\n\nIsi dokumen pertama yang cukup.\n"})
    assert again.status_code == 409
    client.put(f"/api/documents/{a['id']}", headers=auth, json={"markdown": "# A\n\nIsi sudah diubah total."})
    ok = client.post("/api/documents/manual", headers=auth, json={"title": "B", "markdown": "# A\n\nIsi dokumen pertama yang cukup."})
    assert ok.status_code == 201  # hash lama sudah tidak dipakai


# --- file asli untuk bot ---------------------------------------------------------------------------------

def test_file_asli_hanya_bisa_diunduh_bila_diizinkan(client, auth):
    doc = upload(client, auth).json()
    assert doc["downloadable"] is False
    assert client.get(f"/api/files/{doc['id']}", headers=BOT).status_code == 404

    r = client.put(f"/api/documents/{doc['id']}", headers=auth, json={"downloadable": True})
    assert r.json()["downloadable"] is True
    got = client.get(f"/api/files/{doc['id']}", headers=BOT)
    assert got.status_code == 200 and b"Pengisian KRS" in got.content
    assert "panduan.md" in got.headers["content-disposition"]
    assert client.get(f"/api/files/{doc['id']}").status_code == 401  # butuh API key


def test_dokumen_tanpa_file_asli_tidak_bisa_diunduh(client, auth):
    doc = client.post("/api/documents/manual", headers=auth, json={"title": "M", "markdown": "# M\n\nIsi manual yang cukup panjang."}).json()
    client.put(f"/api/documents/{doc['id']}", headers=auth, json={"downloadable": True})
    assert client.get(f"/api/files/{doc['id']}", headers=BOT).status_code == 404


def test_sumber_jawaban_menandai_downloadable_dan_cache_dibuang_saat_diubah(client, auth, stub_llm):
    doc = upload(client, auth, downloadable="true").json()
    assert doc["downloadable"] is True
    client.post(f"/api/documents/{doc['id']}/index", headers=auth)
    q = {"question": "Bagaimana cara cuti akademik?"}
    first = client.post("/api/ask", headers=BOT, json=q).json()
    assert first["sources"][0]["downloadable"] is True
    client.put(f"/api/documents/{doc['id']}", headers=auth, json={"downloadable": False})
    second = client.post("/api/ask", headers=BOT, json=q).json()
    assert second["cached"] is False and second["sources"][0]["downloadable"] is False


# --- catatan konversi ------------------------------------------------------------------------------------

def test_gambar_di_upload_lewat_ocr_dan_catatan_tersimpan(client, auth, monkeypatch):
    pytest.importorskip("pytesseract")
    import shutil

    if shutil.which("tesseract") is None:
        pytest.skip("Tesseract tidak terpasang")
    import io

    from PIL import Image, ImageDraw, ImageFont

    monkeypatch.setenv("OCR_LANGUAGES", "eng")
    from app.config import get_settings

    get_settings.cache_clear()
    img = Image.new("RGB", (1400, 200), "white")
    ImageDraw.Draw(img).text((30, 60), "Batas pengajuan cuti akademik dua minggu sebelum kuliah", fill="black", font=ImageFont.load_default(size=34))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    r = client.post("/api/documents/upload", headers=auth, files={"file": ("pengumuman.png", buf.getvalue(), "image/png")})
    assert r.status_code == 201, r.text
    doc = client.get(f"/api/documents/{r.json()['id']}", headers=auth).json()
    assert "cuti" in doc["markdown"].lower()
    assert doc["note"] and "OCR" in doc["note"]


def test_meta_melaporkan_status_ocr(client, auth):
    meta = client.get("/api/meta", headers=auth).json()
    assert set(meta["ocr"]) == {"ready", "message"}


# --- migrasi dan pemeliharaan ------------------------------------------------------------------------------

def test_database_lama_dimigrasi(env):
    env.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(env.db_path)
    conn.executescript(
        """
        CREATE TABLE documents (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'akademik', source_type TEXT NOT NULL DEFAULT 'file',
            source_name TEXT, source_url TEXT, original_path TEXT, markdown TEXT NOT NULL DEFAULT '',
            effective_date TEXT, status TEXT NOT NULL DEFAULT 'draft', dirty INTEGER NOT NULL DEFAULT 0,
            error TEXT, chunk_count INTEGER NOT NULL DEFAULT 0, created_by TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            indexed_at TEXT);
        INSERT INTO documents(title, markdown) VALUES ('Lama', '# Lama');
        """
    )
    conn.commit()
    conn.close()
    init_db()
    with db() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(documents)")}
        assert {"note", "content_hash", "downloadable"} <= cols
        assert c.execute("SELECT title, downloadable FROM documents").fetchone()["downloadable"] == 0


def test_purge_log_lama(env):
    from app.maintenance import purge_old

    init_db()
    with db() as c:
        c.execute("INSERT INTO query_log(question, status, created_at) VALUES ('lama', 'answered', datetime('now', '-400 days'))")
        c.execute("INSERT INTO query_log(question, status) VALUES ('baru', 'answered')")
    assert purge_old(env)["logs"] == 1
    with db() as c:
        assert [r["question"] for r in c.execute("SELECT question FROM query_log")] == ["baru"]


def test_backup_dan_restore(client, auth, env, tmp_path):
    from scripts import backup

    upload(client, auth)
    zip_path = backup.make_backup(tmp_path / "out")
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
    assert "tanya_kampus.db" in names and any(n.startswith("raw/") for n in names)

    client.delete(f"/api/documents/{client.get('/api/documents', headers=auth).json()[0]['id']}", headers=auth)
    with pytest.raises(SystemExit):
        backup.restore(zip_path, force=False)  # menolak menimpa tanpa --force
    backup.restore(zip_path, force=True)
    with db() as c:
        assert c.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    assert env.db_path.with_suffix(".db.before-restore").exists()


def test_doctor_berjalan_dan_menandai_masalah(env, monkeypatch):
    from scripts import doctor

    monkeypatch.setenv("SECRET_KEY", "change-me-in-env")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    from app.config import get_settings

    get_settings.cache_clear()
    init_db()
    checks = {c.name: c for c in doctor.run_checks(get_settings())}
    assert checks["SECRET_KEY"].level == "fail"
    assert checks["GEMINI_API_KEY"].level == "fail"
    assert checks["Folder data"].level == "ok" and checks["SQLite FTS5"].level == "ok"
    assert checks["Knowledge"].level == "warn"  # belum ada dokumen terindeks
