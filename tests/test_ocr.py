"""Tes OCR memakai Tesseract sungguhan (dilewati otomatis bila Tesseract tidak terpasang).

Memakai bahasa 'eng' karena selalu ada; teks uji Latin jelas sehingga hasilnya stabil.
"""
import shutil

import pytest

from app.config import get_settings
from app.ingestion import converter, ocr
from app.ingestion.converter import ConversionError, convert_file

PIL = pytest.importorskip("PIL")
pytest.importorskip("pytesseract")
pytest.importorskip("pypdfium2")
needs_tesseract = pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract tidak terpasang")

LINES = [
    "Persyaratan Sidang Tugas Akhir",
    "",
    "1. Bimbingan minimal 8 kali dengan pembimbing.",
    "2. Naskah diunggah 7 hari sebelum sidang.",
    "3. Skor TOEFL ITP minimal 450.",
]


@pytest.fixture(autouse=True)
def ocr_env(monkeypatch):
    monkeypatch.setenv("OCR_LANGUAGES", "eng")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def make_image(lines=LINES):
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default(size=34)
    img = Image.new("RGB", (1500, 70 * len(lines) + 60), "white")
    draw = ImageDraw.Draw(img)
    y = 30
    for line in lines:
        draw.text((40, y), line, fill="black", font=font)
        y += 70
    return img


def assert_ocr_text(text):
    low = text.lower()
    for kw in ("persyaratan sidang", "bimbingan minimal 8 kali", "7 hari", "450"):
        assert kw in low, f"{kw!r} tidak ada di hasil OCR:\n{text}"


@needs_tesseract
def test_gambar_png_di_ocr(tmp_path):
    p = tmp_path / "scan.png"
    make_image().save(p)
    res = convert_file(p)
    assert_ocr_text(res.markdown)
    assert res.note and "Hasil OCR" in res.note and "keyakinan" in res.note


@needs_tesseract
def test_pdf_scan_seluruh_halaman_di_ocr(tmp_path):
    p = tmp_path / "scan.pdf"
    make_image().save(p)  # PDF berisi gambar saja = hasil scan
    res = convert_file(p)
    assert res.markdown.startswith("## Halaman 1")
    assert_ocr_text(res.markdown)
    assert "seluruh halaman" in res.note


@needs_tesseract
def test_pdf_campuran_hanya_halaman_kosong_yang_di_ocr(tmp_path):
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    img_path = tmp_path / "p2.png"
    make_image().save(img_path)
    p = tmp_path / "campuran.pdf"
    c = canvas.Canvas(str(p), pagesize=(595, 842))
    for i in range(3):  # 3 halaman bertulisan agar rasio halaman kosong di bawah 50%
        c.drawString(72, 750, f"Halaman teks nomor {i + 1}: pengumuman jadwal registrasi ulang mahasiswa semester ganjil.")
        c.showPage()
    c.drawImage(ImageReader(str(img_path)), 20, 400, width=555, height=555 * 0.35)
    c.showPage()
    c.save()
    res = convert_file(p)
    assert "registrasi ulang" in res.markdown
    assert "## Halaman 4 (hasil OCR)" in res.markdown
    assert "bimbingan minimal 8 kali" in res.markdown.lower()
    assert "halaman tanpa teks" in res.note


@needs_tesseract
def test_batas_halaman_ocr(tmp_path, monkeypatch):
    monkeypatch.setenv("OCR_MAX_PAGES", "1")
    get_settings.cache_clear()
    imgs = [make_image(), make_image()]
    p = tmp_path / "dua.pdf"
    imgs[0].save(p, save_all=True, append_images=imgs[1:])
    res = convert_file(p)
    assert "## Halaman 1" in res.markdown and "## Halaman 2" not in res.markdown
    assert "OCR_MAX_PAGES" in res.note


def test_ocr_tidak_tersedia_pdf_scan_memberi_petunjuk(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "tesseract_status", lambda s: (False, "Program Tesseract tidak ditemukan. " + ocr.INSTALL_HINT, None))
    p = tmp_path / "scan.pdf"
    make_image().save(p)
    with pytest.raises(ConversionError, match="Tesseract"):
        convert_file(p)


def test_ocr_tidak_tersedia_gambar_memberi_petunjuk(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "tesseract_status", lambda s: (False, "Program Tesseract tidak ditemukan.", None))
    p = tmp_path / "foto.png"
    make_image().save(p)
    with pytest.raises(ConversionError, match="OCR"):
        convert_file(p)


def test_ocr_dimatikan(tmp_path, monkeypatch):
    monkeypatch.setenv("OCR_ENABLED", "false")
    get_settings.cache_clear()
    p = tmp_path / "foto.png"
    make_image().save(p)
    with pytest.raises(ConversionError, match="OCR_ENABLED"):
        convert_file(p)


def test_bahasa_ocr_tidak_terpasang_dilaporkan(monkeypatch):
    monkeypatch.setenv("OCR_LANGUAGES", "zzz")
    get_settings.cache_clear()
    ok, msg, lang = ocr.tesseract_status(get_settings())
    assert not ok and lang is None and "zzz" in msg


def test_pages_to_markdown_melewatkan_halaman_kosong():
    assert ocr.pages_to_markdown({2: "b", 1: "a", 3: "  "}) == "## Halaman 1\n\na\n\n## Halaman 2\n\nb"
