"""Bot Telegram Tanya Kampus.

Jalankan (setelah API hidup):  python -m app.bot.telegram_bot

Bot hanya antarmuka: semua logika RAG ada di API (/api/ask), jadi bot ringan dan model embedding
tidak dimuat dua kali. Mode polling, tidak butuh domain/webhook.
"""
from __future__ import annotations

import io
import logging

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ChatType
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..config import Settings, get_settings
from ..ingestion.converter import SUPPORTED_EXTENSIONS
from .formatting import (
    API_DOWN,
    BUSY,
    DOWNLOAD_FAILED,
    HELP,
    NO_QUESTION,
    TEXT_ONLY,
    WELCOME,
    Cooldown,
    format_answer,
    smalltalk_reply,
    split_message,
)

log = logging.getLogger("tanya_kampus.bot")
MAX_TG_DOWNLOAD = 20 * 1024 * 1024  # batas unduh file Bot API standar


class ApiClient:
    def __init__(self, settings: Settings):
        headers = {"X-API-Key": settings.bot_api_key} if settings.bot_api_key else {}
        self._http = httpx.AsyncClient(base_url=settings.api_base_url, headers=headers, timeout=90)

    async def ask(self, question: str, user_ref: str) -> dict:
        r = await self._http.post("/api/ask", json={"question": question, "channel": "telegram", "user_ref": user_ref})
        r.raise_for_status()
        return r.json()

    async def download(self, doc_id: int) -> tuple[str, bytes]:
        r = await self._http.get(f"/api/files/{doc_id}")
        r.raise_for_status()
        disposition = r.headers.get("content-disposition", "")
        name = "dokumen"
        if "filename=" in disposition:
            name = disposition.split("filename=", 1)[1].split(";")[0].strip().strip('"')
        if "filename*=" in disposition:  # nama file non-ASCII (RFC 5987)
            from urllib.parse import unquote

            name = unquote(disposition.split("filename*=", 1)[1].split("''", 1)[-1].split(";")[0].strip())
        return name, r.content

    async def feedback(self, query_id: int, rating: int) -> None:
        r = await self._http.post("/api/feedback", json={"query_id": query_id, "rating": rating})
        r.raise_for_status()

    async def ingest(self, filename: str, data: bytes, title: str | None, user_ref: str) -> dict:
        r = await self._http.post(
            "/api/bot/ingest",
            files={"file": (filename, data)},
            data={"user_ref": user_ref, **({"title": title} if title else {})},
        )
        r.raise_for_status()
        return r.json()

    async def close(self) -> None:
        await self._http.aclose()


def _api(context: ContextTypes.DEFAULT_TYPE) -> ApiClient:
    return context.application.bot_data["api"]


# --- handler ------------------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP)


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"ID Telegram kamu: {update.effective_user.id}")


async def answer_question(update: Update, context: ContextTypes.DEFAULT_TYPE, question: str):
    user = update.effective_user
    cooldown: Cooldown = context.application.bot_data["cooldown"]
    if not cooldown.allow(user.id):
        await update.message.reply_text(BUSY)
        return

    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    try:
        result = await _api(context).ask(question, user_ref=str(user.id))
    except httpx.HTTPStatusError as exc:
        log.warning("API menolak permintaan: %s %s", exc.response.status_code, exc.response.text[:200])
        await update.message.reply_text(API_DOWN)
        return
    except httpx.HTTPError as exc:
        log.warning("API tidak terjangkau: %s", exc)
        await update.message.reply_text(API_DOWN)
        return

    parts = split_message(format_answer(result))
    keyboard = build_keyboard(result)
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        await update.message.reply_text(part, reply_markup=keyboard if last else None, disable_web_page_preview=True)


def build_keyboard(result: dict) -> InlineKeyboardMarkup | None:
    rows = []
    seen = set()
    if result.get("status") == "answered":
        for s in result.get("sources", []):  # tombol unduh file asli untuk sumber yang diizinkan admin
            if s.get("downloadable") and s["doc_id"] not in seen:
                seen.add(s["doc_id"])
                title = s["title"] if len(s["title"]) <= 40 else s["title"][:37] + "..."
                rows.append([InlineKeyboardButton(f"📄 Unduh: {title}", callback_data=f"dl:{s['doc_id']}")])
    if result.get("status") in ("answered", "not_found") and result.get("query_id"):
        qid = result["query_id"]
        rows.append([
            InlineKeyboardButton("👍 Membantu", callback_data=f"fb:{qid}:1"),
            InlineKeyboardButton("👎 Kurang tepat", callback_data=f"fb:{qid}:-1"),
        ])
    return InlineKeyboardMarkup(rows) if rows else None


