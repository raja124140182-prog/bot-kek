# Hermes Bot - AI Lokal Anda 🤖

Asisten AI pribadi yang berjalan **100% gratis** di laptop Anda - tanpa akun, tanpa langganan.

## Pakai di Komputer Lain (5 langkah)

Bot ini lokal dan gratis, tetapi **belum bisa langsung dipakai orang lain tanpa menyiapkan
dependensi dan login sendiri**. Ikuti langkah ini:

1. **Pasang Ollama**, lalu di folder `HermesBot` jalankan:
   `ollama pull hermes3:8b` lalu `ollama create hermes-bot -f Modelfile`.
   Cek dengan `ollama list` harus ada `hermes-bot`.
2. **Pasang Python 3.12** (centang *Add Python to PATH* saat instalasi) dan Python
   untuk menjalankan bot. Lalu:
   `python -m pip install -r requirements.txt`
   `py -3.12 -m pip install -r requirements-audio.txt`
   `python -m playwright install chromium` (fallback; Edge/Chrome juga didukung).
3. **Salin `konfigurasi.contoh.json` menjadi `konfigurasi.json`**, lalu isi
   `url_kursus` dengan URL kursus Anda sendiri dan sesuaikan daftar `modul`.
   Hapus/rename folder `BrowserProfile\` supaya profil baru dibuat.
   **Jangan pernah mengirim `BrowserProfile\` ke orang lain** karena di dalamnya
   tersimpan sesi login dan token Anda. Setiap orang login manual.
4. **Klik shortcut** *Hermes Bot - Jalankan Modul* di Desktop (sama dengan
   `Jalankan-Bot-Modul.bat`). Klik pertama menjalankan bot; **klik lagi menghentikan**
   proses bot beserta browser turunannya. Saat dijalankan, browser akan terbuka;
   jika muncul halaman login, login **sendiri** di jendela itu. Bot menunggu
   sampai sesi terdeteksi (maksimal 10 menit), lalu lanjut otomatis. Jangan tutup
   browser manual saat bot berjalan.
5. **Pantau** lewat jendela mini dan `log-modul.txt`. Screenshot sementara dihapus
   otomatis setelah pekerjaan selesai. Aktivitas unggah video/file dan
   `mod/feedback/` sengaja dilewati dan dicatat di log.

## Dua Cara Memakai

### 1️⃣ "Hermes Bot" (Chat Biasa)
Chat sederhana, offline, tanpa internet. Klik dua kali shortcut **"Hermes Bot"** di Desktop.

### 2️⃣ "Hermes Bot Plus" (Asisten Kuliah) ⭐
Untuk mengerjakan tugas kuliah. Klik dua kali shortcut **"Hermes Bot Plus"** di Desktop.

🪟 **Jendela mini Hermes**: saat bot berjalan, jendela kecil milik aplikasi
tetap tampil di pojok kanan atas layar (selalu di atas jendela lain). Di situ
status pekerjaan muncul — mencari, membaca kuis, mengisi jawaban, sampai
jawaban siap. Ini **bukan notifikasi Windows**, melainkan jendela aplikasi
yang tidak bisa hilang dengan sendirinya.

Kemampuan:

| Perintah contoh yang bisa Anda ketik | Apa yang bot lakukan |
|---|---|
| "Buka website rumus fisika di phet.colorado.edu" | 🌐 Membuka website di browser Anda |
| "Cari internet tentang teori relativitas" | 🔍 Mencari info terbaru, lalu menjelaskan |
| "Cari wikipedia tentang fotosintesis lalu jelaskan" | 📚 Mencari materi ensiklopedia, lalu merangkum |
| "Simpan jawaban tadi ke file ringkasan-fisika.txt" | 💾 Menyimpan ke `Dokumen\Hermes\` |
| "Baca file catatan-kuliah.txt" | 📄 Membaca file Anda, lalu menjelaskan/menyimpulkan |
| **"Kerjakan kursus saya di [alamat website]"** | 🖱️ **Browser Hermes terbuka → bot bisa klik isi kursus sendiri** |
| **"Buka kuis Modul Penilaian di kursus saya"** | 🧭 Bot membuka kuis yang tepat lewat menu internal LMS (`buka_quiz`), termasuk kuis yang tampil di dalam embed/iframe |
| **"Isi kuis ini / pilih jawaban yang benar"** | ✍️ **Diisi langsung tanpa ditanya lagi; status tampil di jendela mini Hermes** |
| "Baca PDF materi-kuliah.pdf lalu rangkas" | 📑 Membaca PDF Anda, lalu merangkum isinya |
| "Buat file word tugas.docx berisi jawaban tadi" | 📝 Dokumen Word rapi, siap dikumpulkan |
| "Ingatkan saya besok jam 8 pagi" | ⏰ Pengingat muncul di jendela mini Hermes saat waktunya tiba |
| "Rangkum video ini: youtube.com/watch?v=..." | 🎥 Membaca transkrip video, lalu merangkum |
| "Ucapkan: selamat pagi" | 🔊 Bot mengucapkan dengan suara |
| "Screenshot halaman ini" | 📸 Gambar halaman tersimpan di `Dokumen\Hermes\` |

### 🖱️ Mode Browser Hermes (menelusuri kursus online)
Bot punya browser sendiri yang bisa diklik-kendalikannya. Alurnya:

1. Anda ketik: *"Buka kursus saya di [alamat]"*
2. Jendela **browser Hermes** terbuka menampilkan situsnya
3. **Kalau diminta login → ANDA yang login sendiri** (bot tidak akan pernah
   mengisi form login/password — demi keamanan akun Anda)
4. Setelah login, ketik *"sudah"* → bot mulai menelusuri: membaca halaman,
   klik nama kursus, buka pelajaran, klik lanjut, dst.
5. Sesi login Anda tersimpan otomatis — tidak perlu login ulang lain waktu
6. Setiap ±8 langkah bot berhenti sejenak (pengaman anti-loop) → ketik
   **"lanjutkan"** untuk menyuruhnya lanjut menelusuri materi

Perintah yang dipahami bot secara otomatis: buka alamat, lihat isi halaman,
klik tombol/link, gulir halaman.

### 🧭 Membuka Kuis yang Benar (kuis di dalam embed/iframe)

Di LMS seperti Wadhwani, daftar modul dan tombol **"Kerjakan kuis"** sering
berada **di dalam embed/iframe**, sehingga tidak terlihat oleh cara klik biasa.
Bot sekarang memakai tool khusus **`buka_quiz`** yang:

1. Mencari kuis berdasarkan **nama modul** (mis. *"Modul Penilaian - Keterampilan Berbicara Efektif"*)
2. Membuka **halaman kuis langsung** (bukan menebak-nebak klik kartu modul)
3. Bisa **melihat dan mengklik elemen di dalam iframe** (bukan hanya halaman luar)
4. Pengisian jawaban dan tombol kirim **dijalankan langsung**; statusnya tampil di jendela mini Hermes

Urutan yang disarankan:

```
Anda : buka kursus saya di [alamat LMS]  → login sendiri jika diminta
Anda : sudah
Anda : buka kuis Modul Penilaian - Keterampilan Berbicara Efektif
Bot  : membuka halaman kuis → tunjukkan daftar soal
Anda : kerjakan soal 1 (bot isi langsung, status di jendela mini Hermes)
```

> Jika bot berhenti karena pengaman anti-loop (±8 langkah), cukup ketik
> **"lanjutkan"**.

### 🎧 Kuis berisi gambar, audio, atau video interaktif

Kalau soal/opsi tidak terbaca sebagai teks biasa (misalnya tersimpan di gambar,
grafik, atau tampilan video interaktif), bot bisa:

1. **`baca_layar`** — mengambil screenshot lalu membaca teksnya dengan **Windows
   OCR bawaan** (gratis, cepat, tanpa unduhan). Bila model vision lokal
   (`qwen2.5vl:3b`) sudah terpasang, deskripsi gambar ikut ditambahkan. Untuk
   video, bot bisa mengambil beberapa frame, misalnya `"baca layar 3 frame jeda 2 detik"`.
2. **`cari_dari_layar`** — memakai teks hasil baca layar sebagai kata kunci untuk
   mencari di internet, lalu membandingkan dengan pilihan jawaban.
3. Bot **mengisi jawaban langsung** (tanpa tanya Ya/Tidak); status tampil di jendela mini Hermes.

> **Mata + telinga bot**: screenshot menangkap apa yang *terlihat* di layar dan
> dibaca dengan **Windows OCR bawaan** (binding Python-nya dipasang sekali dengan
> `python -m pip install winrt-Windows.Foundation winrt-Windows.Storage
> winrt-Windows.Graphics.Imaging winrt-Windows.Media.Ocr`).
> Audio murni juga bisa dibaca: narasi SCORM diunduh ke `AudioCache\` lalu
> ditranskrip memakai **faster-whisper lokal** (Python 3.12, gratis, tanpa API).
> Hasilnya dipakai untuk menentukan jawaban dan memeriksa umpan balik setelah
> tombol Kirim ditekan. Model vision tambahan tidak diperlukan.

### 🧠 Aktivitas "Pikirkan" di dalam SCORM (otomatis, dengan pengecekan)

Untuk pelajaran yang isinya berupa aplikasi interaktif SCORM (iframe bersarang
`index_lms.html` di dalam `player.php`), bot menjalankan alur ini:

0. **Masuk ke SCORM** — frame bersarang bisa baru termuat setelah >10 detik, jadi
   bot menunggunya. Jika yang muncul layar awal, bot menekan tombol pembuka yang
   tersedia dalam bahasa apa pun: **Start Course**, **Resume**, **Mulai Kursus**,
   **Lanjutkan**, **MULAI**, atau **play2.png**. Beberapa paket memakai splash
   video dengan **Resume/Restart** atau **Lanjutkan/Mulai ulang**.
1. **Mata di setiap langkah** — screenshot diambil dan dibaca dengan Windows OCR,
   termasuk saat ada **banyak kotak karakter sekaligus** (mis. `Rectangle 5`
   sampai `Rectangle 10`). Semua kotak dikerjakan, bukan hanya satu.
2. **Telinga** — file MP3 narasi diunduh ke `AudioCache\` dan ditranskrip lokal.
   Audio umpan balik yang berisi "Bagus/tepat" menandakan jawaban benar; yang
   berisi "tidak dapat membantu" menandakan jawaban salah.
3. **Klik dua-duanya** — teks tombol jawaban (Benar/Salah) **dan** radio input di
   baliknya, supaya pilihan benar-benar tercatat. Untuk radio yang tidak punya
   label teks, bot mengklik langsung `input.acc-radio` berdasarkan **id** dari
   kunci `data.js` (bukan menebak dari teks yang kosong).
4. **Kirim hanya jika yakin** — setelah Kirim, bot membaca audio + teks umpan
   balik. Kalau ternyata salah, bot kembali ke intro, membuka kotak yang sama,
   dan mencoba pilihan lain sampai benar.
4b. **Halaman hasil** — bila SCORM menunjukkan **"Perlu ditingkatkan" / "tidak
    lolos"**, bot **tidak** menekan Selesai. Ia menekan **Coba lagi**, mengulang
    dari awal, dan memilih opsi lain sampai hasilnya benar.
5. **Selesai** — bot melanjutkan slide sampai tombol **Selesaikan/Selesai** muncul
   lalu diklik. Aktivitas unggah video dan halaman `/mod/feedback/` dilewati.
   Bila sebuah modul memiliki pelajaran feedback sebagai bagian terakhir
   (mis. `Umpan Balik - Pembawaan Diri`, modtype `feedback`), hitungan centang
   bisa berhenti di **3/4**. Itu disengaja: pelajaran itu memakai
   `/mod/feedback/`, tidak memengaruhi completion kursus
   (`courseCompletionInclude: False`), dan sengaja tidak diisi.
6. **Kunci jawaban dari paket SCORM** — selain audio, bot membaca
   `html5/data/js/data.js` di dalam paket SCORM. File itu berisi daftar interaksi
   beserta `choice` yang berstatus `correct`. Dengan itu bot **memastikan jawaban
   benar sebelum menekan Kirim** - termasuk soal **Pick One** (radio) dan
   **Pick Many** (checkbox gambar, mis. `image12.png` + `image13.png`). Untuk
   soal **audio-only** (opsi hanya ikon audio, mis. "Pilih lima opsi"), id
   pilihan `data.js` dicocokkan langsung dengan `id` checkbox
   (`acc-<choiceid>`), lalu checkbox dicentang lewat JS `.click()`. Tombol
   **Kirim** sengaja `disabled` sampai ada pilihan, sehingga deteksi soal
   **tidak** bergantung pada tombol Kirim yang sudah aktif. Tombol pembuka di
   dalam konten seperti **MULAI** dan **play2.png** juga ditekan, karena
   **Start Course** hanya menampilkan splash; splash Storyline dilalui lewat
   `#mobile-start-button` yang tetap ada di DOM setelah diklik (cukup sekali).
