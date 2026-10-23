"""Pilihan penyedia LLM (Groq/Gemini) dari panel admin."""
from dataclasses import replace

import pytest

from app import deps
from app.db import init_db
from app.rag.llm import LLMError, SwitchableLLM


class FakeClient:
    def __init__(self, name):
        self.name = name

    def generate(self, system, prompt):
        return f"dari {self.name}"


def make_switch(env, *, groq="gsk_x", gemini="g_x", provider="groq"):
    init_db()
    settings = replace(env, groq_api_key=groq, gemini_api_key=gemini, llm_provider=provider,
                       gemini_model="gemini-3.5-flash-lite", groq_model="openai/gpt-oss-120b")
    sw = SwitchableLLM(settings)
    sw._clients = {"groq": FakeClient("groq"), "gemini": FakeClient("gemini")}
    return sw


def test_default_dari_env_lalu_pilihan_panel_menang_dan_tersimpan(env):
    sw = make_switch(env)
    assert sw.active() == "groq" and sw.override() is None
    assert sw.generate("s", "p") == "dari groq"
    sw.set_active("gemini")
    assert sw.active() == "gemini" and sw.generate("s", "p") == "dari gemini"
    assert sw.name == "gemini:gemini-3.5-flash-lite"
    # objek baru (mis. setelah restart) membaca pilihan yang sama dari database
    again = make_switch(env)
    assert again.active() == "gemini"


def test_tidak_bisa_memilih_penyedia_tanpa_kunci(env):
    sw = make_switch(env, gemini=None)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        sw.set_active("gemini")
    with pytest.raises(ValueError):
        sw.set_active("openai")
    assert sw.active() == "groq"


def test_pilihan_lama_diabaikan_bila_kuncinya_dihapus(env):
    sw = make_switch(env)
    sw.set_active("gemini")
    no_gemini = make_switch(env, gemini=None)  # kunci Gemini dihapus dari .env
    assert no_gemini.override() is None and no_gemini.active() == "groq"


def test_endpoint_llm_butuh_login_dan_menampilkan_pilihan(client, auth, env):
    assert client.get("/api/llm").status_code == 401
    client.app.dependency_overrides[deps.get_llm_switch] = lambda: make_switch(env)
    data = client.get("/api/llm", headers=auth).json()
    assert data["active"] == "groq" and data["source"] == "env"
    by_id = {p["id"]: p for p in data["providers"]}
    assert by_id["gemini"]["model"] == "gemini-3.5-flash-lite" and by_id["gemini"]["available"] is True


def test_endpoint_ganti_llm(client, auth, env):
    client.app.dependency_overrides[deps.get_llm_switch] = lambda: make_switch(env)
    r = client.put("/api/llm", json={"provider": "Gemini"}, headers=auth)
    assert r.status_code == 200 and r.json()["active"] == "gemini" and r.json()["source"] == "panel"
    assert client.put("/api/llm", json={"provider": "openai"}, headers=auth).status_code == 422
    assert client.put("/api/llm", json={"provider": "gemini"}).status_code == 401


def test_endpoint_menolak_penyedia_tanpa_kunci(client, auth, env):
    client.app.dependency_overrides[deps.get_llm_switch] = lambda: make_switch(env, gemini=None)
    r = client.put("/api/llm", json={"provider": "gemini"}, headers=auth)
    assert r.status_code == 409 and "GEMINI_API_KEY" in r.json()["detail"]
    state = client.get("/api/llm", headers=auth).json()
    assert {p["id"]: p["available"] for p in state["providers"]} == {"groq": True, "gemini": False}


def test_generate_memberi_llm_error_bila_kunci_hilang_saat_berjalan(env):
    sw = make_switch(env)
    sw._clients.pop("groq")
    sw.settings = replace(sw.settings, groq_api_key=None)
    with pytest.raises(LLMError, match="GROQ_API_KEY"):
        sw.generate("s", "p")
