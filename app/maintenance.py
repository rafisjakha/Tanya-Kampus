"""Tugas latar: pembersihan log lama dan pemanasan model embedding."""
from __future__ import annotations

import asyncio
import logging
import time

from .config import Settings
from .db import db

log = logging.getLogger("tanya_kampus.maintenance")
DAY_SECONDS = 24 * 3600


def purge_old(settings: Settings) -> dict:
    """Hapus log lebih tua dari LOG_RETENTION_DAYS (0 = simpan selamanya) dan cache kedaluwarsa."""
    removed_logs = removed_cache = 0
    with db() as conn:
        if settings.log_retention_days > 0:
            removed_logs = conn.execute(
                "DELETE FROM query_log WHERE created_at < datetime('now', ?)",
                (f"-{settings.log_retention_days} days",),
            ).rowcount
        removed_cache = conn.execute(
            "DELETE FROM answer_cache WHERE created_at < datetime('now', ?)",
            (f"-{max(settings.cache_ttl_hours, 1)} hours",),
        ).rowcount
    if removed_logs or removed_cache:
        log.info("Pembersihan: %d log lama, %d cache kedaluwarsa dihapus.", removed_logs, removed_cache)
    return {"logs": removed_logs, "cache": removed_cache}


async def maintenance_loop(settings: Settings) -> None:
    while True:
        try:
            await asyncio.to_thread(purge_old, settings)
        except Exception:  # noqa: BLE001 - jangan sampai tugas latar mematikan server
            log.exception("Pembersihan gagal")
        await asyncio.sleep(DAY_SECONDS)


def warm_up() -> None:
    """Muat model embedding di thread terpisah supaya pertanyaan pertama tidak lambat."""
    from . import deps

    started = time.perf_counter()
    try:
        deps._embedder().embed_query("pemanasan model")
        log.info("Model embedding siap (%.1f detik).", time.perf_counter() - started)
    except Exception as exc:  # noqa: BLE001
        log.warning("Pemanasan model embedding gagal: %s (akan dicoba lagi saat ada pertanyaan)", exc)