7. **Skema, bukan hafalan** — yang bot simpan dari `Pikirkan` adalah **cara
   mengatasi kasus** (prinsip umum dari narasi), bukan pasangan "soal A → jawaban
   A". Skema disimpan di `Dokumen\Hermes\SkemaKasus.json` dan dipakai ulang saat
   bertemu kasus lain.
8. **Peta transkrip = peta pemilih jawaban** — transkrip juga diubah menjadi
   `Dokumen\Hermes\PetaTranskrip.json` berisi **prinsip positif** (Bagus/tepat/
   memastikan), kata kunci situasi, dan sumber audio. Ini **jalur positif saja**:
   tidak ada penalti dari umpan balik negatif, tidak ada hitungan "skor tertinggi".
   Bila beberapa prinsip cocok, model lokal memilih jawaban yang **paling logis
   dan sesuai fakta**. Urutan keputusan: kunci `data.js` → model + peta positif →
   peta transkrip → rotasi opsi. Sumber tiap keputusan dicatat di log dengan
   prefix `[PILIH SCORM]`, `[KUNCI SCORM]`, dan `[PETA TRANSKRIP]`.
9. **Bersih** — semua screenshot sementara (folder `Dokumen\Hermes\ss-pikirkan-*`)
   dihapus otomatis setelah pekerjaan selesai, juga saat terjadi kegagalan.
