"""Sesi percakapan bot: berakhir bila pengguna diam selama `timeout` detik, lalu harus /start lagi.

Status sesi disimpan di memori (hilang saat bot restart, artinya semua pengguna perlu /start lagi). Saat sesi
berakhir, bot mengirim pemberitahuan lewat callback `on_expire`. timeout <= 0 berarti sesi tidak dipakai.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

log = logging.getLogger("tanya_kampus.bot")


class Sessions:
    def __init__(
        self,
        timeout: float,
        on_expire: Callable[[int, int], Awaitable[None]] | None = None,
        clock=time.monotonic,
    ):
        self.timeout = timeout
        self._on_expire = on_expire
        self._clock = clock
        self._deadline: dict[int, float] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self._busy: set[int] = set()  # sedang menunggu jawaban: jangan kedaluwarsakan di tengah proses

    @property
    def enabled(self) -> bool:
        return self.timeout > 0

    def is_active(self, user_id: int) -> bool:
        if not self.enabled:
            return True
        deadline = self._deadline.get(user_id)
        return deadline is not None and self._clock() < deadline

    def touch(self, user_id: int, chat_id: int) -> None:
        """Mulai atau perpanjang sesi, dan jadwalkan ulang hitung mundurnya."""
        if not self.enabled:
            return
        deadline = self._clock() + self.timeout
        self._deadline[user_id] = deadline
        old = self._tasks.pop(user_id, None)
        if old:
            old.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # dipanggil di luar event loop (mis. tes sinkron)
            return
        self._tasks[user_id] = loop.create_task(self._expire_later(user_id, chat_id, deadline))

    def end(self, user_id: int) -> None:
        self._deadline.pop(user_id, None)
        task = self._tasks.pop(user_id, None)
        if task:
            task.cancel()

    def begin_work(self, user_id: int, chat_id: int) -> None:
        self._busy.add(user_id)
        self.touch(user_id, chat_id)

    def end_work(self, user_id: int, chat_id: int) -> None:
        """Jawaban sudah terkirim: hitung mundur dimulai ulang dari sekarang."""
        self._busy.discard(user_id)
        self.touch(user_id, chat_id)

    async def _expire_later(self, user_id: int, chat_id: int, deadline: float) -> None:
        try:
            await asyncio.sleep(self.timeout)
        except asyncio.CancelledError:
            return
        if user_id in self._busy or self._deadline.get(user_id) != deadline:
            return  # ada aktivitas baru atau jawaban masih diproses
        self._deadline.pop(user_id, None)
        self._tasks.pop(user_id, None)
        if self._on_expire:
            try:
                await self._on_expire(user_id, chat_id)
            except Exception:  # noqa: BLE001 - kegagalan kirim pesan tidak boleh mematikan bot
                log.exception("Gagal mengirim pemberitahuan sesi berakhir")
