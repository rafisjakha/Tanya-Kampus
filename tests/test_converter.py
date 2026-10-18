import pytest

from app.ingestion.converter import ConversionError, file_to_markdown, normalize_markdown


def test_markdown_dan_txt_dibaca_apa_adanya(tmp_path):
    p = tmp_path / "a.md"
    p.write_text("# Judul\r\n\r\n\r\n\r\nIsi dokumen yang cukup panjang.", encoding="utf-8")
    out = file_to_markdown(p)
    assert out.startswith("# Judul") and "\r" not in out and "\n\n\n" not in out


def test_encoding_latin1_tidak_crash(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes("Pengumuman résumé untuk mahasiswa baru semester ini".encode("latin-1"))
    assert "Pengumuman" in file_to_markdown(p)


def test_format_tidak_didukung(tmp_path):
    p = tmp_path / "a.exe"
    p.write_bytes(b"MZ")
    with pytest.raises(ConversionError, match="belum didukung"):
        file_to_markdown(p)


def test_file_hampir_kosong_ditolak(tmp_path):
    p = tmp_path / "kosong.txt"
    p.write_text("  \n", encoding="utf-8")
    with pytest.raises(ConversionError, match="Tidak ada teks"):
        file_to_markdown(p)


def test_docx_ke_markdown_mempertahankan_heading_dan_tabel(tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_heading("Persyaratan Sidang", level=1)
    d.add_paragraph("Mahasiswa wajib menyerahkan naskah tugas akhir kepada pembimbing.")
    t = d.add_table(rows=2, cols=2)
    t.rows[0].cells[0].text, t.rows[0].cells[1].text = "Syarat", "Batas"
    t.rows[1].cells[0].text, t.rows[1].cells[1].text = "Naskah", "7 hari"
    p = tmp_path / "sidang.docx"
    d.save(p)
    out = file_to_markdown(p)
    assert "# Persyaratan Sidang" in out
    assert "| Syarat | Batas |" in out and "7 hari" in out


def test_pdf_ke_markdown(tmp_path):
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    p = tmp_path / "info.pdf"
    c = canvas.Canvas(str(p))
    c.drawString(72, 750, "Jadwal pengisian KRS dimulai pada minggu pertama perkuliahan.")
    c.save()
    assert "pengisian KRS" in file_to_markdown(p)


def test_pdf_tanpa_teks_memberi_pesan_ocr(tmp_path):
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    p = tmp_path / "scan.pdf"
    c = canvas.Canvas(str(p))
    c.rect(50, 50, 100, 100)  # hanya gambar, tanpa teks
    c.save()
    with pytest.raises(ConversionError, match="OCR"):
        file_to_markdown(p)


def test_normalize_markdown():
    assert normalize_markdown("a  \n\n\n\nb\x00 c") == "a\n\nb c\n"