10. **Kunci `data.js` bisa basi** — pada beberapa paket, `choice` bertanda
    `correct` justru dinyatakan salah oleh umpan balik di layar (mis. 174108:
    kunci menunjuk D, padahal C yang benar). Bila jawaban dinyatakan salah,
    bot mencoba opsi radio berikutnya **sampai habis**, tidak berhenti di tiga
    percobaan. Penanda `radio_selesai`/`box_selesai` juga dikosongkan saat
    tombol **Coba lagi** ditekan, supaya soal yang sama bisa diulang.
    Umpan balik benar dikenali dari kata **Benar/Tepat/Bagus**, dan status API
    (`completed`) dipakai sebagai sinyal paling pasti.
12. **Bentuk soal berubah-ubah (jalur adaptif)** — bot tidak lagi hanya mengenali
    `input.acc-radio` / `input.acc-checkbox`. Bila keduanya tidak ada tapi halaman
    meminta pilihan, `_opsi_kuis_generik()` mencari opsi dari tombol
    `.acc-button` bertanda `Rectangle`/`Oval`, lalu dari elemen apa pun yang
    punya `data-represents` dan teks opsi. Kunci `data.js` dipetakan lewat id,
    urutan `OptN`, atau teks; klik dilakukan pada elemen dan pembayang teksnya.
    Jika jawaban salah, indeks pilihan digeser beberapa kali. Dengan ini soal
    format baru tidak langsung membuat bot maju 120 slide tanpa jawaban.
