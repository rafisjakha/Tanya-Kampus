"""Pembacaan PDF jadwal berbentuk grid (PDF dibuat dengan reportlab, tanpa file asli)."""
import pytest

pytest.importorskip("pdfplumber")
canvas = pytest.importorskip("reportlab.pdfgen.canvas")

from app.ingestion.converter import convert_file  # noqa: E402

PAGE_H = 600


def y(top):  # koordinat reportlab dihitung dari bawah
    return PAGE_H - top


def box(c, x, top, w, h):
    c.rect(x, y(top + h), w, h, fill=1, stroke=0)


def make_schedule_pdf(path):
    c = canvas.Canvas(str(path), pagesize=(800, PAGE_H))
    # header: sel hari, baris "Ruangan Kelas", baris nama ruangan
    c.setFillGray(0.749)
    box(c, 30, 60, 50, 40)
    box(c, 80, 60, 200, 20)
    box(c, 80, 80, 100, 20)
    box(c, 180, 80, 100, 20)
    c.setFillGray(0)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(35, y(75), "SENIN")
    c.drawString(100, y(94), "RKB.201")
    c.drawString(200, y(94), "RKB.202")
    # label jam: satu baris per 30 poin, label di tengah barisnya (mulai y=100)
    c.setFont("Helvetica", 9)
    for i, label in enumerate(["06.30", "07.30", "08.30", "09.30"]):
        c.drawString(40, y(100 + i * 30 + 18), label)
    # blok kelas: RKB.201 06.30-08.30 (3 baris); RKB.202 hanya baris 07.30 (praktikum)
    c.setFillColorRGB(0.98, 0.89, 0.84)
    box(c, 80, 100, 100, 90)
    c.setFillColorRGB(0.85, 0.95, 0.82)
    box(c, 180, 130, 100, 30)
    c.setFillGray(0)
    for top, text in [(112, "SISTEM"), (124, "INFORMASI"), (136, "FHH"), (148, "S1IT-KJ-24-02")]:
        c.drawString(90, y(top), text)
    for top, text in [(138, "(P) PEMR. WEB"), (148, "AED"), (158, "S1IT-KJ-24-01")]:
        c.drawString(190, y(top), text)
    c.showPage()
    # halaman daftar dosen: dua tabel berdampingan dalam satu baris
    c.setFont("Helvetica", 9)
    c.drawString(40, y(50), "DAFTAR KODE DOSEN")
    c.drawString(40, y(70), "1 NATHASYA UTAMI HAKIM, S.Pd., M.Kom. FHH 2 ARIES SAIFUDIN, S.T., M.Kom. AED")
    c.showPage()
    c.save()


def test_jadwal_grid_dibaca_per_sel(tmp_path):
    pdf = tmp_path / "jadwal.pdf"
    make_schedule_pdf(pdf)
    md = convert_file(pdf).markdown
    assert "## Jadwal hari Senin" in md
    line = next(ln for ln in md.splitlines() if "SISTEM INFORMASI" in ln)
    assert "Jam 06.30 sampai 08.30" in line and "Ruang RKB.201" in line
    assert "NATHASYA UTAMI HAKIM, S.Pd., M.Kom. (FHH)" in line and "Kelas S1IT-KJ-24-02" in line
    prak = next(ln for ln in md.splitlines() if "PEMR. WEB" in ln)
    assert prak.startswith("- Praktikum") and "Ruang RKB.202" in prak and "ARIES SAIFUDIN" in prak


def test_pdf_biasa_bukan_jadwal_tidak_diubah(tmp_path):
    pdf = tmp_path / "biasa.pdf"
    c = canvas.Canvas(str(pdf))
    c.drawString(72, 700, "Panduan akademik. Mahasiswa wajib mengisi KRS setiap semester.")
    c.save()
    from app.ingestion import schedule
    assert schedule.convert_schedule_pdf(pdf) is None
