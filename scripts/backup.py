"""Backup dan restore data Tanya Kampus (database + file asli) dalam satu file zip.

    python -m scripts.backup                       # buat backups/tanya-kampus-YYYYmmdd-HHMMSS.zip
    python -m scripts.backup --out /path/folder    # simpan di folder lain
    python -m scripts.backup --restore file.zip    # pulihkan (hentikan server dulu!)

Backup aman dijalankan saat server hidup (memakai API backup SQLite, bukan salin file mentah).
Embedding ikut tersimpan di database, jadi setelah restore tidak perlu index ulang
selama EMBEDDING_MODEL sama.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from app.config import BASE_DIR, get_settings

DB_NAME = "tanya_kampus.db"


def make_backup(out_dir: Path) -> Path:
    settings = get_settings()
    if not settings.db_path.exists():
        raise SystemExit(f"Database tidak ditemukan di {settings.db_path}. Belum ada data untuk di-backup.")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"tanya-kampus-{datetime.now():%Y%m%d-%H%M%S}.zip"

    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / DB_NAME
        src = sqlite3.connect(settings.db_path)
        dst = sqlite3.connect(snapshot)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(snapshot, DB_NAME)
            if settings.raw_dir.exists():
                for f in sorted(settings.raw_dir.iterdir()):
                    if f.is_file():
                        z.write(f, f"raw/{f.name}")
    return target


def restore(zip_path: Path, force: bool) -> None:
    settings = get_settings()
    if not zip_path.exists():
        raise SystemExit(f"File tidak ditemukan: {zip_path}")
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        if DB_NAME not in names:
            raise SystemExit("Zip ini bukan backup Tanya Kampus (tidak ada tanya_kampus.db).")
        if settings.db_path.exists() and not force:
            raise SystemExit(
                f"Sudah ada database di {settings.db_path}. Hentikan server, lalu jalankan ulang dengan --force "
                "(database lama disimpan sebagai .before-restore)."
            )
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        if settings.db_path.exists():
            shutil.copy2(settings.db_path, settings.db_path.with_suffix(".db.before-restore"))
        for suffix in ("-wal", "-shm"):  # sisa journal lama tidak boleh tercampur dengan database hasil restore
            Path(str(settings.db_path) + suffix).unlink(missing_ok=True)
        settings.raw_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            if name == DB_NAME:
                settings.db_path.write_bytes(z.read(name))
            elif name.startswith("raw/") and not name.endswith("/"):
                safe = Path(name).name  # cegah path traversal
                (settings.raw_dir / safe).write_bytes(z.read(name))
    print(f"Restore selesai ke {settings.data_dir}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(BASE_DIR / "backups"))
    ap.add_argument("--restore", metavar="ZIP")
    ap.add_argument("--force", action="store_true", help="timpa database yang ada saat restore")
    args = ap.parse_args()
    if args.restore:
        restore(Path(args.restore), args.force)
    else:
        path = make_backup(Path(args.out))
        print(f"Backup dibuat: {path} ({path.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
