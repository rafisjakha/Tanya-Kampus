"""Pemeriksaan kesiapan sebelum dipakai. Menunjukkan persis apa yang masih kurang.

    python -m scripts.doctor            # cek konfigurasi, paket, OCR, database (tanpa jaringan)
    python -m scripts.doctor --live     # sekaligus uji nyata: model embedding, Gemini (1 permintaan),
                                        # Telegram getMe, dan API yang sedang berjalan

Keluar dengan kode 1 bila ada item GAGAL.
"""
from __future__ import annotations

import argparse
import importlib
import re
import sqlite3
import sys
import time
from dataclasses import dataclass

from app.config import BASE_DIR, DEFAULT_SECRET, Settings, get_settings
from app.ingestion import ocr

OK, WARN, FAIL, SKIP = "ok", "warn", "fail", "skip"
ICON = {OK: "[OK]   ", WARN: "[PERLU]", FAIL: "[GAGAL]", SKIP: "[LEWAT]"}


@dataclass
class Check:
    level: str
    name: str
    detail: str = ""


def check_python() -> Check:
    v = sys.version_info
    if v >= (3, 10):
        return Check(OK, "Python", f"{v.major}.{v.minor}.{v.micro}")
    return Check(FAIL, "Python", f"{v.major}.{v.minor} terlalu lama, butuh 3.10 atau lebih baru")


def check_packages(settings: Settings) -> list[Check]:
    required = {
        "fastapi": "API", "uvicorn": "server", "python_multipart": "python-multipart", "jwt": "PyJWT", "bcrypt": "bcrypt",
        "numpy": "numpy", "markitdown": "konversi dokumen", "trafilatura": "konversi URL", "telegram": "python-telegram-bot",
        "httpx": "httpx",
    }
    if settings.embedding_backend in ("sentence-transformers", "st"):
        required["sentence_transformers"] = "sentence-transformers (model embedding)"
    if settings.llm_provider == "gemini":
        required["google.genai"] = "google-genai (Gemini)"
    out = []
    for mod, label in required.items():
        try:
            importlib.import_module(mod)
        except ImportError:
            out.append(Check(FAIL, f"Paket {label}", "belum terpasang: pip install -r requirements.txt"))
    if not out:
        out.append(Check(OK, "Paket Python", f"{len(required)} paket wajib terpasang"))
    return out


def check_config(settings: Settings) -> list[Check]:
    out = []
    env = BASE_DIR / ".env"
    out.append(Check(OK if env.exists() else WARN, "File .env", "ada" if env.exists() else "tidak ada: cp .env.example .env"))
    if settings.secret_key == DEFAULT_SECRET:
        out.append(Check(FAIL, "SECRET_KEY", "belum diisi. Buat: python -c \"import secrets; print(secrets.token_hex(32))\""))
    elif len(settings.secret_key) < 32:
        out.append(Check(WARN, "SECRET_KEY", "kurang dari 32 karakter"))
    else:
        out.append(Check(OK, "SECRET_KEY", "terisi"))
    if settings.llm_provider == "groq":
        out.append(Check(OK if settings.groq_api_key else FAIL, "GROQ_API_KEY",
                         "terisi" if settings.groq_api_key else "belum diisi (https://console.groq.com/keys)"))
    elif settings.llm_provider == "gemini":
        out.append(Check(OK if settings.gemini_api_key else FAIL, "GEMINI_API_KEY",
                         "terisi" if settings.gemini_api_key else "belum diisi (https://aistudio.google.com/apikey)"))
    else:
        out.append(Check(WARN, "LLM_PROVIDER", f"'{settings.llm_provider}': bukan Gemini, kualitas jawaban terbatas"))
    if settings.embedding_backend == "hashing":
        out.append(Check(WARN, "EMBEDDING_BACKEND", "hashing hanya untuk tes, kualitas retrieval rendah"))
    token = settings.telegram_token
    if not token:
        out.append(Check(WARN, "TELEGRAM_TOKEN", "belum diisi (perlu untuk menjalankan bot)"))
    elif not re.fullmatch(r"\d{6,}:[\w-]{30,}", token):
        out.append(Check(FAIL, "TELEGRAM_TOKEN", "format tidak seperti token dari @BotFather"))
    else:
        out.append(Check(OK, "TELEGRAM_TOKEN", "format valid"))
    out.append(Check(OK if settings.bot_api_key else WARN, "BOT_API_KEY",
                     "terisi" if settings.bot_api_key else "kosong: /api/ask terbuka dan upload via Telegram nonaktif"))
    if settings.telegram_token and not settings.admin_telegram_ids:
        out.append(Check(WARN, "ADMIN_TELEGRAM_IDS", "kosong: admin tidak bisa kirim file lewat Telegram (opsional)"))
    return out


