"""OCR dengan Tesseract untuk PDF hasil scan dan file gambar.

Dependensi:
- Python : pytesseract, pypdfium2 (render halaman PDF), pillow
- Sistem : program Tesseract + data bahasa
    Ubuntu/Debian : sudo apt install tesseract-ocr tesseract-ocr-ind tesseract-ocr-eng
    macOS         : brew install tesseract tesseract-lang
    Windows       : installer UB Mannheim, pilih bahasa Indonesian saat instalasi

OCR hanya dipanggil bila perlu (PDF tanpa teks, atau gambar). Hasilnya SELALU perlu ditinjau admin:
OCR sering salah membaca angka, tanggal, dan tabel.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Settings

INSTALL_HINT = (
    "Pasang Tesseract: Ubuntu/Debian `sudo apt install tesseract-ocr tesseract-ocr-ind tesseract-ocr-eng`, "
    "macOS `brew install tesseract tesseract-lang`, Windows pakai installer UB Mannheim. "
    "Lalu `pip install pytesseract pypdfium2 pillow`."
)
LOW_CONFIDENCE = 60.0
SPARSE_PAGE_CHARS = 30  # halaman dengan teks lebih sedikit dari ini dianggap tanpa teks


class OCRError(RuntimeError):
    """Pesan dalam Bahasa Indonesia, aman ditampilkan ke admin."""


@dataclass
class OCRResult:
    pages: dict[int, str] = field(default_factory=dict)  # nomor halaman (mulai 1) -> teks
    note: str = ""
    mean_confidence: float | None = None


# --- ketersediaan ---------------------------------------------------------------------------------

def tesseract_status(settings: Settings) -> tuple[bool, str, str | None]:
    """Kembalikan (siap, pesan, bahasa_terpilih)."""
    if not settings.ocr_enabled:
        return False, "OCR dimatikan (OCR_ENABLED=false).", None
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False, "Paket pytesseract/pillow belum terpasang. " + INSTALL_HINT, None
    if not shutil.which("tesseract") and not _tesseract_cmd_set():
        return False, "Program Tesseract tidak ditemukan. " + INSTALL_HINT, None
    try:
        import pytesseract

        installed = set(pytesseract.get_languages(config=""))
    except Exception as exc:  # noqa: BLE001
        return False, f"Tesseract tidak bisa dijalankan: {exc}", None
    wanted = [lang for lang in settings.ocr_languages.split("+") if lang]
    chosen = [lang for lang in wanted if lang in installed]
    if not chosen:
        return (
            False,
            f"Data bahasa OCR '{settings.ocr_languages}' belum terpasang (terpasang: {', '.join(sorted(installed)) or 'tidak ada'}). "
            + INSTALL_HINT,
            None,
        )
    missing = [lang for lang in wanted if lang not in installed]
    msg = "siap"
    if missing:
        msg = f"siap, tetapi bahasa '{'+'.join(missing)}' belum terpasang sehingga hanya memakai '{'+'.join(chosen)}'"
    return True, msg, "+".join(chosen)


def _tesseract_cmd_set() -> bool:
    try:
        import pytesseract

        cmd = pytesseract.pytesseract.tesseract_cmd
        return bool(cmd) and cmd != "tesseract" and Path(cmd).exists()
    except Exception:  # noqa: BLE001
        return False


def require_ready(settings: Settings) -> tuple[str, str]:
    ok, msg, lang = tesseract_status(settings)
    if not ok or lang is None:
        raise OCRError(msg)
    return lang, msg


# --- inti OCR -------------------------------------------------------------------------------------

def _clean(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\f", "\n").splitlines()).strip()


def ocr_image(img, lang: str) -> tuple[str, float | None]:
    """OCR satu gambar PIL. Mengembalikan (teks, rata-rata keyakinan 0..100)."""
    import pytesseract
    from PIL import ImageOps

    gray = ImageOps.grayscale(img)
    data = pytesseract.image_to_data(gray, lang=lang, config="--psm 3", output_type=pytesseract.Output.DICT)

    paragraphs: dict[tuple[int, int], dict[int, list[str]]] = {}
    confs: list[float] = []
    for i, word in enumerate(data["text"]):
        word = (word or "").strip()
        if not word:
            continue
        key = (data["block_num"][i], data["par_num"][i])
        paragraphs.setdefault(key, {}).setdefault(data["line_num"][i], []).append(word)
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf >= 0:
            confs.append(conf)

    blocks = ["\n".join(" ".join(words) for _, words in sorted(lines.items())) for _, lines in sorted(paragraphs.items())]
    text = _clean("\n\n".join(blocks))
    return text, (sum(confs) / len(confs) if confs else None)


def _quality_note(mean_conf: float | None) -> str:
    if mean_conf is None:
        return ""
    if mean_conf < LOW_CONFIDENCE:
        return (
            f" Kualitas OCR rendah (rata-rata keyakinan {mean_conf:.0f}%): periksa dengan teliti "
            "atau pindai ulang dengan resolusi lebih tinggi."
        )
    return f" Rata-rata keyakinan OCR {mean_conf:.0f}%."


def ocr_image_file(path: Path, settings: Settings) -> OCRResult:
    lang, status = require_ready(settings)
    from PIL import Image

    try:
        with Image.open(path) as img:
            img.load()
            text, conf = ocr_image(img, lang)
    except OCRError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise OCRError(f"Gagal membaca gambar: {exc}") from exc
    note = f"Hasil OCR ({lang}) dari gambar. Periksa angka, tanggal, dan tabel sebelum di-index.{_quality_note(conf)}"
    if "belum terpasang" in status:
        note += f" Catatan: {status}."
    return OCRResult(pages={1: text}, note=note, mean_confidence=conf)


def pdf_page_stats(path: Path) -> tuple[int, list[int]] | None:
    """(jumlah_halaman, daftar_halaman_tanpa_teks mulai 1), atau None bila pypdfium2 tidak ada."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return None
    try:
        pdf = pdfium.PdfDocument(str(path))
    except Exception:  # noqa: BLE001
        return None
    try:
        sparse = []
        for i in range(len(pdf)):
            page = pdf[i]
            try:
                textpage = page.get_textpage()
                try:
                    chars = len(textpage.get_text_range().strip())
                finally:
                    textpage.close()
            finally:
                page.close()
            if chars < SPARSE_PAGE_CHARS:
                sparse.append(i + 1)
        return len(pdf), sparse
    finally:
        pdf.close()


