"""Klien LLM. Antarmuka kecil supaya penyedia bisa diganti tanpa menyentuh pipeline.

Penyedia:
- gemini      : Google Gemini lewat SDK google-genai (default).
- extractive  : tanpa LLM. Mengembalikan potongan dokumen terbaik apa adanya. Berguna untuk
                tes offline, demo tanpa API key, atau cadangan saat kuota Gemini habis.
"""
from __future__ import annotations

import re
import time
from typing import Protocol

from ..config import Settings


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    name: str

    def generate(self, system: str, prompt: str) -> str: ...


class GeminiClient:
    RETRY_CODES = {429, 500, 502, 503, 504}

    def __init__(self, api_key: str, model: str, max_attempts: int = 3):
        self.name = f"gemini:{model}"
        self.model = model
        self.api_key = api_key
        self.max_attempts = max_attempts
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def generate(self, system: str, prompt: str) -> str:
        from google.genai import types

        client = self._get_client()
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.2,
            max_output_tokens=1024,
        )
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = client.models.generate_content(
                    model=self.model, contents=prompt, config=config
                )
                text = (response.text or "").strip()
                if not text:
                    raise LLMError("Gemini mengembalikan respons kosong.")
                return text
            except LLMError:
                raise
            except Exception as exc:  # noqa: BLE001 - SDK melempar beragam tipe error
                last_exc = exc
                code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
                retryable = code in self.RETRY_CODES
                if not retryable or attempt == self.max_attempts:
                    break
                time.sleep(delay)
                delay *= 2
        raise LLMError(f"Gagal memanggil Gemini: {last_exc}") from last_exc


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
    if provider == "gemini":
        if not settings.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY belum diset. Ambil gratis di https://aistudio.google.com/apikey "
                "atau pakai LLM_PROVIDER=extractive untuk tes tanpa LLM."
            )
        return GeminiClient(settings.gemini_api_key, settings.gemini_model)
    raise ValueError(f"LLM_PROVIDER tidak dikenal: {provider!r}")