async def cmd_tanya(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = " ".join(context.args or []).strip()
    if not question:
        await update.message.reply_text(NO_QUESTION)
        return
    await answer_question(update, context, question)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != ChatType.PRIVATE:
        return  # di grup hanya merespons /tanya
    text = (update.message.text or "").strip()
    if not text:
        return
    reply = smalltalk_reply(text)
    if reply:
        await update.message.reply_text(reply)
        return
    await answer_question(update, context, text)


async def on_non_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(TEXT_ONLY)


async def on_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mahasiswa menekan tombol 'Unduh': kirim file asli (hanya dokumen yang diizinkan admin)."""
    query = update.callback_query
    try:
        doc_id = int(query.data.split(":")[1])
    except (IndexError, ValueError):
        await query.answer()
        return
    await query.answer("Mengirim file...")
    try:
        name, data = await _api(context).download(doc_id)
    except httpx.HTTPError as exc:
        log.warning("Unduh gagal: %s", exc)
        await context.bot.send_message(query.message.chat_id, DOWNLOAD_FAILED)
        return
    await context.bot.send_document(query.message.chat_id, document=io.BytesIO(data), filename=name)


async def on_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        _, qid, rating = query.data.split(":")
        await _api(context).feedback(int(qid), int(rating))
    except (ValueError, httpx.HTTPError) as exc:
        log.warning("Feedback gagal: %s", exc)
        await query.answer("Maaf, feedback gagal dikirim.", show_alert=False)
        return
    await query.answer("Terima kasih atas masukanmu!")
    await query.edit_message_reply_markup(reply_markup=None)


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin mengirim file: dibuat sebagai DRAFT, ditinjau dan di-index lewat panel admin."""
    settings: Settings = context.application.bot_data["settings"]
    if update.effective_chat.type != ChatType.PRIVATE:
        return
    if update.effective_user.id not in settings.admin_telegram_ids:
        await update.message.reply_text("Upload dokumen hanya untuk admin.")
        return
    doc = update.message.document
    name = doc.file_name or "dokumen"
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in SUPPORTED_EXTENSIONS:
        await update.message.reply_text("Format belum didukung. Didukung: " + ", ".join(sorted(SUPPORTED_EXTENSIONS)))
        return
    if doc.file_size and doc.file_size > MAX_TG_DOWNLOAD:
        await update.message.reply_text("File terlalu besar untuk diunduh bot (maks 20 MB). Upload lewat panel admin.")
        return

    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_DOCUMENT)
    try:
        tg_file = await doc.get_file()
        data = bytes(await tg_file.download_as_bytearray())
        res = await _api(context).ingest(name, data, (update.message.caption or "").strip() or None, str(update.effective_user.id))
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = exc.response.json().get("detail", "")
        except ValueError:
            pass
        await update.message.reply_text(f"Gagal memproses file: {detail or exc.response.status_code}")
        return
    except httpx.HTTPError:
        await update.message.reply_text(API_DOWN)
        return
    await update.message.reply_text(
        f"Draft dibuat: \"{res['title']}\" (#{res['id']}).\n"
        "Buka panel admin untuk memeriksa hasil konversi, lalu klik Index agar bisa dijawab bot."
    )


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Error tak tertangani", exc_info=context.error)


# --- aplikasi -------------------------------------------------------------------------------------

async def _post_init(app: Application):
    settings: Settings = app.bot_data["settings"]
    app.bot_data["api"] = ApiClient(settings)
    app.bot_data["cooldown"] = Cooldown(settings.bot_cooldown_seconds)
    await app.bot.set_my_commands([
        ("start", "Mulai dan cara pakai"),
        ("tanya", "Tanya informasi akademik atau tugas akhir"),
        ("help", "Bantuan"),
    ])


async def _post_shutdown(app: Application):
    api = app.bot_data.get("api")
    if api:
        await api.close()


def build_application(settings: Settings) -> Application:
    if not settings.telegram_token:
        raise SystemExit("TELEGRAM_TOKEN belum diset. Buat bot lewat @BotFather lalu isi .env.")
    app = (
        Application.builder()
        .token(settings.telegram_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.bot_data["settings"] = settings
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("tanya", cmd_tanya))
    app.add_handler(CallbackQueryHandler(on_feedback, pattern=r"^fb:\d+:-?1$"))
    app.add_handler(CallbackQueryHandler(on_download, pattern=r"^dl:\d+$"))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & (filters.PHOTO | filters.VOICE | filters.AUDIO | filters.VIDEO | filters.Sticker.ALL),
        on_non_text,
    ))
    app.add_error_handler(on_error)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = get_settings()
    app = build_application(settings)
    log.info("Bot berjalan (polling). API: %s", settings.api_base_url)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
