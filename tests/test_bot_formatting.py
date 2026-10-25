from app.bot.formatting import Cooldown, format_answer, linkify_phones, split_message, wa_number


def test_format_answer_tanpa_daftar_sumber_dan_tanpa_penanda():
    result = {
        "status": "answered",
        "answer": "Cuti diajukan dua minggu sebelum kuliah [1].\n- Syarat A [1][2]\n- Syarat B [2]",
        "sources": [{"n": 1, "title": "Panduan Akademik", "heading": "Panduan Akademik > Cuti Akademik",
                     "effective_date": "2026-01-01", "url": None}],
    }
    text = format_answer(result)
    assert text == "Cuti diajukan dua minggu sebelum kuliah.\n- Syarat A\n- Syarat B"
    assert "Sumber" not in text and "[" not in text


def test_format_answer_tidak_ditemukan_tanpa_sumber():
    text = format_answer({"status": "not_found", "answer": "Maaf, belum ada.", "sources": []})
    assert text == "Maaf, belum ada."


def test_split_message_tidak_melebihi_batas_dan_tidak_kehilangan_isi():
    text = "\n".join(f"Baris nomor {i} dengan isi yang lumayan panjang." for i in range(400))
    parts = split_message(text, limit=1000)
    assert len(parts) > 1 and all(len(p) <= 1000 for p in parts)
    assert "".join(p.replace("\n", "") for p in parts).replace(" ", "") == text.replace("\n", "").replace(" ", "")


def test_split_message_tanpa_spasi():
    parts = split_message("x" * 2500, limit=1000)
    assert [len(p) for p in parts] == [1000, 1000, 500]


def test_cooldown():
    now = [100.0]
    cd = Cooldown(3, clock=lambda: now[0])
    assert cd.allow(1)
    assert not cd.allow(1)
    assert cd.allow(2)  # pengguna lain tidak terpengaruh
    now[0] += 3.1
    assert cd.allow(1)


def test_nomor_telepon_jadi_tautan_wa_me():
    html = linkify_phones("Hubungi +62 811-9780-0200 atau 081197800200.")
    assert '<a href="https://wa.me/6281197800200">+62 811-9780-0200</a>' in html
    assert '<a href="https://wa.me/6281197800200">081197800200</a>' in html


def test_telepon_rumah_dan_format_62_juga_diubah():
    assert 'href="https://wa.me/62215451597">(021) 545 1597</a>' in linkify_phones("Telp (021) 545 1597.")
    assert 'href="https://wa.me/62215451697">021-5451697</a>' in linkify_phones("Fax 021-5451697")
    assert 'href="https://wa.me/6281197800200">6281197800200</a>' in linkify_phones("WA 6281197800200")


def test_jam_kode_kelas_tahun_dan_angka_biasa_tidak_diubah():
    text = "Jumat 08.30-10.30, kelas S1IT-KJ-23-003, tahun 2026, IPK 2,50, 110 SKS, skor 0.580, 06.30 sampai 08.30"
    assert "wa.me" not in linkify_phones(text)
    assert linkify_phones(text) == text


def test_teks_lain_di_escape_untuk_html():
    assert linkify_phones("A & B < C > D") == "A &amp; B &lt; C &gt; D"
    html = linkify_phones("Kontak <b>0811 9780 0200</b>")
    assert "&lt;b&gt;" in html and 'href="https://wa.me/6281197800200"' in html


def test_url_wa_me_yang_sudah_ada_tidak_digandakan():
    assert linkify_phones("https://wa.me/6281197800200") == "https://wa.me/6281197800200"


def test_wa_number_menolak_yang_tidak_wajar():
    assert wa_number("0811-9780-0200") == "6281197800200"
    assert wa_number("123") is None and wa_number("0123456789012345678") is None