11. **Video dan tombol Keluar** — video diputar wajar pada 2 detik terakhir
    supaya event `ended` benar-benar terjadi. Pencarian tombol Keluar juga
    membaca `aria-label`/`title` dan alias `Exit/Close/Tutup/Kembali/Back`.
    Bila tombol Keluar tidak ada, bot melanjutkan lewat alur SCORM sampai
    tombol **Selesai** muncul; untuk "Pelajari lebih lanjut", tombol **KELUAR**
    di menu eksplorasi juga dikenali.

### 🎬 Aktivitas menonton video sampai habis

Untuk aktivitas seperti **"Perhatikan"**, bot tidak menunggu durasi penuh:
video langsung di-seek ke akhir dan dilanjutkan. Aturan ini **tidak berlaku**
untuk aktivitas **Pikirkan**, yang tetap dikerjakan normal lewat alur SCORM.
Khusus **"Pelajari lebih lanjut"** di Pasca kelas, video juga boleh di-seek ke
akhir, tetapi setelah itu bot **langsung menekan tombol Keluar**.

### ✅ Pemilihan aktivitas: berbasis API

Daftar aktivitas diambil dari API Wadhwani
(`reports/course/.../contents`) memakai token login yang tersimpan di profil
browser. API mencakup **semua grup** — `Pra-Kelas`, `Di kelas`, dan
`Pasca kelas` — padahal TOC halaman pelajaran hanya menampilkan grup yang
sedang aktif. Setiap aktivitas dibuka lewat **URL langsung**
`/id/courses/<course>/course-lesson/<section>/<instance>`, bukan dengan
mengklik kartu/kelas di halaman course home (klik itu tidak memicu navigasi).

