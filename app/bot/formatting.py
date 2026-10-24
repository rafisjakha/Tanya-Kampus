"""Fungsi murni untuk bot (tanpa dependensi Telegram) supaya mudah dites."""
from __future__ import annotations

import re
import time

from ..rag.textclean import clean_answer

TELEGRAM_LIMIT = 4096

WELCOME = (
    "Halo! Aku Tanya Kampus, asisten Prodi S1 Teknologi Informasi Telkom University Jakarta.\n\n"
    "Aku bantu cari informasi seputar magang, Kerja Praktik (KP), MBKM, Innovillage, konversi TAK, "
    "template dokumen, dan tugas akhir dari dokumen resmi, lengkap dengan sumbernya.\n\n"
    "Lagi ada kendala, misalnya soal pembayaran atau akun kampus? Ceritakan saja, nanti aku arahkan "
    "ke kontak yang tepat.\n\n"
    "Cara pakai: ketik pertanyaanmu langsung di kolom chat, contoh: Apa syarat mendaftar Kerja Praktik?\n\n"
    "Jawaban hanya berdasarkan dokumen yang tersedia. Untuk hal yang menentukan (batas waktu, "
    "persyaratan), selalu cocokkan dengan Prodi.\n\n"
    "Privasi: pertanyaanmu dicatat bersama ID Telegram untuk memperbaiki layanan."
)

HELP = (
    "Perintah:\n"
    "/menu : tampilkan tombol menu\n"
    "/about : tentang Tanya Kampus dan tim pengembang\n"
    "/tanya <pertanyaan> : tanya soal magang, KP, MBKM, TAK, dan lainnya\n"
    "/help : bantuan ini\n\n"
    "Di chat pribadi, kamu bisa langsung mengetik pertanyaan tanpa perintah."
)

MENU_TEXT = "Pilih menu di bawah, atau langsung ketik pertanyaanmu."

TANYA_TEXT = (
    "Ketik pertanyaanmu langsung di kolom chat.\n\n"
    "Contoh:\n"
    "- Apa syarat mendaftar Kerja Praktik?\n"
    "- Bagaimana cara konversi magang ke SKS?\n"
    "- Kegiatan apa saja yang bisa dapat poin TAK?\n"
    "- Ada template laporan KP?"
)

ABOUT = (
    "Tentang Tanya Kampus\n\n"
    "Tanya Kampus adalah chatbot Telegram berbasis RAG (Retrieval-Augmented Generation) yang membantu mahasiswa "
    "mendapatkan jawaban seputar magang, Kerja Praktik, MBKM, Innovillage, konversi TAK, template dokumen, dan "
    "tugas akhir dengan cepat. Jawabannya hanya berdasarkan dokumen resmi Prodi Teknologi Informasi yang sudah "
    "dipublikasikan, lengkap dengan sumbernya.\n\n"
    "Kenapa dibuat? Pedoman magang, KP, MBKM, TAK, tugas akhir, dan berbagai template dokumen tersebar di berbagai kanal "
    "dan direvisi tiap tahun ajaran, sehingga informasi di grup percakapan sering simpang siur atau sudah tidak "
    "berlaku. Tanya Kampus menjadi kanal tanya-jawab otomatis yang konsisten, sekaligus mengurangi beban staf Prodi "
    "yang harus menjawab pertanyaan serupa berulang kali.\n\n"
    "Mitra: Program Studi S1 Teknologi Informasi, Universitas Telkom Jakarta "
    "(Kaprodi: Hartanto Suryoprayogo, S.Kom., M.Kom.)\n\n"
    "Tim pengembang (Kelompok TK, Mata Kuliah Proyek TI):\n"
    "- Muhammad Raihan Fadani (Project Manager)\n"
    "- Muhammad Raia Pratama Putra Wibowo\n"
    "- Agil Naufal Al Habib Gurning\n"
    "- Rafi Athallah Sjakha\n"
    "- David Chandra\n\n"
    "Dosen pengampu: Syifa Nurgaida Yutia, S.Tr., M.T."
)

def _duration(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60} menit" if seconds >= 60 and seconds % 60 == 0 else f"{seconds} detik"


def session_expired_text(timeout: float) -> str:
    return (
        f"Sesi percakapan berakhir karena tidak ada aktivitas selama {_duration(timeout)}. "
        "Tekan Mulai di bawah atau kirim /start untuk memulai lagi."
    )


SESSION_NEEDED = "Sesi belum dimulai atau sudah berakhir. Tekan Mulai di bawah atau kirim /start untuk memulai."

TEXT_ONLY = "Aku hanya bisa membaca pesan teks. Ketik pertanyaanmu ya, contoh: Apa syarat mendaftar Kerja Praktik?"
DOWNLOAD_FAILED = "Maaf, file tidak bisa dikirim saat ini. Silakan ambil dari sumber resmi kampus."
NO_QUESTION = "Tulis pertanyaannya setelah perintah, contoh:\n/tanya Apa syarat mendaftar Kerja Praktik?"
BUSY = "Tunggu sebentar sebelum bertanya lagi."
STARTING = "Sedang diproses, tunggu sebentar ya."
START_LABEL = "Mulai"


def is_start_text(text: str) -> bool:
    """Pesan yang dikirim saat tombol "Mulai" (keyboard balasan) ditekan."""
    return text.strip().casefold() in {"mulai", "▶️ mulai", "▶ mulai"}
API_DOWN = "Maaf, layanan sedang tidak bisa dihubungi. Coba lagi beberapa saat lagi."


_CITATION_RE = re.compile(r"[ \t]*(?:\[\d+\])+")


def format_answer(result: dict) -> str:
    """Teks jawaban untuk Telegram. Penanda sumber [1] dibuang karena daftar sumber tidak ditampilkan."""
    text = clean_answer(_CITATION_RE.sub("", result["answer"]))
    return re.sub(r"[ \t]+([.,;:!?])", r"\1", text).strip()


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


class ChatHistory:
    """Riwayat tanya-jawab singkat per pengguna (di memori) supaya pesan lanjutan bisa dipahami.

    Hanya beberapa giliran terakhir dan kedaluwarsa setelah `ttl` detik tanpa pesan baru; hilang saat bot restart.
    """

    def __init__(self, ttl: float = 600, max_turns: int = 3, clock=time.monotonic):
        self.ttl, self.max_turns, self._clock = ttl, max_turns, clock
        self._turns: dict[int, list[tuple[float, str, str]]] = {}

    def get(self, user_id: int) -> list[tuple[str, str]]:
        now = self._clock()
        turns = [t for t in self._turns.get(user_id, []) if now - t[0] < self.ttl]
        if turns:
            self._turns[user_id] = turns
        else:
            self._turns.pop(user_id, None)
        return [(q, a) for _, q, a in turns]

    def add(self, user_id: int, question: str, answer: str) -> None:
        now = self._clock()
        turns = [t for t in self._turns.get(user_id, []) if now - t[0] < self.ttl]
        turns.append((now, question, answer))
        self._turns[user_id] = turns[-self.max_turns:]
        if len(self._turns) > 5000:  # bersihkan pengguna yang sudah lama diam
            self._turns = {u: ts for u, ts in self._turns.items() if ts and now - ts[-1][0] < self.ttl}

    def clear(self, user_id: int) -> None:
        self._turns.pop(user_id, None)
