"""Buat akun admin, atau ganti passwordnya bila username sudah ada.

    python -m scripts.create_admin                # tanya username dan password
    python -m scripts.create_admin -u budi        # tanya password saja
"""
from __future__ import annotations

import argparse
import getpass
import sys

from app.db import db, init_db
from app.security import hash_password


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-u", "--username")
    args = parser.parse_args()

    username = args.username or input("Username admin: ").strip()
    if not username:
        print("Username tidak boleh kosong.")
        return 1
    password = getpass.getpass("Password (8-72 karakter): ")
    if getpass.getpass("Ulangi password: ") != password:
        print("Password tidak sama.")
        return 1
    if not 8 <= len(password.encode("utf-8")) <= 72:
        print("Password harus 8 sampai 72 byte.")
        return 1

    init_db()
    with db() as conn:
        exists = conn.execute("SELECT 1 FROM admins WHERE username = ?", (username,)).fetchone()
        if exists:
            conn.execute("UPDATE admins SET password_hash = ? WHERE username = ?", (hash_password(password), username))
            print(f"Password '{username}' diperbarui.")
        else:
            conn.execute("INSERT INTO admins(username, password_hash) VALUES (?, ?)", (username, hash_password(password)))
            print(f"Admin '{username}' dibuat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
