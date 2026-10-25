"""Pembersihan teks jawaban LLM sebelum ditampilkan.

Model sering menulis Markdown (tebal, judul, bullet bintang) walau prompt melarangnya, padahal Telegram dan
kotak jawaban panel admin menampilkan teks biasa. Beberapa model juga memakai tanda hubung khusus (U+2011) yang
membuat kode kelas atau jam tidak cocok saat disalin atau dicari.
"""
from __future__ import annotations

import re

_HYPHENS = dict.fromkeys(map(ord, "‐‑‒⁃﹣－"), "-")
_BOLD_RE = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.S)
_CODE_RE = re.compile(r"`([^`\n]+)`")
_HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.M)
_STAR_BULLET_RE = re.compile(r"^([ \t]*)[*+][ \t]+", re.M)
_TRAILING_RE = re.compile(r"[ \t]+$", re.M)
_FULLWIDTH_CITE_RE = re.compile(r"[【［](\d+)[】］]")  # sitasi gaya Cina/Jepang: 【1】 -> [1]


def clean_answer(text: str) -> str:
    text = text.translate(_HYPHENS)
    text = _FULLWIDTH_CITE_RE.sub(r"[\1]", text)
    text = _BOLD_RE.sub(r"\2", text)
    text = _CODE_RE.sub(r"\1", text)
    text = _HEADING_RE.sub("", text)
    text = _STAR_BULLET_RE.sub(r"\1- ", text)
    text = _TRAILING_RE.sub("", text)
    return text.strip()
