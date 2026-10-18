"""Tes handler bot dengan objek Telegram tiruan (tanpa jaringan, tanpa token asli)."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

pytest.importorskip("telegram")

from app.bot import telegram_bot as bot  # noqa: E402
from app.bot.formatting import API_DOWN, BUSY, Cooldown  # noqa: E402


class FakeApi:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error
        self.asked, self.feedbacks, self.ingested = [], [], []

    async def ask(self, question, user_ref):
        self.asked.append((question, user_ref))
        if self.error:
            raise self.error
        return self.result

    async def feedback(self, query_id, rating):
        self.feedbacks.append((query_id, rating))

    async def ingest(self, filename, data, title, user_ref):
        self.ingested.append((filename, title, user_ref))
        return {"id": 7, "title": title or filename, "status": "draft"}


def make_update(text="Apa syarat sidang?", user_id=1, chat_type="private"):
    msg = SimpleNamespace(text=text, reply_text=AsyncMock(), caption=None, document=None)
    return SimpleNamespace(
        message=msg,
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=99, type=chat_type),
    )


def make_context(api, admin_ids=(), args=None):
    app = SimpleNamespace(bot_data={
        "api": api,
        "cooldown": Cooldown(3),
        "settings": SimpleNamespace(admin_telegram_ids=frozenset(admin_ids)),
    })
    return SimpleNamespace(application=app, bot=SimpleNamespace(send_chat_action=AsyncMock()), args=args or [])


ANSWER = {"query_id": 5, "status": "answered", "answer": "Butuh 8 kali bimbingan [1].",
          "sources": [{"n": 1, "title": "Panduan TA", "heading": "Panduan TA > Persyaratan Sidang",
                       "effective_date": None, "url": None}]}


def run(coro):
    return asyncio.run(coro)


def test_pertanyaan_dijawab_dengan_sumber_dan_tombol_feedback():
    api, upd, ctx = FakeApi(ANSWER), make_update(), None
    ctx = make_context(api)
    run(bot.on_text(upd, ctx))
    assert api.asked == [("Apa syarat sidang?", "1")]
    args, kwargs = upd.message.reply_text.call_args
    assert "Sumber:" in args[0] and "Persyaratan Sidang" in args[0]
    buttons = kwargs["reply_markup"].inline_keyboard[0]
    assert [b.callback_data for b in buttons] == ["fb:5:1", "fb:5:-1"]


def test_cooldown_menolak_pertanyaan_beruntun():
    api, ctx = FakeApi(ANSWER), None
    ctx = make_context(api)
    u1, u2 = make_update(), make_update()
    run(bot.on_text(u1, ctx))
    run(bot.on_text(u2, ctx))
    assert len(api.asked) == 1
    assert u2.message.reply_text.call_args[0][0] == BUSY


def test_api_mati_memberi_pesan_ramah():
    api = FakeApi(error=httpx.ConnectError("down"))
    upd, ctx = make_update(), make_context(api)
    run(bot.on_text(upd, ctx))
    assert upd.message.reply_text.call_args[0][0] == API_DOWN


def test_grup_hanya_merespons_perintah_tanya():
    api = FakeApi(ANSWER)
    upd, ctx = make_update(chat_type="group"), make_context(api)
    run(bot.on_text(upd, ctx))
    assert api.asked == []
    upd2, ctx2 = make_update(chat_type="group"), make_context(api, args=["syarat", "sidang"])
    run(bot.cmd_tanya(upd2, ctx2))
    assert api.asked == [("syarat sidang", "1")]


def test_tanya_tanpa_pertanyaan():
    api = FakeApi(ANSWER)
    upd, ctx = make_update(), make_context(api, args=[])
    run(bot.cmd_tanya(upd, ctx))
    assert api.asked == [] and "contoh" in upd.message.reply_text.call_args[0][0]


def test_feedback_callback():
    api = FakeApi()
    query = SimpleNamespace(data="fb:5:-1", answer=AsyncMock(), edit_message_reply_markup=AsyncMock())
    upd, ctx = SimpleNamespace(callback_query=query), make_context(api)
    run(bot.on_feedback(upd, ctx))
    assert api.feedbacks == [(5, -1)]
    query.edit_message_reply_markup.assert_awaited_with(reply_markup=None)


def test_upload_dokumen_hanya_admin():
    api = FakeApi()
    doc = SimpleNamespace(file_name="panduan.pdf", file_size=1000, get_file=AsyncMock())
    upd = make_update(user_id=2)
    upd.message.document = doc
    run(bot.on_document(upd, make_context(api, admin_ids={1})))
    assert api.ingested == [] and "admin" in upd.message.reply_text.call_args[0][0]


def test_upload_dokumen_admin_membuat_draft():
    api = FakeApi()
    tg_file = SimpleNamespace(download_as_bytearray=AsyncMock(return_value=bytearray(b"%PDF data")))
    doc = SimpleNamespace(file_name="panduan.pdf", file_size=1000, get_file=AsyncMock(return_value=tg_file))
    upd = make_update(user_id=1)
    upd.message.document, upd.message.caption = doc, "Panduan Baru"
    run(bot.on_document(upd, make_context(api, admin_ids={1})))
    assert api.ingested == [("panduan.pdf", "Panduan Baru", "1")]
    assert "Draft dibuat" in upd.message.reply_text.call_args[0][0]


def test_upload_format_tidak_didukung():
    api = FakeApi()
    doc = SimpleNamespace(file_name="virus.exe", file_size=10, get_file=AsyncMock())
    upd = make_update(user_id=1)
    upd.message.document = doc
    run(bot.on_document(upd, make_context(api, admin_ids={1})))
    assert api.ingested == [] and "belum didukung" in upd.message.reply_text.call_args[0][0]


def test_aplikasi_bisa_dirakit_dengan_token_palsu(env, monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "123456:ABC-DEF_fake")
    from app.config import get_settings

    get_settings.cache_clear()
    app = bot.build_application(get_settings())
    assert len(app.handlers[0]) >= 6


# --- file asli, sapaan, pesan non-teks -------------------------------------------------------------------

def test_keyboard_memuat_tombol_unduh_untuk_sumber_yang_diizinkan():
    result = {
        "query_id": 9, "status": "answered", "answer": "x",
        "sources": [
            {"n": 1, "doc_id": 3, "title": "Template Tugas Akhir", "downloadable": True},
            {"n": 2, "doc_id": 3, "title": "Template Tugas Akhir", "downloadable": True},  # duplikat dokumen
            {"n": 3, "doc_id": 4, "title": "Panduan", "downloadable": False},
        ],
    }
    rows = bot.build_keyboard(result).inline_keyboard
    assert [r[0].callback_data for r in rows[:-1]] == ["dl:3"]
    assert "Template Tugas Akhir" in rows[0][0].text
    assert [b.callback_data for b in rows[-1]] == ["fb:9:1", "fb:9:-1"]


def test_keyboard_tanpa_unduh_saat_tidak_ditemukan():
    rows = bot.build_keyboard({"query_id": 1, "status": "not_found", "answer": "x", "sources": []}).inline_keyboard
    assert len(rows) == 1 and rows[0][0].callback_data == "fb:1:1"
    assert bot.build_keyboard({"status": "error", "answer": "x", "sources": []}) is None


def test_tombol_unduh_mengirim_dokumen():
    class DlApi(FakeApi):
        async def download(self, doc_id):
            return "template.pdf", b"%PDF-isi"

    api = DlApi()
    query = SimpleNamespace(data="dl:3", answer=AsyncMock(), message=SimpleNamespace(chat_id=99))
    ctx = make_context(api)
    ctx.bot.send_document = AsyncMock()
    ctx.bot.send_message = AsyncMock()
    run(bot.on_download(SimpleNamespace(callback_query=query), ctx))
    kwargs = ctx.bot.send_document.call_args.kwargs
    assert kwargs["filename"] == "template.pdf" and kwargs["document"].read() == b"%PDF-isi"


def test_tombol_unduh_gagal_memberi_pesan_ramah():
    class DlApi(FakeApi):
        async def download(self, doc_id):
            raise httpx.ConnectError("down")

    query = SimpleNamespace(data="dl:3", answer=AsyncMock(), message=SimpleNamespace(chat_id=99))
    ctx = make_context(DlApi())
    ctx.bot.send_document = AsyncMock()
    ctx.bot.send_message = AsyncMock()
    run(bot.on_download(SimpleNamespace(callback_query=query), ctx))
    ctx.bot.send_document.assert_not_called()
    assert "tidak bisa dikirim" in ctx.bot.send_message.call_args.args[1]


def test_sapaan_tidak_memanggil_api():
    api = FakeApi(ANSWER)
    upd, ctx = make_update(text="halo kak"), make_context(api)
    run(bot.on_text(upd, ctx))
    assert api.asked == [] and "Tanya Kampus" in upd.message.reply_text.call_args[0][0]


def test_pesan_non_teks_dijawab_sopan():
    upd = make_update()
    run(bot.on_non_text(upd, make_context(FakeApi())))
    assert "pesan teks" in upd.message.reply_text.call_args[0][0]


@pytest.mark.parametrize("disposition,expected", [
    ('attachment; filename="template.pdf"', "template.pdf"),
    ("attachment; filename*=utf-8''Panduan%20Tugas%20Akhir%20%C3%A9.pdf", "Panduan Tugas Akhir é.pdf"),
])
def test_api_client_download_membaca_nama_file(disposition, expected):
    from app.config import get_settings

    def handler(request):
        assert request.url.path == "/api/files/5"
        return httpx.Response(200, content=b"isi", headers={"content-disposition": disposition})

    client = bot.ApiClient(get_settings())
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://api")
    name, data = run(client.download(5))
    assert (name, data) == (expected, b"isi")
