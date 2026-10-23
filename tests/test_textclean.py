from app.bot.formatting import format_answer
from app.rag.textclean import clean_answer


def test_tebal_judul_dan_bullet_bintang_dibuang():
    raw = "## Jadwal\n* Kuliah **PROYEK TI** di __RKB.KJ.403__\n* Dosen `SYJ`"
    assert clean_answer(raw) == "Jadwal\n- Kuliah PROYEK TI di RKB.KJ.403\n- Dosen SYJ"


def test_tanda_hubung_khusus_jadi_hubung_biasa():
    assert clean_answer("S1IT‑KJ‑23‑003, 08.30‑10.30") == "S1IT-KJ-23-003, 08.30-10.30"


def test_bintang_biasa_dan_tanda_lain_tidak_rusak():
    assert clean_answer("Nilai 5 * 3 = 15 (lihat catatan*)") == "Nilai 5 * 3 = 15 (lihat catatan*)"
    assert clean_answer("- poin satu\n1. poin dua") == "- poin satu\n1. poin dua"


def test_jawaban_contoh_dari_bot():
    raw = ("Tentu, ini infonya ya. Kelas S1IT‑KJ‑23‑003:\n\n"
           "- **Jumat, 08.30‑10.30** – Kuliah **PROYEK TI** [1]")
    text = format_answer({"status": "answered", "answer": raw, "sources": []})
    assert "**" not in text and "[1]" not in text and "‑" not in text
    assert "- Jumat, 08.30-10.30 – Kuliah PROYEK TI" in text