def ocr_pdf(path: Path, settings: Settings, pages: list[int] | None = None) -> OCRResult:
    """OCR halaman PDF (semua, atau hanya nomor halaman di `pages`)."""
    lang, status = require_ready(settings)
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise OCRError("Paket pypdfium2 belum terpasang. " + INSTALL_HINT) from exc

    try:
        pdf = pdfium.PdfDocument(str(path))
    except Exception as exc:  # noqa: BLE001
        raise OCRError(f"PDF tidak bisa dibuka: {exc}") from exc

    result = OCRResult()
    confs: list[float] = []
    try:
        total = len(pdf)
        targets = pages if pages is not None else list(range(1, total + 1))
        truncated = len(targets) > settings.ocr_max_pages
        targets = targets[: settings.ocr_max_pages]
        scale = settings.ocr_dpi / 72
        for number in targets:
            page = pdf[number - 1]
            try:
                img = page.render(scale=scale).to_pil()
            finally:
                page.close()
            try:  # gambar 200 DPI satu halaman bisa belasan MB: lepas segera, jangan tunggu GC
                text, conf = ocr_image(img, lang)
            finally:
                img.close()
            if text:
                result.pages[number] = text
            if conf is not None:
                confs.append(conf)
    except OCRError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise OCRError(f"OCR gagal: {exc}") from exc
    finally:
        pdf.close()

    result.mean_confidence = sum(confs) / len(confs) if confs else None
    scope = "halaman tanpa teks" if pages is not None else "seluruh halaman"
    note = f"Hasil OCR ({lang}) untuk {scope} ({len(targets)} halaman). Periksa angka, tanggal, dan tabel sebelum di-index."
    note += _quality_note(result.mean_confidence)
    if truncated:
        note += f" OCR dibatasi {settings.ocr_max_pages} halaman pertama (OCR_MAX_PAGES); sisanya tidak terbaca."
    if "belum terpasang" in status:
        note += f" Catatan: {status}."
    result.note = note
    return result


def pages_to_markdown(pages: dict[int, str], suffix: str = "") -> str:
    """Satu bagian `## Halaman N` per halaman, supaya chunk dan sitasi bisa menunjuk halaman."""
    parts = [f"## Halaman {n}{suffix}\n\n{text}" for n, text in sorted(pages.items()) if text.strip()]
    return "\n\n".join(parts)
