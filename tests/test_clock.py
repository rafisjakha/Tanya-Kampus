from datetime import datetime, timedelta, timezone

from app.rag.clock import day_name, describe_now, resolve_relative_days

# Senin, 19 Oktober 2026, 14.35 WIB
NOW = datetime(2026, 10, 19, 14, 35, tzinfo=timezone(timedelta(hours=7)))


def test_hari_dan_tanggal_server():
    assert day_name(NOW) == "Senin" and day_name(NOW, 1) == "Selasa" and day_name(NOW, -1) == "Minggu"
    assert describe_now(NOW) == "Senin, 19 Oktober 2026, pukul 14.35 WIB"


def test_kata_relatif_diganti_nama_hari():
    assert resolve_relative_days("kelas S1IT-KJ-23-003 hari ini ada apa?", NOW) == "kelas S1IT-KJ-23-003 hari Senin ada apa?"
    assert resolve_relative_days("jadwal besok apa?", NOW) == "jadwal hari Selasa apa?"
    assert resolve_relative_days("jadwal hari besok apa?", NOW) == "jadwal hari Selasa apa?"  # tidak jadi "hari hari"
    assert resolve_relative_days("kuliah lusa jam berapa", NOW) == "kuliah hari Rabu jam berapa"
    assert resolve_relative_days("kemarin ada kelas?", NOW) == "hari Minggu ada kelas?"
    assert resolve_relative_days("sekarang ada kelas apa?", NOW) == "hari Senin jam 14.35 ada kelas apa?"


def test_pertanyaan_tanpa_kata_relatif_tidak_berubah():
    q = "Apa syarat sidang tugas akhir?"
    assert resolve_relative_days(q, NOW) == q
