from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from ..config import Settings, get_settings
from ..db import db
from ..security import (
    client_key,
    create_token,
    hash_password,
    login_limiter,
    require_admin,
    verify_password,
)
from .schemas import ChangePasswordIn, LoginIn

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Hash tiruan supaya waktu respons sama untuk username yang tidak ada.
_DUMMY_HASH = hash_password("tidak-dipakai-untuk-apa-apa")


@router.post("/login")
def login(body: LoginIn, request: Request, settings: Settings = Depends(get_settings)):
    key = client_key(request)
    login_limiter.check(key)
    with db() as conn:
        row = conn.execute(
            "SELECT username, password_hash FROM admins WHERE username = ?", (body.username,)
        ).fetchone()
    ok = verify_password(body.password, row["password_hash"] if row else _DUMMY_HASH)
    if not row or not ok:
        login_limiter.record_failure(key)
        raise HTTPException(401, "Username atau password salah.")
    login_limiter.reset(key)
    return {
        "access_token": create_token(row["username"], settings),
        "token_type": "bearer",
        "username": row["username"],
    }


@router.get("/me")
def me(username: str = Depends(require_admin)):
    return {"username": username}


@router.post("/change-password")
def change_password(body: ChangePasswordIn, username: str = Depends(require_admin)):
    with db() as conn:
        row = conn.execute("SELECT password_hash FROM admins WHERE username = ?", (username,)).fetchone()
        if not row or not verify_password(body.old_password, row["password_hash"]):
            raise HTTPException(400, "Password lama salah.")
        conn.execute(
            "UPDATE admins SET password_hash = ? WHERE username = ?",
            (hash_password(body.new_password), username),
        )
    return {"ok": True}
