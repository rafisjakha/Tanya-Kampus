from app.bot.formatting import Cooldown, format_answer, split_message


def test_format_answer_dengan_sumber():
    result = {
        "status": "answered",
        "answer": "Cuti diajukan dua minggu sebelum kuliah [1].",
        "sources": [{"n": 1, "title": "Panduan Akademik", "heading": "Panduan Akademik > Cuti Akademik",
                     "effective_date": "2026-01-01", "url": None}],
    }
    text = format_answer(result)
    assert text.startswith("Cuti diajukan")
    assert "Sumber:\n[1] Panduan Akademik > Cuti Akademik (berlaku 2026-01-01)" in text


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
