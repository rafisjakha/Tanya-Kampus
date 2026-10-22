"""Jalankan bot Telegram dan mulai ulang otomatis setiap kali kode atau .env berubah (untuk pengembangan).

    python -m scripts.dev_bot                       # pantau app/ dan .env, jalankan app.bot.telegram_bot
    python -m scripts.dev_bot --watch app scripts   # pantau folder lain
    python -m scripts.dev_bot --command "python -m app.bot.telegram_bot"

Hanya file .py dan .env yang dipantau. Hentikan dengan Ctrl+C. API (uvicorn) tidak ikut dijalankan:
pakai `uvicorn app.main:app --reload --port 8001` di terminal lain, yang sudah memuat ulang sendiri.
"""
from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

from watchfiles import Change, run_process

ROOT = Path(__file__).resolve().parent.parent
WATCHED_SUFFIXES = {".py"}
WATCHED_NAMES = {".env"}


def should_restart(change: Change, path: str) -> bool:
    p = Path(path)
    return p.suffix in WATCHED_SUFFIXES or p.name in WATCHED_NAMES


def on_change(changes: set[tuple[Change, str]]) -> None:
    names = ", ".join(sorted({Path(p).name for _, p in changes}))
    print(f"[dev_bot] Perubahan terdeteksi ({names}). Memulai ulang bot...", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Jalankan bot dan mulai ulang otomatis saat file berubah.")
    parser.add_argument("--watch", nargs="+", default=["app", ".env"], help="folder atau file yang dipantau")
    parser.add_argument("--command", default=f"{shlex.quote(sys.executable)} -m app.bot.telegram_bot",
                        help="perintah yang dijalankan (default: bot Telegram)")
    parser.add_argument("--debounce", type=int, default=800, help="jeda ms agar beberapa perubahan sekaligus jadi satu restart")
    args = parser.parse_args(argv)

    paths = [ROOT / w for w in args.watch if (ROOT / w).exists()]
    if not paths:
        print("Tidak ada yang bisa dipantau:", ", ".join(args.watch), file=sys.stderr)
        return 1
    print(f"[dev_bot] Memantau: {', '.join(str(p.relative_to(ROOT)) for p in paths)}. Ctrl+C untuk berhenti.", flush=True)
    try:
        run_process(
            *paths,
            target=args.command,
            target_type="command",
            callback=on_change,
            watch_filter=should_restart,
            debounce=args.debounce,
        )
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
