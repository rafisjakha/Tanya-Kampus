"""Tes handler bot dengan objek Telegram tiruan (tanpa jaringan, tanpa token asli)."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

pytest.importorskip("telegram")

from app.bot import telegram_bot as bot  # noqa: E402
from app.bot.formatting import API_DOWN, BUSY, ChatHistory, Cooldown  # noqa: E402
from app.bot.session import Sessions  # noqa: E402


class FakeApi:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error
        self.asked, self.feedbacks, self.ingested = [], [], []

    async def ask(self, question, user_ref, history=None):
        self.asked.append((question, user_ref))
        self.histories = getattr(self, "histories", []) + [history]
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
        effective_message=msg,
        effective_user=SimpleNamespace(id=user_id),
        effective_chat=SimpleNamespace(id=99, type=chat_type),
    )


def make_context(api, admin_ids=(), args=None):
    app = SimpleNamespace(bot_data={
        "api": api,
        "cooldown": Cooldown(3),
        "history": ChatHistory(),
        "start_kb_shown": set(),
        "start_guard": Cooldown(0),  # tes penjaga klik ganda membuat Cooldown sendiri
        "sessions": Sessions(0),  # 0 = tanpa batas waktu; tes sesi membuat Sessions sendiri
        "settings": SimpleNamespace(admin_telegram_ids=frozenset(admin_ids)),
    })
    return SimpleNamespace(application=app, bot=SimpleNamespace(send_chat_action=AsyncMock(),
                                                       send_message=AsyncMock(return_value=SimpleNamespace(delete=AsyncMock()))),
                            args=args or [])


ANSWER = {"query_id": 5, "status": "answered", "answer": "Butuh 8 kali bimbingan [1].",
          "sources": [{"n": 1, "title": "Panduan TA", "heading": "Panduan TA > Persyaratan Sidang",
                       "effective_date": None, "url": None}]}


def run(coro):
    return asyncio.run(coro)


def test_pertanyaan_dijawab_tanpa_daftar_sumber_dengan_tombol_feedback():
    api, upd, ctx = FakeApi(ANSWER), make_update(), None
    ctx = make_context(api)
    run(bot.on_text(upd, ctx))
    assert api.asked == [("Apa syarat sidang?", "1")]
    args, kwargs = upd.message.reply_text.call_args
    assert args[0] == "Butuh 8 kali bimbingan."  # tanpa daftar sumber dan tanpa penanda [1]
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


def test_sapaan_diteruskan_ke_api():
    api = FakeApi(ANSWER)
    upd, ctx = make_update(text="halo kak"), make_context(api)
    run(bot.on_text(upd, ctx))
    assert len(api.asked) == 1 and api.asked[0][0] == "halo kak"


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


def callback_data(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_start_menampilkan_tombol_menu():
    upd = make_update()
    run(bot.cmd_start(upd, make_context(FakeApi())))
    data = callback_data(upd.message.reply_text.call_args.kwargs["reply_markup"])
    assert data == ["menu:tanya", "menu:help", "menu:about"]


def make_callback(data, user_id=1):
    msg = SimpleNamespace(reply_text=AsyncMock(), chat_id=99)
    query = SimpleNamespace(data=data, answer=AsyncMock(), edit_message_text=AsyncMock(),
                            edit_message_reply_markup=AsyncMock(), message=msg)
    return SimpleNamespace(
        callback_query=query, message=None, effective_message=msg,
        effective_user=SimpleNamespace(id=user_id), effective_chat=SimpleNamespace(id=99, type="private"),
    )


def test_tombol_tentang_kami_menampilkan_tim():
    upd = make_callback("menu:about")
    run(bot.on_menu(upd, make_context(FakeApi())))
    text = upd.callback_query.edit_message_text.call_args.args[0]
    assert "Muhammad Raihan Fadani" in text and "Rafi Athallah Sjakha" in text
    assert callback_data(upd.callback_query.edit_message_text.call_args.kwargs["reply_markup"])


def test_tombol_bantuan_berubah_jadi_tombol_perintah():
    upd = make_callback("menu:help")
    run(bot.on_menu(upd, make_context(FakeApi())))
    call = upd.callback_query.edit_message_text.call_args
    assert "/tanya" in call.args[0] and "/id" not in call.args[0]
    markup = call.kwargs["reply_markup"]
    assert [b.text for row in markup.inline_keyboard for b in row] == ["❓ Tanya", "👥 Tentang Kami", "📋 Menu", "🏠 Beranda"]
    assert callback_data(markup) == ["menu:tanya", "menu:about", "menu:main", "menu:home"]


def test_tombol_menu_kembali_ke_menu_utama():
    upd = make_callback("menu:main")
    run(bot.on_menu(upd, make_context(FakeApi())))
    assert callback_data(upd.callback_query.edit_message_text.call_args.kwargs["reply_markup"]) == [
        "menu:tanya", "menu:help", "menu:about"]


def test_tombol_beranda_kembali_ke_sambutan():
    upd = make_callback("menu:home")
    run(bot.on_menu(upd, make_context(FakeApi())))
    call = upd.callback_query.edit_message_text.call_args
    assert call.args[0] == bot.WELCOME
    assert "menu:home" not in callback_data(call.kwargs["reply_markup"])  # sudah di beranda


def test_tampilan_tentang_kami_punya_tombol_beranda():
    upd = make_callback("menu:about")
    run(bot.on_menu(upd, make_context(FakeApi())))
    assert "menu:home" in callback_data(upd.callback_query.edit_message_text.call_args.kwargs["reply_markup"])


def test_perintah_id_tetap_ada_untuk_admin():
    upd = make_update(user_id=4242)
    run(bot.cmd_id(upd, make_context(FakeApi())))
    assert "4242" in upd.message.reply_text.call_args.args[0]


def test_command_about():
    upd = make_update()
    run(bot.cmd_about(upd, make_context(FakeApi())))
    assert "Tim pengembang" in upd.message.reply_text.call_args.args[0]


def test_pesan_lanjutan_membawa_riwayat_ke_api():
    api = FakeApi(ANSWER)
    ctx = make_context(api)
    run(bot.on_text(make_update(text="kelas S1IT-KJ-23-003 hari selasa apa?"), ctx))
    ctx.application.bot_data["cooldown"] = Cooldown(0)  # lewati jeda antar pertanyaan
    run(bot.on_text(make_update(text="kalo hari kamis?"), ctx))
    assert api.histories[0] == []
    assert api.histories[1] == [("kelas S1IT-KJ-23-003 hari selasa apa?", ANSWER["answer"])]


def test_start_mengosongkan_riwayat():
    api = FakeApi(ANSWER)
    ctx = make_context(api)
    run(bot.on_text(make_update(text="Apa syarat sidang?"), ctx))
    run(bot.cmd_start(make_update(), ctx))
    ctx.application.bot_data["cooldown"] = Cooldown(0)
    run(bot.on_text(make_update(text="kalo yang lain?"), ctx))
    assert api.histories[-1] == []


def test_riwayat_kedaluwarsa_dan_dibatasi():
    now = [0.0]
    h = ChatHistory(ttl=100, max_turns=2, clock=lambda: now[0])
    for i in range(3):
        h.add(1, f"q{i}", f"a{i}")
    assert h.get(1) == [("q1", "a1"), ("q2", "a2")]
    now[0] = 101
    assert h.get(1) == []


# --- sesi: berakhir bila diam, harus /start lagi ------------------------------------------------------------

def session_context(api, timeout=60.0, clock=None):
    ctx = make_context(api)
    ctx.application.bot_data["sessions"] = Sessions(timeout, clock=clock or (lambda: 0.0))
    return ctx


def test_tanpa_start_pesan_ditolak_dan_diminta_start():
    api = FakeApi(ANSWER)
    upd, ctx = make_update(text="Apa syarat sidang?"), session_context(api)
    run(bot.on_text(upd, ctx))
    assert api.asked == []
    markup = upd.message.reply_text.call_args.kwargs["reply_markup"]
    assert [b.text for row in markup.keyboard for b in row] == ["Mulai"]  # tombol di bawah kolom ketik


def test_setelah_start_pertanyaan_dijawab():
    api = FakeApi(ANSWER)
    ctx = session_context(api)
    run(bot.cmd_start(make_update(), ctx))
    run(bot.on_text(make_update(text="Apa syarat sidang?"), ctx))
    assert len(api.asked) == 1


def test_sesi_berakhir_setelah_diam_lalu_harus_start_lagi():
    now = [0.0]
    api = FakeApi(ANSWER)
    ctx = session_context(api, timeout=60, clock=lambda: now[0])
    run(bot.cmd_start(make_update(), ctx))
    now[0] = 61  # lewat 1 menit tanpa aktivitas
    upd = make_update(text="Apa syarat sidang?")
    run(bot.on_text(upd, ctx))
    assert api.asked == []
    assert "berakhir" in upd.message.reply_text.call_args.args[0]
    run(bot.cmd_start(make_update(), ctx))  # mulai lagi
    run(bot.on_text(make_update(text="Apa syarat sidang?"), ctx))
    assert len(api.asked) == 1


def test_aktivitas_memperpanjang_sesi():
    now = [0.0]
    api = FakeApi(ANSWER)
    ctx = session_context(api, timeout=60, clock=lambda: now[0])
    run(bot.cmd_start(make_update(), ctx))
    now[0] = 50
    ctx.application.bot_data["cooldown"] = Cooldown(0)
    run(bot.on_text(make_update(text="pertanyaan satu?"), ctx))
    now[0] = 100  # 50 detik sejak aktivitas terakhir: masih aktif
    run(bot.on_text(make_update(text="pertanyaan dua?"), ctx))
    assert len(api.asked) == 2


def test_grup_tidak_memakai_sesi():
    api = FakeApi(ANSWER)
    ctx = session_context(api)
    run(bot.cmd_tanya(make_update(chat_type="group"), SimpleNamespace(
        application=ctx.application, bot=ctx.bot, args=["syarat", "sidang?"])))
    assert len(api.asked) == 1


def test_pemberitahuan_dikirim_saat_sesi_berakhir():
    sent = []

    async def on_expire(user_id, chat_id):
        sent.append((user_id, chat_id))

    async def scenario():
        sessions = Sessions(0.05, on_expire)
        sessions.touch(7, 70)
        assert sessions.is_active(7)
        await asyncio.sleep(0.15)
        assert not sessions.is_active(7)

    run(scenario())
    assert sent == [(7, 70)]


def test_aktivitas_baru_membatalkan_hitung_mundur_lama():
    sent = []

    async def on_expire(user_id, chat_id):
        sent.append(user_id)

    async def scenario():
        sessions = Sessions(0.1, on_expire)
        sessions.touch(1, 10)
        await asyncio.sleep(0.06)
        sessions.touch(1, 10)  # diperpanjang
        await asyncio.sleep(0.06)
        assert sent == []  # hitung mundur pertama sudah dibatalkan
        await asyncio.sleep(0.1)

    run(scenario())
    assert sent == [1]


def test_sesi_tidak_berakhir_saat_jawaban_diproses():
    sent = []

    async def on_expire(user_id, chat_id):
        sent.append(user_id)

    async def scenario():
        sessions = Sessions(0.05, on_expire)
        sessions.begin_work(1, 10)
        await asyncio.sleep(0.12)  # jawaban lambat melewati batas waktu
        assert sent == []
        sessions.end_work(1, 10)
        await asyncio.sleep(0.12)

    run(scenario())
    assert sent == [1]


# --- klik ganda ---------------------------------------------------------------------------------------------

def test_start_dua_kali_beruntun_hanya_satu_sambutan():
    ctx = make_context(FakeApi())
    ctx.application.bot_data["start_guard"] = Cooldown(3)
    first, second = make_update(), make_update()
    run(bot.cmd_start(first, ctx))
    run(bot.cmd_start(second, ctx))
    assert first.message.reply_text.call_args.args[0] == bot.WELCOME
    assert second.message.reply_text.call_args.args[0] == bot.STARTING  # diberi tahu, tanpa sambutan kedua


def test_tombol_mulai_lagi_ditekan_dua_kali():
    ctx = make_context(FakeApi())
    ctx.application.bot_data["start_guard"] = Cooldown(3)
    first, second = make_callback("session:start"), make_callback("session:start")
    run(bot.on_session_start(first, ctx))
    run(bot.on_session_start(second, ctx))
    first.effective_message.reply_text.assert_called_once()  # sambutan hanya sekali
    second.effective_message.reply_text.assert_not_called()
    second.callback_query.answer.assert_any_call(bot.STARTING)
    first.callback_query.edit_message_reply_markup.assert_called_once_with(reply_markup=None)  # tombol dihapus


def test_pesan_yang_diedit_tidak_ditangani():
    """Mengedit pesan di Telegram menghasilkan update tanpa `message`; dulu membuat on_text error."""
    from dataclasses import replace
    from datetime import datetime, timezone

    from telegram import Chat, Message, Update, User

    from app.config import get_settings

    settings = get_settings()
    app = bot.build_application(replace(settings, telegram_token="123456:ABCdef_fake"))
    msg = Message(message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=1, type="private"),
                  from_user=User(id=1, first_name="x", is_bot=False), text="halo")
    handlers = [h for group in app.handlers.values() for h in group if isinstance(h, bot.MessageHandler)]
    assert handlers
    for update in (Update(update_id=1, edited_message=msg),):
        assert not any(h.check_update(update) for h in handlers)
    assert any(h.check_update(Update(update_id=2, message=msg)) for h in handlers)  # pesan baru tetap ditangani


def test_tombol_mulai_di_bawah_kolom_ketik_memulai_sesi():
    api = FakeApi(ANSWER)
    ctx = session_context(api)
    upd = make_update(text="Mulai")
    run(bot.on_text(upd, ctx))
    assert api.asked == []  # "Mulai" bukan pertanyaan
    assert upd.message.reply_text.call_args.args[0] == bot.WELCOME
    run(bot.on_text(make_update(text="Apa syarat sidang?"), ctx))
    assert len(api.asked) == 1  # sesi sudah aktif


def test_keyboard_mulai_dihapus_saat_pengguna_mengetik_start():
    ctx = session_context(FakeApi(ANSWER))
    run(bot.on_text(make_update(text="halo"), ctx))  # belum mulai: tombol "Mulai" ditampilkan
    assert 1 in ctx.application.bot_data["start_kb_shown"]
    run(bot.cmd_start(make_update(), ctx))
    from telegram import ReplyKeyboardRemove
    kwargs = ctx.bot.send_message.call_args.kwargs
    assert isinstance(kwargs["reply_markup"], ReplyKeyboardRemove)
    assert 1 not in ctx.application.bot_data["start_kb_shown"]


def test_pemberitahuan_sesi_berakhir_memakai_tombol_mulai():
    from app.bot.formatting import session_expired_text
    assert "Mulai" in session_expired_text(60)


def test_nomor_telepon_di_jawaban_jadi_tautan_wa_me():
    result = {**ANSWER, "answer": "Hubungi bagian akademik di (021) 545 1597 atau 0811-9780-0200 ya [1]."}
    upd, ctx = make_update(), make_context(FakeApi(result))
    run(bot.on_text(upd, ctx))
    args, kwargs = upd.message.reply_text.call_args
    assert kwargs["parse_mode"] == "HTML"
    assert '<a href="https://wa.me/62215451597">(021) 545 1597</a>' in args[0]
    assert '<a href="https://wa.me/6281197800200">0811-9780-0200</a>' in args[0]
    assert "[1]" not in args[0]


def test_bila_telegram_menolak_markup_dikirim_ulang_sebagai_teks_biasa():
    from telegram.error import BadRequest

    result = {**ANSWER, "answer": "Hubungi 0811-9780-0200 ya."}
    upd, ctx = make_update(), make_context(FakeApi(result))
    upd.message.reply_text = AsyncMock(side_effect=[BadRequest("Can't parse entities"), None])
    run(bot.on_text(upd, ctx))
    assert upd.message.reply_text.await_count == 2
    second = upd.message.reply_text.await_args_list[1]
    assert "parse_mode" not in second.kwargs and second.args[0] == "Hubungi 0811-9780-0200 ya."