Status diambil ulang dari API setelah tiap aktivitas dikerjakan (cache
di-invalidate), supaya bot tidak tertipu oleh centang TOC yang basi. Aktivitas
yang sudah `completed`/`completedPass` dilewati. Bila setelah dikerjakan
statusnya masih belum selesai, bot mencatatnya dan mengulang di putaran
berikutnya (maksimal 3 putaran) — tidak menekan **`Selanjutnya` secara buta**.

Khusus aktivitas **Berkolaborasi** (LTI), bot **mengerjakan seluruh kartu
"Lihat Aktivitas" di setiap kategori/sektor**, bukan hanya satu atau dua
refleksi. Untuk setiap kartu bot: membuka kartu -> menekan
**Refleksikan aktivitasnya** -> memilih peran -> mengisi refleksi -> menekan
tombol **Kirim** (`button.reflection-submit-btn`) untuk setiap pertanyaan,
lalu kembali ke daftar dan mengerjakan kartu berikutnya sampai semua habis.

Bot **tidak lagi menjawab asal-asalan**: sebelum menjawab, ia membaca teks
studi kasus dan pertanyaan diskusi di halaman aktivitas. Pilihan **nomor siswa**
dan **peran** diputar antar kartu, bukan selalu Siswa 1/Manajer. Jawaban esai
dibuat oleh model lokal Hermes berdasarkan konteks aktivitas tersebut (misalnya
“instruksi Aryo tidak jelas sehingga Lestari bingung”), lalu diverifikasi
dengan screenshot + Windows OCR di setiap langkah. Semua screenshot sementara
dihapus setelah pekerjaan selesai.

Progres yang tersimpan di server (mis. rating `2/5` pada kartu yang sudah
selesai) dipakai untuk memastikan tidak ada kartu yang terlewat. Bila kartu
sudah selesai tetapi ratingnya masih di bawah 5/5, bot membuka kartu itu
lagi, menekan tombol **Mengulang**, lalu menjawab ulang dengan versi yang
lebih spesifik: setiap jawaban esai wajib diakhiri kalimat **"Hasilnya, ..."**
yang menyebut bukti nyata (siapa mengonfirmasi apa, informasi apa yang
diterima, apa yang disepakati), bukan kalimat umum seperti "komunikasi
efektif terwujud". Setelah Kirim terakhir, bot menunggu sekitar **20 detik**
sampai umpan balik GenAI selesai sebelum membaca rating baru, lalu mengulang
kartu tersebut sampai benar-benar menampilkan **5/5**.

Untuk aktivitas **Pelajari lebih lanjut** di bagian Pasca kelas, video boleh
langsung di-seek ke akhir, lalu bot **langsung menekan tombol Keluar**.
Aturan skip-video ini tidak berlaku untuk **Pikirkan** maupun **Pasca kelas**
lainnya.

> Progres pengerjaan modul ditulis seketika ke `HermesBot\log-modul.txt`, jadi
> bisa dipantau tanpa menunggu job selesai.

> Bot tidak pernah mengisi login/password/registrasi, tidak memakai pop-up
> konfirmasi Ya/Tidak, dan tidak memunculkan notifikasi Windows. Status hanya
> tampil di jendela mini Hermes.

### ✍️ Isi Kuis/Form — Langsung Dijalankan
Bot **boleh** membantu mengisi kuis atau form di browser Hermes:

- Bot **mengisi kolom** dan **memilih jawaban** langsung, **tanpa** pop-up Ya/Tidak
- Tombol **kirim/submit/kumpulkan** juga ditekan langsung
- Status tiap aksi (kolom yang diisi, opsi yang dipilih, tombol yang ditekan)
  tampil di **jendela mini Hermes** yang tetap mengambang di layar
- 🔒 **Login, password, dan registrasi TIDAK PERNAH diisi bot** — itu tugas Anda
  (login cukup sekali di jendela browser Hermes, sesi tersimpan otomatis)

