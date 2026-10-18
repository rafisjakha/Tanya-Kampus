"""Fungsi murni untuk bot (tanpa dependensi Telegram) supaya mudah dites."""
from __future__ import annotations

import re
import time

TELEGRAM_LIMIT = 4096

WELCOME = (
    "Halo! Saya Tanya Kampus.\n\n"
    "Saya membantu mencari informasi akademik dan tugas akhir dari dokumen resmi kampus, "
    "lengkap dengan sumbernya.\n\n"
    "Cara pakai:\n"
    "- Ketik pertanyaanmu langsung, atau\n"
    "- Pakai /tanya <pertanyaan>, contoh: /tanya Bagaimana cara mengajukan cuti akademik?\n\n"
    "Jawaban hanya berdasarkan dokumen yang tersedia. Untuk hal yang menentukan (jadwal, "
    "batas waktu, persyaratan), selalu cocokkan dengan bagian akademik.\n\n"
    "Privasi: pertanyaanmu dicatat bersama ID Telegram untuk memperbaiki layanan."
)

HELP = (
    "Perintah:\n"
    "/tanya <pertanyaan> : tanya informasi akademik atau tugas akhir\n"
    "/id : tampilkan ID Telegram kamu\n"
    "/help : bantuan ini\n\n"
    "Di chat pribadi, kamu bisa langsung mengetik pertanyaan tanpa perintah."
)

TEXT_ONLY = "Saya hanya bisa membaca pesan teks. Ketik pertanyaanmu ya, contoh: Apa syarat sidang tugas akhir?"
DOWNLOAD_FAILED = "Maaf, file tidak bisa dikirim saat ini. Silakan ambil dari sumber resmi kampus."
NO_QUESTION = "Tulis pertanyaannya setelah perintah, contoh:\n/tanya Apa saja syarat sidang tugas akhir?"
BUSY = "Tunggu sebentar sebelum bertanya lagi."
API_DOWN = "Maaf, layanan sedang tidak bisa dihubungi. Coba lagi beberapa saat lagi."


def format_sources(sources: list[dict]) -> str:
    lines = []
    for s in sources:
        parts = s.get("heading", "").split(" > ")
        section = " > ".join(parts[1:]) if len(parts) > 1 else ""
        line = f"[{s['n']}] {s['title']}"
        if section:
            line += f" > {section}"
        if s.get("effective_date"):
            line += f" (berlaku {s['effective_date']})"
        if s.get("url"):
            line += f"\n    {s['url']}"
        lines.append(line)
    return "\n".join(lines)


def format_answer(result: dict) -> str:
    text = result["answer"].strip()
    if result.get("status") == "answered" and result.get("sources"):
        text += "\n\nSumber:\n" + format_sources(result["sources"])
    return text


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Pecah pesan panjang di batas baris/spasi supaya tidak melebihi batas Telegram."""
    parts: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts


class Cooldown:
    """Batasi frekuensi pertanyaan per pengguna untuk menjaga kuota LLM."""

    def __init__(self, seconds: float, clock=time.monotonic):
        self.seconds = seconds
        self._clock = clock
        self._last: dict[int, float] = {}

    def allow(self, user_id: int) -> bool:
        now = self._clock()
        last = self._last.get(user_id)
        if last is not None and now - last < self.seconds:
            return False
        self._last[user_id] = now
        if len(self._last) > 5000:  # bersihkan entri lama
            cutoff = now - self.seconds
            self._last = {k: v for k, v in self._last.items() if v >= cutoff}
        return True
