from types import SimpleNamespace

import pytest

from app.rag.llm import ExtractiveClient, GeminiClient, LLMError


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


def test_extractive_mengutip_konteks_pertama():
    prompt = "KONTEKS:\n[1] Judul | Bagian: A\nIsi pertama yang relevan.\n\n[2] Judul2 | Bagian: B\nIsi kedua.\n\nPERTANYAAN: x"
    out = ExtractiveClient().generate("sys", prompt)
    assert out.startswith("Isi pertama yang relevan.") and out.endswith("[1]")
