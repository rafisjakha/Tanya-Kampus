"""Pembaca khusus PDF jadwal berbentuk grid (hari x ruangan x jam).

markitdown hanya membaca teks dari atas ke bawah, jadi hubungan antara jam, ruangan, mata kuliah, dan dosen
hilang pada jadwal yang selnya digabung. Di sini posisi (koordinat) tiap sel dipakai:

- kolom (ruangan)  : dari sel header kolom
- jam              : label jam di kolom kiri yang berada di dalam tinggi sel
- isi sel          : kata-kata yang berada di dalam kotak berwarna

Hasilnya satu baris per kelas, tiap baris berdiri sendiri (memuat hari, jam, ruangan) supaya tetap bermakna
setelah dipotong menjadi chunk. Bila PDF tidak tampak seperti jadwal grid, fungsi mengembalikan None dan
konversi biasa dipakai.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

DAYS = ("SENIN", "SELASA", "RABU", "KAMIS", "JUMAT", "SABTU", "MINGGU")
TIME_RE = re.compile(r"^\d{2}\.\d{2}$")
CLASS_CODE_RE = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+){2,}$")
LECTURER_CODE_RE = re.compile(r"^[A-Z]{3}$")
# dua tabel dosen berdampingan tergabung dalam satu baris teks: "1 NAMA ... ZII 14 NAMA ... FHH"
LECTURER_ROW_RE = re.compile(r"(?<!\S)\d{1,2}\s+(?P<name>[A-Z][^\n]*?)\s+(?P<code>[A-Z]{3})(?=\s+\d{1,2}\s+[A-Z]|\s*$)")
FOOTER_RE = re.compile(r"^(Main Campus|Jakarta Campus|Surabaya Campus|Purwokerto Campus|www\.)", re.I)
PART_CHARS = 1200  # ukuran bagian per hari; di bawah batas chunk supaya satu kelas tidak terpotong
HEADER_GRAY = 0.749  # warna sel header (hari/ruangan)


def _ok_color(color) -> bool:
    return color is not None and color != HEADER_GRAY and color != (1, 1, 1) and color != 1


def _blocks(page) -> list[dict]:
    """Kotak sel terluar yang berwarna (tanpa header), tanpa duplikat."""
    rects = [r for r in page.rects
             if r["width"] > 30 and r["height"] > 10 and r.get("fill") and _ok_color(r.get("non_stroking_color"))]

    def inside(a, b):
        return (a is not b and a["x0"] >= b["x0"] - 1 and a["x1"] <= b["x1"] + 1
                and a["top"] >= b["top"] - 1 and a["bottom"] <= b["bottom"] + 1)

    out, seen = [], set()
    for r in rects:
        if any(inside(r, o) for o in rects):
            continue
        key = tuple(round(r[k]) for k in ("x0", "x1", "top", "bottom"))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _page_grid(page):
    """Kembalikan (hari, kolom, label_jam, blok) bila halaman ini grid jadwal, selain itu None."""
    words = page.extract_words()
    day = next((w for w in words if w["text"] in DAYS and w["x0"] < 100), None)
    if not day:
        return None
    labels = [w for w in words if TIME_RE.match(w["text"]) and w["x0"] < day["x1"] + 5]
    if len(labels) < 3:
        return None
    # kolom: sel header abu-abu terkecil (baris nama ruangan) di bawah baris hari
    headers = [r for r in page.rects
               if r.get("non_stroking_color") == HEADER_GRAY and r["top"] >= day["top"] and r["width"] < 160
               and r["x0"] > day["x1"] - 2]
    if not headers:
        return None
    min_h = min(r["height"] for r in headers)
    cols = {}
    for r in headers:
        if r["height"] <= min_h + 2:
            cols[(round(r["x0"]), round(r["x1"]))] = r
    columns = []
    for (x0, x1), r in sorted(cols.items()):
        text = " ".join(w["text"] for w in words
                        if x0 - 1 <= (w["x0"] + w["x1"]) / 2 <= x1 + 1 and r["top"] - 1 <= w["top"] <= r["bottom"])
        if text:
            columns.append((x0, x1, text))
    if len(columns) < 2:
        return None
    return day["text"].title(), columns, sorted(labels, key=lambda w: w["top"]), _blocks(page)


def _parse_cell(words: list[dict]) -> dict:
    """Pecah isi sel menjadi mata kuliah, kode dosen, dan kode kelas."""
    words = sorted(words, key=lambda w: (round(w["top"] / 3), w["x0"]))
    tokens = [w["text"] for w in words]
    idx = [i for i, t in enumerate(tokens) if CLASS_CODE_RE.match(t) and any(c.isdigit() for c in t)]
    class_code = tokens.pop(idx[-1]) if idx else None
    lecturer = None
    if len(tokens) >= 2 and LECTURER_CODE_RE.match(tokens[-1]):
        lecturer = tokens.pop()
    course = " ".join(tokens).strip()
    practical = course.startswith("(P)")
    if practical:
        course = course[3:].strip()
    return {"course": course, "lecturer": lecturer, "class_code": class_code, "practical": practical}


def _lecturers(pdf) -> dict[str, str]:
    result = {}
    for page in pdf.pages:
        text = page.extract_text() or ""
        if "KODE DOSEN" not in text.upper():
            continue
        for line in text.splitlines():
            for m in LECTURER_ROW_RE.finditer(line.strip()):
                result[m["code"]] = m["name"].strip()
    return result


def _title(page, grid_top: float) -> list[str]:
    lines = []
    for line in (page.within_bbox((0, 0, page.width, grid_top)).extract_text() or "").splitlines():
        line = line.strip()
        if line and not FOOTER_RE.match(line):
            lines.append(line)
    return lines


def convert_schedule_pdf(path: Path):
    """Markdown jadwal terstruktur, atau None bila PDF bukan jadwal grid. Mengembalikan (markdown, catatan)."""
    try:
        import pdfplumber
    except ImportError:  # pragma: no cover
        return None

    with pdfplumber.open(str(path)) as pdf:
        grids = []
        for page in pdf.pages:
            grid = _page_grid(page)
            if grid:
                grids.append((page, grid))
        if not grids:
            return None

        lecturers = _lecturers(pdf)
        title_lines = _title(grids[0][0], min(w["top"] for w in grids[0][0].extract_words() if w["text"] in DAYS and w["x0"] < 100))
        extra = []  # halaman non-grid selain daftar dosen (mis. catatan berlakunya jadwal)
        grid_pages = {id(p) for p, _ in grids}
        for page in pdf.pages:
            text = page.extract_text() or ""
            if id(page) in grid_pages or "KODE DOSEN" in text.upper():
                continue
            extra += [ln.strip() for ln in text.splitlines() if ln.strip() and not FOOTER_RE.match(ln.strip())]

        entries = []  # (hari, mulai, selesai, ruang, dict)
        problems = []
        for page, (day, columns, labels, blocks) in grids:
            words = page.extract_words()
            code_tokens = sum(1 for w in words if CLASS_CODE_RE.match(w["text"]) and any(c.isdigit() for c in w["text"])
                              and w["top"] > labels[0]["top"] - 12)
            found = 0
            centers = [((w["top"] + w["bottom"]) / 2, w["text"]) for w in labels]
            for b in blocks:
                col = next((c for c in columns if c[0] - 2 <= (b["x0"] + b["x1"]) / 2 <= c[1] + 2), None)
                rows = [t for cy, t in centers if b["top"] < cy < b["bottom"]]
                inner = [w for w in words
                         if b["x0"] - 1 <= (w["x0"] + w["x1"]) / 2 <= b["x1"] + 1
                         and b["top"] - 1 <= (w["top"] + w["bottom"]) / 2 <= b["bottom"] + 1]
                if not col or not rows or not inner:
                    continue
                cell = _parse_cell(inner)
                if cell["class_code"]:
                    found += 1
                entries.append((day, rows[0], rows[-1], col[2], cell))
            if found != code_tokens:
                problems.append(f"{day}: {code_tokens} kode kelas di halaman, {found} terbaca")

    order = {d.title(): i for i, d in enumerate(DAYS)}
    entries.sort(key=lambda e: (order.get(e[0], 9), e[1], e[3]))

    out = []
    out.append("# " + (title_lines[0] if title_lines else "Jadwal Perkuliahan"))
    out.append("")
    out += title_lines[1:]
    out += ["", "Catatan: angka jam adalah label baris pada tabel jadwal (jam mulai tiap slot). "
            "Jam selesai tidak tertulis di dokumen. Baris kelas di bawah ini berdiri sendiri, memuat hari, jam, dan ruangan.", ""]

    by_day = defaultdict(list)
    for e in entries:
        by_day[e[0]].append(e)
    for day in sorted(by_day, key=lambda d: order.get(d, 9)):
        lines = []
        for _, start, end, room, c in by_day[day]:
            jam = start if start == end else f"{start} sampai {end}"
            kind = "Praktikum" if c["practical"] else "Kuliah"
            line = f"- {kind} {c['course']} | Hari {day} | Jam {jam} | Ruang {room}"
            if c["lecturer"]:
                name = lecturers.get(c["lecturer"])
                line += f" | Dosen {name + ' (' + c['lecturer'] + ')' if name else 'kode ' + c['lecturer']}"
            if c["class_code"]:
                line += f" | Kelas {c['class_code']}"
            lines.append((start, line))
        # bagi per bagian di batas baris (tidak memotong satu kelas), judul memuat rentang jam mulai
        part, size = [], 0
        for i, (start, line) in enumerate(lines):
            part.append((start, line))
            size += len(line) + 1
            if size >= PART_CHARS or i == len(lines) - 1:
                first, last = part[0][0], part[-1][0]
                span = first if first == last else f"{first} sampai {last}"
                out += [f"## Jadwal hari {day}, kelas mulai jam {span}", "", *[ln for _, ln in part], ""]
                part, size = [], 0

    if lecturers:
        out += ["## Daftar kode dosen", ""]
        out += [f"- {code}: {name}" for code, name in sorted(lecturers.items())]
        out.append("")
    if extra:
        out += ["## Keterangan", "", *extra, ""]

    note = None
    if problems:
        note = "Pembacaan jadwal mungkin tidak lengkap (" + "; ".join(problems) + "). Periksa hasilnya terhadap PDF."
    return "\n".join(out), note
