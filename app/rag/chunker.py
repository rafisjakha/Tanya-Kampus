"""Chunking markdown berbasis heading.

Aturan:
- Dokumen dipecah per heading. Jalur heading ("Judul > Bab 3 > Persyaratan Sidang") dibawa
  ke setiap chunk supaya konteks tidak hilang.
- Satu tabel tetap utuh dalam satu chunk. Tabel yang melebihi batas dipecah per baris dan
  baris header diulang di tiap potongan.
- Blok kode (```) diperlakukan sebagai satu blok, dan '#' di dalamnya bukan heading.
- Paragraf digabung sampai batas `max_chars`; paragraf terakhir chunk sebelumnya diulang
  sebagai overlap bila cukup pendek.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Chunk:
    index: int
    heading_path: str
    content: str

    @property
    def embed_text(self) -> str:
        """Teks yang di-embed: jalur heading + isi."""
        return f"{self.heading_path}\n\n{self.content}" if self.heading_path else self.content


# --- parsing ----------------------------------------------------------------------------------

def _sections(markdown: str, doc_title: str) -> list[tuple[str, list[str]]]:
    """Kembalikan list (heading_path, baris_isi) berurutan."""
    stack: list[tuple[int, str]] = []
    sections: list[tuple[str, list[str]]] = []
    current_lines: list[str] = []
    current_path = doc_title
    in_fence = False

    def flush():
        if any(line.strip() for line in current_lines):
            sections.append((current_path, list(current_lines)))

    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            current_lines.append(line)
            continue
        m = None if in_fence else _HEADING_RE.match(line)
        if m:
            flush()
            current_lines = []
            level, text = len(m.group(1)), m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text))
            parts = [t for _, t in stack]
            if parts and parts[0].casefold() == doc_title.casefold():
                parts = parts[1:]
            current_path = " > ".join([doc_title] + parts) if doc_title else " > ".join(parts)
        else:
            current_lines.append(line)
    flush()
    return sections


def _blocks(lines: list[str]) -> list[str]:
    """Pecah baris menjadi blok: paragraf, tabel, atau blok kode."""
    blocks: list[str] = []
    buf: list[str] = []
    mode = "text"  # text | table | code

    def flush():
        nonlocal buf
        text = "\n".join(buf).strip("\n")
        if text.strip():
            blocks.append(text)
        buf = []

    for line in lines:
        stripped = line.strip()
        if mode == "code":
            buf.append(line)
            if stripped.startswith("```"):
                flush()
                mode = "text"
            continue
        if stripped.startswith("```"):
            flush()
            buf.append(line)
            mode = "code"
            continue
        is_table_row = stripped.startswith("|")
        if is_table_row and mode != "table":
            flush()
            mode = "table"
        elif not is_table_row and mode == "table":
            flush()
            mode = "text"
        if mode == "text" and not stripped:
            flush()
            continue
        buf.append(line)
    flush()
    return blocks


def _split_oversize(block: str, max_chars: int) -> list[str]:
    if len(block) <= max_chars:
        return [block]
    lines = block.splitlines()
    if lines and lines[0].lstrip().startswith("|"):
        return _split_table(lines, max_chars)
    pieces: list[str] = []
    cur = ""
    units: list[str] = []
    for line in lines:
        units.extend(s for s in _SENTENCE_RE.split(line) if s)
    for unit in units:
        while len(unit) > max_chars:  # satu kalimat sangat panjang: potong paksa
            if cur:
                pieces.append(cur.strip())
                cur = ""
            pieces.append(unit[:max_chars])
            unit = unit[max_chars:]
        if cur and len(cur) + len(unit) + 1 > max_chars:
            pieces.append(cur.strip())
            cur = unit
        else:
            cur = f"{cur}\n{unit}" if cur else unit
    if cur.strip():
        pieces.append(cur.strip())
    return pieces


def _split_table(lines: list[str], max_chars: int) -> list[str]:
    header = lines[:2] if len(lines) > 2 and set(lines[1].replace("|", "").strip()) <= set("-: ") else lines[:1]
    body = lines[len(header):]
    head_text = "\n".join(header)
    pieces: list[str] = []
    cur: list[str] = []
    cur_len = len(head_text)
    for row in body:
        if cur and cur_len + len(row) + 1 > max_chars:
            pieces.append(head_text + "\n" + "\n".join(cur))
            cur, cur_len = [], len(head_text)
        cur.append(row)
        cur_len += len(row) + 1
    if cur:
        pieces.append(head_text + "\n" + "\n".join(cur))
    return pieces or ["\n".join(lines)]


def _pack(blocks: list[str], max_chars: int, overlap_chars: int) -> list[str]:
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for block in blocks:
        for piece in _split_oversize(block, max_chars):
            add = len(piece) + 2
            if cur and cur_len + add > max_chars:
                chunks.append("\n\n".join(cur))
                tail = cur[-1] if len(cur[-1]) <= overlap_chars else None
                cur = [tail] if tail else []
                cur_len = sum(len(x) + 2 for x in cur)
            cur.append(piece)
            cur_len += add
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


# --- API publik ----------------------------------------------------------------------------------

def chunk_markdown(
    markdown: str,
    doc_title: str = "",
    max_chars: int = 1800,
    overlap_chars: int = 200,
) -> list[Chunk]:
    result: list[Chunk] = []
    for path, lines in _sections(markdown, doc_title):
        for text in _pack(_blocks(lines), max_chars, overlap_chars):
            text = text.strip()
            if text:
                result.append(Chunk(index=len(result), heading_path=path, content=text))
    return result
