from app.db import db
from tests.conftest import SAMPLE_MD


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_endpoint_admin_butuh_login(client):
    assert client.get("/api/documents").status_code == 401
    assert client.get("/api/stats").status_code == 401
    assert client.post("/api/reindex").status_code == 401


def test_login_salah_dan_benar(client):
    bad = client.post("/api/auth/login", json={"username": "admin", "password": "salah"})
    assert bad.status_code == 401
    ok = client.post("/api/auth/login", json={"username": "admin", "password": "password-tes-123"})
    assert ok.status_code == 200 and ok.json()["access_token"]


def test_login_dibatasi_setelah_banyak_gagal(client):
    from app.security import login_limiter

    login_limiter._hits.clear()
    codes = [
        client.post("/api/auth/login", json={"username": "admin", "password": "x"}).status_code
        for _ in range(7)
    ]
    login_limiter._hits.clear()
    assert 429 in codes


def test_alur_upload_markdown_index_dan_tanya(client, auth, stub_llm):
    up = client.post(
        "/api/documents/upload",
        headers=auth,
        files={"file": ("panduan.md", SAMPLE_MD.encode(), "text/markdown")},
        data={"title": "Panduan Akademik", "category": "Akademik", "effective_date": "2026-01-01"},
    )
    assert up.status_code == 201, up.text
    doc = up.json()
    assert doc["status"] == "draft" and doc["category"] == "akademik" and doc["has_original"]
    assert "original_path" not in doc

    idx = client.post(f"/api/documents/{doc['id']}/index", headers=auth).json()
    assert idx["status"] == "indexed" and idx["chunk_count"] >= 2 and not idx["dirty"]

    r = client.post(
        "/api/ask", headers={"X-API-Key": "bot-key-tes"},
        json={"question": "Kapan batas pengajuan cuti akademik?", "channel": "telegram", "user_ref": "42"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["found"] and body["status"] == "answered"
    assert body["sources"][0]["title"] == "Panduan Akademik"
    assert "Cuti" in stub_llm.last_prompt  # konteks yang tepat dikirim ke LLM
    assert "Berlaku: 2026-01-01" in stub_llm.last_prompt


def test_ask_butuh_api_key_bila_diset(client, indexed_doc):
    assert client.post("/api/ask", json={"question": "cuti"}).status_code == 401
    assert client.post("/api/ask", headers={"X-API-Key": "salah"}, json={"question": "cuti"}).status_code == 401


def test_pertanyaan_di_luar_dokumen_tidak_memanggil_llm(client, indexed_doc, stub_llm):
    r = client.post(
        "/api/ask", headers={"X-API-Key": "bot-key-tes"},
        json={"question": "Siapa pemenang piala dunia sepak bola terakhir?"},
    )
    body = r.json()
    assert body["status"] == "not_found" and not body["found"]
    assert stub_llm.calls == 0
    assert "belum menemukan" in body["answer"]


def test_llm_membalas_tidak_ditemukan(client, indexed_doc, stub_llm):
    stub_llm.reply = "TIDAK_DITEMUKAN"
    r = client.post("/api/ask", headers={"X-API-Key": "bot-key-tes"},
                    json={"question": "Bagaimana cara cuti akademik?"})
    assert r.json()["status"] == "not_found"


def test_kegagalan_llm_jadi_pesan_ramah(client, indexed_doc, stub_llm):
    from app.rag.llm import LLMError

    def boom(system, prompt):
        raise LLMError("kuota habis")

    stub_llm.generate = boom
    r = client.post("/api/ask", headers={"X-API-Key": "bot-key-tes"},
                    json={"question": "Bagaimana cara cuti akademik?"})
    assert r.status_code == 200
    assert r.json()["status"] == "error" and "bermasalah" in r.json()["answer"]


def test_cache_jawaban_dan_invalidasi_saat_index_berubah(client, auth, indexed_doc, stub_llm):
    h = {"X-API-Key": "bot-key-tes"}
    q = {"question": "Bagaimana cara cuti akademik?"}
    first = client.post("/api/ask", headers=h, json=q).json()
    second = client.post("/api/ask", headers=h, json=q).json()
    assert not first["cached"] and second["cached"]
    assert stub_llm.calls == 1

    client.post(f"/api/documents/{indexed_doc['id']}/index", headers=auth)  # versi indeks naik
    third = client.post("/api/ask", headers=h, json=q).json()
    assert not third["cached"] and stub_llm.calls == 2


def test_filter_kategori(client, auth, indexed_doc, stub_llm):
    h = {"X-API-Key": "bot-key-tes"}
    r = client.post("/api/ask", headers=h, json={"question": "cuti akademik", "category": "tugas_akhir"})
    assert r.json()["status"] == "not_found"
    r = client.post("/api/ask", headers=h, json={"question": "cuti akademik", "category": "akademik"})
    assert r.json()["status"] == "answered"


def test_edit_markdown_menandai_dirty_dan_index_ulang_mengganti_chunk(client, auth, indexed_doc):
    doc_id = indexed_doc["id"]
    r = client.put(f"/api/documents/{doc_id}", headers=auth,
                   json={"markdown": "# Panduan Akademik\n\n## Wisuda\n\nWisuda diadakan setiap bulan Oktober."})
    assert r.json()["dirty"] is True and r.json()["status"] == "indexed"
    client.post(f"/api/documents/{doc_id}/index", headers=auth)
    chunks = client.get(f"/api/documents/{doc_id}/chunks", headers=auth).json()
    assert len(chunks) == 1 and "Wisuda" in chunks[0]["content"]
    # chunk lama tidak lagi bisa ditemukan lewat keyword
    with db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'KRS'").fetchone()[0]
    assert n == 0


def test_hapus_dokumen_membersihkan_chunk_dan_fts(client, auth, indexed_doc):
    doc_id = indexed_doc["id"]
    assert client.delete(f"/api/documents/{doc_id}", headers=auth).status_code == 204
    assert client.get(f"/api/documents/{doc_id}", headers=auth).status_code == 404
    with db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'cuti'").fetchone()[0] == 0
    r = client.post("/api/ask", headers={"X-API-Key": "bot-key-tes"}, json={"question": "cuti akademik"})
    assert r.json()["status"] == "not_found"


def test_format_tidak_didukung_dan_file_kosong(client, auth):
    r = client.post("/api/documents/upload", headers=auth,
                    files={"file": ("a.exe", b"abc", "application/octet-stream")})
    assert r.status_code == 422
    r = client.post("/api/documents/upload", headers=auth,
                    files={"file": ("a.md", b"", "text/markdown")})
    assert r.status_code == 422


def test_url_internal_ditolak(client, auth):
    r = client.post("/api/documents/url", headers=auth, json={"url": "http://127.0.0.1:8000/health"})
    assert r.status_code == 422 and "internal" in r.json()["detail"]


def test_feedback_dan_log_dan_stats(client, auth, indexed_doc):
    h = {"X-API-Key": "bot-key-tes"}
    qid = client.post("/api/ask", headers=h, json={"question": "Bagaimana cara cuti akademik?"}).json()["query_id"]
    assert client.post("/api/feedback", headers=h, json={"query_id": qid, "rating": 1}).status_code == 200
    assert client.post("/api/feedback", headers=h, json={"query_id": qid, "rating": 5}).status_code == 422
    assert client.post("/api/feedback", headers=h, json={"query_id": 9999, "rating": 1}).status_code == 404

    client.post("/api/ask", headers=h, json={"question": "resep nasi goreng spesial"})
    logs = client.get("/api/logs", headers=auth).json()
    assert len(logs) == 2
    nf = client.get("/api/logs?status=not_found", headers=auth).json()
    assert len(nf) == 1 and nf[0]["question"].startswith("resep")
    s = client.get("/api/stats", headers=auth).json()
    assert s["queries"] == 2 and s["feedback_up"] == 1 and s["not_found"] == 1 and s["documents_indexed"] == 1


def test_admin_ask_menyertakan_debug(client, auth, indexed_doc):
    r = client.post("/api/admin/ask", headers=auth, json={"question": "Bagaimana cara cuti akademik?"})
    body = r.json()
    assert body["hits"] and {"semantic", "lexical", "score", "heading"} <= set(body["hits"][0])
    # endpoint publik tidak membocorkan debug
    pub = client.post("/api/ask", headers={"X-API-Key": "bot-key-tes"}, json={"question": "cuti akademik"}).json()
    assert "hits" not in pub


def test_bot_ingest_selalu_draft_dan_butuh_key(client, auth):
    files = {"file": ("info.md", b"# Info\n\nIsi dokumen cukup panjang untuk lolos validasi.", "text/markdown")}
    assert client.post("/api/bot/ingest", files=files).status_code == 401
    r = client.post("/api/bot/ingest", headers={"X-API-Key": "bot-key-tes"}, files=files,
                    data={"user_ref": "123"})
    assert r.status_code == 201 and r.json()["status"] == "draft"


def test_reindex_all(client, auth, indexed_doc):
    r = client.post("/api/reindex", headers=auth).json()
    assert r["total"] == 1 and r["ok"] == 1 and r["failed"] == []


def test_ganti_password(client, auth):
    r = client.post("/api/auth/change-password", headers=auth,
                    json={"old_password": "password-tes-123", "new_password": "password-baru-456"})
    assert r.status_code == 200
    again = client.post("/api/auth/login", json={"username": "admin", "password": "password-baru-456"})
    assert again.status_code == 200


def test_karakter_aneh_di_pertanyaan_tidak_merusak_pencarian(client, auth, indexed_doc):
    h = {"X-API-Key": "bot-key-tes"}
    for q in ['cuti "akademik"', "cuti'; DROP TABLE chunks;--", "KRS AND OR NOT (*)", "^^^ ??? ***", "cuti\x00akademik"]:
        r = client.post("/api/ask", headers=h, json={"question": q})
        assert r.status_code == 200, (q, r.text)
    # tabel tetap utuh
    assert len(client.get("/api/documents", headers=auth).json()) == 1
    assert client.get("/api/stats", headers=auth).json()["chunks"] >= 2
