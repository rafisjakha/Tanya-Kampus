"""Direktori kontak (dokumen kategori 'kontak') ikut dikirim ke LLM untuk rujukan kendala dan urusan akademik."""
BOT = {"X-API-Key": "bot-key-tes"}

DIREKTORI = """# Direktori Kontak Layanan

## Hotline Tel-U Jakarta
- Menangani: kendala umum layanan kampus
- Kontak: WhatsApp 0812-1111-2222

## Kemahasiswaan
- Menangani: urusan akademik
- Kontak: kemahasiswaan@contoh.ac.id
"""


def pasang_direktori(client, auth, isi=DIREKTORI) -> int:
    r = client.post("/api/documents/manual", headers=auth,
                    json={"title": "Direktori Kontak Layanan", "markdown": isi, "category": "kontak"})
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]
    assert client.post(f"/api/documents/{doc_id}/index", headers=auth).status_code == 200
    return doc_id


def tanya(client, q):
    return client.post("/api/ask", headers=BOT, json={"question": q}).json()


def test_tanpa_direktori_prompt_tidak_memuat_blok_kontak(client, indexed_doc, stub_llm):
    tanya(client, "Kapan batas pengajuan cuti akademik?")
    assert "DIREKTORI KONTAK" not in stub_llm.last_prompt


def test_direktori_dikirim_bersama_konteks_jawaban(client, auth, indexed_doc, stub_llm):
    pasang_direktori(client, auth)
    body = tanya(client, "Kapan batas pengajuan cuti akademik?")
    assert body["status"] == "answered"
    assert "KONTEKS:" in stub_llm.last_prompt
    assert "DIREKTORI KONTAK:" in stub_llm.last_prompt and "0812-1111-2222" in stub_llm.last_prompt


def test_direktori_dikirim_saat_tidak_ditemukan(client, auth, indexed_doc, stub_llm):
    pasang_direktori(client, auth)
    stub_llm.reply = "TIDAK_DITEMUKAN: Maaf, soal itu belum ada di dokumen. Hubungi Hotline Tel-U Jakarta di WhatsApp 0812-1111-2222 ya."
    body = tanya(client, "Pembayaran UKT saya belum terverifikasi padahal sudah transfer kemarin")
    assert body["status"] == "not_found"
    assert "0812-1111-2222" in body["answer"]
    assert "DIREKTORI KONTAK:" in stub_llm.last_prompt and "PESAN:" in stub_llm.last_prompt


def test_direktori_diperbarui_setelah_index_ulang(client, auth, indexed_doc, stub_llm):
    doc_id = pasang_direktori(client, auth)
    tanya(client, "Kapan batas pengajuan cuti akademik?")
    assert "0812-1111-2222" in stub_llm.last_prompt

    baru = DIREKTORI.replace("0812-1111-2222", "0813-9999-8888")
    client.put(f"/api/documents/{doc_id}", headers=auth, json={"markdown": baru})
    tanya(client, "Apa syarat cuti akademik?")
    assert "0812-1111-2222" in stub_llm.last_prompt  # belum di-index ulang: direktori lama tetap dipakai

    client.post(f"/api/documents/{doc_id}/index", headers=auth)
    tanya(client, "Berapa lama cuti akademik boleh diambil?")
    assert "0813-9999-8888" in stub_llm.last_prompt and "0812-1111-2222" not in stub_llm.last_prompt


def test_direktori_dibatasi_panjangnya(client, auth, indexed_doc, stub_llm):
    from app.rag.pipeline import DIRECTORY_MAX_CHARS

    panjang = DIREKTORI + "\n\n## Unit Lain\n\n" + ("- Kontak cadangan unit lain.\n" * 400)
    pasang_direktori(client, auth, panjang)
    tanya(client, "Kapan batas pengajuan cuti akademik?")
    blok = stub_llm.last_prompt.split("DIREKTORI KONTAK:\n", 1)[1].split("\n\nPERTANYAAN:", 1)[0]
    assert len(blok) <= DIRECTORY_MAX_CHARS


def test_cerita_kendala_panjang_tetap_sampai_ke_llm(client, auth, indexed_doc, stub_llm):
    pasang_direktori(client, auth)
    stub_llm.reply = "TIDAK_DITEMUKAN: Maaf ya, coba hubungi Hotline Tel-U Jakarta."
    cerita = ("Halo kak saya mau tanya, dari kemarin saya tidak bisa login ke akun kampus padahal password sudah "
              "benar, sudah coba reset juga tetap gagal, besok ada tugas yang harus dikumpulkan lewat LMS, "
              "saya harus menghubungi siapa ya?")
    assert 30 < len(cerita.split()) <= 60
    body = tanya(client, cerita)
    assert stub_llm.calls >= 1 and "Hotline" in body["answer"]
