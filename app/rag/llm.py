"""Klien LLM. Antarmuka kecil supaya penyedia bisa diganti tanpa menyentuh pipeline.

Penyedia:
- groq        : Groq (API kompatibel OpenAI) lewat httpx. Default: llama-3.3-70b-versatile.
- gemini      : Google Gemini lewat SDK google-genai.
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


class GroqClient:
    """Groq Chat Completions (https://api.groq.com/openai/v1). Tanpa SDK tambahan, cukup httpx."""

    RETRY_CODES = {429, 500, 502, 503, 504}
    URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str, model: str, max_attempts: int = 3):
        self.name = f"groq:{model}"
        self.model = model
        self.api_key = api_key
        self.max_attempts = max_attempts

    def generate(self, system: str, prompt: str) -> str:
        import httpx

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 1024,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                resp = httpx.post(self.URL, json=payload, headers=headers, timeout=60)
                if resp.status_code in self.RETRY_CODES and attempt < self.max_attempts:
                    last_exc = LLMError(f"HTTP {resp.status_code}")
                    time.sleep(delay)
                    delay *= 2
                    continue
                if resp.status_code >= 400:
                    raise LLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                text = (resp.json()["choices"][0]["message"].get("content") or "").strip()
                if not text:
                    raise LLMError("Groq mengembalikan respons kosong.")
                return text
            except LLMError:
                raise
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt == self.max_attempts:
                    break
                time.sleep(delay)
                delay *= 2
            except (KeyError, IndexError, ValueError) as exc:
                raise LLMError(f"Respons Groq tidak terduga: {exc}") from exc
        raise LLMError(f"Gagal memanggil Groq: {last_exc}") from last_exc


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
                "GROQ_API_KEY belum diset. Ambil gratis di https://console.groq.com/keys "
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
    raise ValueError(f"LLM_PROVIDER tidak dikenal: {provider!r}")