def check_storage(settings: Settings) -> list[Check]:
    out = []
    try:
        settings.raw_dir.mkdir(parents=True, exist_ok=True)
        probe = settings.data_dir / ".write-test"
        probe.write_text("x")
        probe.unlink()
        out.append(Check(OK, "Folder data", str(settings.data_dir)))
    except OSError as exc:
        return [Check(FAIL, "Folder data", f"tidak bisa ditulis: {exc}")]
    try:
        mem = sqlite3.connect(":memory:")
        mem.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        mem.close()
        out.append(Check(OK, "SQLite FTS5", f"SQLite {sqlite3.sqlite_version}"))
    except sqlite3.OperationalError:
        out.append(Check(FAIL, "SQLite FTS5", "tidak tersedia di build SQLite ini (pakai Python dari python.org/Homebrew/uv)"))
    if settings.db_path.exists():
        conn = sqlite3.connect(settings.db_path)
        try:
            docs, indexed, chunks, admins = (
                conn.execute(q).fetchone()[0]
                for q in (
                    "SELECT COUNT(*) FROM documents",
                    "SELECT COUNT(*) FROM documents WHERE status='indexed'",
                    "SELECT COUNT(*) FROM chunks",
                    "SELECT COUNT(*) FROM admins",
                )
            )
            out.append(Check(OK if admins else WARN, "Akun admin", f"{admins} akun" if admins else "belum ada (isi ADMIN_USERNAME/PASSWORD lalu jalankan API)"))
            out.append(Check(OK if indexed else WARN, "Knowledge", f"{docs} dokumen, {indexed} terindeks, {chunks} chunk" if indexed
                             else "belum ada dokumen terindeks (python -m scripts.seed_demo atau upload lewat panel)"))
        except sqlite3.OperationalError:
            out.append(Check(WARN, "Database", "ada tetapi skema belum dibuat (jalankan API sekali)"))
        finally:
            conn.close()
    else:
        out.append(Check(WARN, "Database", "belum dibuat (jalankan API atau seed_demo)"))
    return out


def check_ocr(settings: Settings) -> Check:
    ok, msg, lang = ocr.tesseract_status(settings)
    if ok:
        return Check(OK, "OCR (Tesseract)", f"{msg}; bahasa {lang}")
    return Check(WARN, "OCR (Tesseract)", f"{msg} (opsional, hanya untuk PDF scan dan gambar)")


# --- uji nyata ---------------------------------------------------------------------------------------

def live_embedding(settings: Settings) -> Check:
    from app.rag.embeddings import build_embedder

    try:
        t = time.perf_counter()
        emb = build_embedder(settings)
        vec = emb.embed_query("syarat sidang tugas akhir")
        return Check(OK, "Model embedding", f"{emb.name}, dimensi {len(vec)}, {time.perf_counter() - t:.1f} detik (termasuk unduh/muat)")
    except Exception as exc:  # noqa: BLE001
        return Check(FAIL, "Model embedding", f"{type(exc).__name__}: {exc}")


def live_gemini(settings: Settings) -> Check:
    if settings.llm_provider != "gemini" or not settings.gemini_api_key:
        return Check(SKIP, "Gemini", "tidak dikonfigurasi")
    from app.rag.llm import GeminiClient, LLMError

    try:
        t = time.perf_counter()
        reply = GeminiClient(settings.gemini_api_key, settings.gemini_model, max_attempts=1).generate(
            "Jawab sangat singkat.", "Balas hanya dengan kata: OK"
        )
        return Check(OK, "Gemini", f"model {settings.gemini_model} merespons ({reply[:20]!r}, {time.perf_counter() - t:.1f} detik)")
    except LLMError as exc:
        hint = " Cek nama model di Google AI Studio (GEMINI_MODEL) dan API key." if "404" in str(exc) or "not found" in str(exc).lower() else ""
        return Check(FAIL, "Gemini", f"{exc}{hint}")


def live_groq(settings: Settings) -> Check:
    if settings.llm_provider != "groq" or not settings.groq_api_key:
        return Check(SKIP, "Groq", "tidak dikonfigurasi")
    from app.rag.llm import GroqClient, LLMError

    try:
        t = time.perf_counter()
        reply = GroqClient(settings.groq_api_key, settings.groq_model, max_attempts=1).generate(
            "Jawab sangat singkat.", "Balas hanya dengan kata: OK"
        )
        return Check(OK, "Groq", f"model {settings.groq_model} merespons ({reply[:20]!r}, {time.perf_counter() - t:.1f} detik)")
    except LLMError as exc:
        return Check(FAIL, "Groq", f"{exc} Cek GROQ_MODEL dan API key.")


def live_telegram(settings: Settings) -> Check:
    if not settings.telegram_token:
        return Check(SKIP, "Telegram", "TELEGRAM_TOKEN kosong")
    import httpx

    try:
        r = httpx.get(f"https://api.telegram.org/bot{settings.telegram_token}/getMe", timeout=15)
        data = r.json()
        if data.get("ok"):
            return Check(OK, "Telegram", f"bot @{data['result']['username']}")
        return Check(FAIL, "Telegram", f"token ditolak: {data.get('description', r.status_code)}")
    except Exception as exc:  # noqa: BLE001
        return Check(FAIL, "Telegram", f"tidak terjangkau: {exc}")


def live_api(settings: Settings) -> Check:
    import httpx

    try:
        r = httpx.get(f"{settings.api_base_url}/health", timeout=5)
        return Check(OK if r.status_code == 200 else FAIL, "API berjalan", f"{settings.api_base_url} -> {r.status_code}")
    except Exception:  # noqa: BLE001
        return Check(WARN, "API berjalan", f"{settings.api_base_url} tidak terjangkau (jalankan: uvicorn app.main:app --port 8001)")


def run_checks(settings: Settings | None = None, live: bool = False) -> list[Check]:
    settings = settings or get_settings()
    checks = [check_python(), *check_packages(settings), *check_config(settings), *check_storage(settings), check_ocr(settings)]
    if live:
        checks += [live_embedding(settings), live_gemini(settings), live_groq(settings), live_telegram(settings), live_api(settings)]
    else:
        checks.append(Check(SKIP, "Uji nyata", "model embedding, Gemini, Telegram: jalankan dengan --live"))
    return checks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args()
    checks = run_checks(live=args.live)
    for c in checks:
        print(f"{ICON[c.level]} {c.name}: {c.detail}")
    fails = sum(c.level == FAIL for c in checks)
    warns = sum(c.level == WARN for c in checks)
    print(f"\n{fails} gagal, {warns} perlu perhatian.")
    if fails == 0 and warns == 0:
        print("Siap dipakai.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
