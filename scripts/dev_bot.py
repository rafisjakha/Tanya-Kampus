"""Jalankan bot Telegram dan mulai ulang otomatis setiap kali kode atau .env berubah (untuk pengembangan).

    python -m scripts.dev_bot                       # pantau app/ dan .env, jalankan app.bot.telegram_bot
    python -m scripts.dev_bot --watch app scripts   # pantau folder lain
    python -m scripts.dev_bot --command "python -m app.bot.telegram_bot"

Hanya file .py dan .env yang dipantau. Hentikan dengan Ctrl+C. API (uvicorn) tidak ikut dijalankan:
pakai `uvicorn app.main:app --reload --port 8001` di terminal lain, yang sudah memuat ulang sendiri.
"""
from __future__ import annotations

import argparse
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


def run_bot() -> None:
    """Target default. Dijalankan sebagai fungsi di proses baru, bukan string perintah: di Windows watchfiles
    memecah perintah tanpa membuang tanda kutip, sehingga path Python yang mengandung spasi gagal dijalankan."""
    from app.bot.telegram_bot import main as bot_main

    bot_main()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Jalankan bot dan mulai ulang otomatis saat file berubah.")
    parser.add_argument("--watch", nargs="+", default=["app", ".env"], help="folder atau file yang dipantau")
    parser.add_argument("--command", default=None,
                        help="perintah lain yang dijalankan (default: bot Telegram dengan Python yang sama)")
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
            target=args.command or run_bot,
            target_type="command" if args.command else "function",
            callback=on_change,
            watch_filter=should_restart,
            debounce=args.debounce,
        )
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
