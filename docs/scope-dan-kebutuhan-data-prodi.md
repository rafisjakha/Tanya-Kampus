# Tanya Kampus: Scope Layanan dan Kebutuhan Data dari Prodi TI

Bahan rapat dengan Kaprodi S1 Teknologi Informasi, Selasa, 27 Oktober 2026.
Disusun dari hasil rapat progres 23 Oktober 2026.

## 1. Arah baru dari rapat 23 Oktober

1. Informasi harian (jadwal kelas, ruang, mata kuliah) dan tutorial pembayaran UKT **bukan prioritas**. Mayoritas mahasiswa sudah bisa mencarinya sendiri.
2. Mahasiswa paling butuh bantuan **saat mengalami kendala**, misalnya pembayaran atau akun kampus. Bot perlu mengarahkan mereka ke unit yang tepat, seperti hotline Tel-U Jakarta atau Kemahasiswaan. Topik di luar perkuliahan reguler adalah yang paling sering dicari.
3. Topik yang paling sering dicari mahasiswa selama kuliah:
   - Magang
   - Kerja Praktik (KP)
   - MBKM, termasuk konsepnya
   - Innovillage
   - Template berbagai dokumen
   - Konversi TAK
4. Pertanyaan akademik diarahkan ke kontak Kemahasiswaan.
5. Tim perlu menetapkan scope dan menyampaikan dokumen yang dibutuhkan dari Prodi TI.

## 2. Usulan scope bot

| Kelompok | Contoh pertanyaan mahasiswa | Yang dilakukan bot |
|---|---|---|
| **Topik Prodi** (prioritas) | "Apa syarat daftar KP?", "Bagaimana konversi magang ke SKS?", "Kegiatan apa saja yang dapat poin TAK?" | Menjawab dari dokumen resmi Prodi, lengkap dengan sumbernya. Template yang diizinkan bisa langsung diunduh lewat bot. |
| **Kendala layanan** | "Pembayaran saya belum terverifikasi", "Tidak bisa login akun kampus" | Memberi langkah awal bila tercantum di dokumen, lalu **mengarahkan ke kontak unit yang menangani**, misalnya hotline Tel-U Jakarta atau layanan IT. |
| **Akademik** | "Nilai saya belum keluar", "Cara mengurus cuti" | Mengarahkan ke **kontak Kemahasiswaan**, ditambah informasi singkat bila ada di dokumen. |
| **Di luar scope** | Jadwal kelas harian, tutorial UKT, pertanyaan umum non-kampus | Menyampaikan dengan sopan bahwa itu di luar layanan bot, dan menyarankan kanal resmi yang sesuai. |

Bot **tidak pernah mengarang** syarat, tanggal, atau kontak. Bila informasinya tidak ada di dokumen, bot mengatakan belum menemukannya lalu memberi kontak rujukan.

## 3. Dokumen yang dibutuhkan dari Prodi TI

| Topik | Dokumen yang diminta | Pertanyaan yang ingin bisa dijawab |
|---|---|---|
| **Magang** | Pedoman magang Prodi, alur pendaftaran, syarat (minimal SKS/semester), surat pengantar, aturan konversi ke SKS | Syarat, alur, berkas, konversi SKS, siapa koordinatornya |
| **Kerja Praktik (KP)** | Pedoman KP, syarat, alur dari pengajuan sampai seminar, template laporan, form penilaian | Syarat, tahapan, format laporan, penilaian, tenggat |
| **MBKM** | Penjelasan skema yang masih berlaku di Prodi, pedoman konversi SKS, alur persetujuan, daftar program yang diakui | Apa itu MBKM, program apa yang bisa diikuti, cara konversi SKS, ke siapa minta persetujuan |
| **Innovillage** | Gambaran program, alur pendaftaran, timeline, aturan konversi ke SKS/TAK | Cara ikut, kapan pendaftaran, apa yang diperoleh |
| **Konversi TAK** | Pedoman TAK, tabel poin per jenis kegiatan, cara pengajuan, batas minimal poin | Kegiatan apa yang dapat poin, berapa poinnya, cara mengajukan |
| **Template dokumen** | Semua template yang boleh dipakai mahasiswa (surat, proposal, laporan, formulir) dalam format aslinya (DOCX/PDF) | "Template laporan KP di mana?", lalu bot mengirim filenya |
| **Kontak rujukan** | Direktori kontak resmi (lihat bagian 4) | Ke mana harus menghubungi saat ada kendala |

