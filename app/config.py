"""Konfigurasi aplikasi. Semua nilai dibaca dari environment variable / file .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_SECRET = "change-me-in-env"


def _get(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _get_int(name: str, default: int) -> int:
    value = _get(name)
    return int(value) if value is not None else default


def _get_float(name: str, default: float) -> float:
    value = _get(name)
    return float(value) if value is not None else default


def _get_bool(name: str, default: bool) -> bool:
    value = _get(name)
    if value is None:
        return default
    return value.lower() in ("1", "true", "yes", "ya", "on")


def _get_id_set(name: str) -> frozenset[int]:
    raw = _get(name, "") or ""
    ids = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            ids.add(int(part))
    return frozenset(ids)


def _default_prefixes(model: str) -> tuple[str, str]:
    """Model e5 wajib memakai prefix 'query: ' / 'passage: '. Model lain tidak."""
    if "e5" in model.lower():
        return "query: ", "passage: "
    return "", ""


@dataclass(frozen=True)
class Settings:
    # Penyimpanan
    data_dir: Path
    # Keamanan
    secret_key: str
    token_expire_minutes: int
    admin_username: str | None
    admin_password: str | None
    bot_api_key: str | None
    cors_origins: tuple[str, ...]
    max_upload_mb: int
    log_retention_days: int
    # OCR
    ocr_enabled: bool
    ocr_languages: str
    ocr_max_pages: int
    ocr_dpi: int
    # Embedding
    embedding_backend: str
    embedding_model: str
    embedding_query_prefix: str
    embedding_passage_prefix: str
    # LLM
    llm_provider: str
    gemini_api_key: str | None
    gemini_model: str
    # Retrieval
    top_k: int
    semantic_weight: float
    score_threshold: float
    chunk_max_chars: int
    chunk_overlap_chars: int
    max_question_chars: int
    cache_ttl_hours: int
    warmup: bool
    # Telegram
    telegram_token: str | None
    api_base_url: str
    admin_telegram_ids: frozenset[int]
    bot_cooldown_seconds: float
    session_timeout_seconds: float
    timezone: str

    @property
    def db_path(self) -> Path:
        return self.data_dir / "tanya_kampus.db"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @classmethod
    def from_env(cls) -> "Settings":
        model = _get("EMBEDDING_MODEL", "intfloat/multilingual-e5-small") or ""
        q_default, p_default = _default_prefixes(model)
        # Prefix boleh dikosongkan dengan sengaja, jadi bedakan "tidak diset" dan "string kosong".
        q_prefix = os.environ.get("EMBEDDING_QUERY_PREFIX")
        p_prefix = os.environ.get("EMBEDDING_PASSAGE_PREFIX")
        data_dir = Path(_get("DATA_DIR", str(BASE_DIR / "data")) or "")
        origins = tuple(
            o.strip() for o in (_get("CORS_ORIGINS", "") or "").split(",") if o.strip()
        )
        return cls(
            data_dir=data_dir,
            secret_key=_get("SECRET_KEY", DEFAULT_SECRET) or DEFAULT_SECRET,
            token_expire_minutes=_get_int("TOKEN_EXPIRE_MINUTES", 720),
            admin_username=_get("ADMIN_USERNAME"),
            admin_password=_get("ADMIN_PASSWORD"),
            bot_api_key=_get("BOT_API_KEY"),
            cors_origins=origins,
            max_upload_mb=_get_int("MAX_UPLOAD_MB", 25),
            log_retention_days=_get_int("LOG_RETENTION_DAYS", 180),
            ocr_enabled=_get_bool("OCR_ENABLED", True),
            ocr_languages=_get("OCR_LANGUAGES", "ind+eng") or "ind+eng",
            ocr_max_pages=_get_int("OCR_MAX_PAGES", 60),
            ocr_dpi=_get_int("OCR_DPI", 200),
            embedding_backend=(_get("EMBEDDING_BACKEND", "sentence-transformers") or "").lower(),
            embedding_model=model,
            embedding_query_prefix=q_default if q_prefix is None else q_prefix,
            embedding_passage_prefix=p_default if p_prefix is None else p_prefix,
            llm_provider=(_get("LLM_PROVIDER", "gemini") or "").lower(),
            gemini_api_key=_get("GEMINI_API_KEY"),
            gemini_model=_get("GEMINI_MODEL", "gemini-3.6-flash") or "gemini-3.6-flash",
            top_k=_get_int("TOP_K", 5),
            semantic_weight=_get_float("SEMANTIC_WEIGHT", 0.6),
            score_threshold=_get_float("SCORE_THRESHOLD", 0.5),
            chunk_max_chars=_get_int("CHUNK_MAX_CHARS", 1800),
            chunk_overlap_chars=_get_int("CHUNK_OVERLAP_CHARS", 200),
            max_question_chars=_get_int("MAX_QUESTION_CHARS", 500),
            cache_ttl_hours=_get_int("CACHE_TTL_HOURS", 24),
            warmup=_get_bool("WARMUP", True),
            telegram_token=_get("TELEGRAM_TOKEN"),
            api_base_url=(_get("API_BASE_URL", "http://127.0.0.1:8001") or "").rstrip("/"),
            admin_telegram_ids=_get_id_set("ADMIN_TELEGRAM_IDS"),
            bot_cooldown_seconds=_get_float("BOT_COOLDOWN_SECONDS", 3.0),
            session_timeout_seconds=_get_float("SESSION_TIMEOUT_SECONDS", 60.0),
            timezone=_get("TIMEZONE") or "Asia/Jakarta",
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
