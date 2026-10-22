import pytest
from fastapi import HTTPException

from app.security import LoginLimiter


def test_limiter_memblokir_setelah_batas():
    limiter = LoginLimiter(max_attempts=3, window_seconds=60)
    for _ in range(3):
        limiter.check("1.2.3.4")
        limiter.record_failure("1.2.3.4")
    with pytest.raises(HTTPException) as exc:
        limiter.check("1.2.3.4")
    assert exc.value.status_code == 429
    limiter.check("5.6.7.8")  # IP lain tidak ikut terblokir


def test_limiter_tidak_menyimpan_ip_yang_hanya_dicek():
    limiter = LoginLimiter()
    for i in range(100):
        limiter.check(f"10.0.0.{i}")
    assert limiter._hits == {}


def test_limiter_jumlah_ip_dibatasi(monkeypatch):
    limiter = LoginLimiter(window_seconds=60)
    monkeypatch.setattr(LoginLimiter, "MAX_KEYS", 10)
    clock = iter(range(0, 10_000, 100))  # tiap kegagalan 100 detik setelah sebelumnya: entri lama sudah kedaluwarsa
    monkeypatch.setattr("app.security.time.monotonic", lambda: next(clock))
    for i in range(50):
        limiter.record_failure(f"ip-{i}")
    assert len(limiter._hits) <= 10