Ketentuan dokumen:

- **Format:** PDF berbasis teks atau DOCX lebih baik daripada hasil scan. Scan tetap bisa dibaca lewat OCR, tetapi perlu diperiksa ulang.
- **Versi:** kirim versi terbaru beserta **tanggal berlakunya**. Bila ada beberapa versi, bot mengutamakan yang terbaru.
- **Izin:** tandai dokumen yang **boleh dibagikan** ke mahasiswa. Isi dokumen dikirim ke penyedia LLM (Groq atau Gemini) saat menyusun jawaban, jadi **dokumen internal yang tidak boleh dipublikasikan sebaiknya tidak dimasukkan**.

## 4. Direktori kontak rujukan (mohon diisi Prodi)

| Unit | Menangani | Kanal resmi (WA/email/telepon/tautan) | Jam layanan | Boleh ditampilkan bot? |
|---|---|---|---|---|
| Hotline Tel-U Jakarta | Kendala umum layanan kampus | | | |
| Kemahasiswaan | Pertanyaan akademik dan kemahasiswaan | | | |
| Keuangan | Kendala pembayaran | | | |
| Layanan IT | Akun kampus, email, SSO, LMS | | | |
| Admin Prodi TI | Administrasi Prodi | | | |
| Koordinator Magang / KP | Magang dan KP | | | |
| PIC MBKM | MBKM dan konversi SKS | | | |
| PIC Innovillage | Innovillage | | | |
| PIC TAK | Konversi TAK | | | |

Direktori ini akan dimasukkan sebagai satu dokumen berkategori `kontak` di panel admin, jadi admin Prodi bisa memperbaruinya kapan saja tanpa mengubah kode. Format dan cara memasangnya ada di [template-direktori-kontak.md](template-direktori-kontak.md).

## 5. Data untuk mengetahui kebutuhan mahasiswa

1. **Pertanyaan yang paling sering masuk** ke admin Prodi atau Kemahasiswaan dalam 3 sampai 6 bulan terakhir, tanpa identitas mahasiswa. Data ini menjadi bahan uji akurasi bot.
2. **Izin survei singkat** ke mahasiswa TI, sekitar 5 menit. Usulan pertanyaannya ada di Lampiran.
3. Setelah bot berjalan, panel admin mencatat pertanyaan yang **tidak terjawab**. Tim akan melaporkannya ke Prodi secara berkala sebagai daftar dokumen yang masih kurang.

## 6. Hal yang perlu diputuskan dalam rapat

1. Untuk pertanyaan akademik, unit yang dituju **Kemahasiswaan** (sesuai rapat 23 Oktober) atau layanan akademik (BAA/LAA)?
2. Kontak mana saja yang **boleh ditampilkan** oleh bot, misalnya nomor WhatsApp pribadi atau hanya kanal resmi?
3. Siapa **PIC Prodi** untuk mengirim dan memperbarui dokumen, dan seberapa sering dokumen diperbarui (setiap semester atau setiap ada perubahan)?
4. Apa **nama dan skema MBKM** yang masih berlaku di Prodi saat ini?
5. Bila dokumen datang bertahap, **topik mana yang didahulukan**?
6. Fitur pembacaan jadwal kuliah yang sudah ada: **dipertahankan** sebagai fitur tambahan atau **dinonaktifkan**?

## 7. Rencana tim setelah data diterima

1. Menyesuaikan fokus bot ke topik di atas: kategori dokumen, teks sambutan, dan gaya jawaban.
2. Menambahkan direktori kontak rujukan, sehingga kendala dan pertanyaan akademik diarahkan ke unit yang tepat.
3. Memasukkan dokumen dari Prodi, memeriksa hasil konversinya, lalu meng-index.
4. Menguji bot dengan pertanyaan nyata dari bagian 5, lalu melaporkan hasilnya ke Prodi.

## Lampiran: usulan pertanyaan survei mahasiswa

1. Angkatan dan status (aktif/cuti).
2. Topik apa yang paling sering kamu cari informasinya? (pilih maks. 3: Magang, KP, MBKM, Innovillage, Konversi TAK, Template dokumen, Tugas akhir, Lainnya)
3. Kendala apa yang paling sering kamu alami? (Pembayaran, Akun kampus, Administrasi akademik, Lainnya)
4. Biasanya ke mana kamu bertanya saat ada kendala, dan berapa lama sampai mendapat jawaban?
5. Pertanyaan apa yang paling sulit kamu temukan jawabannya? (isian bebas)
