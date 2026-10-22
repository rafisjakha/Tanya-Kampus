import json
from types import SimpleNamespace

import httpx
import pytest

from app.config import Settings
from app.rag.llm import ExtractiveClient, GeminiClient, GroqClient, LLMError, build_llm


class FakeApiError(Exception):
    def __init__(self, code):
        super().__init__(f"error {code}")
        self.code = code


def fake_client(outcomes):
    """outcomes: daftar exception atau teks, dikembalikan berurutan tiap panggilan."""
    calls = {"n": 0}

    def generate_content(model, contents, config):
        item = outcomes[min(calls["n"], len(outcomes) - 1)]
        calls["n"] += 1
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(text=item)

    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)), calls


@pytest.fixture()
def gemini(monkeypatch):
    monkeypatch.setattr("app.rag.llm.time.sleep", lambda s: None)
    return GeminiClient("kunci-palsu", "gemini-tes", max_attempts=3)


def test_config_sdk_valid():
    """Nama parameter yang kita pakai harus ada di SDK google-genai yang terpasang."""
    types = pytest.importorskip("google.genai.types")
    cfg = types.GenerateContentConfig(system_instruction="s", temperature=0.2, max_output_tokens=10)
    assert cfg.temperature == 0.2


def test_retry_pada_429_lalu_berhasil(gemini):
    client, calls = fake_client([FakeApiError(429), FakeApiError(503), " Halo [1] "])
    gemini._client = client
    assert gemini.generate("sys", "prompt") == "Halo [1]"
    assert calls["n"] == 3


def test_tidak_retry_untuk_error_permanen(gemini):
    client, calls = fake_client([FakeApiError(400)])
    gemini._client = client
    with pytest.raises(LLMError):
        gemini.generate("sys", "prompt")
    assert calls["n"] == 1


def test_menyerah_setelah_percobaan_habis(gemini):
    client, calls = fake_client([FakeApiError(429)])
    gemini._client = client
    with pytest.raises(LLMError, match="Gagal memanggil Gemini"):
        gemini.generate("sys", "prompt")
    assert calls["n"] == 3


def test_respons_kosong_adalah_error(gemini):
    client, _ = fake_client(["   "])
    gemini._client = client
    with pytest.raises(LLMError, match="kosong"):
        gemini.generate("sys", "prompt")


# --- Groq -----------------------------------------------------------------------------------------

def groq_with(responses, monkeypatch, max_attempts=3):
    """responses: daftar httpx.Response atau exception, dikembalikan berurutan tiap permintaan."""
    sleeps: list[float] = []
    monkeypatch.setattr("app.rag.llm.time.sleep", sleeps.append)
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        item = responses[min(len(seen) - 1, len(responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    client = GroqClient("kunci-groq", "llama-tes", max_attempts=max_attempts, transport=httpx.MockTransport(handler))
    return client, seen, sleeps


def ok(text):
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": text}}]})


def test_groq_format_permintaan_dan_jawaban(monkeypatch):
    client, seen, _ = groq_with([ok(" Jawaban [1] ")], monkeypatch)
    assert client.generate("aturan", "pertanyaan") == "Jawaban [1]"
    req = seen[0]
    assert req.url == "https://api.groq.com/openai/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer kunci-groq"
    body = json.loads(req.content)
    assert body["model"] == "llama-tes"
    assert body["messages"] == [{"role": "system", "content": "aturan"}, {"role": "user", "content": "pertanyaan"}]


def test_groq_retry_429_memakai_retry_after(monkeypatch):
    limited = httpx.Response(429, headers={"retry-after": "2"}, json={"error": {"message": "rate limit"}})
    client, seen, sleeps = groq_with([limited, httpx.Response(503, text="sibuk"), ok("Halo")], monkeypatch)
    assert client.generate("s", "p") == "Halo"
    assert len(seen) == 3 and sleeps == [2.0, 2.0]  # Retry-After dari server, lalu jeda bertambah


def test_groq_retry_saat_jaringan_putus(monkeypatch):
    client, seen, _ = groq_with([httpx.ConnectTimeout("timeout"), ok("Halo")], monkeypatch)
    assert client.generate("s", "p") == "Halo" and len(seen) == 2


def test_groq_error_permanen_tidak_diulang(monkeypatch):
    client, seen, _ = groq_with([httpx.Response(401, json={"error": {"message": "Invalid API Key"}})], monkeypatch)
    with pytest.raises(LLMError, match="Invalid API Key"):
        client.generate("s", "p")
    assert len(seen) == 1


def test_groq_kuota_habis_tidak_menunggu_lama(monkeypatch):
    limited = httpx.Response(429, headers={"retry-after": "3600"}, json={"error": {"message": "quota"}})
    client, seen, sleeps = groq_with([limited], monkeypatch)
    with pytest.raises(LLMError, match="Groq"):
        client.generate("s", "p")
    assert len(seen) == 1 and sleeps == []


def test_groq_respons_kosong_adalah_error(monkeypatch):
    client, _, _ = groq_with([ok("  ")], monkeypatch)
    with pytest.raises(LLMError, match="kosong"):
        client.generate("s", "p")


def test_pilih_penyedia_otomatis(monkeypatch):
    for var in ("LLM_PROVIDER", "GROQ_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert Settings.from_env().llm_provider == "gemini"  # .env lama tanpa Groq tetap memakai Gemini
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    settings = Settings.from_env()
    assert settings.llm_provider == "groq" and settings.llm_model == "llama-3.3-70b-versatile"
    assert isinstance(build_llm(settings), GroqClient)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")  # pilihan eksplisit selalu menang
    assert Settings.from_env().llm_provider == "gemini"


def test_groq_tanpa_kunci_memberi_petunjuk(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="console.groq.com"):
        build_llm(Settings.from_env())


def test_extractive_mengutip_konteks_pertama():
    prompt = "KONTEKS:\n[1] Judul | Bagian: A\nIsi pertama yang relevan.\n\n[2] Judul2 | Bagian: B\nIsi kedua.\n\nPERTANYAAN: x"
    out = ExtractiveClient().generate("sys", prompt)
    assert out.startswith("Isi pertama yang relevan.") and out.endswith("[1]")