### 📑 Skill Tambahan
| Skill | Contoh perintah |
|---|---|
| Baca PDF | *"Baca PDF materi.pdf lalu rangkas"* — file dicari otomatis di Dokumen, Desktop, Downloads |
| Buat Word | *"Buat word tugas.docx berisi: # Judul, ## Bagian, - poin"* |
| Screenshot | *"Screenshot halaman ini"* → PNG tersimpan di `Dokumen\Hermes` |
| Pengingat | *"Ingatkan saya 2 jam lagi / besok jam 8 / 20:00"* |
| Kelola pengingat | *"Lihat pengingat saya"* / *"Hapus pengingat [nama]"* |
| Transkrip YouTube | *"Rangkum video ini: [link YouTube]"* |
| Baca layar | *"Baca isi layar ini"* — bot mengambil screenshot lalu **membaca teks/gambar** dengan model vision lokal |
| Cari dari layar | *"Cari jawaban dari apa yang terlihat di layar"* — hasil baca layar dipakai sebagai kata kunci pencarian internet |
| Suara | *"Ucapkan: [kalimat]"* (pakai suara Windows) |

> **Catatan jendela mini**: jendela status hanya aktif selama jendela Hermes Bot
> Plus masih terbuka, dan bisa diminimalkan tapi tidak hilang dengan sendirinya.
> Pengingat yang belum terpicu tersimpan dan akan muncul saat bot dibuka lagi.

Perintah khusus: `keluar` = tutup bot, `/reset` = mulai chat baru.

## Contoh Alur Mengerjakan Tugas
```
🧑 Anda > cari wikipedia tentang fotosintesis lalu jelaskan untuk tugas kuliah
  ⚙️  [memanggil alat: cari_wikipedia]
  ✅ Hasil Wikipedia Indonesia untuk 'fotosintesis':
  (bot menjelaskan materi dengan lengkap...)

🧑 Anda > simpan jawaban tadi ke file fotosintesis.txt
  ⚙️  [memanggil alat: simpan_file]
  ✅ Berhasil disimpan ke: C:\Users\<nama>\Documents\Hermes\fotosintesis.txt
```

## File dalam Folder Ini
- `Chat-Hermes.bat` — launcher chat biasa (offline)
- `Chat-Hermes-Plus.bat` - launcher asisten kuliah (butuh internet saat mencari)
- `Jalankan-Bot-Modul.bat` - launcher sekali klik: klik untuk jalankan, klik lagi untuk hentikan
- `toggle-bot.ps1` - logika toggle (matikan proses bot + bersihkan kunci profil browser)
- `hermes-agent.py` - otak asisten kuliah (bisa diedit/dikembangkan)
- `jalankan-modul.py` - launcher portable untuk mengerjakan semua modul (baca `konfigurasi.json`)
- `konfigurasi.contoh.json` - template konfigurasi (salin ke `konfigurasi.json`)
- `konfigurasi.json` - pengaturan lokal Anda (tidak ikut di-`commit`)
- `requirements.txt` - dependensi utama (Python untuk bot)
- `requirements-audio.txt` - dependensi transkrip (Python 3.12)
- `transkrip_audio.py` - transkrip MP3 narasi SCORM dengan faster-whisper lokal
- `AudioCache\` — MP3 narasi + `transkrip.json` (hasil transkrip; **jangan dihapus**
  kalau tidak mau narasi diunduh dan ditranskrip ulang)
- `Documents\Hermes\SkemaKasus.json` - skema umum penanganan kasus hasil belajar
- `Documents\Hermes\PetaTranskrip.json` - peta prinsip positif dari transkrip audio
  yang dipakai sebagai pemilih jawaban SCORM
  dari aktivitas `Pikirkan` (bukan daftar jawaban hafalan)
- `Modelfile` — pengaturan kepribadian bot
- `BrowserProfile\` - profil browser Hermes (sesi login kursus Anda tersimpan di sini;
  **jangan dihapus** kalau tidak mau login ulang, dan **jangan dibagikan** karena
  berisi token/login pribadi; tiap pengguna membuat profilnya sendiri)

## Manajemen (opsional, lewat CMD/PowerShell)
- Lihat model terpasang: `ollama list`
- Hapus model jika tak mau dipakai lagi: `ollama rm hermes3:8b` dan `ollama rm hermes-bot`
- Matikan service: klik kanan ikon paus 🐳 Ollama di system tray
- Ollama otomatis jalan saat Windows menyala

## Biaya
**Rp 0 selamanya.** Semua komponen gratis dan open source:
- Ollama (software): MIT License
- Hermes 3 8B (model AI): open weights dari Nous Research
- Script asisten: dibuat khusus untuk Anda
- Semua komputasi AI terjadi di GPU laptop Anda sendiri

> Catatan: fitur cari internet/wikipedia butuh koneksi saat menggunakannya
> (tentu saja — mencari informasi butuh internet). Tapi chat biasa tetap
> bisa offline penuh. Tidak ada biaya apa pun di kedua mode.
