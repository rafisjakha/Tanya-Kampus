# Template Direktori Kontak

Direktori kontak adalah satu dokumen yang **selalu dikirim ke LLM** di setiap pertanyaan. Bot memakainya untuk mengarahkan mahasiswa ke unit yang tepat:

- **Kendala layanan** (pembayaran, akun kampus, fasilitas) diarahkan ke unit yang menanganinya.
- **Urusan akademik** diarahkan ke Layanan Akademik, dan **kegiatan kemahasiswaan** (UKM, lomba, minat bakat) ke Kemahasiswaan. Pembagian ini mengikuti FAQ resmi Telkom University Jakarta.
- **Bila tidak jelas harus ke mana**, diarahkan ke hotline umum.

Versi terisi dari sumber resmi sudah tersedia di `data/knowledge/direktori-kontak-tel-u-jakarta.md`. Template di bawah dipakai bila Prodi ingin menyusun ulang.

Bot hanya menyalin kontak yang tertulis di sini dan tidak pernah mengarangnya.

## Cara memasang

1. Buka panel admin, lalu pilih **Tulis manual**.
2. Isi judul `Direktori Kontak Layanan`, pilih kategori **`kontak`**, lalu isi tanggal berlaku.
3. Salin isi di bawah garis ke kolom isi, ganti semua tanda `<...>` dengan data resmi, dan hapus unit yang tidak dipakai.
4. Klik **Simpan & Index**. Perubahan langsung dipakai bot setelah di-index ulang.

Ketentuan:

- **Hanya kanal resmi** yang boleh ditampilkan ke mahasiswa.
- **Jangan meng-index sebelum semua `<...>` terisi.** Bot akan menyalin teks itu apa adanya.
- **Batas panjang direktori 3.000 karakter.** Bagian setelah batas itu tidak terbaca. Tulis ringkas.
- **Tulis "menangani" dengan kata-kata yang dipakai mahasiswa** (mis. "lupa password", "pembayaran belum terverifikasi"), supaya LLM mudah mencocokkan pertanyaan dengan unit.

---

# Direktori Kontak Layanan

## Hotline Tel-U Jakarta
- Menangani: kendala umum layanan kampus, informasi umum, pertanyaan yang belum jelas harus ke unit mana
- Kontak: <WhatsApp / telepon / email>
- Jam layanan: <hari dan jam>

## Kemahasiswaan
- Menangani: urusan akademik dan kemahasiswaan, <rincian>
- Kontak: <WhatsApp / telepon / email>
- Jam layanan: <hari dan jam>

## Keuangan
- Menangani: pembayaran belum terverifikasi, tagihan, <rincian>
- Kontak: <kanal resmi>
- Jam layanan: <hari dan jam>

## Layanan IT
- Menangani: lupa password, akun kampus terkunci, email kampus, SSO, LMS
- Kontak: <kanal resmi>
- Jam layanan: <hari dan jam>

## Admin Prodi S1 Teknologi Informasi
- Menangani: administrasi Prodi, surat pengantar, <rincian>
- Kontak: <kanal resmi>
- Jam layanan: <hari dan jam>

## Koordinator Magang dan Kerja Praktik
- Menangani: pendaftaran dan persetujuan magang/KP, konversi SKS magang
- Kontak: <kanal resmi>

## PIC MBKM
- Menangani: program MBKM, persetujuan, konversi SKS
- Kontak: <kanal resmi>

## PIC Innovillage
- Menangani: pendaftaran dan informasi Innovillage
- Kontak: <kanal resmi>

## PIC TAK
- Menangani: pengajuan dan konversi poin TAK
- Kontak: <kanal resmi>
