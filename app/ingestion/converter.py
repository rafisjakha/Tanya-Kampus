"""Konversi berbagai sumber ke markdown (format tengah untuk seluruh pipeline).

- File PDF/DOCX/PPTX/XLSX/HTML/CSV : markitdown (Microsoft, open source)
- File MD/TXT                      : dibaca apa adanya
- URL                              : trafilatura (ekstrak konten utama halaman ke markdown)

- PDF hasil scan dan gambar (PNG/JPG/TIFF/BMP): OCR Tesseract (lihat ocr.py)

PDF campuran (sebagian halaman teks, sebagian scan): halaman tanpa teks di-OCR dan ditambahkan di akhir
sebagai bagian "Halaman N (hasil OCR)". Bila OCR tidak tersedia, hasil teks tetap dipakai dan catatan
peringatan dibuat supaya admin tahu ada halaman yang tidak terbaca.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from ..config import get_settings
from . import ocr, schedule

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}
SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm", ".csv", ".md", ".markdown", ".txt",
} | IMAGE_EXTENSIONS
MIN_TEXT_CHARS = 20
SCANNED_RATIO = 0.5  # bila >= separuh halaman PDF tanpa teks, seluruh PDF di-OCR


@dataclass
class ConversionResult:
    markdown: str
    note: str | None = None


class ConversionError(ValueError):
    """Pesan dalam Bahasa Indonesia, aman ditampilkan ke admin."""


_markitdown = None


def _get_markitdown():
    global _markitdown
    if _markitdown is None:
        try:
            from markitdown import MarkItDown
        except ImportError as exc:  # pragma: no cover
            raise ConversionError("markitdown belum terpasang. Jalankan: pip install -r requirements.txt") from exc
        _markitdown = MarkItDown()
    return _markitdown


def normalize_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = text.replace(" ", " ")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _markitdown_text(path: Path) -> str:
    try:
        return normalize_markdown(_get_markitdown().convert(str(path)).text_content or "")
    except ConversionError:
        raise
    except Exception as exc:  # noqa: BLE001 - parser pihak ketiga melempar beragam error
        raise ConversionError(f"Gagal membaca file: {exc}") from exc


def _enough(text: str) -> bool:
    return len(text.strip()) >= MIN_TEXT_CHARS


def _convert_schedule(path: Path) -> ConversionResult | None:
    """PDF jadwal berbentuk grid dibaca per sel (lihat schedule.py); None bila bukan jadwal grid."""
    try:
        res = schedule.convert_schedule_pdf(path)
    except Exception:  # noqa: BLE001 - parser eksperimental: jangan gagalkan konversi biasa
        return None
    if not res or not _enough(res[0]):
        return None
    return ConversionResult(normalize_markdown(res[0]), res[1] or "Jadwal dibaca per sel (hari, jam, ruangan, dosen).")


def _convert_pdf(path: Path) -> ConversionResult:
    settings = get_settings()
    grid = _convert_schedule(path)
    if grid:
        return grid
    try:
        text = _markitdown_text(path)
    except ConversionError:
        text = ""  # PDF rusak atau tanpa teks: biarkan OCR mencoba
    stats = ocr.pdf_page_stats(path) if settings.ocr_enabled else None
    total, sparse = stats if stats else (0, [])
    mostly_scanned = (not _enough(text)) or (total > 0 and len(sparse) / total >= SCANNED_RATIO)

    if mostly_scanned:
        try:
            res = ocr.ocr_pdf(path, settings)
        except ocr.OCRError as exc:
            if _enough(text):  # teks ada walau sedikit: pakai itu, tapi beri peringatan
                return ConversionResult(
                    text, f"Banyak halaman tampak hasil scan tetapi OCR tidak tersedia: {exc} Isi mungkin tidak lengkap."
                )
            raise ConversionError(
                f"PDF ini tampak hasil scan (tidak ada teks) dan OCR tidak tersedia. {exc}"
            ) from exc
        md = normalize_markdown(ocr.pages_to_markdown(res.pages))
        if not _enough(md):
            raise ConversionError("OCR tidak menemukan teks yang terbaca di dokumen ini.")
        return ConversionResult(md, res.note)

    if sparse:  # campuran: OCR halaman tanpa teks dan tambahkan di akhir
        try:
            res = ocr.ocr_pdf(path, settings, pages=sparse)
        except ocr.OCRError as exc:
            nums = ", ".join(map(str, sparse[:15])) + (" dan lainnya" if len(sparse) > 15 else "")
            return ConversionResult(
                text, f"Halaman {nums} tidak punya teks (kemungkinan gambar/scan) dan tidak terbaca: {exc}"
            )
        extra = ocr.pages_to_markdown(res.pages, suffix=" (hasil OCR)")
        if extra:
            text = normalize_markdown(text + "\n\n" + extra)
            return ConversionResult(text, res.note + " Bagian OCR ditambahkan di akhir dokumen.")
    return ConversionResult(text)


def _convert_image(path: Path) -> ConversionResult:
    settings = get_settings()
    try:
        res = ocr.ocr_image_file(path, settings)
    except ocr.OCRError as exc:
        raise ConversionError(f"File gambar membutuhkan OCR. {exc}") from exc
    md = normalize_markdown(res.pages.get(1, ""))
    if not _enough(md):
        raise ConversionError("OCR tidak menemukan teks yang terbaca di gambar ini.")
    return ConversionResult(md, res.note)


def convert_file(path: Path) -> ConversionResult:
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ConversionError(
            f"Format {ext or '(tanpa ekstensi)'} belum didukung. Didukung: "
            + ", ".join(sorted(SUPPORTED_EXTENSIONS))
        )
    try:
        if ext == ".pdf":
            return _convert_pdf(path)
        if ext in IMAGE_EXTENSIONS:
            return _convert_image(path)
        if ext in {".md", ".markdown", ".txt"}:
            text = normalize_markdown(_read_text(path))
        else:
            text = _markitdown_text(path)
    except ConversionError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ConversionError(f"Gagal membaca file: {exc}") from exc
    if not _enough(text):
        raise ConversionError("Tidak ada teks yang terbaca di file ini.")
    return ConversionResult(text)


def file_to_markdown(path: Path) -> str:
    """Versi sederhana: hanya markdown, catatan konversi dibuang."""
    return convert_file(path).markdown


# --- URL ----------------------------------------------------------------------------------------

def assert_public_url(url: str) -> None:
    """Tolak URL ke jaringan internal (SSRF dasar). Hanya http/https."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ConversionError("URL harus diawali http:// atau https://")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ConversionError(f"Domain tidak ditemukan: {parsed.hostname}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ConversionError("URL ke alamat internal/lokal tidak diizinkan.")


def url_to_markdown(url: str) -> tuple[str, str | None]:
    """Kembalikan (markdown, judul_halaman)."""
    assert_public_url(url)
    try:
        import trafilatura
    except ImportError as exc:  # pragma: no cover
        raise ConversionError("trafilatura belum terpasang. Jalankan: pip install -r requirements.txt") from exc

    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise ConversionError("Halaman tidak bisa diunduh (diblokir, timeout, atau URL salah).")
    text = trafilatura.extract(
        downloaded,
        output_format="markdown",
        include_tables=True,
        include_links=False,
        include_comments=False,
        favor_recall=True,
    )
    if not text or len(text.strip()) < MIN_TEXT_CHARS:
        raise ConversionError(
            "Konten utama halaman tidak terbaca. Halaman yang bergantung pada JavaScript "
            "belum didukung; salin isinya lewat menu 'Tulis manual'."
        )
    title = None
    try:
        meta = trafilatura.extract_metadata(downloaded)
        title = meta.title if meta and meta.title else None
    except Exception:  # noqa: BLE001
        pass
    return normalize_markdown(text), title
