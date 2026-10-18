"""Fixture tes: DB sementara, embedding hashing, LLM tiruan. Tidak butuh internet atau API key."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import deps
from app.config import get_settings
from app.rag.embeddings import HashingEmbedder
from app.rag.pipeline import Pipeline
from app.rag.search import Retriever


class StubLLM:
    """LLM tiruan: mengutip nomor [1] dan mencatat prompt terakhir."""

    name = "stub"

    def __init__(self):
        self.calls = 0
        self.last_prompt = ""
        self.reply: str | None = None

    def generate(self, system: str, prompt: str) -> str:
        self.calls += 1
        self.last_prompt = prompt
        return self.reply if self.reply is not None else "Jawaban berdasarkan dokumen [1]."


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EMBEDDING_BACKEND", "hashing")
    monkeypatch.setenv("SECRET_KEY", "kunci-rahasia-khusus-tes-0123456789abcdef")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password-tes-123")
    monkeypatch.setenv("BOT_API_KEY", "bot-key-tes")
    monkeypatch.setenv("SCORE_THRESHOLD", "0.2")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture()
def stub_llm():
    return StubLLM()


@pytest.fixture()
def client(env, stub_llm):
    from app.main import app

    embedder = HashingEmbedder()
    pipeline = Pipeline(Retriever(embedder, env), stub_llm, env)
    app.dependency_overrides[deps.get_embedder] = lambda: embedder
    app.dependency_overrides[deps.get_pipeline] = lambda: pipeline
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def auth(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "password-tes-123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


SAMPLE_MD = """# Panduan Akademik

## Pengisian KRS

Pengisian KRS dilakukan melalui portal akademik pada minggu pertama semester. Mahasiswa wajib
berkonsultasi dengan dosen wali sebelum mengesahkan KRS.

## Cuti Akademik

Cuti akademik diajukan paling lambat dua minggu sebelum perkuliahan dimulai. Mahasiswa harus
melampirkan surat permohonan dan persetujuan orang tua.

| Jenis | Batas Pengajuan |
|---|---|
| Cuti semester | 2 minggu sebelum kuliah |
| Cuti studi | 4 minggu sebelum kuliah |
"""


@pytest.fixture()
def indexed_doc(client, auth):
    r = client.post(
        "/api/documents/manual",
        headers=auth,
        json={"title": "Panduan Akademik", "markdown": SAMPLE_MD, "category": "akademik",
              "effective_date": "2026-01-01"},
    )
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]
    r = client.post(f"/api/documents/{doc_id}/index", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()
