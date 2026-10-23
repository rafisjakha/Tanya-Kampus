"""Klien LLM. Antarmuka kecil supaya penyedia bisa diganti tanpa menyentuh pipeline.

Penyedia (LLM_PROVIDER):
- groq        : Groq lewat API kompatibel OpenAI (httpx langsung, tanpa SDK tambahan).
- gemini      : Google Gemini lewat SDK google-genai.
- extractive  : tanpa LLM. Mengembalikan potongan dokumen terbaik apa adanya. Berguna untuk
                tes offline, demo tanpa API key, atau cadangan saat kuota habis.

Menambah penyedia baru: turunkan `_RetryingClient`, isi `_call`, lalu daftarkan di `build_llm`.
"""
from __future__ import annotations

import re
import time
from typing import Protocol

from ..config import Settings

TEMPERATURE = 0.2
MAX_OUTPUT_TOKENS = 1024
MAX_RETRY_WAIT = 20.0  # detik; Retry-After yang lebih lama dianggap kuota habis, bukan sekadar sibuk


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    name: str

    def generate(self, system: str, prompt: str) -> str: ...


class _RetryingClient:
    """Retry dengan jeda bertambah untuk error sementara (limit, server sibuk, jaringan)."""

    RETRY_CODES = {429, 500, 502, 503, 504}
    label = "LLM"

    def __init__(self, max_attempts: int = 3):
        self.max_attempts = max_attempts

    def _call(self, system: str, prompt: str) -> str | None:
        raise NotImplementedError

    def _retryable(self, exc: Exception) -> bool:
        flag = getattr(exc, "retryable", None)
        if flag is not None:
            return bool(flag)
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        return code in self.RETRY_CODES

    def generate(self, system: str, prompt: str) -> str:
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                text = (self._call(system, prompt) or "").strip()
                if not text:
                    raise LLMError(f"{self.label} mengembalikan respons kosong.")
                return text
            except LLMError:
                raise
            except Exception as exc:  # noqa: BLE001 - SDK dan HTTP melempar beragam tipe error
                last_exc = exc
                if not self._retryable(exc) or attempt == self.max_attempts:
                    break
                wait = getattr(exc, "retry_after", None) or delay
                if wait > MAX_RETRY_WAIT:
                    break
                time.sleep(wait)
                delay *= 2
        raise LLMError(f"Gagal memanggil {self.label}: {last_exc}") from last_exc


# --- Gemini -------------------------------------------------------------------------------------

class GeminiClient(_RetryingClient):
    label = "Gemini"

    def __init__(self, api_key: str, model: str, max_attempts: int = 3):
        super().__init__(max_attempts)
        self.name = f"gemini:{model}"
        self.model = model
        self.api_key = api_key
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _call(self, system: str, prompt: str) -> str | None:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system, temperature=TEMPERATURE, max_output_tokens=MAX_OUTPUT_TOKENS
        )
        response = self._get_client().models.generate_content(model=self.model, contents=prompt, config=config)
        return response.text


# --- Groq ---------------------------------------------------------------------------------------

class GroqApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, retry_after: float | None = None,
                 retryable: bool | None = None):
        super().__init__(f"{status_code} {message}" if status_code else message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.retryable = retryable


def _retry_after(headers) -> float | None:
    try:
        return float(headers.get("retry-after", ""))
    except ValueError:
        return None


class GroqClient(_RetryingClient):
    """Groq Chat Completions (https://console.groq.com/docs). Satu klien HTTP dipakai ulang antarpermintaan."""

    label = "Groq"
    BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self, api_key: str, model: str, max_attempts: int = 3, timeout: float = 60.0, transport=None):
        super().__init__(max_attempts)
        self.name = f"groq:{model}"
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self._transport = transport  # untuk tes (httpx.MockTransport)
        self._http = None

    def _get_http(self):
        if self._http is None:
            import httpx

            self._http = httpx.Client(
                base_url=self.BASE_URL, timeout=self.timeout, transport=self._transport,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        return self._http

    def _call(self, system: str, prompt: str) -> str | None:
        import httpx

        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": TEMPERATURE,
            "max_completion_tokens": MAX_OUTPUT_TOKENS,
        }
        if "gpt-oss" in self.model:
            # model penalaran: usaha berpikir rendah supaya jawaban cepat, hemat kuota, dan token penalaran
            # tidak menghabiskan batas keluaran sebelum jawabannya tertulis
            payload["reasoning_effort"] = "low"
        try:
            r = self._get_http().post("/chat/completions", json=payload)
        except httpx.TransportError as exc:  # timeout, koneksi putus: layak dicoba lagi
            raise GroqApiError(f"jaringan: {exc}", retryable=True) from exc
        if r.status_code != 200:
            try:
                message = r.json().get("error", {}).get("message") or r.text[:200]
            except ValueError:
                message = r.text[:200]
            raise GroqApiError(message, r.status_code, _retry_after(r.headers))
        choices = r.json().get("choices") or []
        return (choices[0].get("message") or {}).get("content") if choices else None


# --- tanpa LLM ----------------------------------------------------------------------------------

_CONTEXT_RE = re.compile(r"^\[(\d+)\][^\n]*\n(.*?)(?=^\[\d+\]|\Z)", re.MULTILINE | re.DOTALL)


class ExtractiveClient:
    """Menjawab dengan mengutip chunk pertama dari KONTEKS (tanpa model bahasa)."""

    name = "extractive"

    def generate(self, system: str, prompt: str) -> str:
        m = _CONTEXT_RE.search(prompt)
        if not m:
            return "TIDAK_DITEMUKAN"
        body = m.group(2).strip()
        return f"{body[:700]} [{m.group(1)}]"


def build_llm(settings: Settings) -> LLMClient:
    provider = settings.llm_provider
    if provider == "extractive":
        return ExtractiveClient()
    if provider == "groq":
        if not settings.groq_api_key:
            raise RuntimeError(
                "GROQ_API_KEY belum diset. Ambil di https://console.groq.com/keys "
                "atau pakai LLM_PROVIDER=extractive untuk tes tanpa LLM."
            )
        return GroqClient(settings.groq_api_key, settings.groq_model)
    if provider == "gemini":
        if not settings.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY belum diset. Ambil gratis di https://aistudio.google.com/apikey "
                "atau pakai LLM_PROVIDER=extractive untuk tes tanpa LLM."
            )
        return GeminiClient(settings.gemini_api_key, settings.gemini_model)
    raise ValueError(f"LLM_PROVIDER tidak dikenal: {provider!r} (pilihan: groq, gemini, extractive)")
