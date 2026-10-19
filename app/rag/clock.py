"""Waktu server untuk pertanyaan relatif ("hari ini", "besok", "sekarang") pada jadwal.

Kata relatif diganti nama hari yang sebenarnya sebelum pencarian, karena baris jadwal memuat nama hari
("Hari Senin"), bukan kata "hari ini". Waktu sekarang juga diberikan ke LLM sebagai konteks.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

DAYS = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")
MONTHS = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
          "November", "Desember")
ZONE_LABELS = {"Asia/Jakarta": "WIB", "Asia/Makassar": "WITA", "Asia/Jayapura": "WIT"}

_HARI_INI_RE = re.compile(r"\bhari\s+ini\b", re.I)
_SEKARANG_RE = re.compile(r"\b(?:sekarang|saat\s+ini)\b", re.I)
_OFFSET_RES = (
    (re.compile(r"\b(?:hari\s+)?(?:besok|esok)\b", re.I), 1),
    (re.compile(r"\b(?:hari\s+)?lusa\b", re.I), 2),
    (re.compile(r"\b(?:hari\s+)?kemarin\b", re.I), -1),
)


def now_local(timezone_name: str = "Asia/Jakarta") -> datetime:
    """Waktu server di zona waktu tersebut. Bila database zona waktu tidak ada, pakai UTC+7."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(timezone_name))
    except Exception:  # noqa: BLE001 - ZoneInfoNotFoundError dan sejenisnya
        return datetime.now(timezone(timedelta(hours=7)))


def day_name(now: datetime, offset: int = 0) -> str:
    return DAYS[(now + timedelta(days=offset)).weekday()]


def describe_now(now: datetime, timezone_name: str = "Asia/Jakarta") -> str:
    label = ZONE_LABELS.get(timezone_name, timezone_name)
    return f"{DAYS[now.weekday()]}, {now.day} {MONTHS[now.month - 1]} {now.year}, pukul {now:%H.%M} {label}"


def resolve_relative_days(question: str, now: datetime) -> str:
    """"hari ini" -> "hari Senin", "besok" -> "hari Selasa", "sekarang" -> "hari Senin jam 14.35"."""
    text = _HARI_INI_RE.sub(f"hari {day_name(now)}", question)
    for pattern, offset in _OFFSET_RES:
        text = pattern.sub(f"hari {day_name(now, offset)}", text)
    return _SEKARANG_RE.sub(f"hari {day_name(now)} jam {now:%H.%M}", text)
