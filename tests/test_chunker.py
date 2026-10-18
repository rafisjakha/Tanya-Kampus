from app.rag.chunker import chunk_markdown

MD = """# Panduan TA

Pengantar singkat.

## Bab 3

### Persyaratan Sidang

1. Lulus semua mata kuliah wajib.
2. Menyerahkan naskah.

```python
# ini bukan heading
print("x")
```

### Template

Unduh template terbaru.
"""


def test_heading_path_dibawa_ke_chunk():
    chunks = chunk_markdown(MD, "Panduan TA")
    paths = [c.heading_path for c in chunks]
    assert "Panduan TA > Bab 3 > Persyaratan Sidang" in paths
    assert "Panduan TA > Bab 3 > Template" in paths
    # judul h1 yang sama dengan judul dokumen tidak diulang
    assert "Panduan TA > Panduan TA" not in paths


def test_kode_tidak_dianggap_heading():
    chunks = chunk_markdown(MD, "Panduan TA")
    joined = "\n".join(c.content for c in chunks)
    assert "# ini bukan heading" in joined
    assert not any(c.heading_path.endswith("ini bukan heading") for c in chunks)


def test_tabel_tetap_utuh():
    rows = "\n".join(f"| baris {i} | nilai {i} |" for i in range(5))
    md = f"# T\n\n## Data\n\n| a | b |\n|---|---|\n{rows}\n"
    chunks = chunk_markdown(md, "T", max_chars=2000)
    table_chunks = [c for c in chunks if "| a | b |" in c.content]
    assert len(table_chunks) == 1
    assert "baris 4" in table_chunks[0].content


def test_tabel_besar_dipecah_dengan_header_diulang():
    rows = "\n".join(f"| baris {i} | {'x' * 40} |" for i in range(40))
    md = f"# T\n\n## Data\n\n| a | b |\n|---|---|\n{rows}\n"
    chunks = chunk_markdown(md, "T", max_chars=500, overlap_chars=0)
    assert len(chunks) > 1
    assert all(c.content.startswith("| a | b |") for c in chunks)


def test_paragraf_panjang_dipecah_dan_tidak_melebihi_batas():
    para = " ".join(f"Kalimat nomor {i} yang cukup panjang untuk tes." for i in range(80))
    chunks = chunk_markdown(f"# D\n\n## S\n\n{para}\n", "D", max_chars=400, overlap_chars=0)
    assert len(chunks) > 3
    assert all(len(c.content) <= 400 for c in chunks)


def test_dokumen_tanpa_heading_tetap_menghasilkan_chunk():
    chunks = chunk_markdown("Hanya satu paragraf biasa tanpa heading.", "Catatan")
    assert len(chunks) == 1
    assert chunks[0].heading_path == "Catatan"


def test_markdown_kosong():
    assert chunk_markdown("   \n\n", "X") == []


def test_indeks_berurutan():
    chunks = chunk_markdown(MD, "Panduan TA")
    assert [c.index for c in chunks] == list(range(len(chunks)))
