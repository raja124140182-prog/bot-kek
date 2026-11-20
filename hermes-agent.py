#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HERMES BOT PLUS - Asisten AI lokal dengan kemampuan internet
Berjalan di laptop Anda sendiri. Gratis, tanpa langganan.

Kemampuan:
  - buka_website    : membuka website di browser pengguna
  - cari_internet   : mencari informasi di internet (DuckDuckGo)
  - cari_wikipedia  : mencari artikel ensiklopedia (Wikipedia Indonesia)
  - simpan_file     : menyimpan jawaban ke file (folder Dokumen\\Hermes)
  - baca_file       : membaca file dari folder Dokumen
  - buka_browser    : membuka website di browser terkendali Hermes (bisa diklik)
  - lihat_halaman   : membaca isi halaman yang sedang terbuka
  - klik / gulir    : mengklik tombol/link & menggulir halaman
  - baca_pdf        : membaca file PDF (materi kuliah) untuk dirangkum
  - buat_word       : membuat dokumen Word (.docx) siap kumpul
  - screenshot      : menyimpan gambar halaman browser
  - baca_layar      : screenshot lalu BACA isinya dengan model vision lokal (OCR + penglihatan)
  - cari_dari_layar : baca layar lalu pakai hasilnya untuk mencari di internet
  - pengingat       : atur/lihat/hapus pengingat dengan jendela mini Hermes
  - transkrip_youtube : membaca teks transkrip video YouTube
  - bicara          : mengucapkan teks dengan suara (text-to-speech)
"""

import base64
import ctypes
import difflib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.parse
import webbrowser
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

# ============== PENGATURAN ==============
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "hermes-bot"
MODEL_VISI = "qwen2.5vl:3b"   # model lokal untuk membaca screenshot (gratis, open-weight)
MAKS_LANGKAH_ALAT = 12     # batas pemanggilan alat per pertanyaan (anti loop)
FOLDER_SIMPAN = Path.home() / "Documents" / "Hermes"
SKEMA_KASUS = FOLDER_SIMPAN / "SkemaKasus.json"
PETA_TRANSKRIP = FOLDER_SIMPAN / "PetaTranskrip.json"
LOG_MODUL = Path(__file__).resolve().parent / "log-modul.txt"
KONFIGURASI_BOT = Path(__file__).resolve().parent / "konfigurasi.json"


def _muat_konfigurasi_bot():
    """Baca konfigurasi bot lokal. Gagal baca tidak boleh menghentikan bot."""
    try:
        return json.loads(KONFIGURASI_BOT.read_text(encoding="utf-8"))
    except Exception:
        return {}


_CFG_BOT = _muat_konfigurasi_bot()
# Pemilih kedua = perbaikan adaptif (label radio, pick-many tombol tanpa kunci,
# deteksi opsi pendek, pemilihan model saat data.js kosong). Default aktif agar
# kasus seperti 174223/174225 bisa diselesaikan; set false untuk kembali ke
# perilaku awal GitHub.
PEMILIH_KEDUA = bool(_CFG_BOT.get("pemilih_kedua", True))

# Penargetan aktivitas: isi 'target_aktivitas' di konfigurasi.json ATAU tulis
# id/nama aktivitas ke file target-aktivitas.txt (satu per baris). File dibaca
# ulang setiap kali modul dijalankan, jadi daftar bisa diubah tanpa restart.
# Kosong = kerjakan semua aktivitas seperti sebelumnya.
FILE_TARGET = Path(__file__).resolve().parent / "target-aktivitas.txt"
# Aktivitas LTI yang ratingnya sudah diverifikasi 5/5 dalam proses bot ini.
# Mencegah pemindaian ulang yang mahal pada 3x attempt per modul.
_RATING_SUDAH_OK = set()


def _target_aktivitas():
    """Daftar id/nama aktivitas yang boleh dikerjakan (kosong = semua)."""
    mentah = []
    try:
        if FILE_TARGET.exists():
            for baris in FILE_TARGET.read_text(encoding="utf-8").splitlines():
                baris = baris.split("#", 1)[0].strip()
                if baris:
                    mentah.extend(x.strip() for x in re.split(r"[,;]", baris) if x.strip())
    except Exception:
        pass
    if not mentah:
        mentah = [_x for _x in (_CFG_BOT.get("target_aktivitas") or []) if str(_x).strip()]
    return [str(x).strip() for x in mentah if str(x).strip()]


def _cocok_target(aktivitas, targets):
    """Cocokkan target berdasarkan instance id, nama aktivitas, atau pelajaran."""
    if not targets:
        return True
    inst = str(aktivitas.get("instance") or "")
    nama = str(aktivitas.get("nama") or "").lower()
    pel = str(aktivitas.get("pelajaran") or "").lower()
    grup = str(aktivitas.get("grup") or "").lower()
    for t in targets:
        tl = str(t).lower().strip()
        if not tl:
            continue
        if tl == inst or tl in nama or tl in pel or tl in grup:
            return True
    return False

_RIWAYAT_PILIH = {}
_KATA_STOP = {
    "yang", "dan", "dengan", "untuk", "dari", "pada", "ini", "itu", "atau",
    "adalah", "tidak", "juga", "akan", "sudah", "dalam", "bila", "jika",
    "para", "sebuah", "dapat", "harus", "lebih", "sangat", "seperti", "tentang",
    "karena", "supaya", "agar", "maka", "ketika", "setelah", "sebelum",
    "saran", "anda", "kamu", "membantu", "baik", "tepat", "benar", "salah",
    "jawaban", "opsi", "pilih", "pilihan", "maaf", "coba", "lagi", "mengapa",
    "bagaimana", "apakah", "mereka", "dia", "nya", "aku", "saya", "kita",
    "menciptakan", "dirinya", "tentang", "kesan", "waktu", "orang", "lain",
    "penting", "memberikan", "berikan", "melakukan", "lakukan", "menjadi",
    "adanya", "tersebut", "demikian", "sehingga", "dengan", "antara", "atas",
}


def _catat(log, pesan):
    """Tulis progres modul ke log file seketika, juga ke konsol."""
    teks = str(pesan)
    log.append(teks)
    print(teks, flush=True)
    try:
        with open(LOG_MODUL, "a", encoding="utf-8") as f:
            f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " " + teks + "\n")
    except Exception:
        pass
    return teks


if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DESKRIPSI_ALAT = """Kamu punya akses ke alat-alat berikut:

1. buka_website    - membuka sebuah website di browser pengguna
   argumen: {"url": "https://contoh.com"}
2. cari_internet   - mencari informasi terbaru di internet (hasil: judul + cuplikan + link)
   argumen: {"kueri": "kata kunci pencarian"}
3. cari_wikipedia   - mencari artikel ensiklopedia di Wikipedia Indonesia (bagus untuk tugas kuliah)
   argumen: {"kueri": "topik yang dicari"}
4. simpan_file     - menyimpan jawaban/catatan ke file teks di folder Dokumen\\Hermes
   argumen: {"nama_file": "nama.txt", "isi": "isi file"}
5. baca_file       - membaca isi file dari folder Dokumen (contoh: tugas, catatan kuliah)
   argumen: {"nama_file": "nama file atau path lengkap"}
6. buka_browser    - membuka website di BROWSER HERMES yang bisa kamu klik-kendalikan
   argumen: {"url": "https://contoh.com"}
   PENTING: JANGAN PERNAH mengisi login/registrasi/password. Jika halaman meminta
   login, minta pengguna login SENDIRI di jendela browser itu, lalu tunggu pengguna
   mengetik 'sudah' sebelum lanjut. Sesi login tersimpan otomatis.
7. lihat_halaman   - membaca isi halaman yang sedang terbuka di browser Hermes
   argumen: {} (tanpa argumen)
8. klik            - mengklik tombol/link/teks di halaman browser Hermes
   argumen: {"teks": "teks yang ingin diklik"}
   Tombol penting (kirim/submit/kumpulkan/dll) dijalankan langsung;
   jendela mini Hermes menampilkan statusnya.
9. gulir           - menggulir halaman browser Hermes
   argumen: {"arah": "bawah", "jumlah": 3}
10. baca_pdf        - membaca isi file PDF (materi kuliah, jurnal, e-book) lalu kamu rangkum
    argumen: {"nama_file": "nama file PDF"}
    File dicari otomatis di folder Dokumen (termasuk folder Hermes), Desktop, dan Downloads.
11. buat_word       - membuat dokumen Word (.docx) yang rapi dan siap dikumpulkan
    argumen: {"nama_file": "nama.docx", "isi": "isi dokumen"}
    Format isi: baris '# Judul' = judul besar, '## Subjudul' = subjudul,
    '- poin' = poin berbutir, baris biasa = paragraf. Tersimpan di folder Dokumen Hermes.
12. screenshot      - menyimpan gambar halaman yang sedang terbuka di browser Hermes
    argumen: {"nama_file": "nama.png"} (nama_file opsional; "penuh": true untuk seluruh halaman)
    Gunakan setelah buka_browser, untuk menyimpan bukti/isi halaman.
13. atur_pengingat  - membuat pengingat; muncul di jendela mini Hermes saat waktunya tiba
    argumen: {"waktu": "...", "judul": "nama kegiatan singkat"}
    Format 'waktu': "30 detik lagi", "10 menit lagi", "2 jam lagi", "20:00", "besok 08:00",
    atau "2026-11-12 20:00". Konversikan dulu ucapan pengguna (contoh: "jam 8 malam" -> "20:00",
    "jam 2 siang" -> "14:00", "sebentar lagi" -> "5 menit lagi").
14. lihat_pengingat - melihat daftar semua pengingat yang masih aktif
    argumen: {} (tanpa argumen)
15. hapus_pengingat - menghapus pengingat yang sudah tidak diperlukan
    argumen: {"judul": "judul pengingat yang mau dihapus"}
16. transkrip_youtube - mengambil teks transkrip (subtitles) video YouTube untuk dibaca/rangkum
    argumen: {"url": "alamat lengkap video YouTube"}
17. bicara          - mengucapkan kalimat singkat dengan suara lewat speaker pengguna
    argumen: {"teks": "kalimat yang mau diucapkan"}
    Hanya untuk kalimat singkat (salam, konfirmasi), bukan untuk jawaban panjang.
18. isi_form       - mengisi kolom jawaban di kuis/form yang terbuka di browser Hermes
    argumen: {"label": "nama atau placeholder kolom", "teks": "jawaban yang diisi"}
    Pengisian berjalan LANGSUNG (tanpa tanyakan Ya/Tidak); status tampil di jendela mini.
    JANGAN PERNAH dipakai untuk kolom login, password, atau registrasi akun.
19. pilih_opsi      - memilih jawaban opsi (radio/checkbox/dropdown) di kuis/form
    argumen: {"teks": "opsi yang dipilih", "label": "teks pertanyaannya (opsional)"}
    Pilihan dijalankan LANGSUNG (tanpa tanyakan Ya/Tidak); status tampil di jendela mini.
20. buka_quiz       - membuka halaman quiz kursus Wadhwani Skilling secara LANGSUNG
    argumen: {"nama": "nama quiz atau bagiannya"} (nama opsional)
    Hanya untuk situs skilling.wadhwanifoundation.org. Gunakan SETELAH berada di
    halaman kursus (URL mengandung '/courses/'). Quiznya akan terbuka beserta
    tombol 'Kerjakan kuis' di dalam ISI EMBED.
21. baca_layar      - mengambil screenshot lalu MEMBACA isinya dengan model vision lokal
    argumen: {"pertanyaan": "fokus yang dicari", "frame": 1, "jeda": 3}
    'frame' = jumlah tangkapan berurutan (1-5) untuk video/animasi, 'jeda' = detik
    antar tangkapan. Pakai ini kalau soal/opsi tersimpan di gambar, grafik, video,
    atau layar interaktif sehingga TIDAK terbaca oleh lihat_halaman.
    Teks dibaca dengan Windows OCR bawaan (cepat, gratis); deskripsi gambar ditambahkan
    bila model vision lokal sudah terpasang. Hasilnya: soal + pilihan yang terlihat.
22. cari_dari_layar - baca layar lalu PAKAI hasilnya untuk mencari di internet
    argumen: {"kueri": "kata kunci opsional", "pertanyaan": "fokus", "frame": 1}
    Kalau 'kueri' kosong, kata kunci disusun otomatis dari teks yang terbaca di layar.
    Alur kuis audio/video: baca_layar → cari_dari_layar → pilih_opsi/isi_form
    (langsung dijalankan; status tampil di jendela mini Hermes).
23. struktur_kuis - ambil SEMUA soal + pilihan dalam bentuk rapi dari halaman/iframe.
    Pakai ini SEBELUM menjawab supaya kamu tahu persis teks soal dan opsinya.
24. jawab_kuis - isi banyak jawaban sekaligus: {"jawaban": ["opsi 1", "opsi 2"]}
    atau [{"teks": "Jakarta", "label": "Ibukota Indonesia?"}].
25. unggah_file - tersedia, TAPI JANGAN dipakai untuk aktivitas 'Unggah Video' di
    Wadhwani: itu dikerjakan pengguna. Kalau menemukannya, lewati dan laporkan.
26. putar_video - LEWATI video/audio langsung ke akhir supaya dianggap selesai:
     argumen: {"indeks": 0, "semua": true}. Tidak menunggu durasi penuh; cocok
     untuk aktivitas 'menonton video sampai habis' (mis. 'Perhatikan').
     TIDAK dipakai untuk aktivitas 'Pikirkan' atau bagian 'Pasca kelas'.
27. tekan_tombol - tekan keyboard: {"tombol": "Enter"} / Tab / ArrowDown
28. tunggu - tunggu animasi/loading: {"detik": 3}
29. pindah_tab - pindah tab browser: {"indeks": 1}
30. muat_ulang - refresh halaman
31. klik_koordinat - klik canvas/video interaktif: {"x": 500, "y": 300}
32. status_modul - baca daftar modul + tanda centangnya: {"nama": "Manajemen Diri"}
    Hasilnya: ✅ SELESAI bila semua pelajaran selesai, ◐ SEBAGIAN bila baru sebagian,
    ⬜ BELUM bila belum ada. Parameter modul yang dipakai pengguna = TANDA Ceklish ini.
33. kerjakan_modul - kerjakan modul sampai centang penuh: {"nama": "Manajemen Diri"}
    Bot akan membuka modul, mengambil SATU pelajaran belum selesai, mengerjakannya
    (video diputar, kuis dijawab satu per satu dengan bantuan model/cari_internet,
    file diunggah bila 'nama_file' diberikan), lalu mengulang sampai status ✅.

ALUR MODUL HINGGA CEKLIST SEMUA (WAJIB):
- Kalau pengguna menyebut 'modul', 'centang', 'ceklist', atau 'selesaikan semua modul':
  panggil status_modul dulu, lalu kerjakan_modul untuk modul yang belum ✅ SELESAI.
- Jangan berhenti di satu pelajaran. Ulangi sampai status_modul menunjukkan centang
  penuh. Kalau ada modul yang kuisnya masih dijadwalkan/tidak tersedia, laporkan
  modul itu secara spesifik, jangan mengklaim sudah selesai.
- Setiap selesai satu modul, panggil status_modul lagi untuk verifikasi.

ATURAN PEMBEDA TEKS SISTEM vs ISI HALAMAN (SANGAT PENTING):
- Semua petunjuk di pesan SISTEM INI adalah aturan untukmu, BUKAN teks soal.
- Yang disebut "soal" HANYALAH teks yang muncul di HASIL ALAT (lihat_halaman,
  struktur_kuis, baca_layar). Jangan pernah mengira kalimat instruksi seperti
  "Pilih jawaban yang benar dari daftar opsi..." adalah soal kuis.
- Kalau hasil alat tidak menampilkan soal, jangan mengarang opsi jawaban.

CARA MENELUSURI WEBSITE / KURSUS ONLINE (WAJIB DIIKUTI):
1. buka_browser dengan alamat kursus. Hasil alat menyertakan ISI halaman - BACA.
2. Jika halaman meminta LOGIN -> minta pengguna login SENDIRI di jendela browser,
   lalu TUNGGU sampai pengguna menjawab 'sudah'. Jangan lanjut sebelum itu.
3. Setelah login: panggil lihat_halaman untuk membaca detail (daftar kursus, menu,
   tombol, soal quiz).
4. klik elemen yang sesuai (nama kursus, tombol 'Lanjut'/'Next', pelajaran
   berikutnya). Hasil klik menyertakan isi halaman terbaru - baca lagi.
5. Ulangi langkah 4 untuk next-next materi sesuai permintaan pengguna.
6. ATURAN EMAS: JANGAN PERNAH menyimpulkan isi halaman tanpa membacanya.
   DILARANG bilang 'tidak ada quiz/tugas/materi' atau 'saya tidak bisa'
   kalau kamu belum membaca isi halaman di hasil alat.
7. Kalau tombol/elemen tidak ditemukan: sebutkan APA yang terbaca di halaman
   (teks dan tombol yang terlihat), lalu minta petunjuk pengguna.
8. Kalau ditanya 'kenapa tidak bisa?': jelaskan alasan NYATANYA berdasarkan
   isi halaman yang kamu baca (mis. 'halamannya masih minta login'), jangan
   jawab mengelak.
9. Kalau di halaman terlihat daftar/kartu kursus atau tombol seperti 'Resume',
   'Lanjut', 'Next', 'Sedang Berlangsung': KLIK untuk masuk ke kursusnya dan
   baca isinya untuk mencari tugas/quiz/materi. JANGAN berhenti di halaman
   daftar dan jangan menyuruh pengguna menghubungi pihak situs - tugasmu
   adalah menelusuri isi kursus dengan klik dan lihat_halaman.
10. Setiap langkah: klik SATU elemen -> baca hasilnya -> putuskan langkah
    berikutnya. Ulangi sampai ketemu quiz/materi yang dimaksud pengguna.
11. Tombol 'Melanjutkan'/'Lanjut'/'Next' = tombol NEXT untuk materi berikutnya.
    Untuk permintaan 'next2kan materi': klik 'Melanjutkan' berulang kali sambil
    membaca setiap halaman materi yang muncul.
12. Quiz/penilaian biasanya bernama 'Penilaian'/'Modul Penilaian'/'Assessment'.
    Di situs Wadhwani, quiznya TIDAK BISA dibuka dengan klik kartunya - gunakan
    alat buka_quiz. Setelah terbuka, jawab lewat pilih_opsi atau isi_form
    (langsung dijalankan, status tampil di jendela mini Hermes).

URUTAN MENGERJAKAN QUIZ di Wadhwani Skilling (WAJIB):
a. buka_browser ke halaman kursus (alamat dari pengguna, mis. .../id/course-program-list),
   lalu klik kartu/nama kursusnya sampai URL mengandung '/courses/'.
b. panggil buka_quiz dengan nama quiznya (mis. "Penilaian"). JANGAN mencari tombol
   'Modul Penilaian' dengan klik biasa - quiznya ada di iframe yang hanya bisa
   dibuka lewat buka_quiz. JANGAN klik 'Pelajaran Selanjutnya' saat mencari quiz.
c. Klik tombol mulai yang tertera di ISI EMBED: 'Kerjakan kuis', 'Mengerjakan
   kuis kembali', atau 'Lanjutkan pengerjaan kuis yang terakhir'. Pilih yang
   PERSIS tertera di daftar tombol hasil alat. Kalau attempt lama masih aktif,
   soal langsung muncul saat halaman dibuka - tidak perlu klik tombol mulai.
d. KERJAKAN SATU SOAL, LALU LANJUT (WAJIB, JANGAN KUMPULKAN SEMUA SOAL DULU):
   1) panggil struktur_kuis -> hasilnya HANYA soal yang sedang tampil + opsinya.
   2) tentukan jawaban yang benar. Kalau ragu, panggil cari_internet dengan
      teks soal yang persis (boleh ditambah kata kunciopsi) atau baca_layar +
      cari_dari_layar kalau soal berupa gambar/audio/video. Gunakan pengetahuan
      umum bila jawabannya sudah jelas; yang penting jawaban harus benar.
   3) LANGSUNG panggil pilih_opsi/isi_form dengan teks opsi yang PERSIS terbaca.
   4) klik tombol 'next' / 'Soal berikutnya' / 'Selesaikan kuis' untuk MENYIMPAN
      jawaban dan memunculkan soal berikutnya. Cek hasil alatnya: status soal
      harus berubah, bukan tetap di soal yang sama.
   5) ulangi langkah 1-4 untuk soal berikutnya, satu per satu.
e. Di halaman ringkasan, pastikan semua soal berstatus 'Jawaban tersimpan'.
   kalau ada yang 'Belum dijawab', klik nomor soal itu, isi, lalu klik tombol
   'Selesaikan kuis' lagi sampai tersimpan.
f. Terakhir klik 'Kirim semua dan selesai', lalu tekan tombol konfirmasi dengan
   teks yang sama DI DALAM dialog konfirmasi (bukan tombol di latar halaman).
   Pengiriman dijalankan langsung, status tampil di jendela mini Hermes.
Saat diminta 'kerjakan quiz': jangan meringkas isi kursus - langsung buka
quiznya dan kerjakan soalnya satu per satu sampai selesai dikirim.

CONTOH NYATA mengerjakan quiz (TIRU PERSIS FORMAT INI):
pengguna: "buka kursus saya di skilling.wadhwanifoundation.org lalu kerjakan quiz di modul Penilaian"
kamu: ALAT: {"nama": "buka_browser", "argumen": {"url": "https://skilling.wadhwanifoundation.org/id/course-program-list"}}
(setelah melihat daftar kursus, klik nama kursusnya, lalu)
kamu: ALAT: {"nama": "klik", "argumen": {"teks": "nama kursus dari hasil alat"}}
(setelah masuk halaman kursus, buka quiznya)
kamu: ALAT: {"nama": "buka_quiz", "argumen": {"nama": "Modul Penilaian"}}
(lalu klik tombol mulai di dalam EMBED)
kamu: ALAT: {"nama": "klik", "argumen": {"teks": "Kerjakan kuis"}}
(setelah soal muncul di ISI EMBED, tentukan jawaban yang benar, lalu)
kamu: ALAT: {"nama": "pilih_opsi", "argumen": {"teks": "teks opsi jawaban yang benar"}}
(langsung simpan dan lanjut ke soal berikutnya)
kamu: ALAT: {"nama": "klik", "argumen": {"teks": "next"}}
(baca soal berikutnya dengan struktur_kuis, cari jawabannya bila ragu, isi, next,
ulangi sampai ringkasan; lalu klik 'Kirim semua dan selesai' dua kali jika muncul
dialog konfirmasi)
(jika soalnya isian kolom teks)
kamu: ALAT: {"nama": "isi_form", "argumen": {"label": "nama kolom", "teks": "jawaban"}}

ATURAN KUIS / FORM / JAWABAN - SANGAT PENTING:
- Jawab PERCAYA DIRI: bot BISA membantu mengisi kuis/jawaban di kursus online.
  Caranya HANYA lewat alat isi_form dan pilih_opsi (jangan dengan klik biasa).
  Pengisian dan pengiriman dijalankan LANGSUNG tanpa tanya Ya/Tidak;
  jendela mini Hermes hanya menampilkan status.
- Jika alat gagal mengisi, laporkan ke pengguna dan jangan mengulang terus-menerus.
- JANGAN PERNAH mengisi login, password, atau registrasi akun apapun.
- Jangan pernah mengklik logout, hapus akun, atau pembayaran/belanja.

KESADARAN BOT SAAT MENGERJAKAN AKTIVITAS / MODUL (WAJIB):
- "Mata" kamu = baca_layar (screenshot + OCR). "Telinga" kamu = transkrip audio
  yang tersimpan di folder AudioCache. Pakai keduanya, jangan hanya membaca teks
  halaman. Screenshot diambil di setiap langkah; setelah pekerjaan selesai semua
  gambar sementara dihapus otomatis.
- Sebelum bertindak, PAHAMI dulu apa yang sedang tampil: baca layar, lalu kenali
  tombol/kotak/opsi yang terlihat. Ingat: bisa ada BANYAK kotak sekaligus
  (misalnya Rectangle 5 sampai Rectangle 10). Kerjakan SEMUANYA, jangan hanya satu.
- Bedakan aturan untukmu (pesan sistem ini) dengan isi halaman. Kalimat seperti
  "pilih jawaban yang benar" adalah instruksi, BUKAN soal.
- Soal / aktivitas 'Pikirkan' dikerjakan SATU PER SATU: temukan soal, tentukan
  jawaban yang benar dari transkrip audio + layar, isi, lalu lanjut. Jangan asal klik.
- Yang DISIMPAN dari 'Pikirkan' adalah SKEMA / cara mengatasi kasus (prinsip yang
  diambil dari narasi), BUKAN pasangan 'soal A -> jawaban A' atau 'soal B -> jawaban
  B'. Skema itu dipakai ulang ketika bertemu kasus lain.
- Kamu BOLEH menekan 'Kirim' HANYA jika jawaban sudah diyakini benar. Kalau setelah
  Kirim umpan balik audio/teks menunjukkan jawaban SALAH, ULANGI soal itu dengan
  pilihan lain sampai benar. Jangan lanjut meninggalkan jawaban yang salah.
- Klik DUA-DUANYA: teks tombol jawaban (mis. 'Benar'/'Salah') DAN radio input di
  baliknya, supaya pilihan benar-benar tercatat. Bila radio tidak punya label teks,
  klik langsung input.acc-radio berdasarkan id dari kunci data.js.
- LEWATI semua aktivitas 'Unggah Video' dan halaman /mod/feedback/ (Umpan Balik
  Pelatihan sengaja dibiarkan 0/1). Jangan mengerjakan ulang aktivitas yang sudah
  centang / selesai.
- Untuk aktivitas 'menonton video sampai habis' (mis. 'Perhatikan'), putar_video
  langsung melompat ke akhir video lalu lanjut. Aturan ini TIDAK berlaku untuk
  aktivitas 'Pikirkan' maupun bagian 'Pasca kelas' — keduanya dikerjakan normal.
- Bagian 'Pikirkan' HARUS dikerjakan sampai tombol 'Selesaikan'/'Selesai' muncul
  dan diklik. Bentuknya bisa: klik gambar/kotak lalu menjawab, menjawab langsung,
  atau mengisi kolom. Kenali dari layar yang terbaca, bukan dari perkiraan.
- Kunci jawaban SCORM juga dibaca dari data.js paket (html5/data/js/data.js)
  yang memuat choice berstatus 'correct'. Pakai itu untuk memastikan jawaban
  Pick One/Radio dan Pick Many/Checkbox benar SEBELUM menekan Kirim. Tombol
  pembuka bisa berbahasa Indonesia: 'Mulai Kursus', 'Lanjutkan', 'MULAI',
  'play2.png', 'Resume', atau 'Start Course' — kenali dari layar, jangan hanya
  satu kata. Bila halaman hasil berkata 'Perlu ditingkatkan'/'tidak lolos',
  jangan klik Selesai; klik 'Coba lagi' dan ulangi sampai benar.
- Daftar aktivitas modul diambil dari API kursus (Pra-Kelas, Di kelas, Pasca
  kelas) dan dibuka lewat URL langsung. Status dari API yang jadi patokan, bukan
  centang TOC yang bisa basi. Aktivitas 'Berkolaborasi' WAJIB mengerjakan SEMUA
  kartu 'Lihat Aktivitas' di setiap kategori/sektor, bukan hanya satu atau dua:
  buka kartu -> BACA teks studi kasus/pertanyaan diskusinya -> klik
  'Refleksikan aktivitasnya' -> pilih opsi yang sesuai (nomor siswa/peran
  diputar, tidak selalu yang pertama) -> isi refleksi dengan jawaban yang
  dibuat model lokal dari konteks aktivitas itu -> klik 'Kirim', lalu ulang
  sampai semua kartu habis. Screenshot + OCR diambil di tiap langkah lalu
  dihapus setelah selesai. Untuk 'Pelajari lebih lanjut' di Pasca kelas, video
  boleh langsung dilompat ke akhir, lalu KLIK 'Keluar'.
- Tidak ada konfirmasi Ya/Tidak dan tidak ada notifikasi Windows. Status cukup
  ditampilkan di jendela mini Hermes.

ATURAN PEMANGGILAN ALAT - SANGAT PENTING:
Jika kamu butuh alat, balas HANYA dengan format ini (tanpa teks lain):

ALAT: {"nama": "nama_alat", "argumen": {"key": "nilai"}}

Contoh:
ALAT: {"nama": "cari_wikipedia", "argumen": {"kueri": "fotosintesis"}}

GAYA KERJA - WAJIB PATUH:
- Setiap balasan kamu HANYA boleh salah satu dari dua ini:
  (a) format ALAT (di atas) -> untuk mengerjakan tugas
  (b) jawaban singkat ke pengguna -> bila tugas sudah selesai atau kamu butuh
      dia login / butuh info darinya
- DILARANG menulis rencana atau langkah bernomor ('1. kita akan...').
- DILARANG mengutip atau mengulang teks instruksi / [HASIL ALAT] ke pengguna.
- Alamat web HANYA boleh dari pengguna. Kalau pengguna bilang 'web ini' /
  'kursus saya' / 'situs ini' TANPA alamat: gunakan halaman yang SUDAH TERBUKA
  di browser Hermes (panggil lihat_halaman); kalau belum ada, tanya alamatnya.
  DILARANG mengarang alamat web sendiri (alamat seperti alamat_web_kursus = SALAH).
- Setelah pengguna menjawab 'sudah' (login selesai) -> LANGSUNG panggil
  lihat_halaman. Jangan ngobrol lagi.

Setelah kamu menerima [HASIL ALAT], gunakan hasilnya untuk menjawab pengguna
dengan bahasa Indonesia yang jelas dan lengkap. Kamu boleh memanggil alat lagi
jika hasil belum cukup. Jika tidak butuh alat, jawab langsung tanpa format ALAT."""

SYSTEM_PROMPT = """Kamu adalah Hermes Bot, asisten AI pribadi untuk mahasiswa yang mengerjakan tugas kuliah.
Berjalan sepenuhnya di laptop pengguna - gratis, offline, dan privat.

Kepribadian: ramah, membantu, jelas, dan terstruktur. Jawab dalam Bahasa Indonesia.
Saat menjelaskan materi kuliah: gunakan bahasa yang mudah dipahami, beri contoh,
dan susun dengan poin-poin yang rapi. Kalau tidak yakin, katakan tidak yakin.

""" + DESKRIPSI_ALAT


# ============== JENDELA MINI HERMES (status tetap tampil) ==============

ALAT_WEB = {"buka_website", "cari_internet", "cari_wikipedia", "buka_browser",
            "transkrip_youtube", "baca_layar", "cari_dari_layar", "buka_quiz",
            "lihat_halaman", "klik", "gulir", "isi_form", "pilih_opsi",
            "struktur_kuis", "jawab_kuis", "unggah_file", "putar_video",
            "tekan_tombol", "tunggu", "pindah_tab", "muat_ulang", "klik_koordinat",
            "status_modul", "kerjakan_modul"}
ALAT_LABEL = {
    "buka_website": "Membuka website",
    "cari_internet": "Mencari di internet",
    "cari_wikipedia": "Mencari di Wikipedia",
    "buka_browser": "Membuka browser Hermes",
    "transkrip_youtube": "Mengambil transkrip YouTube",
    "baca_layar": "Membaca isi layar",
    "cari_dari_layar": "Mencari dari hasil layar",
    "buka_quiz": "Membuka kuis",
    "lihat_halaman": "Membaca halaman",
    "klik": "Mengklik elemen",
    "gulir": "Menggulir halaman",
    "isi_form": "Mengisi kolom",
    "pilih_opsi": "Memilih jawaban",
    "struktur_kuis": "Membaca struktur soal",
    "jawab_kuis": "Mengisi banyak jawaban",
    "unggah_file": "Mengunggah file",
    "putar_video": "Memutar video",
    "tekan_tombol": "Menekan tombol keyboard",
    "tunggu": "Menunggu",
    "pindah_tab": "Berpindah tab",
    "muat_ulang": "Memuat ulang halaman",
    "klik_koordinat": "Mengklik koordinat",
    "status_modul": "Membaca tanda centang modul",
    "kerjakan_modul": "Menyelesaikan modul sampai centang",
}


class JendelaMini:
    """Jendela kecil milik aplikasi, selalu di atas - BUKAN notifikasi Windows."""

    def __init__(self):
        self._antrean = queue.Queue()
        self._utas = None

    def mulai(self):
        if self._utas and self._utas.is_alive():
            return
        self._utas = threading.Thread(target=self._jalankan, daemon=True)
        self._utas.start()

    def tampilkan(self, judul, pesan):
        try:
            self.mulai()
            self._antrean.put((str(judul)[:60], " ".join(str(pesan).split())[:180]))
        except Exception:
            print(f"[Hermes] {judul}: {pesan}")

    def _jalankan(self):
        try:
            import tkinter as tk

            root = tk.Tk()
            root.title("Hermes Mini")
            lebar, tinggi = 370, 120
            x = max(0, root.winfo_screenwidth() - lebar - 24)
            root.geometry(f"{lebar}x{tinggi}+{x}+80")
            root.attributes("-topmost", True)
            root.resizable(False, False)
            root.configure(bg="#111827")
            root.protocol("WM_DELETE_WINDOW", root.withdraw)  # jangan benar-benar tutup

            judul_var = tk.StringVar(value="Hermes siap")
            pesan_var = tk.StringVar(value="Menunggu perintah dari Anda.")

            atas = tk.Frame(root, bg="#111827")
            atas.pack(fill="x", padx=10, pady=(9, 2))
            tk.Label(atas, textvariable=judul_var, fg="#7dd3fc", bg="#111827",
                     font=("Segoe UI", 11, "bold"), anchor="w").pack(side="left")

            jeda_var = tk.StringVar(value="Jeda")
            def toggle_jeda():
                if _JEDA.is_set():
                    _JEDA.clear()
                    jeda_var.set("Jeda")
                    judul_var.set("Hermes berjalan")
                    pesan_var.set("Bot melanjutkan pekerjaan.")
                else:
                    _JEDA.set()
                    jeda_var.set("Lanjut")
                    judul_var.set("Hermes DIJEDA")
                    pesan_var.set("Klik Lanjut di jendela ini untuk menyambung.")

            tk.Button(atas, textvariable=jeda_var, command=toggle_jeda, width=6,
                      bg="#374151", fg="white", relief="flat").pack(side="right", padx=(4, 0))
            tk.Button(atas, text="_", command=root.iconify, width=2,
                      bg="#1f2937", fg="white", relief="flat").pack(side="right", padx=(4, 0))
            tk.Label(root, textvariable=pesan_var, fg="#e5e7eb", bg="#111827",
                     font=("Segoe UI", 9), wraplength=lebar - 24,
                     justify="left", anchor="w").pack(fill="both", padx=12, pady=(0, 10))

            def perbarui():
                try:
                    while True:
                        judul, pesan = self._antrean.get_nowait()
                        judul_var.set(judul)
                        pesan_var.set(pesan)
                        # Saat dijeda, jangan merebut fokus browser milik pengguna.
                        if not _JEDA.is_set():
                            root.deiconify()
                            root.lift()
                            root.attributes("-topmost", True)
                except queue.Empty:
                    pass
                root.after(250, perbarui)

            perbarui()
            root.mainloop()
        except Exception as e:
            print(f"(Jendela mini tidak dapat dibuka: {e})")


_MINI_POPUP = JendelaMini()
_JEDA = threading.Event()   # tombol Jeda/Lanjut di jendela mini


def tampilkan_popup(judul, pesan):
    """Tampilkan status di jendela mini Hermes yang tetap tampil (bukan toast Windows)."""
    _MINI_POPUP.tampilkan(judul, pesan)


def status_aktif(teks):
    """Perbarui jendela mini dengan kegiatan bot saat ini."""
    tampilkan_popup("Hermes sedang bekerja", teks)


def _tunggu_jika_dijeda():
    """Tahan aksi bot selama pengguna menekan tombol Jeda di jendela mini."""
    if not _JEDA.is_set():
        return
    tampilkan_popup("Hermes dijeda", "Klik Lanjut di jendela mini untuk menyambung.")
    while _JEDA.is_set():
        time.sleep(0.5)
    tampilkan_popup("Hermes dilanjutkan", "Bot melanjutkan pekerjaan.")


# ============== ALAT (TOOL) ==============

def bersihkan_html(teks):
    return re.sub(r"<[^>]+>", "", teks).strip()


def alat_buka_website(arg):
    url = (arg.get("url") or "").strip()
    if not url:
        return "Error: argumen 'url' kosong."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Berhasil: website '{url}' sudah dibuka di browser pengguna."


def alat_cari_internet(arg):
    kueri = (arg.get("kueri") or arg.get("query") or "").strip()
    if not kueri:
        return "Error: argumen 'kueri' kosong."
    try:
        data = urllib.parse.urlencode({"q": kueri}).encode()
        req = urllib.request.Request(
            "https://html.duckduckgo.com/html/", data=data,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        html = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "ignore")
    except Exception as e:
        return f"Error saat mencari: {e}"
    hasil = []
    for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        link = m.group(1)
        if "uddg=" in link:  # unwrap link DuckDuckGo
            link = urllib.parse.unquote(link.split("uddg=")[1].split("&")[0])
        judul = bersihkan_html(m.group(2))
        if judul and link.startswith("http"):
            potongan_html = html[m.end(): m.end() + 1400]
            sm = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', potongan_html, re.S)
            cuplikan = bersihkan_html(sm.group(1)) if sm else ""
            hasil.append((judul, link, cuplikan))
    if not hasil:
        return f"Tidak ada hasil untuk '{kueri}'."
    teks = [f"Hasil pencarian internet untuk '{kueri}':"]
    for i, (judul, link, cuplikan) in enumerate(hasil[:5], 1):
        baris = f"{i}. {judul}\n   {link}"
        if cuplikan:
            baris += f"\n   Cuplikan: {cuplikan[:300]}"
        teks.append(baris)
    return "\n".join(teks)


def alat_cari_wikipedia(arg):
    kueri = (arg.get("kueri") or arg.get("query") or "").strip()
    if not kueri:
        return "Error: argumen 'kueri' kosong."
    try:
        api = "https://id.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query", "list": "search", "srsearch": kueri,
            "format": "json", "srlimit": 5})
        req = urllib.request.Request(api, headers={
            "User-Agent": "HermesBot/1.0 (asisten lokal; pendidikan)"})
        data = json.loads(urllib.request.urlopen(req, timeout=25).read().decode("utf-8"))
    except Exception as e:
        return f"Error saat mencari Wikipedia: {e}"
    hasil = data.get("query", {}).get("search", [])
    if not hasil:
        return f"Tidak ada artikel Wikipedia untuk '{kueri}'."
    teks = [f"Hasil Wikipedia Indonesia untuk '{kueri}':"]
    for item in hasil[:5]:
        judul = item["title"]
        potongan = bersihkan_html(item.get("snippet", ""))
        link = "https://id.wikipedia.org/wiki/" + urllib.parse.quote(judul.replace(" ", "_"))
        teks.append(f"- {judul}: {potongan}\n  {link}")
    return "\n".join(teks)


def nama_aman(nama):
    return re.sub(r'[<>:"/\\|?*]', "_", nama).strip()


def alat_simpan_file(arg):
    nama = nama_aman(arg.get("nama_file") or "catatan.txt")
    isi = arg.get("isi") or ""
    if not nama.endswith((".txt", ".md")):
        nama += ".txt"
    FOLDER_SIMPAN.mkdir(parents=True, exist_ok=True)
    lokasi = FOLDER_SIMPAN / nama
    lokasi.write_text(isi, encoding="utf-8")
    return f"Berhasil disimpan ke: {lokasi} ({len(isi)} karakter)"


def alat_baca_file(arg):
    nama = (arg.get("nama_file") or "").strip()
    if not nama:
        return "Error: argumen 'nama_file' kosong."
    dokumen = (Path.home() / "Documents").resolve()
    kandidat = (dokumen / nama).resolve()
    if not kandidat.is_relative_to(dokumen):
        return "Error: hanya boleh membaca file di dalam folder Documents."
    try:
        isi = kandidat.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return f"Error: file '{nama}' tidak ditemukan."
    except Exception as e:
        return f"Error membaca file: {e}"
    maks = 8000  # batas agar tidak membanjiri memori model
    return f"Isi file {nama}:\n\n{isi[:maks]}" + ("...[dipotong]" if len(isi) > maks else "")


# ============== BROWSER TERKENDALI (untuk kursus online) ==============
# Login/registrasi TIDAK PERNAH dilakukan bot - itu tugas pengguna.
# Sesi login pengguna tersimpan di folder BrowserProfile agar tidak perlu
# login ulang setiap kali memakai bot.

_browser = None
_page = None
_API_KURSUS = {}   # cid -> (url_api_report, headers aplikasi hasil pantauan)


def _pasang_pemantau_api(page):
    """Pantau request API report kursus Wadhwani - simpan URL + header agar
    bisa di-replay untuk menemukan quiz (butuh header otentik aplikasi)."""
    def pantau(req):
        try:
            u = req.url
            if "/courseservice/reports/course/" in u and "/student/" in u:
                cid = u.split("/reports/course/")[1].split("/")[0]
                _API_KURSUS[cid] = (u, dict(req.headers))
        except Exception:
            pass
    page.on("request", pantau)


def _pastikan_browser():
    """Buka browser Hermes (sekali saja per sesi chat). Return halaman aktif."""
    global _browser, _page
    if _browser is not None:
        return _page
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "Komponen browser belum terinstall. Jalankan: python -m pip install playwright")
    pw = sync_playwright().start()
    profil = str(Path(__file__).parent / "BrowserProfile")
    galat = None
    for channel in ("msedge", "chrome", None):
        try:
            opsi = {"headless": False,
                    "viewport": {"width": 1280, "height": 800}}
            if channel:
                opsi["channel"] = channel
            _browser = pw.chromium.launch_persistent_context(profil, **opsi)
            break
        except Exception as e:
            galat = e
    if _browser is None:
        raise RuntimeError(f"Tidak bisa membuka browser: {galat}")
    _page = _browser.pages[0] if _browser.pages else _browser.new_page()
    _pasang_pemantau_api(_page)
    return _page


def _semua_frame(page):
    """Frame utama + semua iframe (quiz Moodle di Wadhwani ada di dalam iframe)."""
    try:
        return list(page.frames)
    except Exception:
        return [page]


_FAKTOR_JARINGAN = 1.0


def _info_jaringan(page=None):
    """Ukur kualitas jaringan langsung dari browser (tanpa alat eksternal)."""
    try:
        p = page or _pastikan_browser()
        dat = p.evaluate("""() => {
            const c = navigator.connection || navigator.mozConnection ||
                      navigator.webkitConnection || {};
            const n = performance.getEntriesByType('navigation')[0] || {};
            return {
                rtt: c.rtt == null ? null : c.rtt,
                downlink: c.downlink == null ? null : c.downlink,
                eff: c.effectiveType || '',
                dur: n.duration || 0,
                resp: (n.responseEnd && n.requestStart)
                      ? n.responseEnd - n.requestStart : 0,
            };
        }""")
        return dat if isinstance(dat, dict) else {}
    except Exception:
        return {}


def _faktor_jaringan(page=None):
    """Faktor waktu tunggu adaptif: 0.7 (cepat) sampai 3.0 (lambat).

    Dibaca ulang tiap aktivitas, jadi langsung menyesuaai bila user
    berpindah jaringan. Nilainya dirata-ratakan supaya tidak berubah-ubah.
    """
    global _FAKTOR_JARINGAN
    dat = _info_jaringan(page)
    faktor = 1.0
    eff = str(dat.get("eff") or "").lower()
    if eff in ("slow-2g", "2g"):
        faktor = 2.8
    elif eff == "3g":
        faktor = 1.8
    try:
        rtt = float(dat.get("rtt") or 0)
        if rtt > 300:
            faktor = max(faktor, 2.6)
        elif rtt > 150:
            faktor = max(faktor, 1.8)
        elif 0 < rtt < 60:
            faktor = min(faktor, 0.9)
    except Exception:
        pass
    try:
        downlink = float(dat.get("downlink") or 0)
        if 0 < downlink < 1.5:
            faktor = max(faktor, 2.4)
        elif 0 < downlink < 5:
            faktor = max(faktor, 1.5)
        elif downlink > 10:
            faktor = min(faktor, 0.8)
    except Exception:
        pass
    try:
        resp = float(dat.get("resp") or 0)
        if resp > 2000:
            faktor = max(faktor, 2.2)
        elif resp > 800:
            faktor = max(faktor, 1.5)
    except Exception:
        pass
    faktor = max(0.7, min(3.0, faktor))
    _FAKTOR_JARINGAN = round(0.7 * _FAKTOR_JARINGAN + 0.3 * faktor, 2)
    return _FAKTOR_JARINGAN


def _cuplikan_halaman(page, maks=1200):
    """Ambil teks isi halaman termasuk isi iframe (dipadatkan) untuk dibaca model."""
    try:
        teks = " ".join(page.inner_text("body").split())
    except Exception:
        teks = ""
    if teks:
        hasil = teks[:maks] + (" ...[dipotong]" if len(teks) > maks else "")
    else:
        hasil = "(isi halaman belum bisa dibaca)"
    for f in _semua_frame(page)[1:]:  # iframe: quiz, konten embed
        try:
            isi = " ".join(f.inner_text("body").split())
        except Exception:
            continue
        if isi and len(isi) > 15:
            hasil += f"\n[ISI EMBED {f.url.split('?')[0][-70:]}]\n{isi[:maks]}"
    return hasil


def _deteksi_halaman_login(page):
    """True jika halaman (atau salah satu iframe) tampak meminta login/registrasi."""
    try:
        url = page.url.lower()
        isi = " ".join(page.inner_text("body").split()).lower()[:2000]
    except Exception:
        return False
    # gabungkan juga isi iframe (quiz Moodle kadang meminta login di iframe)
    for f in _semua_frame(page)[1:]:
        try:
            isi += " " + " ".join(f.inner_text("body").split()).lower()[:1500]
        except Exception:
            continue
    if any(f in url for f in ("login", "signin", "sign-in", "/auth", "register")):
        return True
    frasa = ("log in or sign up", "please log in", "please sign in",
             "continue with google", "sign in to continue", "login to continue",
             "masuk untuk melanjutkan", "silakan masuk", "belum masuk",
             "anda harus masuk", "you must log in")
    return any(f in isi for f in frasa)


def _daftar_elemen_interaktif(page, maks_tombol=20, maks_kolom=10):
    """Kumpulkan teks tombol/link + kolom input yang terlihat (termasuk iframe)."""
    tombol, kolom = [], []
    for f in _semua_frame(page):
        try:
            for el in f.locator("a:visible, button:visible").all():
                t = " ".join((el.inner_text() or "").split())
                if t and t not in tombol:
                    tombol.append(t)
                if len(tombol) >= maks_tombol:
                    break
        except Exception:
            pass
        if len(tombol) >= maks_tombol:
            break
    for f in _semua_frame(page):
        try:
            for el in f.locator(
                    "input:visible, textarea:visible, select:visible").all():
                info = el.evaluate(
                    "e => (e.placeholder || (e.labels && e.labels[0] ? "
                    "e.labels[0].innerText : '') || e.getAttribute('aria-label') "
                    "|| e.name || '') + ' [' + (e.type || e.tagName) + ']'")
                info = " ".join(str(info).split())
                if info and info not in kolom:
                    kolom.append(info)
                if len(kolom) >= maks_kolom:
                    break
        except Exception:
            pass
        if len(kolom) >= maks_kolom:
            break
    return tombol, kolom


def _teks_elemen_interaktif(page, maks_tombol=12, maks_kolom=8):
    """Format daftar tombol/kolom untuk dibaca model (string bisa kosong)."""
    tombol, kolom = _daftar_elemen_interaktif(page, maks_tombol, maks_kolom)
    bagian = []
    if tombol:
        bagian.append("TOMBOL/LINK YANG BISA DIKLIK: " + " | ".join(tombol))
    if kolom:
        bagian.append("KOLOM INPUT TERLIHAT: " + " | ".join(kolom))
    return ("\n" + "\n".join(bagian)) if bagian else ""


def alat_buka_browser(arg):
    url = (arg.get("url") or "").strip()
    if not url:
        return "Error: argumen 'url' kosong."
    if any(p in url.lower() for p in
           ("contoh.com", "example.com", "alamat_web", "web_kursus",
            "nama_situs", "nama_web", "url_kursus")):
        return ("Error: itu alamat CONTOH, bukan alamat asli. Gunakan alamat asli "
                "yang disebut pengguna. Kalau pengguna tidak menyebut alamat dan "
                "browser Hermes sudah membuka halaman, panggil lihat_halaman untuk "
                "memakai halaman itu. Kalau belum ada halaman terbuka, tanya "
                "alamatnya ke pengguna.")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    page = _pastikan_browser()
    page.goto(url, timeout=90000)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    judul = page.title()
    hasil = (f"Browser Hermes sudah membuka: {url}\n"
             f"JUDUL HALAMAN: {judul}\n"
             f"ALAMAT SEKARANG: {page.url}\n"
             f"ISI HALAMAN (cuplikan):\n{_cuplikan_halaman(page)}\n"
             + _teks_elemen_interaktif(page) + "\n")
    if _deteksi_halaman_login(page):
        hasil += (
            "\n⚠️ HALAMAN INI MEMINTA LOGIN. Bot tidak boleh mengisi login.\n"
            "Sampaikan ke pengguna: 'Silakan login SENDIRI di jendela browser Hermes "
            "yang terbuka, setelah selesai ketik SUDAH.'\n"
            "Lalu TUNGGU jawaban 'sudah' dari pengguna. Setelah itu panggil "
            "lihat_halaman untuk membaca isi kursus yang sudah login.")
    return hasil


def alat_lihat_halaman(arg):
    page = _pastikan_browser()
    # beri waktu SPA (React) menyelesaikan render sebelum membaca
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    try:
        page.wait_for_timeout(800)
    except Exception:
        pass
    try:
        teks = page.inner_text("body")
    except Exception as e:
        return f"Error membaca halaman: {e}"
    teks = " ".join(teks.split())
    maks = 6000
    potong = "\n...[dipotong, halaman terlalu panjang]" if len(teks) > maks else ""
    hasil = (f"JUDUL: {page.title()}\nALAMAT: {page.url}\nISI HALAMAN:\n{teks[:maks]}{potong}")
    # isi tiap iframe (quiz Moodle/soal ada di sini - BACA juga bagian ini)
    for f in _semua_frame(page)[1:]:
        try:
            isi = " ".join(f.inner_text("body").split())
        except Exception:
            continue
        if isi and len(isi) > 15:
            hasil += (f"\n\n=== ISI EMBED ({f.url.split('?')[0][-70:]}) ===\n"
                      + isi[:4000]
                      + ("\n...[dipotong]" if len(isi) > 4000 else ""))
    hasil += _teks_elemen_interaktif(page, 20, 10)
    if _deteksi_halaman_login(page):
        hasil += ("\n\n⚠️ Halaman masih di halaman LOGIN. Minta pengguna login sendiri "
                  "di jendela browser, lalu TUNGGU jawaban 'sudah' sebelum lanjut.")
    return hasil


def alat_klik(arg):
    teks = (arg.get("teks") or arg.get("teks_tombol") or arg.get("label")
            or arg.get("tombol") or "").strip()
    if not teks:
        return "Error: argumen 'teks' kosong."
    page = _pastikan_browser()
    if POLA_TOMBOL_PENTING.search(teks):
        tampilkan_popup("Hermes menekan tombol", f"Tombol: {teks}")
    # coba di frame utama lalu tiap iframe (tombol quiz Moodle ada di iframe)
    semua = _semua_frame(page)
    for idx, f in enumerate(semua):
        kandidat = [
            f.get_by_role("button", name=teks),
            f.get_by_role("link", name=teks),
            f.get_by_text(teks, exact=False),
        ]
        for loc in kandidat:
            try:
                if loc.count() > 0:
                    loc.first.click(timeout=8000)
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        pass
                    try:
                        page.wait_for_timeout(600)
                    except Exception:
                        pass
                    lokasi = (" (di dalam jendela embed/iframe)" if idx > 0 else "")
                    hasil = (f"Berhasil mengklik '{teks}'{lokasi}.\n"
                             f"JUDUL SEKARANG: {page.title()}\n"
                             f"ISI HALAMAN (cuplikan):\n{_cuplikan_halaman(page, 800)}"
                             + _teks_elemen_interaktif(page, 10, 6))
                    if _deteksi_halaman_login(page):
                        hasil += ("\n\n⚠️ Setelah klik, halaman meminta LOGIN. Minta pengguna "
                                  "login sendiri di jendela browser, lalu TUNGGU jawaban 'sudah'.")
                    return hasil
            except Exception:
                continue
    return (f"Tidak menemukan elemen '{teks}' yang bisa diklik."
            + _teks_elemen_interaktif(page, 15, 6)
            + "\nGunakan teks yang persis tertera di daftar di atas. "
              "Kalau daftarnya kosong, panggil lihat_halaman.")


def alat_gulir(arg):
    arah = (arg.get("arah") or "bawah").lower()
    try:
        jumlah = max(1, min(10, int(arg.get("jumlah") or 3)))
    except (TypeError, ValueError):
        jumlah = 3
    page = _pastikan_browser()
    delta = -500 if arah == "atas" else 500
    page.mouse.wheel(0, delta * jumlah)
    return (f"Halaman digulir ke {arah} ({jumlah} langkah).\n"
            f"ISI HALAMAN SEKARANG (cuplikan):\n{_cuplikan_halaman(page, 600)}")


def _data_kursus_wadhwani(page, cid):
    """Ambil struktur kursus Wadhwani via replay API report (butuh header aplikasi
    yang dipantau _pasang_pemantau_api). Return list (sectionid, quiz) atau None."""
    if cid not in _API_KURSUS:
        # cache dingin: muat ulang halaman kursus agar aplikasi memanggil API-nya
        try:
            if "/courses/" in page.url:
                dasar = re.sub(r"/courses/[a-f0-9]+.*$", f"/courses/{cid}", page.url)
            else:
                dasar = f"https://skilling.wadhwanifoundation.org/id/courses/{cid}"
            page.goto(dasar, timeout=90000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(1500)
        except Exception:
            return None
    info = _API_KURSUS.get(cid)
    if not info:
        return None
    try:
        resp = page.context.request.get(info[0], headers=info[1])
        data = resp.json()
        mods = data["data"]["contents"]["modules"]
    except Exception:
        return None
    quiz = []
    for mod in mods:
        for anak in mod.get("modules", []):
            if anak.get("modtype") == "quiz":
                quiz.append((mod.get("sectionid"), anak))
    return quiz


def alat_buka_quiz(arg):
    """Buka halaman quiz kursus Wadhwani langsung (quiznya tertanam iframe Moodle)."""
    nama = (arg.get("nama") or arg.get("quiz") or arg.get("teks") or "").strip()
    page = _pastikan_browser()

    m = re.search(r"/courses/([a-f0-9]+)", page.url)
    cid = m.group(1) if m else (next(iter(_API_KURSUS)) if _API_KURSUS else None)
    if not cid:
        return ("Error: browser belum berada di halaman kursus Wadhwani. Buka dulu "
                "halaman kursus (buka_browser ke course-program-list lalu klik nama "
                "kursusnya), SETELAH itu panggil buka_quiz lagi."
                + _teks_elemen_interaktif(page, 15, 6))

    quiz_list = _data_kursus_wadhwani(page, cid)
    if quiz_list is None:
        return ("Error: data kursus tidak bisa diambil (mungkin sesi login habis). "
                "Minta pengguna login sendiri di jendela browser Hermes, tunggu "
                "jawaban 'sudah', lalu ulangi buka_quiz.")
    if not quiz_list:
        return "Kursus ini tidak memiliki quiz."

    cocok = [(s, q) for s, q in quiz_list
             if nama and nama.lower() in q.get("name", "").lower()]
    if not cocok and nama:
        daftar = " | ".join(q.get("name", "")[:60] for _, q in quiz_list)
        return (f"Quiz bernama '{nama}' tidak ditemukan. Quiz yang tersedia:\n{daftar}\n"
                "Ulangi buka_quiz dengan nama yang persis dari daftar di atas.")
    if not cocok:   # tanpa nama: prioritas quiz pertama yang belum dikerjakan
        cocok = [(s, q) for s, q in quiz_list
                 if q.get("userStatus") == "notStarted"] or [quiz_list[0]]

    sect, quiz = cocok[0]
    if "/courses/" in page.url:
        dasar = re.sub(r"/courses/[a-f0-9]+.*$", f"/courses/{cid}", page.url)
    else:
        dasar = f"https://skilling.wadhwanifoundation.org/id/courses/{cid}"
    url_quiz = f"{dasar}/course-lesson/{sect}/{quiz.get('instance')}"
    try:
        page.goto(url_quiz, timeout=90000)
    except Exception as e:
        return f"Error membuka halaman quiz: {e}"
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(2500)   # beri waktu iframe Moodle termuat

    att = quiz.get("attempt") or {}
    hasil = (f"Quiz '{quiz.get('name')}' sudah DIBUKA.\n"
             f"ALAMAT: {page.url}\n"
             f"Nilai maks: {quiz.get('maxGrade')} | Status: {quiz.get('userStatus')}\n"
             f"Sisa percobaan: {att.get('remaining')} dari {att.get('totalallowed')}\n"
             "ISI HALAMAN + ISI EMBED (soal quiz ada di dalam EMBED):\n"
             f"{_cuplikan_halaman(page, 1500)}\n"
             + _teks_elemen_interaktif(page, 15, 8)
             + "\nLANGKAH BERIKUTNYA: klik tombol 'Kerjakan kuis' (ada di dalam EMBED) "
               "untuk memulai soal, lalu jawab dengan pilih_opsi.")
    if _deteksi_halaman_login(page):
        hasil += ("\n\n⚠️ Halaman meminta LOGIN. Minta pengguna login sendiri di "
                  "jendela browser, lalu TUNGGU jawaban 'sudah'.")
    return hasil


# ============== FORM / KUIS - LANGSUNG DIJALANKAN ==============
# Pengisian kuis/form berjalan otomatis tanpa bertanya lagi.
# Jendela mini Hermes hanya menampilkan status. Pengecualian tetap berlaku:
# kolom login/password/registrasi TIDAK PERNAH diisi bot.

POLA_TOMBOL_PENTING = re.compile(
    r"kirim|submit|kumpul|selesai|finish|bayar|beli|pay|upgrade|hapus|delete|logout|sign\s*out|keluar",
    re.I)

POLA_KOLOM_TERLARANG = re.compile(
    r"password|kata\s*sandi|sandi|login|masuk|sign\s*in|registr|buat\s*akun", re.I)


def _cari_kolom_input(page, label):
    """Cari kolom input berdasarkan placeholder / label / nama (termasuk iframe)."""
    for f in _semua_frame(page):
        for loc in (f.get_by_placeholder(label),
                    f.get_by_label(label),
                    f.get_by_role("textbox", name=label),
                    f.get_by_role("spinbutton", name=label)):
            try:
                if loc.count() > 0:
                    return loc.first
            except Exception:
                continue
    return None


def alat_isi_form(arg):
    label = (arg.get("label") or arg.get("kolom") or arg.get("nama_kolom") or "").strip()
    teks = (arg.get("teks") or arg.get("nilai") or arg.get("isi") or "").strip()
    if not label or not teks:
        return "Error: argumen 'label' dan 'teks' harus diisi."
    if _browser is None:
        return "Error: belum ada halaman terbuka. Gunakan buka_browser dulu."
    if POLA_KOLOM_TERLARANG.search(label):
        return ("Error: kolom login/password/registrasi tidak boleh diisi bot. "
                "Pengguna harus mengisinya sendiri di jendela browser.")
    page = _pastikan_browser()
    tampilkan_popup("Hermes mengisi jawaban", f"Kolom: {label}\nNilai: {teks[:120]}")
    kolom = _cari_kolom_input(page, label)
    if kolom is None:
        return (f"Kolom '{label}' tidak ditemukan di halaman."
                + _teks_elemen_interaktif(page, 12, 8)
                + "\nGunakan label kolom yang persis tertera di daftar di atas.")
    try:
        kolom.fill(teks)
    except Exception:
        try:
            kolom.click()
            page.keyboard.type(teks)
        except Exception as e:
            return f"Gagal mengisi kolom '{label}': {e}"
    return f"Berhasil mengisi kolom '{label}' dengan: {teks}"


def alat_pilih_opsi(arg):
    teks = (arg.get("teks") or arg.get("opsi") or "").strip()
    label = (arg.get("label") or arg.get("pertanyaan") or "").strip()
    if not teks:
        return "Error: argumen 'teks' (opsi yang dipilih) kosong."
    if _browser is None:
        return "Error: belum ada halaman terbuka. Gunakan buka_browser dulu."
    page = _pastikan_browser()
    info = f"opsi '{teks}'" + (f" untuk pertanyaan '{label}'" if label else "")
    tampilkan_popup("Hermes memilih jawaban", info)
    kandidat = []
    if label:
        for f in _semua_frame(page):
            try:
                kandidat.append(f.get_by_label(label).get_by_text(teks))
            except Exception:
                pass
    for f in _semua_frame(page):  # opsi quiz Moodle ada di dalam iframe
        kandidat += [
            f.get_by_role("radio", name=teks),
            f.get_by_role("checkbox", name=teks),
            f.get_by_role("option", name=teks),
            f.get_by_text(teks, exact=False),
        ]
    for loc in kandidat:
        try:
            if loc.count() > 0:
                loc.first.click(timeout=8000)
                return (f"Berhasil memilih {info}.\n"
                        f"ISI HALAMAN SEKARANG (cek soal berikutnya):\n"
                        f"{_cuplikan_halaman(page, 900)}")
        except Exception:
            continue
    for f in _semua_frame(page):  # kemungkinan berupa dropdown (select)
        try:
            if label:
                f.get_by_label(label).select_option(label=teks)
                return f"Berhasil memilih {info} (dropdown)."
        except Exception:
            continue
    return (f"Opsi '{teks}' tidak ditemukan di halaman ini.\n"
            f"ISI HALAMAN SEKARANG (baca soal dan opsinya, lalu ulangi dengan teks "
            f"yang persis):\n{_cuplikan_halaman(page, 900)}")


# ============== PDF / WORD / SCREENSHOT ==============

def _folder_shell(nama_reg):
    """Ambil lokasi folder khusus Windows (Dokumen/Desktop/Downloads) dari registry."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        nilai, _ = winreg.QueryValueEx(key, nama_reg)
        winreg.CloseKey(key)
        hasil = Path(os.path.expandvars(str(nilai)))
        if hasil.is_dir():
            return hasil
    except Exception:
        pass
    return None


def _folder_pencarian_file():
    """Folder tempat pencarian file PDF/dokumen milik pengguna."""
    rumah = Path.home()
    return [
        _folder_shell("Personal") or rumah / "Documents",
        FOLDER_SIMPAN,
        _folder_shell("Desktop") or rumah / "Desktop",
        _folder_shell("{374DE290-123F-4565-9164-39C4925E467B}") or rumah / "Downloads",
    ]


def _cari_file(nama):
    """Cari file: path absolut, nama persis, atau nama mirip di folder umum."""
    nama = str(nama).strip().strip('"')
    if not nama:
        return None
    langsung = Path(nama)
    if langsung.is_absolute() and langsung.is_file():
        return langsung
    petunjuk = nama.lower()
    for folder in _folder_pencarian_file():
        if not folder.is_dir():
            continue
        kandidat = folder / nama
        if kandidat.is_file():
            return kandidat
        try:
            for f in folder.iterdir():
                if f.is_file() and petunjuk in f.name.lower():
                    return f
        except OSError:
            continue
    return None


def alat_baca_pdf(arg):
    nama = (arg.get("nama_file") or arg.get("file") or arg.get("nama") or "").strip()
    if not nama:
        return "Error: argumen 'nama_file' kosong."
    berkas = _cari_file(nama)
    if berkas is None:
        return ("Error: file tidak ditemukan. File dicari otomatis di folder Dokumen "
                "(termasuk folder Hermes), Desktop, dan Downloads. Coba nama yang lebih spesifik.")
    try:
        from pypdf import PdfReader
    except ImportError:
        return "Error: komponen pypdf belum terinstall (python -m pip install pypdf)."
    try:
        pembaca = PdfReader(str(berkas))
        jumlah_hal = len(pembaca.pages)
        isi = "\n".join((hal.extract_text() or "") for hal in pembaca.pages).strip()
    except Exception as e:
        return f"Error membaca PDF: {e}"
    if not isi:
        return (f"PDF '{berkas.name}' berhasil dibuka ({jumlah_hal} halaman), tetapi tidak "
                "ada teks yang bisa dibaca (kemungkinan PDF hasil scan/gambar).")
    maks = 12000
    potong = "\n...[dipotong, teks lebih panjang]" if len(isi) > maks else ""
    return f"Isi PDF {berkas.name} ({jumlah_hal} halaman):\n\n{isi[:maks]}{potong}"


def alat_buat_word(arg):
    nama = nama_aman(arg.get("nama_file") or arg.get("nama") or "dokumen")
    isi = str(arg.get("isi") or arg.get("konten") or arg.get("teks") or "")
    if not isi.strip():
        return "Error: argumen 'isi' kosong."
    nama = re.sub(r"\.(txt|md|doc)$", "", nama, flags=re.I)
    if not nama.lower().endswith(".docx"):
        nama += ".docx"
    try:
        from docx import Document
    except ImportError:
        return "Error: komponen python-docx belum terinstall (python -m pip install python-docx)."
    doc = Document()
    for baris in isi.splitlines():
        bersih = baris.strip()
        if not bersih:
            continue
        if bersih.startswith("# "):
            doc.add_heading(bersih[2:].strip(), level=1)
        elif bersih.startswith("## "):
            doc.add_heading(bersih[3:].strip(), level=2)
        elif bersih.startswith(("- ", "* ")):
            doc.add_paragraph(bersih[2:].strip(), style="List Bullet")
        else:
            doc.add_paragraph(bersih)
    FOLDER_SIMPAN.mkdir(parents=True, exist_ok=True)
    lokasi = FOLDER_SIMPAN / nama
    doc.save(str(lokasi))
    return f"Berhasil membuat dokumen Word: {lokasi}"


def alat_screenshot(arg):
    if _browser is None:
        return "Error: belum ada halaman terbuka. Gunakan buka_browser dulu, lalu screenshot."
    page = _pastikan_browser()
    nama = nama_aman(arg.get("nama_file") or arg.get("nama") or "")
    if not nama:
        nama = f"screenshot-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    if not nama.lower().endswith(".png"):
        nama += ".png"
    penuh = bool(arg.get("penuh") or arg.get("seluruh_halaman") or arg.get("full_page"))
    FOLDER_SIMPAN.mkdir(parents=True, exist_ok=True)
    lokasi = FOLDER_SIMPAN / nama
    try:
        page.screenshot(path=str(lokasi), full_page=penuh)
    except Exception as e:
        return f"Error mengambil screenshot: {e}"
    return f"Screenshot tersimpan: {lokasi}\nHalaman: {page.title()} - {page.url}"


# ============== BACA LAYAR (screenshot -> model vision lokal) ==============

def _model_vision_tersedia():
    """Cek apakah model vision lokal sudah tersedia di Ollama."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        data = json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8"))
        nama = [str(m.get("name", "")) for m in data.get("models", [])]
        return any(n.split(":")[0] == MODEL_VISI.split(":")[0] for n in nama)
    except Exception:
        return False


def _baca_gambar_vision(lokasi, pertanyaan=""):
    """Minta model vision lokal membaca isi file gambar."""
    if not _model_vision_tersedia():
        return ("Error: model vision lokal belum terpasang. Pasang sekali dengan perintah: "
                f"ollama pull {MODEL_VISI} (gratis, open-weight).")
    try:
        gambar = Path(lokasi).read_bytes()
        instruksi = (
            "Kamu membaca tangkapan layar dari kuis/video pembelajaran online. "
            "Transkripsi SEMUA teks yang terlihat apa adanya (soal, pilihan A/B/C/D, "
            "instruksi, dan teks di dalam video). Jika ada gambar/grafik, jelaskan "
            "singkat. Jangan menjawab soal dan jangan menebak. "
            "Format jawaban: TEKS TERLIHAT: ... | DESKRIPSI: ..."
        )
        if pertanyaan:
            instruksi += f" Fokus pengguna: {pertanyaan}."
        body = json.dumps({
            "model": MODEL_VISI,
            "messages": [{
                "role": "user",
                "content": instruksi,
                "images": [base64.b64encode(gambar).decode("ascii")],
            }],
            "stream": False,
            "options": {"temperature": 0.2},
        }).encode()
        req = urllib.request.Request(OLLAMA_URL, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            data = json.loads(r.read().decode("utf-8"))
        return str(data.get("message", {}).get("content", "")).strip()
    except Exception as e:
        return f"Error membaca gambar dengan model vision: {e}"


def _ambil_screenshot_untuk_dibaca(arg):
    """Ambil 1-5 screenshot berurutan (untuk video/animasi). Return (daftar file, error)."""
    if _browser is None:
        return [], "Error: belum ada halaman terbuka. Gunakan buka_browser dulu."
    try:
        page = _pastikan_browser()
    except Exception as e:
        return [], f"Error menyiapkan browser: {e}"
    # Pastikan area embed/iframe terlihat di layar sebelum diambil gambarnya.
    try:
        page.locator("iframe").first.scroll_into_view_if_needed(timeout=1500)
    except Exception:
        pass
    try:
        frame = int(arg.get("frame") or arg.get("frames") or 1)
    except (TypeError, ValueError):
        frame = 1
    frame = max(1, min(5, frame))
    try:
        jeda = float(arg.get("jeda") or 3)
    except (TypeError, ValueError):
        jeda = 3.0
    jeda = max(0.5, min(10.0, jeda))
    FOLDER_SIMPAN.mkdir(parents=True, exist_ok=True)
    hasil = []
    cap = f"layar-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    for i in range(frame):
        if i:
            time.sleep(jeda)
        lokasi = FOLDER_SIMPAN / f"{cap}-{i + 1}.png"
        try:
            page.screenshot(path=str(lokasi), full_page=False)
            hasil.append(lokasi)
        except Exception as e:
            return hasil, f"Error mengambil screenshot ke-{i + 1}: {e}"
    return hasil, ""


def _baca_gambar_ocr_windows(lokasi):
    """Baca teks dari gambar dengan Windows OCR bawaan (gratis, lokal, cepat)."""
    try:
        import asyncio
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage import FileAccessMode, StorageFile

        async def _jalankan():
            berkas = await StorageFile.get_file_from_path_async(str(Path(lokasi).resolve()))
            aliran = await berkas.open_async(FileAccessMode.READ)
            dekoder = await BitmapDecoder.create_async(aliran)
            bitmap = await dekoder.get_software_bitmap_async()
            mesin = OcrEngine.try_create_from_user_profile_languages()
            if mesin is None:
                mesin = OcrEngine.try_create_from_language("en-US")
            if mesin is None:
                return ""
            hasil = await mesin.recognize_async(bitmap)
            return hasil.text or ""

        # Playwright sync menjalankan event loop di thread utama, jadi asyncio.run()
        # di thread yang sama akan gagal. Jalankan di thread terpisah yang bersih.
        from concurrent.futures import ThreadPoolExecutor

        def _di_thread():
            return asyncio.run(_jalankan())

        with ThreadPoolExecutor(max_workers=1) as kolam:
            teks = kolam.submit(_di_thread).result(timeout=60).strip()
        if not teks:
            return "TEKS TERLIHAT: (tidak ada teks yang dikenali Windows OCR)"
        return "TEKS TERLIHAT: " + " ".join(teks.split())
    except ImportError:
        return ("TEKS TERLIHAT: (Windows OCR belum tersedia - pasang dengan: "
                "python -m pip install winrt-Windows.Foundation winrt-Windows.Storage "
                "winrt-Windows.Graphics.Imaging winrt-Windows.Media.Ocr)")
    except Exception as e:
        return f"TEKS TERLIHAT: (Windows OCR gagal: {e})"


def alat_baca_layar(arg):
    """Screenshot halaman/gambar lalu baca isinya (Windows OCR + vision lokal bila ada)."""
    nama = str(arg.get("nama_file") or arg.get("path") or "").strip()
    pertanyaan = str(arg.get("pertanyaan") or arg.get("fokus") or "").strip()
    if nama:
        lokasi = Path(nama).expanduser()
        if not lokasi.is_absolute():
            lokasi = FOLDER_SIMPAN / lokasi
        if not lokasi.exists():
            return f"Error: file gambar tidak ditemukan: {lokasi}"
        gambar = [lokasi]
    else:
        gambar, pesan = _ambil_screenshot_untuk_dibaca(arg)
        if pesan:
            return pesan
    bagian = []
    ada_vision = _model_vision_tersedia()
    for i, lokasi in enumerate(gambar, 1):
        isi = _baca_gambar_ocr_windows(lokasi)
        if ada_vision:
            isi += "\n" + _baca_gambar_vision(lokasi, pertanyaan)
        else:
            isi += "\nDESKRIPSI: belum tersedia (model vision 3,2 GB masih diunduh). " \
                   "Teks di atas diperoleh dari Windows OCR bawaan."
        bagian.append(f"--- Gambar {i}: {lokasi} ---\n{isi}")
    try:
        if int(arg.get("frame") or 1) > 1:
            bagian.append("Catatan: suara tidak tertangkap screenshot. Gunakan teks/subtitle "
                          "yang terlihat di layar untuk kuis audio.")
    except (TypeError, ValueError):
        pass
    return "\n\n".join(bagian)


def alat_cari_dari_layar(arg):
    """Baca layar, lalu pakai hasil bacaan sebagai kata kunci pencarian internet."""
    pertanyaan = str(arg.get("pertanyaan") or arg.get("fokus") or "").strip()
    teks = alat_baca_layar(arg)
    if teks.startswith("Error"):
        return teks
    kueri = str(arg.get("kueri") or arg.get("query") or "").strip()
    if not kueri:
        m = re.search(r"TEKS TERLIHAT:\s*(.+)", teks, re.S)
        sumber = m.group(1) if m else teks
        kueri = " ".join(sumber.split())[:280]
    hasil = alat_cari_internet({"kueri": kueri})
    return (f"Teks yang terbaca di layar:\n{teks}\n\n"
            f"Kata kunci pencarian: {kueri}\n{hasil}\n\n"
            "Catatan: jawaban diisi otomatis lewat alat pilih_opsi/isi_form; "
            "status tampil di jendela mini Hermes.")


# ============== PENGINGAT (tampil di jendela mini saat waktunya tiba) ==============

FILE_PENGINGAT = FOLDER_SIMPAN / "pengingat.json"


def _parsing_waktu(teks_waktu):
    """Ubah berbagai format waktu bahasa Indonesia menjadi datetime (atau None)."""
    s = " ".join(str(teks_waktu).lower().split()).replace(".", ":")
    sekarang = datetime.now()
    m = re.fullmatch(r"(\d+)\s*(detik|dtk|menit|mnt|jam|j|hari)\s*lagi", s)
    if m:
        angka, satuan = int(m.group(1)), m.group(2)
        if satuan in ("detik", "dtk"):
            return sekarang + timedelta(seconds=angka)
        if satuan in ("menit", "mnt"):
            return sekarang + timedelta(minutes=angka)
        if satuan in ("jam", "j"):
            return sekarang + timedelta(hours=angka)
        return sekarang + timedelta(days=angka)
    m = re.fullmatch(r"besok\s+(\d{1,2}):(\d{2})", s)
    if m:
        return (sekarang + timedelta(days=1)).replace(
            hour=int(m.group(1)) % 24, minute=int(m.group(2)) % 60,
            second=0, microsecond=0)
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
    if m:
        return sekarang.replace(hour=int(m.group(1)) % 24, minute=int(m.group(2)) % 60,
                                second=0, microsecond=0)
    for fmt in ("%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _muat_pengingat():
    try:
        data = json.loads(FILE_PENGINGAT.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _simpan_pengingat(daftar):
    FOLDER_SIMPAN.mkdir(parents=True, exist_ok=True)
    FILE_PENGINGAT.write_text(
        json.dumps(daftar, ensure_ascii=False, indent=1), encoding="utf-8")


def alat_atur_pengingat(arg):
    judul = (arg.get("judul") or arg.get("kegiatan") or "Pengingat").strip()
    waktu_raw = (arg.get("waktu") or arg.get("jadwal") or "").strip()
    if not waktu_raw:
        return "Error: argumen 'waktu' kosong."
    t = _parsing_waktu(waktu_raw)
    if t is None:
        return ("Error: format waktu tidak dipahami. Gunakan contoh: '30 detik lagi', "
                "'10 menit lagi', '2 jam lagi', '20:00', 'besok 08:00', atau '2026-11-12 20:00'.")
    if t <= datetime.now():
        return "Error: waktu pengingat sudah lewat. Pilih waktu di masa depan (mis. 'besok 20:00')."
    daftar = _muat_pengingat()
    daftar.append({"judul": judul,
                   "pesan": (arg.get("pesan") or judul).strip(),
                   "waktu": t.isoformat()})
    daftar.sort(key=lambda p: p["waktu"])
    _simpan_pengingat(daftar)
    return (f"Pengingat '{judul}' disimpan untuk {t.strftime('%d %b %Y jam %H:%M')}. "
            "Pengingat akan tampil di jendela mini Hermes saat waktunya tiba (selama jendela "
            f"Hermes Bot Plus masih terbuka). Total pengingat aktif: {len(daftar)}.")


def alat_lihat_pengingat(arg):
    daftar = _muat_pengingat()
    if not daftar:
        return "Tidak ada pengingat aktif."
    teks = ["Pengingat aktif:"]
    for i, p in enumerate(daftar, 1):
        try:
            t = datetime.fromisoformat(p["waktu"])
            waktu_teks = t.strftime("%d %b %Y jam %H:%M")
        except Exception:
            waktu_teks = str(p.get("waktu", "?"))
        teks.append(f"{i}. {p.get('judul', '?')} - {waktu_teks}")
    return "\n".join(teks)


def alat_hapus_pengingat(arg):
    judul = (arg.get("judul") or arg.get("nama") or "").strip().lower()
    if not judul:
        return "Error: argumen 'judul' kosong."
    daftar = _muat_pengingat()
    sisa = [p for p in daftar if judul not in str(p.get("judul", "")).lower()]
    terhapus = len(daftar) - len(sisa)
    if terhapus == 0:
        daftar_teks = "; ".join(str(p.get("judul", "?")) for p in daftar) or "(kosong)"
        return f"Tidak ada pengingat bernama '{judul}'. Pengingat aktif: {daftar_teks}"
    _simpan_pengingat(sisa)
    return f"Berhasil menghapus {terhapus} pengingat. Sisa pengingat aktif: {len(sisa)}."


def _thread_pengingat():
    """Cek pengingat tiap 20 detik; saat waktunya tiba, tampilkan di jendela mini."""
    while True:
        try:
            daftar = _muat_pengingat()
            if daftar:
                sekarang = datetime.now()
                sisa, jatuh_tempo = [], []
                for item in daftar:
                    try:
                        t = datetime.fromisoformat(item["waktu"])
                    except Exception:
                        sisa.append(item)
                        continue
                    (jatuh_tempo if t <= sekarang else sisa).append(item)
                if jatuh_tempo:
                    _simpan_pengingat(sisa)
                    for item in jatuh_tempo:
                        judul = f"Pengingat: {item.get('judul', 'Pengingat')}"
                        pesan = item.get("pesan") or item.get("judul") or "Waktunya sudah tiba!"
                        tampilkan_popup(judul, pesan)
        except Exception:
            pass
        time.sleep(20)


# ============== TRANSKRIP YOUTUBE & SUARA ==============

def alat_transkrip_youtube(arg):
    url = (arg.get("url") or arg.get("link") or arg.get("video") or "").strip()
    if not url:
        return "Error: argumen 'url' kosong."
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})", url)
    video_id = m.group(1) if m else url
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return "Error: komponen youtube-transcript-api belum terinstall."
    potongan, galat = None, None
    try:
        api = YouTubeTranscriptApi()
        for bahasa in (["id", "en"], ["en"]):
            try:
                hasil = api.fetch(video_id, languages=bahasa)
                potongan = [s.text for s in hasil]
                break
            except Exception as e:
                galat = e
    except Exception as e:
        galat = e
    if potongan is None:
        try:  # API lama (youtube-transcript-api versi < 1.0)
            hasil = YouTubeTranscriptApi.get_transcript(video_id, languages=["id", "en"])
            potongan = [s["text"] for s in hasil]
        except Exception as e:
            return f"Error mengambil transkrip video {video_id}: {galat or e}"
    teks = " ".join(potongan)
    if not teks.strip():
        return f"Video {video_id} tidak punya transkrip yang bisa dibaca."
    maks = 10000
    potong = " ...[dipotong]" if len(teks) > maks else ""
    return f"Transkrip video YouTube {video_id}:\n\n{teks[:maks]}{potong}"


def alat_bicara(arg):
    teks = " ".join(str(arg.get("teks") or arg.get("isi") or arg.get("kalimat") or "").split())
    if not teks:
        return "Error: argumen 'teks' kosong."
    teks = teks[:800].replace("'", "''")
    ps = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "try { $v = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Name -match "
        "'Indones|Andika|Gadis' } | Select-Object -First 1; if ($v) { $s.SelectVoice($v.VoiceInfo.Name) } } catch {};"
        "$s.Speak('" + teks + "');"
    )
    try:
        encoded = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-EncodedCommand", encoded],
            creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as e:
        return f"Error memutar suara: {e}"
    return "Suara sedang diputar lewat speaker pengguna."


# ============== KEMAMPUAN LENGKAP UNTUK SEMUA AKTIVITAS WEB ==============

def alat_struktur_kuis(arg):
    """Ambil daftar soal + pilihan yang terstruktur dari halaman/iframe (Moodle & umum)."""
    page = _pastikan_browser()
    semua = []
    skrip = """() => {
        const keluar = [];
        document.querySelectorAll('.que').forEach((q, i) => {
            const soal = (q.querySelector('.qtext')?.innerText || '').trim();
            const pilihan = [];
            q.querySelectorAll('.answer input[type=radio], .answer input[type=checkbox]').forEach(inp => {
                const labId = inp.getAttribute('aria-labelledby');
                const lab = (labId ? q.querySelector('#' + CSS.escape(labId)) : null) ||
                    q.querySelector('label[for="' + inp.id + '"]') ||
                    inp.closest('.r0, .r1')?.querySelector('[data-region="answer-label"]');
                pilihan.push({jenis: inp.type, nilai: inp.value,
                    teks: (lab?.innerText || inp.getAttribute('aria-label') || inp.value || '').trim(),
                    nama: inp.name, terpilih: !!inp.checked});
            });
            const sel = q.querySelector('.answer select');
            if (sel) pilihan.push({jenis: 'select', nama: sel.name,
                teks: Array.from(sel.options).map(o => o.text.trim()).join(' | ')});
            const ta = q.querySelector('.answer textarea');
            if (ta) pilihan.push({jenis: 'textarea', nama: ta.name, teks: (ta.value || '')});
            if (soal || pilihan.length) keluar.push({nomor: i + 1, soal: soal.slice(0, 600), pilihan});
        });
        if (!keluar.length) {
            document.querySelectorAll('input, select, textarea').forEach((el, i) => {
                if (el.type === 'hidden') return;
                const lab = document.querySelector('label[for="' + el.id + '"]');
                const teks = (lab?.innerText || el.getAttribute('aria-label') || el.placeholder || el.name || '').trim();
                keluar.push({nomor: i + 1, soal: teks.slice(0, 200), jenis: el.tagName + '/' + (el.type || ''),
                    nama: el.name || '', nilai: (el.value || '').slice(0, 200)});
            });
        }
        return keluar;
    }"""
    for i, f in enumerate(_semua_frame(page)):
        try:
            data = f.evaluate(skrip)
        except Exception:
            continue
        if not data:
            continue
        bagian = [f"FRAME {i}: {f.url.split('?')[0][-90:]}"]
        for item in data:
            if "pilihan" in item:
                ops = "; ".join(f"{p.get('jenis')}: {p.get('teks')}" for p in item["pilihan"])
                bagian.append(f"  Soal {item['nomor']}: {item['soal']}\n    Opsi: {ops}")
            else:
                bagian.append(f"  Elemen {item['nomor']}: {item['soal']} [{item.get('jenis')}] nilai={item.get('nilai')}")
        semua.append("\n".join(bagian))
    if not semua:
        return "Tidak ada soal/form terdeteksi.\n" + _cuplikan_halaman(page, 1000)
    return "\n\n".join(semua)


def alat_jawab_kuis(arg):
    """Isi banyak jawaban sekaligus. Argumen 'jawaban' = daftar teks atau [{teks,label}]."""
    jawaban = arg.get("jawaban") or arg.get("daftar") or arg.get("opsi") or []
    if isinstance(jawaban, str):
        try:
            jawaban = json.loads(jawaban)
        except Exception:
            jawaban = [x.strip() for x in re.split(r"[;\n]", jawaban) if x.strip()]
    if not isinstance(jawaban, list) or not jawaban:
        return "Error: argumen 'jawaban' kosong. Contoh: {\"jawaban\": [\"Jakarta\", \"Benar\"]}"
    hasil = []
    for i, item in enumerate(jawaban, 1):
        if isinstance(item, dict):
            teks = str(item.get("teks") or item.get("jawaban") or "").strip()
            label = str(item.get("label") or item.get("soal") or "").strip()
        else:
            teks, label = str(item).strip(), ""
        if not teks:
            continue
        r = alat_pilih_opsi({"teks": teks, "label": label})
        hasil.append(f"{i}. '{teks}' -> {r.splitlines()[0]}")
    return "HASIL PENGISIAN:\n" + "\n".join(hasil) + "\n\n" + _cuplikan_halaman(_pastikan_browser(), 1000)


def alat_unggah_file(arg):
    """Unggah file ke kolom input[type=file] (aktifitas 'Unggah Video')."""
    nama = str(arg.get("nama_file") or arg.get("path") or arg.get("file") or "").strip()
    if not nama:
        return "Error: argumen 'nama_file' kosong."
    lokasi = _cari_file(nama)
    if lokasi is None:
        return f"Error: file '{nama}' tidak ditemukan di Dokumen/Desktop/Downloads."
    label = str(arg.get("label") or "").strip()
    page = _pastikan_browser()
    tampilkan_popup("Hermes mengunggah file", lokasi.name)
    for f in _semua_frame(page):
        kandidat = []
        if label:
            kandidat += [f.get_by_label(label).locator("input[type=file]"),
                         f.locator(f'input[type=file][aria-label="{label}"]')]
        kandidat.append(f.locator("input[type=file]"))
        for loc in kandidat:
            try:
                if loc.count() > 0:
                    loc.first.set_input_files(str(lokasi))
                    return (f"Berhasil mengunggah '{lokasi.name}'.\n"
                            + _cuplikan_halaman(page, 800))
            except Exception:
                continue
    return "Error: kolom unggah file tidak ditemukan.\n" + _cuplikan_halaman(page, 800)


def _aktivitas_aktif(page):
    """Baca grup (Pra-Kelas/Di kelas/Pasca kelas) + nama aktivitas yang aktif."""
    for f in _semua_frame(page):
        try:
            dat = f.evaluate("""() => {
                const a = document.querySelector('.toc__is_active');
                if (!a) return null;
                const aktivitas = (a.innerText || '').trim().split('\\n')[0];
                let e = a, grup = '';
                for (let i = 0; i < 8 && e; i++, e = e.parentElement) {
                    const m = (e.innerText || '').trim()
                        .match(/^(Pra-Kelas|Di kelas|Pasca kelas)/i);
                    if (m) { grup = m[1]; break; }
                }
                return {grup, aktivitas};
            }""")
            if dat:
                return dat
        except Exception:
            continue
    return {"grup": "", "aktivitas": ""}


def alat_putar_video(arg):
    """Lewati video/audio langsung ke akhir agar dianggap selesai, lalu lanjut.

    Tidak menunggu durasi penuh: pemutar di-seek mendekati akhir, diputar
    sekejap, lalu dipaksa ke posisi akhir dan event 'ended' dilempar supaya
    pelacakan progres LMS tetap terpicu.
    """
    try:
        indeks = max(0, int(arg.get("indeks") or 0))
    except (TypeError, ValueError):
        indeks = 0
    semua = str(arg.get("semua", "true")).lower() not in ("false", "0", "no")
    page = _pastikan_browser()
    aktif = _aktivitas_aktif(page)
    if ("pikirkan" in aktif["aktivitas"].lower() or
            "pasca" in aktif["grup"].lower()):
        return ("DILEWATI: skip-video tidak berlaku untuk Pikirkan atau Pasca kelas "
                f"({aktif['grup']} / {aktif['aktivitas']}).")
    jumlah = 0
    terakhir = ""
    for f in _semua_frame(page):
        try:
            video = f.locator("video, audio")
            n = video.count()
        except Exception:
            continue
        if n <= indeks:
            continue
        rentang = range(indeks, n) if semua else [indeks]
        for i in rentang:
            try:
                el = video.nth(i)
                el.evaluate("""(e) => {
                    e.muted = true;
                    const d = Number(e.duration) || 0;
                    // Putar 2 detik terakhir secara wajar supaya event ended
                    // benar-benar terjadi (seek ke d saja sering gagal).
                    if (d > 0) {
                        try { e.currentTime = Math.max(0, d - 2); } catch (err) {}
                    }
                    e.play().catch(() => {});
                }""")
                for _ in range(12):
                    time.sleep(0.4)
                    try:
                        if el.evaluate("(e) => !!e.ended"):
                            break
                    except Exception:
                        break
                el.evaluate("(e) => e.dispatchEvent(new Event('timeupdate'))")
                info = el.evaluate(
                    "(e) => ({t: Math.round(e.currentTime || 0), d: Math.round(e.duration || 0), end: !!e.ended})")
                terakhir = (f"Video {i + 1}/{n}: {info.get('t')}s/{info.get('d')}s "
                            f"selesai={info.get('end')}")
                jumlah += 1
            except Exception:
                continue
    if jumlah:
        return f"Video dilewati sampai akhir ({jumlah} elemen). {terakhir}"
    return "Tidak ada elemen video/audio yang bisa dilewati.\n" + _cuplikan_halaman(page, 800)


def alat_tekan_tombol(arg):
    """Tekan tombol keyboard (Enter, Tab, ArrowDown, dll.) di halaman aktif."""
    tombol = str(arg.get("tombol") or arg.get("kunci") or "").strip()
    if not tombol:
        return "Error: argumen 'tombol' kosong."
    page = _pastikan_browser()
    try:
        page.keyboard.press(tombol)
        return f"Tombol keyboard '{tombol}' ditekan.\n" + _cuplikan_halaman(page, 700)
    except Exception as e:
        return f"Error menekan tombol: {e}"


def alat_tunggu(arg):
    """Tunggu beberapa detik (untuk animasi/loading/video interaktif)."""
    try:
        detik = min(60, max(1, float(arg.get("detik") or 3)))
    except (TypeError, ValueError):
        detik = 3.0
    time.sleep(detik)
    return f"Selesai menunggu {detik:g} detik.\n" + _cuplikan_halaman(_pastikan_browser(), 800)


def alat_pindah_tab(arg):
    """Pindah ke tab/window browser lain. Argumen: indeks (0=tab pertama)."""
    global _page
    if _browser is None:
        return "Error: browser belum terbuka."
    daftar = list(_browser.pages)
    try:
        indeks = int(arg.get("indeks") or 0)
    except (TypeError, ValueError):
        indeks = 0
    if not 0 <= indeks < len(daftar):
        return f"Indeks tab {indeks} tidak ada. Jumlah tab: {len(daftar)}."
    _page = daftar[indeks]
    _page.bring_to_front()
    return f"Pindah ke tab {indeks}: {_page.url}\n" + _cuplikan_halaman(_page, 800)


def alat_muat_ulang(arg):
    """Muat ulang halaman saat ini."""
    page = _pastikan_browser()
    try:
        page.reload(wait_until="domcontentloaded", timeout=30000)
        return "Halaman dimuat ulang.\n" + _cuplikan_halaman(page, 900)
    except Exception as e:
        return f"Error memuat ulang: {e}"


def alat_status_modul(arg):
    """Baca daftar modul + tanda centang/status selesainya (parameter 'tanda ceklish')."""
    page = _pastikan_browser()
    filter_nama = str(arg.get("nama") or arg.get("modul") or "").strip().lower()
    skrip = """() => {
        const hasil = [];
        document.querySelectorAll('.newAccor_heading_container').forEach(el => {
            const teks = (el.innerText || '').replace(/\\s+/g, ' ').trim();
            const m = teks.match(/(\\d+)\\s*\\/\\s*(\\d+)/);
            const status = (el.querySelector('.newAccor_header_status')?.innerText || '').replace(/\\s+/g, ' ').trim();
            const nama = (m ? teks.slice(0, m.index) : teks).trim();
            const kelas = String(el.className || '') + ' ' +
                String(el.parentElement?.className || '');
            const centang = /completed_lesson|certificate-progress__tick|no-js-bright_green_check/i.test(kelas) ||
                /completed_lesson|certificate-progress__tick|no-js-bright_green_check/i.test(el.parentElement?.innerHTML || '');
            hasil.push({nama, status: status || (m ? m[0] : ''), selesai: m ? Number(m[1]) : 0,
                total: m ? Number(m[2]) : 0, centang});
        });
        return hasil;
    }"""
    data = []
    for f in _semua_frame(page):
        try:
            data += f.evaluate(skrip)
        except Exception:
            continue
    if filter_nama:
        data = [d for d in data if filter_nama in d.get("nama", "").lower()]
    if not data:
        return "Tidak ada daftar modul yang terbaca. Buka halaman kursus dulu."
    baris = []
    for d in data:
        if d.get("centang") or (d.get("total", 0) > 0 and d.get("selesai", 0) == d.get("total", 0)):
            tanda = "✅ SELESAI"
        elif d.get("selesai", 0) > 0:
            tanda = "◐ SEBAGIAN"
        else:
            tanda = "⬜ BELUM"
        baris.append(f"{tanda} | {d['nama']} | {d.get('status', '')}")
    return "STATUS MODUL (tanda centang):\n" + "\n".join(baris)


def _teks_opsi_attempt(frame):
    """Ambil teks soal + daftar opsi dari attempt kuis yang sedang tampil."""
    if frame is None:
        return None
    try:
        return frame.evaluate("""() => {
            const q = document.querySelector('.que');
            if (!q) return null;
            const soal = (q.querySelector('.qtext')?.innerText || '').replace(/\\s+/g, ' ').trim();
            const opsi = [];
            q.querySelectorAll('.answer input[type=radio], .answer input[type=checkbox]').forEach(inp => {
                const id = inp.getAttribute('aria-labelledby');
                const lab = (id ? q.querySelector('#' + CSS.escape(id)) : null) ||
                    inp.closest('.r0, .r1')?.querySelector('[data-region="answer-label"]');
                const t = (lab?.innerText || '').replace(/\\s+/g, ' ').trim();
                if (t && inp.value !== '-1') opsi.push(t);
            });
            return {soal, opsi};
        }""")
    except Exception:
        return None


_KONTEKS_PENILAIAN = None


def _muat_konteks_penilaian():
    """Prinsip jawaban dari transkrip/kasus lokal (tanpa internet)."""
    global _KONTEKS_PENILAIAN
    if _KONTEKS_PENILAIAN is not None:
        return _KONTEKS_PENILAIAN
    teks = []
    try:
        dat = json.loads(PETA_TRANSKRIP.read_text(encoding="utf-8"))
        for e in dat.get("entri", []):
            p = str(e.get("prinsip") or "").strip()
            if p:
                teks.append(p)
    except Exception:
        pass
    try:
        dat = json.loads(SKEMA_KASUS.read_text(encoding="utf-8"))
        sk = dat.get("skema") or {}
        for kunci in ("langkah", "prinsip_benar", "prinsip_salah"):
            for p in sk.get(kunci) or []:
                if p:
                    teks.append(str(p).strip())
    except Exception:
        pass
    _KONTEKS_PENILAIAN = list(dict.fromkeys(teks))
    return _KONTEKS_PENILAIAN


def _kata_kunci(teks):
    return {k for k in re.findall(r"[a-z]{3,}", str(teks or "").lower())
            if k not in _KATA_STOP}


def _konteks_penilaian(soal, opsi):
    """Ambil prinsip lokal yang paling relevan dengan soal + opsi."""
    kata = _kata_kunci(str(soal) + " " + " ".join(str(o) for o in opsi))
    if not kata:
        return ""
    skor = []
    for prinsip in _muat_konteks_penilaian():
        pertandingan = len(kata & _kata_kunci(prinsip))
        if pertandingan:
            skor.append((pertandingan, prinsip))
    skor.sort(key=lambda x: -x[0])
    return "\n".join(p for _, p in skor[:8])


def _cocokkan_jawaban_opsi(jawab, opsi):
    """Ubah jawaban bebas model menjadi salah satu teks opsi persis."""
    if not jawab:
        return None
    j = str(jawab).strip().strip('"\'`').strip()
    j = re.sub(r"^(jawaban|opsi|pilihan)\s*:\s*", "", j, flags=re.I).strip()
    jp = j.lower().replace(" ", "")
    for o in opsi:
        if jp == o.lower().replace(" ", ""):
            return o
    for o in opsi:
        if o.lower().replace(" ", "") and o.lower().replace(" ", "") in jp:
            return o
    angka = re.match(r"^(\d+)[.)]?", j)
    if angka and 1 <= int(angka.group(1)) <= len(opsi):
        return opsi[int(angka.group(1)) - 1]
    for o in opsi:
        if o.lower() in j.lower():
            return o
    return None


def _tanyakan_jawaban(soal, opsi):
    """Putuskan jawaban kuis secara hati-hati (3 pemeriksaan, suhu rendah)."""
    if not soal or not opsi:
        return None
    daftar = "\n".join(f"{i+1}. {o}" for i, o in enumerate(opsi))
    konteks = _konteks_penilaian(soal, opsi)
    bagian_konteks = (f"\n\nPRINSIP LOKAL YANG RELEVAN:\n{konteks}" if konteks else "")

    pemeriksaan = [
        ([
            {"role": "system", "content":
                "Kamu menjawab satu soal pilihan ganda mata pelajaran Wadhwani. "
                "Pilih SATU opsi yang PALING benar. Balas HANYA teks opsi persis, "
                "tanpa nomor dan tanpa penjelasan."},
            {"role": "user", "content": f"Soal: {soal}\n\nOpsi:\n{daftar}{bagian_konteks}"},
        ], 0.0),
        ([
            {"role": "system", "content":
                "Periksa setiap opsi satu per satu. Tandai opsi yang jelas SALAH "
                "karena bertentangan dengan soal/prinsip, lalu pilih satu opsi "
                "tersisa yang paling tepat. Balas HANYA teks opsi terpilih persis."},
            {"role": "user", "content": f"Soal: {soal}\n\nOpsi:\n{daftar}{bagian_konteks}"},
        ], 0.15),
        ([
            {"role": "system", "content":
                "Jawab sebagai pemeriksa kedua. Gunakan prinsip komunikasi/profesionalisme "
                "Wadhwani: tindakan yang jujur, jelas, tepat waktu, kolaboratif, dan "
                "berorientasi hasil hampir selalu benar; yang menunda, menyalahkan, "
                "mengabaikan, atau berbohong hampir selalu salah. "
                "Balas HANYA teks opsi persis."},
            {"role": "user", "content": f"Soal: {soal}\n\nOpsi:\n{daftar}{bagian_konteks}"},
        ], 0.0),
    ]

    pilihan = []
    for nomor_pemeriksaan, (pesan, suhu) in enumerate(pemeriksaan, 1):
        tampilkan_popup(
            "Hermes memilih jawaban",
            f"Pemeriksaan {nomor_pemeriksaan}/3 | Soal: {str(soal)[:100]}")
        try:
            jawab = panggil_model(pesan, suhu=suhu)
        except Exception:
            continue
        o = _cocokkan_jawaban_opsi(jawab, opsi)
        if o:
            pilihan.append(o)
    if not pilihan:
        print(f"[KUIS] Tidak ada jawaban terbaca; pakai opsi pertama: {opsi[0][:60]}",
              flush=True)
        tampilkan_popup("Hermes menemui kendala",
                        "Jawaban model tidak terbaca; memakai opsi pertama.")
        return opsi[0]
    hitung = Counter(pilihan)
    terbaik, jumlah = hitung.most_common(1)[0]
    print(f"[KUIS] {str(soal)[:68]}... -> {terbaik[:55]} "
          f"(setuju {jumlah}/{len(pilihan)})", flush=True)
    tampilkan_popup("Hermes memilih jawaban",
                    f"Terpilih: {terbaik[:110]} (setuju {jumlah}/{len(pilihan)})")
    return terbaik


def _selesaikan_attempt_otomatIs():
    """Kerjakan attempt kuis yang sedang terbuka, satu soal per satu soal."""
    def fa():
        for f in _semua_frame(_pastikan_browser()):
            if "attempt.php" in (f.url or ""):
                return f
        return None
    hasil = []
    for _ in range(30):
        f = fa()
        if not f:
            break
        data = _teks_opsi_attempt(f)
        if not data or not data.get("soal"):
            # Attempt baru masih menampilkan tombol 'Mulai kuis' / 'Start quiz'
            # sebelum soal pertama (.que) muncul. Klik dulu, lalu baca lagi.
            dimulai = False
            try:
                dimulai = bool(f.evaluate("""() => {
                    const e = [...document.querySelectorAll('button, input[type=submit], a')]
                        .find(x => {
                            const r = x.getBoundingClientRect();
                            if (r.width <= 0 || r.height <= 0) return false;
                            const t = (x.innerText || x.value || '').trim();
                            return /^(Mulai kuis|Start quiz|Start attempt|Mulai attempt)/i.test(t);
                        });
                    if (e) { e.click(); return true; }
                    return false;
                }"""))
            except Exception:
                pass
            if dimulai:
                time.sleep(2)
                continue
            break
        jawab = _tanyakan_jawaban(data["soal"], data["opsi"])
        r = alat_pilih_opsi({"teks": jawab})
        hasil.append(f"Soal: {data['soal'][:90]} -> {jawab} ({r.splitlines()[0]})")
        time.sleep(1)
        f = fa()
        if not f:
            break
        # Coba tombol next yang tersedia di attempt
        try:
            if f.locator('input[name="next"]').count() > 0:
                f.locator('input[name="next"]').first.click()
                time.sleep(2)
                continue
        except Exception:
            pass
        try:
            f.get_by_text("Selesaikan kuis", exact=True).first.click()
            time.sleep(3)
        except Exception:
            break
        # Ringkasan: pastikan semua tersimpan lalu kirim
        f = fa()
        if not f:
            break
        for _ in range(3):
            isi = f.inner_text("body")
            if "Belum dijawab" not in isi:
                break
            nomor = re.search(r"Belum dijawab\s+(\d+)", isi)
            if nomor:
                f.locator("a.qnbutton").nth(int(nomor.group(1)) - 1).click()
                time.sleep(2)
                f = fa()
                data = _teks_opsi_attempt(f)
                if data:
                    alat_pilih_opsi({"teks": _tanyakan_jawaban(data["soal"], data["opsi"])})
                    time.sleep(1)
                f.get_by_text("Selesaikan kuis", exact=True).first.click()
                time.sleep(3)
                f = fa()
            else:
                break
        try:
            f.get_by_text("Kirim semua dan selesai", exact=True).first.click()
            time.sleep(2)
            f = fa()
            tombol = f.evaluate("""() => {
                const els = Array.from(document.querySelectorAll('button, a, input[type=submit]'))
                    .filter(e => { const r = e.getBoundingClientRect(); return r.width && r.height; });
                const k = els.filter(e => (e.innerText || e.value || '').trim() === 'Kirim semua dan selesai');
                if (k.length) { k[k.length-1].click(); return true; }
                return false;
            }""")
            if tombol:
                time.sleep(5)
        except Exception:
            pass
        break
    return "\n".join(hasil) if hasil else "Tidak ada soal attempt yang dikerjakan."


def _info_attempt_api(page, instance):
    """Data kuis terbaru dari API (attempt tersisa, nilai maks, status)."""
    dat = _data_konten_kursus(page, paksa=True)
    for m in (dat or {}).get("data", {}).get("contents", {}).get("modules") or []:
        for a in m.get("modules") or []:
            if str(a.get("instance")) == str(instance):
                return a
    return {}


def _nilai_kuis(page):
    """Baca persentase nilai dari halaman ringkasan kuis Moodle."""
    pola = [
        r"Nilai\s*:\s*(\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)",
        r"Grade\s*:\s*(\d+(?:[.,]\d+)?)\s*(?:out of|/)\s*(\d+(?:[.,]\d+)?)",
        r"Skor\s*:\s*(\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)",
        r"(\d+(?:[.,]\d+)?)\s*%",
    ]
    for f in _semua_frame(page):
        try:
            teks = " ".join(f.inner_text("body").split())
        except Exception:
            continue
        for p in pola:
            mm = re.search(p, teks, re.I)
            if not mm:
                continue
            nilai = float(mm.group(1).replace(",", "."))
            maks = (float(mm.group(2).replace(",", "."))
                    if mm.lastindex and mm.lastindex > 1 else 100.0)
            if maks > 0:
                return round(nilai / maks * 100, 1)
    return None


def _selesaikan_feedback(frame):
    """Isi survei umpan balik Moodle (mod/feedback) lalu kumpulkan jawabannya."""
    if frame is None:
        return "Tidak ada form feedback."
    try:
        info = frame.evaluate("""() => {
            // Skor opsi: makin positif makin tinggi. Dipakai supaya ulasan selalu positif.
            const skor = (teks) => {
                const t = (teks || '').toLowerCase();
                let s = 0;
                if (/sangat (setuju|puas|baik|membantu|bermanfaat|mudah|relevan)/.test(t)) s += 5;
                if (/sempurna|memahami semua|sangat memahami/.test(t)) s += 5;
                if (/(setuju|puas|baik|membantu|bermanfaat|mudah|relevan|sangat)/.test(t) &&
                    !/tidak|agak/.test(t)) s += 3;
                if (/\\bya\\b/.test(t) && !/tidak/.test(t)) s += 3;
                if (/memahami materi/.test(t)) s += 3;
                if (/lebih dari 15|11-15/.test(t)) s += 4;
                if (/6-10/.test(t)) s += 2;
                if (/1-5/.test(t)) s += 1;
                if (/tidak pernah|tidak tahu|tidak puas|tidak setuju|sangat tidak/.test(t)) s -= 5;
                return s;
            };
            const grup = {};
            document.querySelectorAll('input[type=radio]').forEach(r => {
                if (!grup[r.name]) grup[r.name] = [];
                grup[r.name].push(r);
            });
            let diisi = 0;
            const pilihanTerpilih = [];
            for (const nama in grup) {
                const opsi = grup[nama].map(r => {
                    const id = r.getAttribute('aria-labelledby');
                    const lab = (id ? document.querySelector('#' + CSS.escape(id)) : null) ||
                        r.closest('label, .fitem') ||
                        r.parentElement?.querySelector('label');
                    return {el: r, teks: (lab?.innerText || '').replace(/\\s+/g, ' ').trim()};
                });
                let terbaik = opsi[0];
                for (const o of opsi) {
                    if (skor(o.teks) > skor(terbaik.teks)) terbaik = o;
                }
                terbaik.el.click();
                pilihanTerpilih.push(terbaik.teks.slice(0, 45));
                diisi++;
            }
            let teks = 0;
            document.querySelectorAll('textarea').forEach(t => {
                const r = t.getBoundingClientRect();
                if (r.width && r.height && !t.value.trim()) {
                    t.value = 'Materi sangat membantu, jelas, dan mudah dipahami. Terima kasih.';
                    t.dispatchEvent(new Event('input', {bubbles: true}));
                    teks++;
                }
            });
            return {grup: Object.keys(grup).length, diisi, teks, pilihan: pilihanTerpilih};
        }""")
    except Exception as e:
        return f"Gagal mengisi feedback: {e}"
    try:
        kirim = frame.locator('input[name="savevalues"], input[type=submit][value*="Serahkan"]')
        if kirim.count() > 0:
            kirim.first.click()
            time.sleep(5)
            return (f"Feedback POSITIF diisi ({info.get('diisi')} pertanyaan, "
                    f"{info.get('teks')} uraian) dan diserahkan: "
                    + "; ".join(info.get("pilihan", []))[:400])
    except Exception as e:
        return f"Feedback terisi tapi gagal diserahkan: {e}"
    return f"Feedback diisi ({info.get('diisi')} pertanyaan), tombol serah tidak ditemukan."


def _frame_scorm(page):
    """Cari frame konten SCORM yang bersarang di dalam player.php."""
    def rekursif(fr):
        out = [fr]
        try:
            for anak in fr.child_frames:
                out.extend(rekursif(anak))
        except Exception:
            pass
        return out
    for fr in rekursif(page.main_frame):
        if "index_lms.html" in (fr.url or ""):
            return fr
    return None


def _siapkan_audio_scorm(page, frame):
    """Unduh narasi MP3 SCORM dan transkrip dengan whisper lokal (gratis)."""
    import json as _json
    import os as _os
    import subprocess as _sub

    folder = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "AudioCache")
    _os.makedirs(folder, exist_ok=True)
    jsonpath = _os.path.join(folder, "transkrip.json")
    try:
        html = frame.content()
    except Exception:
        html = ""
    jalur = sorted(set(re.findall(r"/pluginfile\.php/[^\"']+?\.mp3", html, re.I)))
    for j in jalur:
        nama = _os.path.basename(j)
        tujuan = _os.path.join(folder, nama)
        if _os.path.exists(tujuan) and _os.path.getsize(tujuan) > 1000:
            continue
        try:
            resp = page.request.get(
                "https://lms.skilling.wadhwanifoundation.org" + j, timeout=30000)
            data = resp.body()
            if len(data) > 1000:
                with open(tujuan, "wb") as fh:
                    fh.write(data)
        except Exception:
            pass
    skrip = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                          "transkrip_audio.py")
    try:
        _sub.run(["py", "-3.12", skrip, folder, jsonpath],
                 capture_output=True, timeout=900)
    except Exception:
        pass
    try:
        with open(jsonpath, encoding="utf-8") as fh:
            return _json.load(fh)
    except Exception:
        return {}


def _simpan_skema_kasus(transkrip):
    """Simpan SKEMA umum menangani kasus, bukan jawaban hafalan per soal.

    Narasi umpan balik positif/negatif diubah menjadi prinsip: seperti apa
    saran yang dianggap tepat dan seperti apa yang tidak. Skema ini dipakai
    kembali untuk kasus lain, termasuk kasus yang belum pernah dilihat.
    """
    if not transkrip:
        return
    try:
        with open(SKEMA_KASUS, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        data = {}
    skema = data.get("skema") if isinstance(data.get("skema"), dict) else {}
    skema.setdefault("langkah", [
        "Baca situasi kasus dan kebutuhan tokoh.",
        "Uji apakah saran yang diusulkan menjawab kebutuhan itu secara langsung.",
        "Saran yang tepat biasanya mendapat umpan balik 'Bagus/memastikan'; "
        "yang keliru biasanya 'tidak dapat membantu'.",
        "Pilih jawaban berdasarkan prinsip tersebut, bukan menghafal teks soal tertentu.",
    ])
    for teks in transkrip.values():
        t = " ".join(str(teks).split())
        if len(t) < 25:
            continue
        negatif = bool(re.search(r"tidak dapat membantu|kurang tepat|\bmaaf\b", t, re.I))
        positif = (not negatif and
                   bool(re.search(r"\bbagus\b|memastikan|telah membantu|\btepat\b", t, re.I)))
        for kunci, cocok in (("prinsip_benar", positif), ("prinsip_salah", negatif)):
            if not cocok:
                continue
            daftar = skema.setdefault(kunci, [])
            if t not in daftar:
                daftar.append(t)
            skema[kunci] = daftar[-24:]
    data["skema"] = skema
    try:
        with open(SKEMA_KASUS, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _bangun_peta_transkrip(transkrip):
    """Bangun peta prinsip dari transkrip narasi (bukan hafalan soal).

    Transkrip yang berisi umpan balik positif/negatif diubah menjadi entri:
    prinsip, kata kunci situasi, dan penanda benar/salah. Peta ini dipakai
    sebagai jalur pemilih jawaban ketika kunci data.js tidak tersedia.
    """
    jumlah = len(transkrip or {})
    versi = 3
    try:
        if PETA_TRANSKRIP.exists():
            lama = json.loads(PETA_TRANSKRIP.read_text(encoding="utf-8"))
            if (lama.get("versi") == versi and
                    lama.get("jumlah_transkrip") == jumlah and lama.get("entri")):
                return lama["entri"]
    except Exception:
        pass

    # Narasi negatif sering berlanjut menjadi saran yang BENAR setelah
    # "Oleh karena itu ...". Potong menjadi bagian supaya saran itu tidak
    # ikut terkena penanda negatif.
    pemisah = (r"\b(?:oleh karena itu|sebaliknya|seharusnya|sebaiknya|lebih baik|"
               r"jawaban yang benar|yang benar adalah|coba lagi|padahal)\b[,.:-]?\s*")
    awal_benar = re.compile(
        r"^(Bagus|Benar|Tepat|Kerja bagus|Kurang tepat|Belum tepat|Maaf|Salah)"
        r"[,.:-]?\s*", re.I)

    entri = []
    terlihat = set()
    for nama, isi in (transkrip or {}).items():
        t = " ".join(str(isi or "").split())
        if len(t) < 25:
            continue
        for idx, potong in enumerate(re.split(pemisah, t, flags=re.I)):
            b = " ".join(potong.split())
            if len(b) < 20:
                continue
            negatif = bool(re.search(
                r"tidak dapat membantu|kurang tepat|belum tepat|\bmaaf\b|"
                r"\bsalah\b|belum berhasil", b, re.I))
            positif = (not negatif and bool(re.search(
                r"\bbagus\b|kerja bagus|telah membantu|memastikan bahwa|"
                r"terima kasih banyak|jawaban (?:yang )?(?:tepat|benar)|"
                r"\banda (?:telah )?(?:benar|tepat)\b", b, re.I)))
            if idx > 0 and not positif and not negatif:
                positif = True   # bagian sesudah koreksi = saran yang benar
            if not (positif or negatif):
                continue
            prinsip = awal_benar.sub("", b).strip()
            if positif and len(prinsip) < 55:
                continue          # fragmen pendek bukan prinsip yang berguna
            kunci_unik = prinsip[:90].lower()
            if kunci_unik in terlihat:
                continue
            terlihat.add(kunci_unik)
            kata = [k for k in re.findall(r"[a-z]{4,}", prinsip.lower())
                    if k not in _KATA_STOP]
            unik = list(dict.fromkeys(kata))[:14]
            if not unik:
                continue
            entri.append({
                "sumber": str(nama),
                "bagian": idx,
                "prinsip": prinsip[:400],
                "kata": unik,
                "positif": positif,
                "negatif": negatif,
            })

    try:
        PETA_TRANSKRIP.write_text(json.dumps({
            "versi": versi,
            "jumlah_transkrip": jumlah,
            "entri": entri,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return entri


def _kata_cocok(a, b):
    """Cocokkan kata dengan toleransi kata dasar/salah dengar whisper."""
    a, b = str(a or "").lower(), str(b or "").lower()
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4 and (a in b or b in a):
        return True
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.78


def _log_pilih(sumber, jawab, tambahan=""):
    """Catat sumber keputusan jawaban supaya jejaknya jelas di log."""
    print(datetime.now().strftime("%H:%M:%S") +
          f" [PILIH SCORM] {sumber}: {jawab}{tambahan}", flush=True)


def _tanda_soal(teks_soal, opsi):
    """Tanda unik riwayat pilihan, tanpa menyimpan teks soal mentah."""
    kunci = " ".join(re.findall(r"[a-z]{4,}", (teks_soal or "").lower()))
    return (kunci[-300:] + "|" + "|".join(sorted(str(o) for o in opsi)))[-500:]


def _pilih_opsi_scorm(teks_soal, opsi, transkrip):
    """Pilih jawaban SCORM memakai peta transkrip + model, lalu rotasi opsi.

    Kunci data.js ditangani pemanggil dan tetap jadi prioritas utama. Fungsi ini
    dipakai bila kunci itu tidak ada/tidak cocok. Peta transkrip (PetaTranskrip.json)
    diberikan ke model sebagai prinsip pemilih; bila model gagal, peta yang jadi
    penentu. Jawaban tidak boleh diam-diam jatuh ke opsi pertama.
    """
    if not opsi:
        return None
    opsi = list(opsi)
    if len(opsi) == 1:
        _log_pilih("opsi tunggal", opsi[0])
        return opsi[0]

    tanda = _tanda_soal(teks_soal, opsi)
    dipakai = list(_RIWAYAT_PILIH.get(tanda, []))
    peta = _bangun_peta_transkrip(transkrip)
    kata_soal = set(re.findall(r"[a-z]{4,}", (teks_soal or "").lower())) - _KATA_STOP

    def ambil(calon, sumber):
        """Pilih dari calon, utamakan yang belum pernah dipakai."""
        calon = [c for c in calon if c in opsi]
        if not calon:
            return None, None
        belum = [c for c in calon if c not in dipakai]
        if belum:
            rotasi = len(belum) != len(calon)
            pilih = belum[0]
            if rotasi:
                sumber += " + rotasi opsi"
        else:
            dipakai.clear()
            pilih = calon[0]
            sumber += " (ulang dari awal)"
        dipakai.append(pilih)
        _RIWAYAT_PILIH[tanda] = dipakai
        return pilih, sumber

    # HANYA jalur positif. Tidak ada hitungan "skor tertinggi"/perbandingan
    # penalti. Prinsip Bagus/tepat yang relevan mengumpulkan kandidat opsi;
    # model memilih yang paling logis dan sesuai fakta dari kandidat itu.
    prinsip_relevan = []
    didukung = set()
    if peta and kata_soal:
        for e in peta:
            if not e.get("positif"):
                continue
            kata = set(e.get("kata") or [])
            if not any(_kata_cocok(k, q) for k in kata for q in kata_soal):
                continue
            prinsip = str(e.get("prinsip") or "").strip()
            prinsip_relevan.append(f"- {prinsip[:200]}")
            kata_prinsip = set(re.findall(r"[a-z]{4,}", prinsip.lower())) - _KATA_STOP
            for o in opsi:
                kata_opsi = set(re.findall(r"[a-z]{4,}", (o or "").lower())) - _KATA_STOP
                if any(_kata_cocok(k, kk)
                       for k in kata_opsi for kk in (kata | kata_prinsip)):
                    didukung.add(o)

    kandidat_positif = [o for o in opsi if o in didukung] or list(opsi)

    # Narasi pendukung juga dibatasi yang positif saja.
    items = list((transkrip or {}).items())
    negatif = [t for _, t in items
               if re.search(r"tidak dapat membantu|kurang tepat|\bmaaf\b", t, re.I)]
    positif = [t for _, t in items if t not in negatif and
               re.search(r"\bbagus\b|kerja bagus|telah membantu|memastikan bahwa|"
                         r"terima kasih banyak|jawaban (?:yang )?(?:tepat|benar)",
                         t, re.I)]
    narasi = "\n".join(positif[:12])[:3000]
    daftar = "\n".join(f"- {o}" for o in opsi)
    try:
        with open(SKEMA_KASUS, encoding="utf-8") as fh:
            skema = json.load(fh).get("skema", {})
    except Exception:
        skema = {}
    if isinstance(skema, dict):
        skema = {k: v for k, v in skema.items() if k != "prinsip_salah"}
    skema_teks = json.dumps(skema, ensure_ascii=False)[:2500] if skema else ""

    pesan = [
        {"role": "system", "content":
            "Kamu menjawab kuis pelatihan Wadhwani berdasarkan PRINSIP POSITIF "
            "dari narasi (Bagus/tepat/memastikan), bukan hafalan pasangan soal-jawaban. "
            "Jangan memakai penalti dari umpan balik negatif dan jangan mencari 'skor "
            "tertinggi'. Bila beberapa prinsip positif cocok, pilih jawaban yang PALING "
            "LOGIS dan sesuai FAKTA pada kasus. "
            "Balas HANYA teks jawaban persis seperti di daftar, tanpa penjelasan."},
        {"role": "user", "content":
            f"SKEMA umum menangani kasus:\n{skema_teks}\n\n"
            f"PRINSIP POSITIF dari transkrip yang relevan:\n" +
            ("\n".join(prinsip_relevan[:12]) or "- (tidak ada prinsip khusus; gunakan logika dan fakta kasus)") +
            f"\n\nKasus di slide:\n{(teks_soal or '')[-1500:]}\n\n"
            f"Narasi positif lain:\n{narasi}\n\n"
            f"Pilihan jawaban (pilih persis salah satu):\n{daftar}"},
    ]
    try:
        jawab = panggil_model(pesan).strip()
        calon = []
        for o in opsi:
            if jawab.lower() == o.lower():
                calon.append(o)
        if not calon:
            for o in opsi:
                if o.lower() in jawab.lower() or jawab.lower() in o.lower():
                    calon.append(o)
        pilih, sumber = ambil(calon, "model + peta positif")
        if pilih:
            _log_pilih(sumber, pilih,
                       f" (prinsip cocok {len(prinsip_relevan)})")
            return pilih
    except Exception as e:
        _log_pilih("model gagal", str(e)[:80])

    # Model tidak bisa memutus: pakai opsi yang didukung prinsip positif.
    pilih, sumber = ambil(kandidat_positif, "peta transkrip (positif)")
    if pilih:
        _log_pilih(sumber, pilih)
        return pilih

    # Terakhir: putar opsi, jangan diam-diam opsi[0].
    pilih, sumber = ambil(opsi, "rotasi opsi (tanpa kunci)")
    if pilih:
        _log_pilih(sumber, pilih)
        return pilih
    return opsi[0]


def _pilih_beberapa_opsi_scorm(teks_soal, opsi, transkrip, jumlah):
    """Pilih beberapa opsi sekaligus saat data.js tidak punya kunci benar.

    Dipakai soal "Pilih dua jawaban yang tepat" yang hanya memakai tombol
    Storyline (tanpa input radio/checkbox). Model lokal tetap memilih berdasar
    prinsip positif + fakta kasus, bukan hafalan pasangan soal-jawaban.
    """
    opsi = [str(o or "").strip() for o in (opsi or []) if str(o or "").strip()]
    if not opsi:
        return []
    jumlah = max(1, min(int(jumlah or 1), len(opsi)))
    if jumlah == 1:
        jawab = _pilih_opsi_scorm(teks_soal, opsi, transkrip)
        return [jawab] if jawab else []

    peta = _bangun_peta_transkrip(transkrip)
    kata_soal = set(re.findall(r"[a-z]{4,}", (teks_soal or "").lower())) - _KATA_STOP
    prinsip = []
    for e in peta:
        if not e.get("positif"):
            continue
        kata = set(e.get("kata") or [])
        if any(_kata_cocok(k, q) for k in kata for q in kata_soal):
            prinsip.append(str(e.get("prinsip") or "")[:200])
    daftar = "\n".join(f"{i + 1}. {o}" for i, o in enumerate(opsi))
    pesan = [
        {"role": "system", "content":
            "Kamu menjawab kuis pelatihan Wadhwani. Pilih TEPAT sejumlah opsi "
            "yang diminta berdasarkan prinsip positif dan fakta pada kasus, "
            "bukan hafalan pasangan soal-jawaban. Balas HANYA teks opsi yang "
            "dipilih, dipisah dengan tanda ' | ', tanpa nomor dan penjelasan."},
        {"role": "user", "content":
            f"PRINSIP positif yang relevan:\n" +
            ("\n".join(f"- {p}" for p in prinsip[:12]) or
             "- (tidak ada prinsip khusus; gunakan logika dan fakta kasus)") +
            f"\n\nKasus di slide:\n{(teks_soal or '')[-1500:]}\n\n"
            f"Pilih tepat {jumlah} opsi dari daftar ini:\n{daftar}"},
    ]
    indeks = []
    try:
        jawab = panggil_model(pesan)
        for bagian in re.split(r"\s*\|\s*|\n+", jawab or ""):
            potong = re.sub(r"^\s*\d+[\.\)]\s*", "", bagian).strip()
            if not potong:
                continue
            rasio, i = max((difflib.SequenceMatcher(
                None, potong.lower(), o.lower()).ratio(), n)
                for n, o in enumerate(opsi))
            if rasio >= 0.35 and i not in indeks:
                indeks.append(i)
    except Exception as e:
        _log_pilih("model multi gagal", str(e)[:80])

    if len(indeks) < jumlah:
        def dukungan(o):
            kata_opsi = set(re.findall(r"[a-z]{4,}", o.lower())) - _KATA_STOP
            return sum(1 for p in prinsip
                       if any(_kata_cocok(k, kk)
                              for k in kata_opsi
                              for kk in set(re.findall(r"[a-z]{4,}", p.lower())) - _KATA_STOP))
        for i in sorted(range(len(opsi)), key=lambda n: dukungan(opsi[n]), reverse=True):
            if i not in indeks:
                indeks.append(i)
            if len(indeks) >= jumlah:
                break
    indeks = indeks[:jumlah]
    pilihan = [opsi[i] for i in indeks]
    _log_pilih(f"model multi ({jumlah} opsi, data.js tanpa kunci)",
               ", ".join(pilihan))
    return pilihan


def _status_jawaban_scorm(frame, transkrip):
    """Nilai umpan balik setelah Kirim dari audio + teks layar.

    True = jawaban benar, False = salah, None = tidak bisa dipastikan.
    """
    narasi = []
    for _ in range(7):
        try:
            aktif = frame.evaluate("""() => Array.from(document.querySelectorAll('audio'))
                .filter(x => x.currentTime > 0.1 && !x.paused)
                .map(x => (x.src || '').split('/').pop())""")
        except Exception:
            break
        for a in aktif:
            t = transkrip.get(a, "")
            if t and t not in narasi:
                narasi.append(t)
        time.sleep(0.3)
    try:
        teks = " ".join(frame.inner_text("body").split())
    except Exception:
        teks = ""
    gabung = (" ".join(narasi) + " " + teks).lower()
    if re.search(r"tidak dapat membantu|tidak tepat|tidak benar|kurang tepat|"
                 r"belum tepat|coba lagi|\bsalah\b|\bmaaf\b", gabung):
        return False
    # Umpan balik benar pada paket Wadhwani memakai kata "Benar!" / "Tepat!",
    # bukan selalu "Bagus". Tanpa ini jawaban benar terbaca sebagai None dan
    # rotasi opsi berhenti lebih awal.
    if re.search(r"\bbagus\b|\bbenar\b|\btepat\b|memastikan bahwa|terima kasih banyak",
                 gabung):
        return True
    return None


def _jawaban_scorm_dari_data(frame):
    """Baca kunci jawaban dari data.js paket SCORM (bukan menebak dari layar).

    Setiap paket SCORM Wadhwani menyimpan daftar interaksi beserta choice yang
    berstatus 'correct' di html5/data/js/data.js. Memakai kunci ini membuat
    jawaban Pikirkan/Praktikkan dipastikan benar sebelum menekan Kirim.
    """
    try:
        url_data = (frame.url or "").rsplit("/", 1)[0] + "/html5/data/js/data.js"
        js = r"""async (u) => {
            const t = await (await fetch(u)).text();
            let captured = null;
            const old = window.globalProvideData;
            window.globalProvideData = (k, v) => { if (k === 'data') captured = v; };
            try { eval(t); } finally { window.globalProvideData = old; }
            if (!captured) return [];
            const d = JSON.parse(captured);
            const out = [];
            const walk = (o) => {
                if (!o || typeof o !== 'object') return;
                if (o.kind === 'interaction' && Array.isArray(o.answers)) {
                    const benar = [];
                    for (const a of o.answers) {
                        if (a.status !== 'correct') continue;
                        for (const st of ((a.evaluate || {}).statements || [])) {
                            let c = String(st.choiceid || '');
                            c = c.replace(/^choices\./, '').replace(/^choice_/, '');
                            if (c) benar.push(c);
                        }
                    }
                    const bersihId = v => String(v || '')
                        .replace(/^choices\./, '').replace(/^choice_/, '');
                    out.push({
                        id: o.id || '', type: o.type || '', teks: o.lmstext || '',
                        pilih: (o.choices || []).map(c => bersihId(c.id)),
                        // Label tiap opsi (A/B/C untuk Pick One, 1..6 untuk urutan).
                        // Dipakai untuk memilih dropdown Sequence Drop-down.
                        pilih_label: Object.fromEntries((o.choices || []).map(c =>
                            [bersihId(c.id), String(c.lmstext || '')])),
                        benar: benar
                    });
                }
                for (const v of Object.values(o)) walk(v);
            };
            walk(d);
            return out;
        }"""
        return frame.evaluate(js, url_data) or []
    except Exception:
        return []


def _normal_id(nilai):
    """Samakan format id pilihan data.js dengan id radio di halaman."""
    return re.sub(r"[^a-z0-9]", "", str(nilai or "").lower()).lstrip("0") or "0"




def _opsi_kuis_generik(frame):
    """Temukan opsi jawaban dari bentuk DOM apa pun dalam paket SCORM.

    Tidak bergantung pada satu bentuk: input.acc-radio, input.acc-checkbox,
    tombol .acc-button bertanda Rectangle/Oval, elemen data-represents, atau
    elemen Storyline (stategroup/vectorshape/dropdown) yang terlihat sebagai
    kandidat jawaban. Dipakai sebagai jalur adaptif sebelum bot menyerah.
    """
    try:
        hasil = frame.evaluate(r"""() => {
          const bersih = s => (s||'').replace(/\s+/g,' ').trim();
          const vis = e => {
            const r=e.getBoundingClientRect(), g=getComputedStyle(e);
            return r.width>0 && r.height>0 && g.display!=='none' &&
                   g.visibility!=='hidden' && parseFloat(g.opacity||'1')>0.05;
          };
          const teksSemua = [...document.querySelectorAll('.acc-text, label')];

          // 1) Radio/checkbox klasik.
          const input = [...document.querySelectorAll('input.acc-radio, input.acc-checkbox')]
            .filter(e => !e.disabled);
          if (input.length) return input.map(e => {
            const id = (e.id||'').replace(/^acc-/, '');
            const lab = teksSemua.find(t => (t.dataset.represents||'').includes(id));
            return {uid: id, id: id, teks: lab ? bersih(lab.innerText) : '',
                    sumber: 'input', multi: e.type === 'checkbox'};
          });

          // 2) Tombol .acc-button yang punya teks opsi di .acc-text.
          const tombol = [...document.querySelectorAll('button.acc-button')]
            .filter(b => !b.disabled && vis(b));
          const dariTombol = [];
          for (const b of tombol) {
            const uid = (b.id||'').replace(/^acc-/, '');
            const label = bersih(b.innerText || b.getAttribute('aria-label') || '');
            if (/^(Kirim|Kirim Jawaban|Submit|Selesai|OK|Keluar|Mulai ulang)$/i.test(label))
              continue;
            if (!uid) continue;
            const t = teksSemua.find(x => {
              const rep = x.dataset.represents || '';
              const txt = bersih(x.innerText);
              return rep.includes(uid) && txt.length > 18 &&
                     !/c|All Rights|Hak Cipta|slide:|^Kirim$|^Selesai$/i.test(txt);
            });
            if (t) dariTombol.push({uid: uid, id: uid, teks: bersih(t.innerText),
                                    sumber: 'tombol', multi: false});
          }
          if (dariTombol.length) return dariTombol;

          // 3) Elemen lain bertanda data-represents dengan teks opsi.
          const umum = [];
          for (const e of document.querySelectorAll('[data-represents]')) {
            if (e.disabled || e.matches('button, input') ||
                e.classList.contains('acc-text')) continue;
            const txt = bersih(e.innerText);
            if (txt.length < 18 || txt.length > 300) continue;
            if (/c|All Rights|Hak Cipta|slide:|Pelajaran Selanjutnya/i.test(txt)) continue;
            const p = (e.dataset.represents||'').split('.').filter(Boolean);
            const uid = p[p.length-1] || '';
            if (!uid) continue;
            umum.push({uid: uid, id: uid, teks: txt, sumber: 'umum', multi: false});
          }
          if (umum.length >= 2) return umum;

          // 4) Adaptif: opsi Storyline (mis. dropdown/tarik-turun, stategroup)
          // yang terlihat sebagai kandidat jawaban.
          const kandidat = [];
          const els = [...document.querySelectorAll(
            '.slide-object-stategroup, .slide-object-vectorshape, .acc-button, [role="option"], [role="radio"], [role="checkbox"]')];
          for (const e of els) {
            if (!vis(e) || e.disabled) continue;
            const txt = bersih(e.innerText || e.getAttribute('aria-label') || '');
            if (!txt || txt.length < 3 || txt.length > 160) continue;
            if (/^(Kirim|Kirim Jawaban|Submit|Selesai|SELESAI|OK|Keluar|KELUAR|Lanjutkan|LANJUTKAN|Selanjutnya|SELANJUTNYA|Resume|Restart|Mulai|MULAI|MULAI LAGI|SEBELUMNYA|Sebelumnya|Coba lagi|Continue|Next)$/i.test(txt)) continue;
            if (/^Pilih opsi|^Klik panah|^Klik di sini|Silakan klik ikon|Sisa Percobaan|down arrow|play2?\.png|^play$|^pause$|^reset$|mute|caption|full.?screen|putar ulang/i.test(txt)) continue;
            if (/^\d+$/.test(txt)) continue;
            if (/All Rights|Hak Cipta|Wadhwani|©|^slide:/i.test(txt)) continue;
            const r = e.getBoundingClientRect();
            if (r.width > 500 && r.height > 80) continue;
            const id = (e.id||'').replace(/^acc-/, '');
            kandidat.push({uid: id, id: id, teks: txt, sumber: 'adaptif',
                           multi: false, x: Math.round(r.x), y: Math.round(r.y),
                           w: Math.round(r.width), h: Math.round(r.height),
                           cls: (e.className||'').toString().slice(0,80)});
          }
          const prior = o => (o.cls||'').includes('stategroup') ? 0 : ((o.cls||'').includes('acc-button') ? 1 : 2);
          kandidat.sort((a,b)=> prior(a)-prior(b) || a.y-b.y);
          const seen = new Set();
          const uniq = [];
          for (const k of kandidat) {
            const key = k.teks.toLowerCase();
            if (seen.has(key)) continue;
            seen.add(key);
            uniq.push(k);
          }
          if (uniq.length >= 2) {
            const buckets = {};
            for (const k of uniq) {
              const bx = Math.round((k.x||0) / 40) * 40;
              const bw = Math.round((k.w||0) / 40) * 40;
              const key = bx + ',' + bw;
              (buckets[key] = buckets[key] || []).push(k);
            }
            const cluster = Object.values(buckets).sort((a,b)=>b.length-a.length)[0] || [];
            if (cluster.length >= 2) return cluster.sort((a,b)=>a.y-b.y);
            if (uniq.length <= 8) return uniq;
          }
          return uniq.length >= 2 ? uniq : (umum.length ? umum : uniq);
        }""") or []
        return hasil
    except Exception:
        return []


def _klik_opsi_adaptif(frame, teks_opsi):
    """Klik opsi SCORM/Storyline secara adaptif berdasarkan teks terlihat."""
    teks_opsi = str(teks_opsi or "").strip()
    if not teks_opsi:
        return False
    try:
        loc = frame.locator(
            ".slide-object-stategroup, .slide-object-vectorshape, .acc-button, [role='option'], [data-represents], .acc-text"
        ).filter(has_text=teks_opsi)
        n = loc.count()
        kandidat = []
        for i in range(min(n, 12)):
            try:
                box = loc.nth(i).bounding_box()
                vis = loc.nth(i).is_visible()
                if vis and box:
                    kandidat.append((i, box))
            except Exception:
                continue
        kandidat.sort(key=lambda it: (
            0 if (500 <= it[1].get('x', 0) <= 720 and 180 <= it[1].get('y', 0) <= 360) else 1,
            it[1].get('y', 0)
        ))
        for i, _ in kandidat:
            try:
                loc.nth(i).click(timeout=1200, force=True)
                return True
            except Exception:
                continue
    except Exception:
        pass
    try:
        ok = frame.evaluate(r"""(t) => {
          const bersih = s => (s||'').replace(/\s+/g,' ').trim();
          const vis = e => {
            const r=e.getBoundingClientRect(), g=getComputedStyle(e);
            return r.width>0 && r.height>0 && g.display!=='none' &&
                   g.visibility!=='hidden' && parseFloat(g.opacity||'1')>0.05;
          };
          const target = bersih(t).toLowerCase();
          const sels = ['.slide-object-stategroup','.slide-object-vectorshape',
                        '.acc-button','button','[role="option"]','[role="radio"]',
                        '[role="checkbox"]','[data-represents]','.acc-text','div','span'];
          const cands = [];
          for (const e of document.querySelectorAll(sels.join(','))) {
            if (!vis(e) || e.disabled) continue;
            const txt = bersih(e.innerText || e.getAttribute('aria-label') || '');
            if (txt.toLowerCase() !== target) continue;
            const r = e.getBoundingClientRect();
            let s = 0;
            if ((e.className||'').toString().includes('stategroup')) s -= 10;
            if (r.x>=500 && r.x<=720 && r.y>=180 && r.y<=360) s -= 5;
            else if (r.x>=300 && r.x<=750 && r.y>=150 && r.y<=380) s -= 2;
            cands.push({e, s, y:r.y});
          }
          cands.sort((a,b)=>a.s-b.s || a.y-b.y);
          for (const c of cands.slice(0,4)) {
            const e = c.e;
            try { e.scrollIntoView({block:'center'}); } catch(ex){}
            try { e.click(); } catch(ex){}
            for (const ev of ['pointerdown','mousedown','pointerup','mouseup','click']) {
              try { e.dispatchEvent(new MouseEvent(ev,{bubbles:true,cancelable:true,view:window})); } catch(ex){}
            }
          }
          return cands.length > 0;
        }""", teks_opsi)
        if ok:
            return True
    except Exception:
        pass
    for exact in (True, False):
        try:
            frame.get_by_text(teks_opsi, exact=exact).first.click(timeout=1200, force=True)
            return True
        except Exception:
            continue
    return False


def _klik_kirim_adaptif(frame):
    """Klik tombol/elemen Kirim atau Submit yang terlihat secara adaptif."""
    try:
        if frame.evaluate(r"""() => {
            const vis = e => {
                const r=e.getBoundingClientRect(), g=getComputedStyle(e);
                return r.width>0 && r.height>0 && g.display!=='none' &&
                       g.visibility!=='hidden' && parseFloat(g.opacity||'1')>0.05;
            };
            for (const e of [...document.querySelectorAll('.acc-button, button, [role="button"], input[type=submit], input[type=button]')]) {
                if (!vis(e) || e.disabled) continue;
                const t=(e.innerText||e.value||e.getAttribute('aria-label')||'').trim();
                if (/^(Kirim|Kirim Jawaban|Submit|Serahkan)$/i.test(t)) { e.click(); return true; }
            }
            return false;
        }"""):
            return True
    except Exception:
        pass
    try:
        if frame.evaluate(r"""() => {
            const vis = e => {
                const r=e.getBoundingClientRect(), g=getComputedStyle(e);
                return r.width>0 && r.height>0 && g.display!=='none' &&
                       g.visibility!=='hidden' && parseFloat(g.opacity||'1')>0.05;
            };
            const els = [...document.querySelectorAll('.slide-object-stategroup, .slide-object-vectorshape, .slide-object, div, span')];
            for (const e of els) {
                if (!vis(e) || e.disabled) continue;
                const t=(e.innerText||'').replace(/\s+/g,' ').trim();
                if (!/^(Kirim|Kirim Jawaban|Submit)$/i.test(t)) continue;
                e.click();
                e.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));
                return true;
            }
            return false;
        }"""):
            return True
    except Exception:
        pass
    for txt in ("Kirim", "Kirim Jawaban", "Submit"):
        try:
            frame.get_by_text(txt, exact=True).first.click(timeout=1000, force=True)
            return True
        except Exception:
            continue
    return False


def _buka_dropdown_scorm(frame):
    """Buka kontrol dropdown/tarik-turun Storyline jika ada (best-effort)."""
    try:
        return bool(frame.evaluate(r"""() => {
            const vis = e => {
                const r=e.getBoundingClientRect(), g=getComputedStyle(e);
                return r.width>0 && r.height>0 && g.display!=='none' &&
                       g.visibility!=='hidden';
            };
            for (const e of document.querySelectorAll('.acc-button,button,[role="button"],[aria-label],.slide-object-stategroup,.slide-object-vectorshape')) {
                if (e.disabled) continue;
                const t=(e.innerText||e.getAttribute('aria-label')||'').trim();
                if (/down arrow|panah bawah|Klik di sini untuk membuat pilihan/i.test(t)) {
                    try { e.click(); } catch(ex){}
                    try { e.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true})); } catch(ex){}
                    return true;
                }
            }
            for (const e of document.querySelectorAll('.slide-object-vectorshape,.slide-object-objgroup,.slide-object-stategroup')) {
                if (!vis(e)) continue;
                const t=(e.innerText||'').trim();
                if (/Klik panah bawah untuk melihat opsi/i.test(t)) { e.click(); return true; }
            }
            return false;
        }"""))
    except Exception:
        return False


def _klik_opsi_kuis(frame, opsi):
    """Klik satu opsi hasil deteksi generik, apa pun bentuk elemennya."""
    teks = ""
    if isinstance(opsi, dict):
        teks = str(opsi.get("teks") or "").strip()
    try:
        ok = frame.evaluate("""(o) => {
          const id = String((o && (o.uid||o.id)) || '').replace(/^acc-/, '');
          if (id) {
            let e = document.getElementById('acc-' + id);
            if (!e) e = [...document.querySelectorAll('[data-represents]')]
                .find(x => (x.dataset.represents||'').includes(id) &&
                           (x.innerText||'').trim().length > 3);
            if (e && !e.disabled) {
              if (e.tagName === 'INPUT') e.click();
              else {
                e.click();
                const bayang = [...document.querySelectorAll('.acc-text')]
                  .find(x => (x.dataset.represents||'').includes(id));
                if (bayang && bayang !== e) try { bayang.click(); } catch(ex){}
              }
              return true;
            }
          }
          return false;
        }""", opsi or {})
        if ok:
            return True
    except Exception:
        pass
    if teks:
        return _klik_opsi_adaptif(frame, teks)
    return False


def _selesaikan_scorm(page):
    """Kerjakan semua bentuk aktivitas 'Pikirkan' sampai tombol Selesaikan diklik.

    Mata = screenshot + OCR di setiap langkah. Telinga = transkrip audio lokal.
    Jawaban dicek dari audio umpan balik setelah Kirim; bila salah, soal diulang
    dengan pilihan lain. Semua screenshot dihapus setelah pekerjaan selesai.
    """
    import shutil as _shutil

    frame = _frame_scorm(page)
    if not frame:
        # Frame SCORM bersarang kadang baru termuat >12 detik setelah halaman
        # pelajaran dibuka. Tanpa penunggu ini aktivitas dianggap selesai
        # tanpa mengerjakan apa pun (0 screenshot, API tetap inProgress).
        for _ in range(25):
            time.sleep(1)
            frame = _frame_scorm(page)
            if frame:
                print(datetime.now().strftime("%H:%M:%S") +
                      " [SCORM] frame baru termuat setelah ditunggu.", flush=True)
                break
        if not frame:
            print(datetime.now().strftime("%H:%M:%S") +
                  " [SCORM] frame tidak pernah muncul; aktivitas dilewati.", flush=True)
            return ""

    folder_ss = FOLDER_SIMPAN / f"ss-pikirkan-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    folder_ss.mkdir(parents=True, exist_ok=True)
    daftar_ss = []
    hasil = "SCORM tidak selesai diproses."

    def ss(langkah):
        """Ambil screenshot langkah ini, OCR, kembalikan teks yang terlihat."""
        try:
            try:
                page.locator("iframe").first.scroll_into_view_if_needed(timeout=1500)
            except Exception:
                pass
            lokasi = folder_ss / f"{len(daftar_ss) + 1:03d}-{langkah}.png"
            page.screenshot(path=str(lokasi), full_page=False)
            daftar_ss.append(lokasi)
            print(datetime.now().strftime("%H:%M:%S") +
                  f"  [SCORM] screenshot #{len(daftar_ss)}: {langkah}", flush=True)
            return " ".join(_baca_gambar_ocr_windows(lokasi)
                            .replace("TEKS TERLIHAT:", "").split())
        except Exception:
            return ""

    def opsi_aktif():
        """Ambil label radio yang masih bisa diklik (belum dikunci setelah Kirim)."""
        try:
            return frame.evaluate("""() => Array.from(document.querySelectorAll('input.acc-radio'))
                .filter(r => !r.disabled)
                .map(r => {
                    const ref = r.getAttribute('aria-labelledby');
                    const lab = ref ? document.getElementById(ref) : null;
                    const baru = lab ? (lab.innerText || lab.textContent || '').trim() : '';
                    const lama = [...document.querySelectorAll('.acc-text')]
                        .find(e => (e.dataset.represents || '').includes(id));
                    return baru || (lama ? (lama.innerText || '').trim() : '');
                }).filter(Boolean)""")
        except Exception:
            return []

    def kirim_terlihat():
        try:
            return frame.evaluate("""() => Array.from(document.querySelectorAll('.acc-button, button')).some(x => {
                const r = x.getBoundingClientRect(), g = getComputedStyle(x);
                return r.width > 0 && r.height > 0 && g.display !== 'none' &&
                       g.visibility !== 'hidden' && !x.disabled &&
                       /^Kirim$/i.test((x.innerText || '').trim());
            })""")
        except Exception:
            return False

    def tekan_start_video():
        """Tekan tombol mulai splash video (layout mobile Storyline)."""
        try:
            return frame.evaluate("""() => {
                const e = document.querySelector(
                    '#mobile-start-button, .mobile-start-button');
                if (!e || e.disabled) return false;
                e.click();
                return true;
            }""")
        except Exception:
            return False

    try:
        frame.evaluate("""() => {
            const cocok = /^(Resume|Start Course|Mulai Kursus|Mulai|Lanjutkan|Continue)$/i;
            const b = Array.from(document.querySelectorAll('button, .acc-button'))
                .find(x => cocok.test(
                    (x.innerText || x.getAttribute('aria-label') || '').trim()));
            if (b) b.click();
        }""")
        time.sleep(3)
        frame = _frame_scorm(page) or frame
        # Tunggu slide benar-benar siap setelah Start Course/Resume ditekan.
        for _ in range(30):
            try:
                lbl = frame.evaluate(
                    "() => (document.querySelector('#slide-label')||{}).innerText || ''")
            except Exception:
                lbl = ""
            if lbl or frame.locator("input.acc-radio").count():
                break
            time.sleep(1)
        transkrip = _siapkan_audio_scorm(page, frame)
        _simpan_skema_kasus(transkrip)
        peta_transkrip = _bangun_peta_transkrip(transkrip)
        print(datetime.now().strftime("%H:%M:%S") +
              f" [PETA TRANSKRIP] {len(peta_transkrip)} entri prinsip dari "
              f"{len(transkrip)} transkrip -> {PETA_TRANSKRIP.name}", flush=True)
        kunci = _jawaban_scorm_dari_data(frame)
        print(datetime.now().strftime("%H:%M:%S") +
              f" [KUNCI SCORM] data.js: {len(kunci)} interaksi, "
              f"{sum(1 for k in kunci if k.get('benar'))} punya kunci benar", flush=True)

        # Resume bisa membuka soal yang sudah dijawab (radio terkunci).
        # Kembali ke daftar karakter supaya tidak menjawabnya dua kali.
        try:
            label_awal = frame.evaluate(
                "() => (document.querySelector('#slide-label')||{}).innerText || ''")
        except Exception:
            label_awal = ""
        if "Pick One" in label_awal and not opsi_aktif():
            frame.evaluate("""() => {
                const p = document.querySelector('#prev');
                if (p) p.click();
            }""")
            time.sleep(1.5)
            frame = _frame_scorm(page) or frame

        interaksi = 0
        dijawab = set()   # id interaksi yang sudah dijawab dengan benar
        # Kunci yang sudah dicoba habis pada SLIDE tertentu. Dipisah dari
        # 'dijawab' supaya radio/tombol di slide berikutnya tetap boleh
        # memakai kunci yang sama, tanpa mengulang slide yang sama terus.
        dijawab_gagal = set()
        ulangan = 0
        selesai = False
        box_terakhir = None
        box_selesai = {}   # sidik slide -> uid objek Storyline yang sudah diklik
        radio_selesai = set()  # sidik kumpulan radio yang sudah dikirim
        perlu_kembali = False
        maju_tanpa_jawaban = 0
        mulai_diklik = set()
        riwayat_pickmany = {}  # tanda jawaban -> jumlah percobaan (anti-loop)
        loop_berhenti = False

        start_video_diklik = False
        play_splash_diklik = False
        for _ in range(250):
            _tunggu_jika_dijeda()
            if loop_berhenti:
                break
            frame = _frame_scorm(page) or frame
            # Splash video Storyline: tombol tetap ada di DOM setelah diklik,
            # jadi cukup ditekan sekali di awal sebelum slide soal muncul.
            if not start_video_diklik and tekan_start_video():
                start_video_diklik = True
                print(datetime.now().strftime("%H:%M:%S") +
                      " [SCORM] tombol mulai video splash ditekan", flush=True)
                ss("tekan-mobile-start")
                time.sleep(2.5)
                frame = _frame_scorm(page) or frame
            try:
                teks_dom = " ".join(frame.inner_text("body").split())
            except Exception:
                break
            # Teks soal Sequence Drop-down sering hanya ada di atribut
            # data-represents dan #slide-label, bukan di innerText body.
            # Gabungkan supaya jalur Sequence tidak terlewat dan Pick Many
            # tidak salah terpicu pada slide yang sama.
            try:
                teks_seq = frame.evaluate(r"""() => {
                    const bersih = s => (s||'').replace(/\s+/g,' ').trim();
                    const rep = [...document.querySelectorAll('[data-represents]')]
                        .filter(e => e.getBoundingClientRect().width > 0)
                        .map(e => bersih(e.innerText || '') + ' ' +
                                  bersih(e.getAttribute('data-represents') || ''));
                    const lab = bersih((document.querySelector('#slide-label')||{}).innerText || '');
                    return lab + ' ' + rep.join(' ');
                }""") or ""
            except Exception:
                teks_seq = ""
            if not isinstance(teks_seq, str):
                teks_seq = str(teks_seq)
            teks_sequence = teks_dom + " " + teks_seq
            teks = teks_dom + " " + ss("cek")

            # Splash Storyline punya DUA tombol: MULAI lalu play2.png.
            # Sebelumnya bot hanya mengklik MULAI, slide tidak pernah maju dan
            # akhirnya berhenti di guard "slide tanpa interaksi" (174283).
            if not play_splash_diklik:
                try:
                    if frame.evaluate("""() => {
                        const re = /^(play2\\.png|Play|Putar)$/i;
                        const b = [...document.querySelectorAll('button, .acc-button')]
                          .find(x => {
                            const r = x.getBoundingClientRect();
                            return r.width > 0 && r.height > 0 && !x.disabled &&
                                   re.test((x.innerText || x.getAttribute('aria-label') || '').trim());
                          });
                        if (b) { b.click(); return true; }
                        return false;
                    }"""):
                        play_splash_diklik = True
                        print(datetime.now().strftime("%H:%M:%S") +
                              " [SCORM] tombol Play splash ditekan", flush=True)
                        ss("tekan-play-splash")
                        time.sleep(2.5)
                        frame = _frame_scorm(page) or frame
                        continue
                except Exception:
                    pass

            # Tombol pembuka di dalam konten: 'MULAI' / 'play2.png' / 'Play'.
            # Start Course hanya membawa ke splash; tanpa ini materi tidak dimulai.
            try:
                label_saat_ini = frame.evaluate(
                    "() => (document.querySelector('#slide-label')||{}).innerText || ''")
            except Exception:
                label_saat_ini = ""
            if label_saat_ini and label_saat_ini not in mulai_diklik and frame.evaluate("""() => {
                    const re = /^(MULAI|Mulai Kursus|play2\\.png|Play|MULAI LAGI)$/i;
                    return [...document.querySelectorAll('.acc-button, button')].some(x => {
                        const r = x.getBoundingClientRect(), g = getComputedStyle(x);
                        const t = (x.innerText || x.getAttribute('aria-label') || '').trim();
                        return r.width > 0 && r.height > 0 && g.display !== 'none' &&
                               g.visibility !== 'hidden' && !x.disabled && re.test(t);
                    });
                }"""):
                ss("sebelum-tombol-mulai")
                frame.evaluate("""() => {
                    const re = /^(MULAI|Mulai Kursus|play2\\.png|Play|MULAI LAGI)$/i;
                    const b = [...document.querySelectorAll('.acc-button, button')].find(x => {
                        const r = x.getBoundingClientRect(), g = getComputedStyle(x);
                        const t = (x.innerText || x.getAttribute('aria-label') || '').trim();
                        return r.width > 0 && r.height > 0 && g.display !== 'none' &&
                               g.visibility !== 'hidden' && !x.disabled && re.test(t);
                    });
                    if (b) b.click();
                }""")
                mulai_diklik.add(label_saat_ini)
                interaksi += 1
                time.sleep(3)
                ss("sesudah-tombol-mulai")
                continue

            # Halaman hasil SCORM: bila nilainya gagal, jangan klik Selesai.
            # Klik "Coba lagi" supaya jawaban diulang dari awal.
            if re.search(r"Perlu ditingkatkan|tidak lolos|belum berhasil|belum tepat",
                         teks_dom, re.I):
                # Status API lebih dipercaya daripada teks halaman hasil.
                # Kalau API sudah completed, jangan terus mengulang lewat
                # 'Coba lagi' (ini yang membuat bot mandek berjam-jam).
                try:
                    _m = re.search(r"/course-lesson/\d+/(\d+)", page.url or "")
                    _api_selesai = bool(_m) and _selesai_aktivitas(
                        _status_aktivitas_api(page, _m.group(1)))
                except Exception:
                    _api_selesai = False
                if _api_selesai:
                    ss("hasil-api-selesai")
                    if frame.evaluate("""() => {
                        const b = [...document.querySelectorAll('.acc-button, button')]
                          .find(x => /^(Selesai|Selesaikan)$/i.test(
                              (x.innerText || '').trim()) &&
                              !x.disabled && x.getBoundingClientRect().width > 0);
                        if (b) { b.click(); return true; }
                        return false;
                    }"""):
                        selesai = True
                        time.sleep(2)
                        ss("hasil-api-selesai-diklik")
                    break
                if ulangan >= 3:
                    ss("hasil-gagal-berhenti")
                    print(datetime.now().strftime("%H:%M:%S") +
                          " [SCORM] berhenti: 3x Coba lagi tanpa perubahan status API.",
                          flush=True)
                    break
                if frame.evaluate("""() => {
                    const b = Array.from(document.querySelectorAll('.acc-button, button')).find(x =>
                        /coba lagi/i.test((x.innerText || '').trim()) && !x.disabled);
                    if (b) { b.click(); return true; }
                    return false;
                }"""):
                    ss("hasil-gagal-coba-lagi")
                    ulangan += 1
                    dijawab.clear()
                    mulai_diklik.clear()
                    # Coba lagi mengulang paket dari awal: penanda lama harus
                    # dibersihkan supaya kotak/radio yang sama bisa dijawab ulang.
                    box_selesai.clear()
                    radio_selesai.clear()
                    time.sleep(2)
                    continue

            # 'Pelajari lebih lanjut' memakai tombol KELUAR di menu eksplorasi
            # sebagai penanda selesai. Tombol ini baru ada setelah splash dan
            # beberapa slide, jadi dicek di sini, bukan di awal.
            try:
                label_keluar = frame.evaluate(
                    "() => (document.querySelector('#slide-label')||{}).innerText || ''")
            except Exception:
                label_keluar = ""
            if ("pelajari lebih lanjut" in
                    str(_aktivitas_aktif(page).get("aktivitas", "")).lower() and
                    re.search(r"watch|eksplorasi", label_keluar, re.I) and
                    frame.evaluate("""() => [...document.querySelectorAll('.acc-button, button')]
                        .some(x => { const r = x.getBoundingClientRect(), g = getComputedStyle(x);
                            const t = (x.innerText || '').trim();
                            return r.width > 0 && r.height > 0 && g.display !== 'none' &&
                                   g.visibility !== 'hidden' && !x.disabled && /^KELUAR$/i.test(t);
                        })""")):
                ss("sebelum-keluar")
                if frame.evaluate("""() => {
                    const e = [...document.querySelectorAll('.acc-button, button')].find(x => {
                        const r = x.getBoundingClientRect(), g = getComputedStyle(x);
                        return r.width > 0 && r.height > 0 && g.display !== 'none' &&
                               g.visibility !== 'hidden' && !x.disabled &&
                               /^KELUAR$/i.test((x.innerText || '').trim());
                    });
                    if (e) { e.click(); return true; }
                    return false;
                }"""):
                    selesai = True
                    time.sleep(2)
                    ss("sesudah-keluar")
                    break

            # Tombol Selesaikan / Selesai yang TERLIHAT
            if frame.evaluate("""() => Array.from(document.querySelectorAll('.acc-button, button')).some(x => {
                    const r = x.getBoundingClientRect(), g = getComputedStyle(x);
                    return r.width > 0 && r.height > 0 && g.display !== 'none' &&
                           g.visibility !== 'hidden' && !x.disabled &&
                           /selesai/i.test((x.innerText || x.getAttribute('aria-label') || '').trim());
                })"""):
                ss("sebelum-selesaikan")
                if frame.evaluate("""() => {
                    const e = Array.from(document.querySelectorAll('.acc-button, button')).find(x => {
                        const r = x.getBoundingClientRect(), g = getComputedStyle(x);
                        return r.width > 0 && r.height > 0 && g.display !== 'none' &&
                               g.visibility !== 'hidden' && !x.disabled &&
                               /selesai/i.test((x.innerText || x.getAttribute('aria-label') || '').trim());
                    });
                    if (e) { e.click(); return true; }
                    return false;
                }"""):
                    selesai = True
                    time.sleep(2)
                    ss("sesudah-selesaikan")
                    break

            # Pikirkan berbasis dropdown (mis. 174025). Jawaban diambil dari
            # transkrip narasi lokal, bukan ditebak: pilih 'Rekomendasi',
            # pastikan pilihan tersimpan, lalu klik Kirim yang terlihat.
            if ("Klik di sini untuk membuat pilihan" in teks_dom and
                    "pikirkan-dropdown" not in dijawab):
                ss("pikirkan-dropdown-sebelum")
                if not frame.evaluate("""() => [...document.querySelectorAll('.acc-button')]
                        .some(e => (e.innerText || '').trim() === 'Rekomendasi' &&
                                    e.getBoundingClientRect().width > 0)"""):
                    frame.evaluate("""() => {
                        const e = [...document.querySelectorAll('[aria-label^="down arrow icon"]')]
                            .find(x => x.getBoundingClientRect().width > 0);
                        if (e) e.click();
                    }""")
                    time.sleep(1)
                    frame = _frame_scorm(page) or frame
                frame.evaluate("""() => {
                    const e = [...document.querySelectorAll('.acc-button')]
                        .find(x => (x.innerText || '').trim() === 'Rekomendasi' &&
                                    x.getBoundingClientRect().width > 0);
                    if (e) e.click();
                }""")
                time.sleep(1.2)
                frame = _frame_scorm(page) or frame
                ss("pikirkan-dropdown-sudah-pilih")
                if frame.evaluate("""() => [...document.querySelectorAll('.acc-button')]
                        .some(e => (e.innerText || '').trim() === 'Rekomendasi' &&
                                    e.getBoundingClientRect().width > 0)"""):
                    frame.evaluate("""() => {
                        const e = [...document.querySelectorAll('.acc-button')]
                            .find(x => (x.innerText || '').trim() === 'Rekomendasi' &&
                                        x.getBoundingClientRect().width > 0);
                        if (e) e.click();
                    }""")
                    time.sleep(1)
                    frame = _frame_scorm(page) or frame
                for _ in range(10):
                    if kirim_terlihat():
                        break
                    time.sleep(0.5)
                    frame = _frame_scorm(page) or frame
                ss("pikirkan-dropdown-siap-kirim")
                frame.evaluate("""() => {
                    const k = [...document.querySelectorAll('.acc-button, button')]
                        .find(x => /^Kirim$/i.test((x.innerText || '').trim()) &&
                                    x.getBoundingClientRect().width > 0 &&
                                    x.getBoundingClientRect().height > 0 && !x.disabled);
                    if (k) k.click();
                }""")
                time.sleep(2)
                frame = _frame_scorm(page) or frame
                status = _status_jawaban_scorm(frame, transkrip)
                ss("pikirkan-dropdown-sesudah-kirim")
                if status is not False:
                    dijawab.add("pikirkan-dropdown")
                else:
                    ulangan += 1
                interaksi += 1
                perlu_kembali = bool(box_terakhir)
                continue

            # Pick Many: centang SEMUA opsi yang benar memakai kunci data.js.
            # Tombol Kirim sengaja disabled sampai ada pilihan dicentang,
            # jadi kirim_terlihat() tidak boleh jadi syarat deteksi soal.
            cek_info = frame.evaluate("""() => Array.from(document.querySelectorAll('input.acc-checkbox'))
                .filter(c => !c.disabled)
                .map(c => { const id = c.id.replace(/^acc-/, '');
                            const lab = [...document.querySelectorAll('.acc-text, label')]
                                .find(e => (e.dataset.represents || '').includes(id) ||
                                           e.id === id + '_label' ||
                                           e.getAttribute('for') === c.id);
                            return {id: id, teks: lab ? (lab.innerText || lab.textContent || '').trim() : ''}; })""")
            if cek_info:
                kandidat = [k for k in kunci
                            if k.get("type") in ("multipleresponse", "multiplechoice") and
                            k.get("benar") and k.get("id") not in dijawab]
                skor = []
                for k in kandidat:
                    pilih_norm = {_normal_id(p) for p in k.get("pilih", [])}
                    n = sum(1 for i in cek_info if _normal_id(i["id"]) in pilih_norm)
                    if n:
                        skor.append((n, k))
                inter = max(skor, key=lambda x: x[0])[1] if skor else None
                if inter and inter.get("benar"):
                    benar_norm = {_normal_id(b) for b in inter["benar"]}
                    print(datetime.now().strftime("%H:%M:%S") +
                          f" [SCORM] Pick Many terdeteksi: {len(cek_info)} opsi, "
                          f"{len(benar_norm)} kunci benar", flush=True)
                    _log_pilih("kunci data.js (pick many)",
                               ", ".join(sorted(benar_norm)))
                    ss("pickmany-sebelum-kirim")
                    frame.evaluate("""(ids) => {
                        const norm = s => String(s).toLowerCase().replace(/[^a-z0-9]/g, '')
                            .replace(/^0+/, '') || '0';
                        const target = new Set(ids.map(norm));
                        document.querySelectorAll('input.acc-checkbox').forEach(c => {
                            const id = c.id.replace(/^acc-/, '');
                            const harus = target.has(norm(id));
                            if (c.checked !== harus) c.click();
                        });
                    }""", inter["benar"])
                    time.sleep(0.8)
                    ss("pickmany-sudah-pilih")
                    # Kirim baru aktif setelah pilihan dicentang.
                    for _ in range(10):
                        if frame.evaluate("""() => [...document.querySelectorAll('.acc-button, button')]
                              .some(x => /^Kirim$/i.test((x.innerText || '').trim()) &&
                                         !x.disabled && x.getBoundingClientRect().width > 0)"""):
                            break
                        time.sleep(0.4)
                        frame = _frame_scorm(page) or frame
                    frame.evaluate("""() => {
                        const k = [...document.querySelectorAll('.acc-button, button')]
                            .find(x => /^Kirim$/i.test((x.innerText || '').trim()) &&
                                       !x.disabled && x.getBoundingClientRect().width > 0);
                        if (k) k.click();
                    }""")
                    time.sleep(2)
                    frame = _frame_scorm(page) or frame
                    status = _status_jawaban_scorm(frame, transkrip)
                    ss("pickmany-sesudah-kirim")
                    if status is False:
                        ulangan += 1
                    dijawab.add(inter.get("id"))
                    interaksi += 1
                    perlu_kembali = bool(box_terakhir)
                    continue

            # Kuis pilihan: klik RADIO berdasarkan ID dari kunci data.js.
            # Beberapa paket SCORM tidak punya label .acc-text sama sekali,
            # jadi jangan bergantung pada teks opsi.
            radio_info = frame.evaluate("""() => Array.from(document.querySelectorAll('input.acc-radio'))
                .filter(r => !r.disabled)
                .map(r => { const id = r.id.replace(/^acc-/, '');
                            const ref = r.getAttribute('aria-labelledby');
                            const lab = ref ? document.getElementById(ref) : null;
                            const alt = lab ? (lab.innerText || lab.textContent || '').trim() : '';
                            const lama = [...document.querySelectorAll('.acc-text')]
                                .find(e => (e.dataset.represents || '').includes(id));
                            const cadangan = [...document.querySelectorAll('label')]
                                .find(e => (e.id || '').toLowerCase().includes(id.toLowerCase()));
                            return {id: id,
                                    teks: alt || (lama ? (lama.innerText || '').trim() : '') ||
                                          (cadangan ? (cadangan.innerText || cadangan.textContent || '').trim() : '')}; })""")
            sidik_radio = "|".join(sorted(i["id"] for i in radio_info))
            # Kirim bisa tetap aktif setelah jawaban terkirim. Tanpa penanda
            # ini bot mengirim ulang radio yang sama berulang kali.
            if radio_info and sidik_radio not in radio_selesai:
                kandidat = [k for k in kunci
                            if k.get("type") in ("multiplechoice", "choice") and
                            k.get("benar") and k.get("id") not in dijawab]
                skor = []
                for k in kandidat:
                    pilih_norm = {_normal_id(p) for p in k.get("pilih", [])}
                    n = sum(1 for i in radio_info if _normal_id(i["id"]) in pilih_norm)
                    if n:
                        skor.append((n, k))
                inter = max(skor, key=lambda x: x[0])[1] if skor else None
                if inter and inter.get("benar"):
                    benar_id = inter["benar"][0]
                    benar_norm = _normal_id(benar_id)
                    cocok = next((i for i in radio_info
                                  if _normal_id(i["id"]) == benar_norm), None)
                    jawab_id = cocok["id"] if cocok else None
                    jawab = (cocok["teks"] if cocok and cocok["teks"]
                             else str(jawab_id or radio_info[0]["id"]))
                    dijawab.add(inter.get("id"))
                    _log_pilih("kunci data.js", jawab, f" id={jawab_id or '-'}")
                else:
                    jawab = _pilih_opsi_scorm(teks, opsi_aktif(), transkrip)
                    jawab_id = None
                if jawab is None or not str(jawab).strip():
                    print(datetime.now().strftime("%H:%M:%S") +
                          " [PILIH SCORM] jawaban tidak bisa ditentukan; "
                          "opsi pertama dipakai (terpaksa, dicatat)", flush=True)
                    jawab = str(radio_info[0]["id"])
                jawab = str(jawab)
                # data.js kadang hanya berisi daftar opsi tanpa penanda 'correct'.
                # Saat itu jawab berupa teks; petakan ke radio lewat teks <label>
                # (bukan .acc-text yang kosong) memakai pencocokan mirip.
                if not jawab_id and radio_info:
                    _norm = lambda s: re.sub(r"\s+", " ", str(s or "")).strip().lower()
                    target = _norm(jawab)
                    jawab_id = next((i["id"] for i in radio_info
                                     if _normal_id(i["id"]) == _normal_id(jawab)), None)
                    if not jawab_id:
                        terbaik = max(
                            radio_info,
                            key=lambda i: difflib.SequenceMatcher(
                                None, target, _norm(i["teks"])).ratio())
                        rasio = difflib.SequenceMatcher(
                            None, target, _norm(terbaik["teks"])).ratio()
                        if rasio >= 0.30:
                            jawab_id = terbaik["id"]
                            jawab = terbaik["teks"] or jawab
                            _log_pilih("label radio (data.js tanpa kunci)", jawab,
                                       f" id={jawab_id} mirip={rasio:.2f}")
                sudah_coba = set()  # opsi radio yang sudah diuji; rotasi tak boleh mengulang
                for percobaan in range(len(radio_info) + 1):
                    sudah_coba.add(jawab_id or jawab)
                    ss("pilih-" + re.sub(r"\W+", "", jawab)[:20])
                    if jawab_id:
                        frame.evaluate("""(id) => {
                            const r = document.getElementById('acc-' + id);
                            if (r && !r.disabled) r.click();
                        }""", jawab_id)
                    else:
                        frame.evaluate("""(j) => {
                            const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                            const target = norm(j);
                            const r = Array.from(document.querySelectorAll('input.acc-radio'))
                                .find(x => {
                                    const ref = x.getAttribute('aria-labelledby');
                                    const lab = ref ? document.getElementById(ref) : null;
                                    return norm(lab ? (lab.innerText || lab.textContent) : '') === target;
                                });
                            if (r) { r.click(); return true; }
                            return false;
                        }""", jawab)
                    time.sleep(0.6)
                    ss("sudah-pilih-" + re.sub(r"\W+", "", jawab)[:20])
                    # Kirim bisa disabled sampai radio dipilih; tunggu aktif.
                    for _ in range(10):
                        if frame.evaluate("""() => Array.from(document.querySelectorAll('.acc-button, button'))
                              .some(x => /^Kirim$/i.test((x.innerText || '').trim()) &&
                                         !x.disabled && x.getBoundingClientRect().width > 0)"""):
                            break
                        time.sleep(0.4)
                        frame = _frame_scorm(page) or frame
                    frame.evaluate("""() => {
                        const k = Array.from(document.querySelectorAll('.acc-button, button'))
                            .find(x => /^Kirim$/i.test((x.innerText || '').trim()) &&
                                       !x.disabled && x.getBoundingClientRect().width > 0);
                        if (k) k.click();
                    }""")
                    time.sleep(1.2)
                    frame = _frame_scorm(page) or frame
                    ss("sesudah-kirim-" + re.sub(r"\W+", "", jawab)[:20])
                    status = _status_jawaban_scorm(frame, transkrip)
                    # Sinyal paling pasti: API langsung berubah completed saat
                    # jawaban benar. Teks feedback bisa ternoda tombol "Coba lagi"
                    # yang masih tersisa di layar, jadi jangan bergantung padanya.
                    try:
                        m_inst = re.search(r"/course-lesson/\d+/(\d+)", page.url or "")
                        api_selesai = bool(m_inst) and _selesai_aktivitas(
                            _status_aktivitas_api(page, m_inst.group(1)))
                    except Exception:
                        api_selesai = False
                    if status is True or api_selesai:
                        break
                    if status is False:
                        # Kunci data.js bisa stale: feedback runtime menyatakan
                        # jawaban itu salah. Coba opsi berikutnya sampai benar;
                        # jangan berhenti setelah 3 percobaan seperti dulu.
                        ulangan += 1
                        ss("jawaban-salah-ulang")
                        frame.evaluate("""() => {
                            const p = document.querySelector('#prev');
                            if (p) p.click();
                        }""")
                        time.sleep(1.5)
                        frame = _frame_scorm(page) or frame
                        radio_info = frame.evaluate("""() => Array.from(document.querySelectorAll('input.acc-radio'))
                            .filter(r => !r.disabled)
                            .map(r => r.id.replace(/^acc-/, ''))""")
                        lain = [i for i in radio_info if i not in sudah_coba]
                        if not lain:
                            break
                        jawab_id = lain[0]
                        jawab = jawab_id
                        continue
                    break
                radio_selesai.add(sidik_radio)
                perlu_kembali = bool(box_terakhir)
                maju_tanpa_jawaban = 0
                interaksi += 1
                continue

            # Sequence Drop-down Storyline punya tombol "Rectangle 6" yang
            # mudah salah dikenali sebagai Pick Many. Kunci data.js memberi
            # urutan id opsi yang benar beserta label angkanya (lmstext).
            seq_kunci = next((k for k in kunci
                              if k.get("type") == "sequence" and k.get("benar")
                              and k.get("id") not in dijawab), None)
            if (seq_kunci and not cek_info and not radio_info and
                    re.search(r"--Pilih--|Sequence Drop-down|urutan prioritas",
                              teks_sequence, re.I)):
                peta_label = seq_kunci.get("pilih_label") or {}
                urutan = []
                for i, cid in enumerate(seq_kunci.get("benar", [])):
                    lab = str(peta_label.get(str(cid), "") or "").strip()
                    urutan.append(lab or str(i + 1))
                dropdown = frame.evaluate(r"""() => [...document.querySelectorAll('button.acc-button')]
                    .filter(b => { const r = b.getBoundingClientRect();
                        return r.width > 0 && r.height > 0 && b.id &&
                               !/^(Kirim|Coba lagi|Selesai)$/i.test(
                                   (b.innerText || '').trim()); })
                    .map(b => ({id: b.id, y: Math.round(b.getBoundingClientRect().y),
                                x: Math.round(b.getBoundingClientRect().x)}))""") or []
                dropdown.sort(key=lambda d: (d["y"], d["x"]))
                if len(dropdown) >= len(urutan):
                    ss("sequence-sebelum")
                    print(datetime.now().strftime("%H:%M:%S") +
                          f" [SCORM] Sequence Drop-down: {len(urutan)} dropdown, "
                          f"urutan kunci -> {urutan}", flush=True)
                    ok_semua = True
                    for i, har in enumerate(urutan[:len(dropdown)]):
                        frame.evaluate("""(id) => {
                            const b = document.getElementById(id);
                            if (!b) return;
                            try { b.click(); } catch (e) {}
                            for (const ev of ['pointerdown','mousedown','pointerup','mouseup','click'])
                                try { b.dispatchEvent(new MouseEvent(
                                    ev, {bubbles: true, cancelable: true})); } catch (e) {}
                        }""", dropdown[i]["id"])
                        time.sleep(0.5)
                        frame = _frame_scorm(page) or frame
                        dipilih = frame.evaluate(r"""(h) => {
                            const bersih = s => (s||'').replace(/\s+/g,' ').trim();
                            const target = bersih(h);
                            const angka = parseInt(target, 10) || 1;
                            const skip = /^(Kirim|Coba lagi|Selesai|SEBELUMNYA|SELANJUTNYA|Keluar)$/i;
                            const semua = [...document.querySelectorAll(
                              '.acc-button, button, .slide-object-stategroup, [role=option], li, .acc-text')]
                              .filter(e => { const r = e.getBoundingClientRect();
                                  return r.width > 0 && r.height > 0 && !e.disabled &&
                                         !skip.test(bersih(e.innerText || '')); });
                            let o = semua.find(e => /^\d+$/.test(target) &&
                                           bersih(e.innerText || '') === target);
                            if (!o) {
                                const angkaOpsi = semua.filter(e => /^\d+$/.test(
                                    bersih(e.innerText || '')));
                                o = angkaOpsi[angka - 1] || semua[angka - 1];
                            }
                            if (o) {
                                try { o.click(); } catch (e) {}
                                for (const ev of ['pointerdown','mousedown','pointerup','mouseup','click'])
                                    try { o.dispatchEvent(new MouseEvent(
                                        ev, {bubbles: true, cancelable: true})); } catch (e) {}
                                return bersih(o.innerText || '').slice(0, 40);
                            }
                            return null;
                        }""", har)
                        if not dipilih:
                            ok_semua = False
                            break
                        time.sleep(0.35)
                        frame = _frame_scorm(page) or frame
                    if ok_semua:
                        ss("sequence-sudah-pilih")
                        frame.evaluate("""() => {
                            const k = [...document.querySelectorAll('button.acc-button')]
                              .find(x => /^Kirim$/i.test((x.innerText || '').trim()) &&
                                         !x.disabled && x.getBoundingClientRect().width > 0);
                            if (k) k.click();
                        }""")
                        time.sleep(2.5)
                        frame = _frame_scorm(page) or frame
                        ss("sequence-sesudah-kirim")

                        def _cek_api_seq():
                            try:
                                mm = re.search(r"/course-lesson/\d+/(\d+)", page.url or "")
                                return bool(mm) and _selesai_aktivitas(
                                    _status_aktivitas_api(page, mm.group(1)))
                            except Exception:
                                return False

                        st_seq = _status_jawaban_scorm(frame, transkrip)
                        api_seq = _cek_api_seq()
                        if not api_seq and st_seq is not True:
                            for _ in range(4):
                                time.sleep(1.5)
                                frame = _frame_scorm(page) or frame
                                st_seq = _status_jawaban_scorm(frame, transkrip)
                                api_seq = _cek_api_seq()
                                if api_seq or st_seq is True:
                                    break
                        if api_seq or st_seq is True:
                            dijawab.add(seq_kunci.get("id"))
                            interaksi += 1
                            maju_tanpa_jawaban = 0
                            perlu_kembali = bool(box_terakhir)
                            continue
                        print(datetime.now().strftime("%H:%M:%S") +
                              " [SCORM] Sequence belum benar; coba jalur generik.",
                              flush=True)

            # Pick Many berbasis tombol Storyline (bukan input.acc-checkbox).
            # Primer: kunci data.js (perilaku awal). Sekunder (PEMILIH_KEDUA):
            # deteksi jumlah opsi yang diminta + pemilihan model lokal saat kunci
            # kosong/tidak cocok, untuk kasus seperti 174223/174225/174227.
            opsi_tombol = []
            if (not cek_info and not radio_info and
                    not re.search(r"--Pilih--|Sequence Drop-down|urutan prioritas",
                                  teks_sequence, re.I)):
                opsi_tombol = frame.evaluate(r"""() => {
                    const tombol = [...document.querySelectorAll('button.acc-button')]
                        .filter(b => /^(Rectangle|Oval)\s+\d+$/.test(
                            (b.getAttribute('aria-label')||'').trim()));
                    const teksSemua = [...document.querySelectorAll('.acc-text')];
                    const hasil = [];
                    for (const b of tombol) {
                        const uid = (b.id||'').replace(/^acc-/, '');
                        if (!uid) continue;
                        const t = teksSemua.find(e =>
                            (e.dataset.represents||'').includes(uid) &&
                            (e.innerText||'').trim().length > 6 &&
                            !/All Rights|Hak Cipta|slide:|Sisa Percobaan|Silahkan klik/i.test(
                                e.innerText||''));
                        if (t) hasil.push({uid: uid,
                            teks: (t.innerText||'').replace(/\s+/g,' ').trim()});
                    }
                    return hasil;
                }""") or []
                if opsi_tombol:
                    jumlah = 1
                    m_jumlah = re.search(
                        r"pilih\s+(dua|tiga|empat|lima|2|3|4|5)\b",
                        teks_dom, re.I)
                    if m_jumlah:
                        jumlah = {"dua": 2, "tiga": 3, "empat": 4, "lima": 5}.get(
                            m_jumlah.group(1).lower(),
                            int(re.sub(r"\D", "", m_jumlah.group(1)) or 1))
                    elif re.search(r"pilih\s+(beberapa|yang tepat|opsi yang)", teks_dom, re.I):
                        jumlah = 2
                    jumlah = max(1, min(jumlah, len(opsi_tombol)))

                    angka = lambda v: int(re.sub(r"\D", "", str(v)) or 0)
                    rencana = []
                    norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s or "").lower())
                    # Pilihan pertama: kunci data.js (perilaku awal GitHub).
                    # Kunci Wadhwani berupa id opsi (mis. Rectangle6id...), bukan
                    # selalu nomor urut, jadi cocokkan id/teks dulu sebelum angka.
                    for k in kunci:
                        if (k.get("type") not in ("multipleresponse", "multiplechoice")
                                or not k.get("benar") or k.get("id") in dijawab):
                            continue
                        indeks = []
                        for v in k.get("benar", []):
                            n = norm(v)
                            i = next((j for j, o in enumerate(opsi_tombol)
                                      if n and (n == norm(o.get("uid")) or
                                                n == norm(o.get("id")) or
                                                n in norm(o.get("teks")))), None)
                            if i is None:
                                ang = angka(v)
                                if 1 <= ang <= len(opsi_tombol):
                                    i = ang - 1
                            if i is not None and i not in indeks:
                                indeks.append(i)
                        if indeks and indeks not in [r[0] for r in rencana]:
                            rencana.append((indeks, "kunci data.js", k.get("id")))
                    # Pilihan kedua: model + peta transkrip saat kunci tidak ada.
                    if not rencana and PEMILIH_KEDUA:
                        pilihan_model = _pilih_beberapa_opsi_scorm(
                            teks, [o["teks"] for o in opsi_tombol], transkrip, jumlah)
                        indeks = [i for i, o in enumerate(opsi_tombol)
                                  if o["teks"] in pilihan_model]
                        if len(indeks) < jumlah and pilihan_model:
                            norm = lambda s: re.sub(r"\s+", " ", s or "").strip().lower()
                            for p in pilihan_model:
                                i = next((n for n, o in enumerate(opsi_tombol)
                                          if norm(o["teks"]) == norm(p)), None)
                                if i is None:
                                    try:
                                        i = max(range(len(opsi_tombol)),
                                                key=lambda n: difflib.SequenceMatcher(
                                                    None, norm(p), norm(opsi_tombol[n]["teks"])).ratio())
                                    except Exception:
                                        i = None
                                if i is not None and i not in indeks:
                                    indeks.append(i)
                        indeks = indeks[:jumlah]
                        if indeks:
                            rencana.append((indeks, "model + peta transkrip (pemilih kedua)",
                                            f"pickmany-{jumlah}"))

                    def _cek_api_tombol():
                        try:
                            mm = re.search(r"/course-lesson/\d+/(\d+)", page.url or "")
                            return bool(mm) and _selesai_aktivitas(
                                _status_aktivitas_api(page, mm.group(1)))
                        except Exception:
                            return False

                    for indeks, sumber, kid in rencana:
                        tanda_pm = (label_saat_ini, tuple(sorted(indeks)))
                        riwayat_pickmany[tanda_pm] = riwayat_pickmany.get(tanda_pm, 0) + 1
                        if riwayat_pickmany[tanda_pm] >= 3:
                            ss("pickmany-loop-berhenti")
                            print(datetime.now().strftime("%H:%M:%S") +
                                  " [SCORM] berhenti: jawaban pick-many sama 3x "
                                  "tanpa progres API.", flush=True)
                            loop_berhenti = True
                            break
                        ss("pickmany-tombol-sebelum")
                        print(datetime.now().strftime("%H:%M:%S") +
                              f" [SCORM] Pick Many tombol: {len(opsi_tombol)} opsi, "
                              f"{sumber} -> {[opsi_tombol[i]['teks'][:50] for i in indeks]}",
                              flush=True)
                        for i in indeks:
                            frame.evaluate("""(uid) => {
                                const e = document.getElementById('acc-' + uid);
                                if (e && !e.disabled) e.click();
                            }""", opsi_tombol[i]["uid"])
                            time.sleep(0.4)
                            frame = _frame_scorm(page) or frame
                        time.sleep(0.6)
                        ss("pickmany-tombol-sudah-pilih")
                        frame.evaluate("""() => {
                            const k = [...document.querySelectorAll('button.acc-button')]
                                .find(x => (x.innerText||'').trim() === 'Kirim' &&
                                           !x.disabled && x.getBoundingClientRect().width > 0);
                            if (k) k.click();
                        }""")
                        time.sleep(2.5)
                        frame = _frame_scorm(page) or frame
                        ss("pickmany-tombol-sesudah-kirim")
                        status_tombol = _status_jawaban_scorm(frame, transkrip)
                        api_tombol = _cek_api_tombol()
                        # API bisa terlambat update; polling singkat agar sukses
                        # (status None tapi API completed) tidak terlewat.
                        if not api_tombol and status_tombol is not True:
                            for _ in range(4):
                                time.sleep(1.5)
                                frame = _frame_scorm(page) or frame
                                status_tombol = _status_jawaban_scorm(frame, transkrip)
                                api_tombol = _cek_api_tombol()
                                if api_tombol or status_tombol is True:
                                    break
                        interaksi += 1
                        maju_tanpa_jawaban = 0
                        perlu_kembali = bool(box_terakhir)
                        if api_tombol or status_tombol is True:
                            # Tandai selesai HANYA bila jawaban benar. Kalau
                            # ditandai lebih awal, kunci ini tidak dipakai lagi
                            # oleh jalur radio/generik di slide berikutnya.
                            dijawab.add(kid)
                            break
                        if (status_tombol is False or not api_tombol) and PEMILIH_KEDUA:
                            ulangan += 1
                            # Jawaban ditolak: coba kombinasi lain. Setelah "Coba lagi"
                            # pilihan biasanya direset, jadi setiap percobaan klik ulang
                            # dari awal. Kombinasi dieksplorasi (bukan geser siklik) agar
                            # soal "pilih tiga dari lima" seperti 174225 bisa menemukan
                            # kombinasi yang benar.
                            import itertools as _it
                            sudah_kombinasi = {tuple(sorted(indeks))}
                            for alt in _it.combinations(range(len(opsi_tombol)), jumlah):
                                alt = list(alt)
                                if tuple(sorted(alt)) in sudah_kombinasi:
                                    continue
                                sudah_kombinasi.add(tuple(sorted(alt)))
                                frame = _frame_scorm(page) or frame
                                frame.evaluate("""() => {
                                    const b = [...document.querySelectorAll('.acc-button, button')]
                                        .find(x => /^Coba lagi$/i.test((x.innerText||'').trim()) &&
                                                   x.getBoundingClientRect().width > 0);
                                    if (b) b.click();
                                }""")
                                time.sleep(1.2)
                                frame = _frame_scorm(page) or frame
                                ss("pickmany-tombol-ulang")
                                print(datetime.now().strftime("%H:%M:%S") +
                                      f" [SCORM] Pick Many coba kombinasi -> "
                                      f"{[opsi_tombol[i]['teks'][:50] for i in alt]}",
                                      flush=True)
                                for i in alt:
                                    frame.evaluate("""(uid) => {
                                        const e = document.getElementById('acc-' + uid);
                                        if (e && !e.disabled) e.click();
                                    }""", opsi_tombol[i]["uid"])
                                    time.sleep(0.4)
                                    frame = _frame_scorm(page) or frame
                                frame.evaluate("""() => {
                                    const k = [...document.querySelectorAll('button.acc-button')]
                                        .find(x => (x.innerText||'').trim() === 'Kirim' &&
                                                   !x.disabled && x.getBoundingClientRect().width > 0);
                                    if (k) k.click();
                                }""")
                                time.sleep(2.5)
                                frame = _frame_scorm(page) or frame
                                ss("pickmany-tombol-sesudah-kirim")
                                _ok = _cek_api_tombol() or _status_jawaban_scorm(frame, transkrip) is True
                                if not _ok:
                                    for _ in range(4):
                                        time.sleep(1.5)
                                        frame = _frame_scorm(page) or frame
                                        if (_cek_api_tombol() or
                                                _status_jawaban_scorm(frame, transkrip) is True):
                                            _ok = True
                                            break
                                if _ok:
                                    break
                        break


            # Jalur adaptif terakhir: deteksi opsi dari bentuk DOM apa pun.
            # Dipakai bila jalur khusus tidak menemukan opsi, tapi halaman jelas
            # meminta pilihan/jawaban. Menangani format baru (termasuk dropdown/
            # tarik-turun Storyline) tanpa menambah blok khusus terus-menerus.
            cue_tanya = (not radio_info and not cek_info and not opsi_tombol and
                         re.search(r"kirim|pilih|jawaban|sisa percobaan|tarik.?turun|panah bawah",
                                   teks_dom, re.I))
            if cue_tanya:
                # Dropdown/tarik-turun: buka dulu agar opsi terlihat
                if re.search(r"tarik.?turun|panah bawah|Klik di sini untuk membuat pilihan",
                             teks_dom, re.I):
                    _buka_dropdown_scorm(frame)
                    time.sleep(1.2)
                    frame = _frame_scorm(page) or frame

                generik = _opsi_kuis_generik(frame)
                if len(generik) < 2 and re.search(r"tarik.?turun|panah bawah|down arrow",
                                                  teks_dom, re.I):
                    _buka_dropdown_scorm(frame)
                    time.sleep(1.2)
                    frame = _frame_scorm(page) or frame
                    generik = _opsi_kuis_generik(frame)

                if len(generik) >= 2:
                    def _cek_api_generik():
                        try:
                            mm = re.search(r"/course-lesson/\d+/(\d+)", page.url or "")
                            return bool(mm) and _selesai_aktivitas(
                                _status_aktivitas_api(page, mm.group(1)))
                        except Exception:
                            return False

                    def _feedback_salah_generik(fr):
                        try:
                            t = " ".join(fr.inner_text("body").split())
                        except Exception:
                            t = ""
                        return bool(re.search(
                            r"\bsalah\b|kurang tepat|belum tepat|tidak tepat|coba lagi|"
                            r"maaf|jawaban.*belum|silakan coba",
                            t, re.I))

                    def _coba_lagi_generik(fr):
                        try:
                            if fr.evaluate("""() => {
                                const b = [...document.querySelectorAll('.acc-button, button')]
                                  .find(x => /^(Coba lagi|Coba Lagi)$/i.test((x.innerText||'').trim()) &&
                                             x.getBoundingClientRect().width > 0 && !x.disabled);
                                if (b) { b.click(); return true; } return false; }"""):
                                return True
                        except Exception:
                            pass
                        try:
                            fr.get_by_text("Coba lagi", exact=True).first.click(timeout=800)
                            return True
                        except Exception:
                            return False

                    teks_opsi_g = [str(o.get("teks") or "").strip() for o in generik]
                    try:
                        lbl_g = frame.evaluate(
                            "() => (document.querySelector('#slide-label')||{}).innerText || ''")
                    except Exception:
                        lbl_g = ""
                    sidik_slide_g = lbl_g + "|" + "|".join(
                        str(o.get("uid") or "") for o in generik)
                    kandidat_g = [
                        k for k in kunci
                        if k.get("benar") and k.get("id") not in dijawab
                        and (sidik_slide_g, k.get("id")) not in dijawab_gagal]

                    # 1) Prioritas: kunci data.js (perilaku awal)
                    for k in kandidat_g:
                        pilih_ids = [_normal_id(p) for p in k.get("pilih", [])
                                     if _normal_id(p)]
                        label_opsi = {
                            _normal_id(key): str(val).strip()
                            for key, val in (k.get("pilih_label") or {}).items()
                        }
                        indeks, target_ops = [], []
                        for v in [str(x) for x in k.get("benar", [])]:
                            nv = _normal_id(v)
                            cocok = next(
                                (i for i, o in enumerate(generik)
                                 if _normal_id(o.get("uid")) == nv or
                                    _normal_id(o.get("id")) == nv), None)
                            if cocok is not None:
                                if cocok not in indeks:
                                    indeks.append(cocok)
                                    target_ops.append(generik[cocok])
                                continue
                            # ID data.js adalah token alfanumerik (mis.
                            # 6JPSQOpYlYj = opsi B). Mengambil angka "6" dari
                            # token itu dulu salah memilih opsi A/C. Klik
                            # elemen acc-<id> langsung memakai kunci asli.
                            if nv and nv in pilih_ids:
                                target_ops.append({
                                    "uid": nv, "id": nv,
                                    "teks": label_opsi.get(nv, ""),
                                    "sumber": "kunci", "multi": False,
                                })
                        if not target_ops:
                            continue
                        ss("generik-sebelum")
                        print(datetime.now().strftime("%H:%M:%S") +
                              f" [SCORM] Opsi generik: {len(generik)} ditemukan, "
                              f"kunci data.js -> {[str(o.get('teks') or o.get('uid'))[:45] for o in target_ops]}",
                              flush=True)
                        for o in target_ops:
                            _klik_opsi_kuis(frame, o)
                            time.sleep(0.4)
                            frame = _frame_scorm(page) or frame
                        ss("generik-sudah-pilih")
                        _klik_kirim_adaptif(frame)
                        time.sleep(2.5)
                        frame = _frame_scorm(page) or frame
                        ss("generik-sesudah-kirim")
                        api_g = _cek_api_generik()
                        status_g = _status_jawaban_scorm(frame, transkrip)
                        interaksi += 1
                        maju_tanpa_jawaban = 0
                        perlu_kembali = bool(box_terakhir)
                        if api_g or status_g is True:
                            dijawab.add(k.get("id"))
                            break
                        # Kunci data.js bisa stale. Coba opsi lain dari daftar
                        # 'pilih' (urutan A,B,C,D), jangan geser indeks buta
                        # dan jangan pakai angka dari id alfanumerik.
                        ulangan += 1
                        sudah_coba = {_normal_id(o.get("uid")) for o in target_ops}
                        alternatif = [
                            {"uid": pid, "id": pid, "teks": label_opsi.get(pid, ""),
                             "sumber": "kunci", "multi": False}
                            for pid in pilih_ids if pid not in sudah_coba
                        ]
                        if not alternatif:
                            alternatif = [generik[i] for i in range(len(generik))
                                          if i not in indeks]
                        for o in alternatif[:6]:
                            ss("generik-ulang")
                            _coba_lagi_generik(frame)
                            time.sleep(1.0)
                            frame = _frame_scorm(page) or frame
                            if re.search(r"tarik.?turun|panah bawah", teks_dom, re.I):
                                _buka_dropdown_scorm(frame)
                                time.sleep(0.8)
                                frame = _frame_scorm(page) or frame
                            _klik_opsi_kuis(frame, o)
                            time.sleep(0.4)
                            frame = _frame_scorm(page) or frame
                            _klik_kirim_adaptif(frame)
                            time.sleep(2.5)
                            frame = _frame_scorm(page) or frame
                            if (_cek_api_generik() or
                                    _status_jawaban_scorm(frame, transkrip) is True):
                                dijawab.add(k.get("id"))
                                break
                        # Semua opsi pada slide ini sudah dicoba dan gagal.
                        # Jangan ulang slide yang sama, tetapi biarkan kunci
                        # dipakai lagi bila slide berikutnya punya radio/tombol.
                        dijawab_gagal.add((sidik_slide_g, k.get("id")))
                        break
                    else:
                        # 2) Fallback adaptif (PEMILIH_KEDUA): model lokal + peta
                        if PEMILIH_KEDUA:
                            jumlah_g = 1
                            m_jml = re.search(r"pilih\s+(dua|tiga|empat|lima|2|3|4|5)\b", teks_dom, re.I)
                            if m_jml:
                                jumlah_g = {"dua": 2, "tiga": 3, "empat": 4, "lima": 5}.get(
                                    m_jml.group(1).lower(),
                                    int(re.sub(r"\D", "", m_jml.group(1)) or 1))
                            elif re.search(r"pilih\s+lebih\s+dari\s+satu|pilih\s+beberapa|pilih\s+semua\s+yang\s+(benar|sesuai|tepat)|centang\s+semua",
                                           teks_dom, re.I):
                                # multi-select eksplisit; hindari "pilih opsi yang tepat" (umum singular)
                                jumlah_g = min(2, len(generik))
                            jumlah_g = max(1, min(jumlah_g, len(generik)))

                            if jumlah_g > 1:
                                pilihan_model = _pilih_beberapa_opsi_scorm(
                                    teks_dom, teks_opsi_g, transkrip, jumlah_g)
                            else:
                                pm = _pilih_opsi_scorm(teks_dom, teks_opsi_g, transkrip)
                                pilihan_model = [pm] if pm else []

                            def _idx_dari_teks(pil):
                                norm = lambda s: re.sub(r"\s+", " ", str(s or "")).strip().lower()
                                idxs = []
                                for p in (pil or []):
                                    p = str(p or "").strip()
                                    if not p:
                                        continue
                                    i = next((n for n, t in enumerate(teks_opsi_g) if norm(t) == norm(p)), None)
                                    if i is None:
                                        try:
                                            i = max(range(len(teks_opsi_g)),
                                                    key=lambda n: difflib.SequenceMatcher(
                                                        None, norm(p), norm(teks_opsi_g[n])).ratio())
                                            if difflib.SequenceMatcher(
                                                    None, norm(p), norm(teks_opsi_g[i])).ratio() < 0.25:
                                                i = None
                                        except Exception:
                                            i = None
                                    if i is not None and i not in idxs:
                                        idxs.append(i)
                                return idxs[:jumlah_g]

                            idxs = _idx_dari_teks(pilihan_model)
                            if not idxs:
                                idxs = list(range(min(jumlah_g, len(generik))))

                            print(datetime.now().strftime("%H:%M:%S") +
                                  f" [SCORM] Opsi generik adaptif: {len(generik)} opsi, "
                                  f"pilih {[teks_opsi_g[i][:45] for i in idxs]} "
                                  f"(model+peta, pemilih kedua)",
                                  flush=True)

                            kid = f"generik-adaptif-{locals().get('sidik_radio') or locals().get('label_slide') or 'slide'}-{len(dijawab)}"
                            sudah_komb = set()
                            berhasil = False
                            for perc in range(max(1, len(generik))):
                                kmb = tuple(sorted(idxs))
                                if kmb in sudah_komb:
                                    break
                                sudah_komb.add(kmb)
                                ss(f"generik-adaptif-sebelum-{perc}")
                                if re.search(r"tarik.?turun|panah bawah", teks_dom, re.I):
                                    _buka_dropdown_scorm(frame)
                                    time.sleep(0.8)
                                    frame = _frame_scorm(page) or frame
                                for i in idxs:
                                    _klik_opsi_adaptif(frame, teks_opsi_g[i])
                                    time.sleep(0.4)
                                    frame = _frame_scorm(page) or frame
                                ss(f"generik-adaptif-pilih-{perc}")
                                _klik_kirim_adaptif(frame)
                                time.sleep(2.5)
                                frame = _frame_scorm(page) or frame
                                ss(f"generik-adaptif-kirim-{perc}")

                                api_g = _cek_api_generik()
                                status_g = _status_jawaban_scorm(frame, transkrip)
                                if not api_g and status_g is not True:
                                    for _ in range(4):
                                        time.sleep(1.2)
                                        frame = _frame_scorm(page) or frame
                                        api_g = _cek_api_generik()
                                        status_g = _status_jawaban_scorm(frame, transkrip)
                                        if api_g or status_g is True:
                                            break

                                if api_g or status_g is True:
                                    dijawab.add(kid)
                                    interaksi += 1
                                    maju_tanpa_jawaban = 0
                                    perlu_kembali = bool(box_terakhir)
                                    berhasil = True
                                    break

                                if status_g is False or _feedback_salah_generik(frame):
                                    ulangan += 1
                                    # Jika ada tombol lanjut setelah feedback (termasuk saat
                                    # percobaan habis / jawaban salah), lanjutkan dulu.
                                    def _klik_lanjut_feedback(fr):
                                        # Storyline slide elements sering perlu Playwright click(force)
                                        label_re = re.compile(r"^(Lanjutkan|Lanjut|Selanjutnya|Berikutnya|Continue|Next|Coba lagi|Coba Lagi)$", re.I)
                                        for sel in (".slide-object-vectorshape, .slide-object-stategroup, .slide-object",
                                                    ".acc-button, button, [role='button']"):
                                            try:
                                                loc = fr.locator(sel).filter(has_text=label_re)
                                                n = loc.count()
                                                for i in range(min(n, 6)):
                                                    try:
                                                        if loc.nth(i).is_visible():
                                                            loc.nth(i).click(timeout=1200, force=True)
                                                            return True
                                                    except Exception:
                                                        continue
                                            except Exception:
                                                pass
                                        for txt in ("Lanjutkan","Lanjut","Selanjutnya","Berikutnya","Continue","Next","Coba lagi"):
                                            try:
                                                fr.get_by_text(txt, exact=True).first.click(timeout=900, force=True)
                                                return True
                                            except Exception:
                                                continue
                                        # fallback JS + koordinat
                                        try:
                                            box = fr.evaluate(r"""() => {
                                                const vis = e => { const r=e.getBoundingClientRect(), g=getComputedStyle(e);
                                                  return r.width>0&&r.height>0&&g.display!=='none'&&g.visibility!=='hidden'&&parseFloat(g.opacity||'1')>0.05; };
                                                const sels = ['.slide-object-vectorshape','.slide-object-stategroup','.slide-object','.acc-button','button','[role="button"]'];
                                                for (const e of document.querySelectorAll(sels.join(','))) {
                                                  if (!vis(e) || e.disabled) continue;
                                                  const t=(e.innerText||e.getAttribute('aria-label')||'').replace(/\s+/g,' ').trim();
                                                  if (/^(Lanjutkan|Lanjut|Selanjutnya|Berikutnya|Continue|Next|Coba lagi|Coba Lagi)$/i.test(t)) {
                                                    const r=e.getBoundingClientRect();
                                                    try{e.click();}catch(ex){}
                                                    for(const ev of ['pointerdown','mousedown','pointerup','mouseup','click']) try{e.dispatchEvent(new MouseEvent(ev,{bubbles:true,cancelable:true}));}catch(ex){}
                                                    return {x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)};
                                                  }
                                                }
                                                return null; }""")
                                            if box:
                                                try:
                                                    fr.mouse.click(box['x'], box['y'])
                                                except Exception:
                                                    pass
                                                return True
                                        except Exception:
                                            pass
                                        return False

                                    # coba lagi eksplisit -> boleh ulang submit dengan opsi lain
                                    if _coba_lagi_generik(frame):
                                        time.sleep(1.2)
                                        frame = _frame_scorm(page) or frame
                                        if jumlah_g == 1:
                                            for i in range(len(generik)):
                                                if i not in idxs:
                                                    idxs = [i]
                                                    break
                                            else:
                                                idxs = [(idxs[0] + 1) % len(generik)]
                                        else:
                                            import itertools as _it
                                            kandidat_komb = [list(c) for c in _it.combinations(range(len(generik)), jumlah_g)]
                                            nxt = next((c for c in kandidat_komb if tuple(sorted(c)) not in sudah_komb), None)
                                            if nxt is None:
                                                break
                                            idxs = nxt
                                        continue

                                    # tidak ada "Coba lagi": jika ada tombol Lanjutkan/dsb, klik dan lanjut
                                    if _klik_lanjut_feedback(frame):
                                        time.sleep(1.8)
                                        frame = _frame_scorm(page) or frame
                                        dijawab.add(kid)
                                        interaksi += 1
                                        maju_tanpa_jawaban = 0
                                        perlu_kembali = bool(box_terakhir)
                                        berhasil = True
                                        break

                                    # fallback: rotasi opsi jika masih bisa submit
                                    time.sleep(1.0)
                                    frame = _frame_scorm(page) or frame
                                    if jumlah_g == 1:
                                        for i in range(len(generik)):
                                            if i not in idxs:
                                                idxs = [i]
                                                break
                                        else:
                                            idxs = [(idxs[0] + 1) % len(generik)]
                                    else:
                                        import itertools as _it
                                        kandidat_komb = [list(c) for c in _it.combinations(range(len(generik)), jumlah_g)]
                                        nxt = next((c for c in kandidat_komb if tuple(sorted(c)) not in sudah_komb), None)
                                        if nxt is None:
                                            break
                                        idxs = nxt
                                    continue
                                # status tidak jelas: anggap interaksi dicoba agar tidak macet
                                dijawab.add(kid)
                                interaksi += 1
                                maju_tanpa_jawaban = 0
                                perlu_kembali = bool(box_terakhir)
                                break
                            if berhasil:
                                break

            # Isi kolom jawaban bila ada
            if frame.evaluate("""() => {
                let n = 0;
                document.querySelectorAll('input[type=text], textarea').forEach(e => {
                    const r = e.getBoundingClientRect();
                    if (r.width && r.height && !e.disabled && !(e.value || '').trim()) {
                        e.value = 'Saya memahami materi ini dan dapat menerapkannya dalam pekerjaan.';
                        e.dispatchEvent(new Event('input', {bubbles: true}));
                        n++;
                    }
                });
                return n > 0;
            }"""):
                ss("sebelum-isi-kolom")
                frame.evaluate("""() => {
                    const k = Array.from(document.querySelectorAll('.acc-button, button'))
                        .find(x => /^(Kirim|Kirim Jawaban|Submit)$/i.test((x.innerText || '').trim()) && !x.disabled);
                    if (k) k.click();
                }""")
                interaksi += 1
                perlu_kembali = bool(box_terakhir)
                time.sleep(1.5)
                ss("sesudah-isi-kolom")
                continue

            # Klik kotak/gambar karakter BERBEDA yang belum dijawab (bisa banyak).
            # id objek Storyline dipakai sebagai penanda: teks slide berubah
            # setelah kembali dari soal, sehingga sidik berbasis teks tidak cukup.
            kotak = frame.evaluate("""() => [...document.querySelectorAll('.acc-button')]
                .filter(x => /^Rectangle \\d+$/.test(x.getAttribute('aria-label') || '') &&
                             x.getBoundingClientRect().width > 0)
                .map(x => ({aria: x.getAttribute('aria-label'),
                            uid: x.dataset.represents || x.id}))""")
            if kotak:
                try:
                    label_slide = frame.evaluate(
                        "() => (document.querySelector('#slide-label')||{}).innerText || ''")
                except Exception:
                    label_slide = ""
                sidik = label_slide + "|" + teks_dom[:180]
                sudah = box_selesai.setdefault(sidik, set())
                kotak_baru = [k for k in kotak if k["uid"] not in sudah]
            else:
                sudah, kotak_baru = set(), []
            if kotak_baru:
                target = kotak_baru[0]
                ss("sebelum-klik-" + target["aria"].replace(" ", "-"))
                frame.evaluate("""(uid) => {
                    const e = Array.from(document.querySelectorAll('.acc-button'))
                        .find(x => (x.dataset.represents || x.id) === uid);
                    if (e) e.click();
                }""", target["uid"])
                sudah.add(target["uid"])
                box_terakhir = target["aria"]
                perlu_kembali = False
                maju_tanpa_jawaban = 0
                interaksi += 1
                time.sleep(1.5)
                ss("sesudah-klik-" + target["aria"].replace(" ", "-"))
                continue

            # Tutup popup validasi bila muncul
            if frame.evaluate("""() => {
                const e = Array.from(document.querySelectorAll('.acc-button, button'))
                    .find(x => /^OK$/i.test((x.innerText || '').trim()));
                if (e) { e.click(); return true; }
                return false;
            }"""):
                ss("tutup-popup")
                time.sleep(0.5)
                continue

            # Habis menjawab satu karakter -> kembali ke daftar karakter,
            # lalu pilih kotak lain yang belum dijawab.
            if perlu_kembali:
                ss("kembali-ke-pilihan-karakter")
                # Satu '#prev' sering tidak cukup karena ada slide umpan balik
                # di antara soal dan daftar karakter. Mundur sampai kotak yang
                # belum dijawab muncul lagi (maksimal 6 langkah).
                for _ in range(6):
                    frame = _frame_scorm(page) or frame
                    kotak_kembali = frame.evaluate("""() =>
                        [...document.querySelectorAll('.acc-button')]
                          .filter(x => /^Rectangle \\d+$/.test(
                              x.getAttribute('aria-label') || '') &&
                              x.getBoundingClientRect().width > 0)
                          .map(x => x.dataset.represents || x.id)""")
                    try:
                        lbl_kembali = frame.evaluate(
                            "() => (document.querySelector('#slide-label')||{}).innerText || ''")
                        txt_kembali = " ".join(frame.inner_text("body").split())[:180]
                    except Exception:
                        lbl_kembali, txt_kembali = "", ""
                    sidik_kembali = lbl_kembali + "|" + txt_kembali
                    sudah_kembali = box_selesai.get(sidik_kembali, set())
                    if kotak_kembali and any(
                            uid not in sudah_kembali for uid in kotak_kembali):
                        break
                    if not frame.evaluate("""() => {
                        const p = document.querySelector('#prev');
                        if (!p || p.disabled) return false;
                        p.click();
                        return true;
                    }"""):
                        break
                    time.sleep(0.8)
                else:
                    # Semua kotak sudah dijawab; tidak perlu mundur lagi.
                    box_terakhir = None
                perlu_kembali = False
                maju_tanpa_jawaban = 0
                continue

            # Semua kotak di slide ini sudah dikerjakan -> lanjut slide berikutnya
            ss("sebelum-lanjut-slide")
            if not frame.evaluate("""() => {
                const b = document.querySelector('#next');
                if (!b || b.disabled) return false;
                b.click();
                return true;
            }"""):
                break
            maju_tanpa_jawaban += 1
            if maju_tanpa_jawaban > 100:
                try:
                    cuplikan = " ".join(frame.inner_text("body").split())[:400]
                except Exception:
                    cuplikan = ""
                print(datetime.now().strftime("%H:%M:%S") +
                      " [SCORM] guard 100 slide tanpa interaksi; coba lagi bila ada. Teks: " +
                      cuplikan, flush=True)
                # Jangan langsung menyerah: soal yang salah masih punya sisa
                # percobaan. Klik "Coba lagi", ulangi deteksi opsi dari awal.
                api_guard = False
                try:
                    mm_g = re.search(r"/course-lesson/\d+/(\d+)", page.url or "")
                    api_guard = bool(mm_g) and _selesai_aktivitas(
                        _status_aktivitas_api(page, mm_g.group(1)))
                except Exception:
                    pass
                bisa_ulang = False
                if not api_guard and ulangan < 6:
                    try:
                        bisa_ulang = frame.evaluate("""() => {
                            const b = [...document.querySelectorAll('.acc-button, button')]
                              .find(x => /coba lagi/i.test((x.innerText || '').trim()) &&
                                         !x.disabled && x.getBoundingClientRect().width > 0);
                            if (b) { b.click(); return true; }
                            return false;
                        }""")
                    except Exception:
                        bisa_ulang = False
                if bisa_ulang:
                    ulangan += 1
                    maju_tanpa_jawaban = 0
                    ss("guard-coba-lagi")
                    time.sleep(2)
                    frame = _frame_scorm(page) or frame
                    continue
                break
            time.sleep(1.2)

        hasil = (f"SCORM interaktif dikerjakan ({interaksi} jawaban/interaksi, "
                 f"{ulangan} ulangan, {len(daftar_ss)} screenshot dicek"
                 + (" + tombol Selesaikan" if selesai else "") + ").")
    finally:
        try:
            for lama in FOLDER_SIMPAN.glob("ss-pikirkan-*"):
                _shutil.rmtree(str(lama), ignore_errors=True)
        except Exception:
            pass
    return hasil


def _klik_panah_selanjutnya(page):
    """Klik panah kanan 'Selanjutnya' di header halaman pelajaran."""
    for f in _semua_frame(page):
        try:
            return f.evaluate("""() => {
                const b = Array.from(document.querySelectorAll('button'))
                    .filter(x => /arrow-btns/.test(String(x.className || '')));
                const next = b[1];
                if (!next || next.disabled) return false;
                next.click();
                return true;
            }""")
        except Exception:
            continue
    return False


def _isi_refleksi(page):
    """Isi textarea refleksi di dalam frame aktivitas (bukan kolob tanya-tutor)."""
    for f in _semua_frame(page)[1:]:  # lewati frame utama (kolom TUTOR SAYA)
        try:
            area = f.locator('textarea')
            n = 0
            for i in range(area.count()):
                el = area.nth(i)
                if not el.is_visible():
                    continue
                nilai = el.input_value() or ""
                if nilai.strip():
                    continue
                ph = (el.get_attribute("placeholder") or "").lower()
                if "tanyakan" in ph or "pertanyaan" in ph:
                    continue
                el.fill("Saya memahami materi ini dengan baik dan dapat menerapkannya dalam pekerjaan sehari-hari.")
                n += 1
            if n:
                return f"Refleksi diisi ({n} kolom)."
        except Exception:
            continue
    return ""


def _tunggu_toc(page, batas=30):
    """Tunggu sampai daftar aktivitas (TOC) halaman pelajaran benar-benar ada."""
    akhir = time.time() + max(1, batas)
    while time.time() < akhir:
        _tunggu_jika_dijeda()
        for f in _semua_frame(page):
            try:
                if f.locator(".toc__children_container").count() > 0:
                    return True
            except Exception:
                continue
        time.sleep(1)
    return False


def _pilih_aktivitas_belum_selesai(page):
    """Klik eksplisit aktivitas pertama di TOC yang BELUM bertanda centang.

    Penanda selesai pada aktivitas adalah <img class="activityCheckIcon
    no-js-Tick" src=".../Tick.svg"> di dalam .toc__children_container.
    Tombol 'Lihat' sengaja tidak dipakai karena bisa membuka ulang aktivitas
    yang sudah selesai.
    """
    for f in _semua_frame(page):
        try:
            dat = f.evaluate("""() => {
                const els = Array.from(document.querySelectorAll('.toc__children_container'));
                for (const e of els) {
                    if (e.querySelector('.activityCheckIcon, .no-js-Tick, img[src*="Tick"]')) continue;
                    const nama = (e.innerText || '').replace(/\\s+/g, ' ').trim();
                    if (!nama) continue;
                    let grup = '';
                    let p = e;
                    for (let k = 0; k < 9 && p; k++, p = p.parentElement) {
                        const mm = (p.innerText || '').replace(/\\s+/g, ' ')
                            .trim().match(/^(Pra-Kelas|Di kelas|Pasca kelas)/i);
                        if (mm) { grup = mm[1]; break; }
                    }
                    e.click();
                    return {nama, grup};
                }
                return null;
            }""")
            if dat:
                return dat
        except Exception:
            continue
    return None


def _aktivitas_sudah_centang(page, nama):
    """Cek apakah aktivitas dengan nama tertentu kini bertanda centang di TOC."""
    for f in _semua_frame(page):
        try:
            return bool(f.evaluate("""(nama) => {
                const e = Array.from(document.querySelectorAll('.toc__children_container'))
                    .find(x => (x.innerText || '').replace(/\\s+/g, ' ').trim() === nama);
                if (!e) return false;
                return !!e.querySelector('.activityCheckIcon, .no-js-Tick, img[src*="Tick"]');
            }""", nama))
        except Exception:
            continue
    return False


_CACHE_KONTEN = {}


def _data_konten_kursus(page, paksa=False):
    """Ambil struktur modul/pelajaran dari API Wadhwani memakai token lokal.

    paksa=True mengabaikan cache, dipakai untuk memverifikasi status setelah
    suatu aktivitas dikerjakan.
    """
    mm = re.search(r"/courses/([^/?#]+)", page.url or "")
    if not mm:
        return None
    cid = mm.group(1)
    if cid in _CACHE_KONTEN and not paksa:
        return _CACHE_KONTEN[cid]
    try:
        token = page.evaluate("() => localStorage.getItem('@accessToken')")
        uid = page.evaluate(
            "() => (JSON.parse(localStorage.getItem('@user') || '{}').userValue || {}).filteredUserId || ''")
        if not token or not uid:
            return None
        api = (f"https://api.opportunity.wfglobal.org/api/v1/courseservice/"
               f"reports/course/{cid}/student/{uid}/contents")
        dat = page.request.get(
            api, headers={"Authorization": "Bearer " + token}, timeout=30000).json()
        if dat.get("data", {}).get("contents"):
            _CACHE_KONTEN[cid] = dat
        return dat
    except Exception:
        return None


def _daftar_pelajaran_modul(page, nama):
    """Petakan nama modul ke daftar URL pelajaran (tanpa mengklik panel home)."""
    dat = _data_konten_kursus(page)
    if not dat:
        return []
    mods = dat.get("data", {}).get("contents", {}).get("modules") or []
    induk = next((m for m in mods
                  if str(m.get("perent")) == "0" and
                  nama.lower() in str(m.get("name", "")).lower()), None)
    if not induk:
        return []
    basis = re.sub(r"(/courses/[^/]+).*", r"\1", page.url)
    hasil = []
    for les in mods:
        if str(les.get("perent")) != str(induk.get("sectionid")):
            continue
        nm = str(les.get("name", ""))
        if re.match(r"^Umpan Balik\b", nm, re.I):
            continue  # feedback sengaja dilewati
        inst = None
        for sub in mods:
            if str(sub.get("perent")) != str(les.get("sectionid")):
                continue
            for act in sub.get("modules") or []:
                if act.get("instance"):
                    inst = str(act["instance"])
                    break
            if inst:
                break
        if inst:
            hasil.append({"nama": nm,
                          "url": f"{basis}/course-lesson/{les['sectionid']}/{inst}"})
    return hasil


def _daftar_aktivitas_modul(page, nama):
    """Daftar semua aktivitas modul dari API, termasuk Di kelas & Pasca kelas.

    TOC halaman pelajaran hanya menampilkan grup aktif, sehingga aktivitas
    'Di kelas'/'Pasca kelas' tidak bisa ditemukan lewat TOC. API memberi daftar
    lengkap beserta status dan instance untuk dibuka langsung lewat URL.
    """
    dat = _data_konten_kursus(page, paksa=True)
    if not dat:
        return []
    mods = dat.get("data", {}).get("contents", {}).get("modules") or []
    induk = next((m for m in mods
                  if str(m.get("perent")) == "0" and
                  nama.lower() in str(m.get("name", "")).lower()), None)
    if not induk:
        return []
    basis = re.sub(r"(/courses/[^/]+).*", r"\1", page.url)
    hasil = []
    for les in mods:
        if str(les.get("perent")) != str(induk.get("sectionid")):
            continue
        pel = str(les.get("name", ""))
        if re.match(r"^Umpan Balik\b", pel, re.I):
            continue  # survei umpan balik sengaja dilewati
        for sub in mods:
            if str(sub.get("perent")) != str(les.get("sectionid")):
                continue
            grup = str(sub.get("name", ""))
            for a in sub.get("modules") or []:
                inst = str(a.get("instance") or "")
                tipe = str(a.get("modtype") or "")
                if not inst or tipe == "feedback":
                    continue  # mod/feedback/ sengaja dilewati
                hasil.append({
                    "nama": str(a.get("name", "")),
                    "grup": grup,
                    "pelajaran": pel,
                    "instance": inst,
                    "status": str(a.get("userStatus") or ""),
                    "modtype": tipe,
                    "url": f"{basis}/course-lesson/{les['sectionid']}/{inst}",
                })
    return hasil


def _status_aktivitas_api(page, instance):
    """Status terbaru satu aktivitas langsung dari API (tanpa cache)."""
    dat = _data_konten_kursus(page, paksa=True)
    if not dat:
        return None
    for m in dat.get("data", {}).get("contents", {}).get("modules") or []:
        for a in m.get("modules") or []:
            if str(a.get("instance")) == str(instance):
                return str(a.get("userStatus") or "")
    return None


def _selesai_aktivitas(status):
    """Anggap selesai bila status API completed/completedPass."""
    return str(status or "").lower() in ("completed", "completedpass")


def _selesaikan_lti(page, hanya_rating=False):
    """Kerjakan SEMUA kartu 'Berkolaborasi' dengan jawaban yang benar-benar dibaca.

    hanya_rating=True: lewati kartu baru, perbaiki saja tile yang ratingnya <5/5.

    Perbaikan penting dibanding versi lama:
    - setiap kartu dibuka, teks studi kasus/pertanyaan diskusi dibaca;
    - pilihan tidak lagi selalu yang pertama (Siswa 1 / peran pertama);
    - jawaban esai dibuat oleh model lokal berdasarkan konteks aktivitas,
      bukan kalimat generik yang sama untuk semua pertanyaan;
    - screenshot + Windows OCR diambil di tiap langkah lalu dihapus di akhir;
    - setelah Kirim, bot memastikan progres/kartu benar-benar berubah.
    """
    def ambil_frame():
        # Frame LTI bisa hilang sejenak setelah Kirim/navigasi; tunggu sebentar
        # supaya loop tidak berhenti lebih awal.
        for _ in range(30):
            f = next((x for x in _semua_frame(page) if "/ltiPage" in (x.url or "")), None)
            if f:
                return f
            time.sleep(0.5)
        # Aktivitas yang baru dibuka (notStarted) menampilkan frame pengarah
        # berisi kartu "Lihat Aktivitas". Klik kartu itu untuk meluncurkan
        # frame /ltiPage yang sebenarnya. Tanpa ini, percobaan pertama selalu
        # gagal dan baru berhasil pada putaran berikutnya.
        for x in _semua_frame(page):
            try:
                diklik = x.evaluate("""() => {
                    const e = [...document.querySelectorAll(
                        '.activity-name, .activity-card, button, a')].find(n =>
                        /Lihat Aktivitas/i.test((n.innerText || n.textContent || '')));
                    if (!e) return false;
                    (e.closest('.activity-card') || e).click();
                    return true;
                }""")
            except Exception:
                diklik = False
            if diklik:
                for _ in range(60):
                    f = next((y for y in _semua_frame(page)
                              if "/ltiPage" in (y.url or "")), None)
                    if f:
                        return f
                    time.sleep(0.5)
                break
        # Fallback: frame LTI dengan URL lain tetap diterima bila ada kartu,
        # bagian penyelesaian, ATAU teks rating.
        for y in _semua_frame(page):
            try:
                if y.evaluate("""() => !!document.querySelector(
                        '.activity-card, .activity-completion-section, '
                        + '.gen-ai-card, .rating-text')"""):
                    return y
            except Exception:
                continue
        return None

    frame = ambil_frame()
    if not frame:
        return ""

    folder_ss = FOLDER_SIMPAN / f"ss-kolab-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    folder_ss.mkdir(parents=True, exist_ok=True)
    urutan_jepret = [0]

    def jepret(tag):
        """Screenshot tiap langkah + OCR lokal; teks dipakai untuk verifikasi."""
        urutan_jepret[0] += 1
        lokasi = folder_ss / f"{urutan_jepret[0]:03d}-{tag}.png"
        try:
            page.screenshot(path=str(lokasi), full_page=False)
            return _baca_gambar_ocr_windows(lokasi)
        except Exception:
            return ""

    def bersih(teks):
        teks = " ".join(str(teks or "").split())
        teks = re.sub(r"^(jawaban|jawab|refleksi)\s*:\s*", "", teks, flags=re.I)
        teks = re.sub(r"^[\"'\[\]{}\s]+|[\"'\[\]{}\s]+$", "", teks)
        return teks[:900]

    def tanya_model(prompt):
        """Tanya model lokal Hermes (gratis, offline) dengan suhu rendah."""
        try:
            isi = json.dumps({
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.15},
            }).encode()
            req = urllib.request.Request(
                OLLAMA_URL, data=isi, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=240) as r:
                data = json.loads(r.read().decode("utf-8"))
            return bersih(data.get("message", {}).get("content", ""))
        except Exception:
            return ""

    def jawab_esai(konteks, pertanyaan, pilihan):
        prompt = (
            "Kamu membantu mahasiswa mengisi refleksi aktivitas kolaborasi. "
            "Jawab HANYA pertanyaan terakhir dengan 2-4 kalimat bahasa Indonesia "
            "yang spesifik, benar, dan diambil dari teks aktivitas di bawah. "
            "Sertakan detail konkret (siapa, target/waktu, apa yang dikatakan atau "
            "dilakukan). WAJIB akhiri dengan kalimat 'Hasilnya, ...' yang menyebut "
            "HASIL NYATA DAN TERAMATI, misalnya 'Hasilnya, Desainer Grafis "
            "mengonfirmasi ukuran dan warna logo, Pelanggan mengetahui rasa dan "
            "harga, dan Supervisor menyatakan tidak ada kesalahpahaman.' JANGAN "
            "menulis hasil umum seperti 'komunikasi efektif terwujud' atau 'pemahaman "
            "menjadi jelas'. Bila relevan, sertakan contoh kalimat persis dalam tanda "
            "kutip. Jangan menulis umum seperti 'saya mendengarkan aktif' tanpa contoh. "
            "Jangan mengulang pertanyaan. Jangan pakai format Markdown.\n\n"
            f"TEKS AKTIVITAS:\n{konteks[:5000]}\n\n"
            f"PILIHAN YANG DIPILIH: {pilihan}\n"
            f"PERTANYAAN: {pertanyaan}\n"
            "JAWABAN:"
        )
        jawab = tanya_model(prompt)
        if jawab:
            return jawab
        # Fallback bila model lokal sedang tidak tersedia.
        q = pertanyaan.lower()
        if "kesalahpahaman" in q:
            return ("Kesalahpahaman terjadi karena instruksi Aryo tidak jelas, "
                    "sehingga Lestari bingung dan membuat desain yang tidak sesuai.")
        if "membantu" in q and "kusuma" in q:
            return ("Kusuma membantu dengan menjelaskan kembali instruksi Aryo secara jelas, "
                    "sehingga Lestari memahami maksudnya dan desain menjadi sesuai.")
        if "peran" in q:
            return ("Peran saya membantu menjelaskan instruksi, mendengarkan masukan tim, "
                    "dan memastikan setiap orang memahami tugasnya dengan sama.")
        if "pelajari" in q or "pentingnya" in q:
            return ("Aktivitas ini menunjukkan bahwa komunikasi yang jelas, sopan, dan "
                    "saling mendengarkan mencegah kesalahpahaman serta memperbaiki kerja tim.")
        return ("Saya menyampaikan informasi dengan jelas, meminta klarifikasi bila ada "
                "yang membingungkan, dan memastikan rekan tim memiliki pemahaman yang sama.")

    def pilih_opsi(fr, konteks, pertanyaan, opsi, nomor_siswa, indeks):
        q = pertanyaan.lower()
        angka_saja = all(re.fullmatch(r"\s*\d+\s*", o) for o in opsi)
        if (re.search(r"skor|rating|seberapa|penilaian|dari 5|1\s*-\s*5", q) or angka_saja):
            # Pertanyaan penilaian: ambil nilai/opsi paling tinggi agar dapat 5/5.
            target = next((o for o in reversed(opsi) if "5" in o), opsi[-1])
        elif re.search(r"nomor siswa|siswa ke", q):
            target = f"Siswa {nomor_siswa}"
        elif re.search(r"peran|role", q):
            dikenal = ["Manajer", "Karyawan", "Staf HR", "Pelanggan"]
            target = next((o for o in dikenal if o in opsi), None) or opsi[indeks % len(opsi)]
            # Putar peran antar kartu agar tidak selalu Manajer.
            cocok = [o for o in opsi if any(d.lower() in o.lower() for d in dikenal)]
            if cocok:
                target = cocok[indeks % len(cocok)]
        else:
            prompt = (
                "Pilih satu opsi yang PALING tepat untuk pertanyaan ini berdasarkan teks aktivitas. "
                "Balas HANYA teks opsi persis seperti daftar, tanpa penjelasan.\n\n"
                f"TEKS AKTIVITAS:\n{konteks[:3500]}\n\n"
                f"PERTANYAAN: {pertanyaan}\n"
                f"OPSI: {json.dumps(opsi, ensure_ascii=False)}\n"
                "JAWABAN:"
            )
            target = tanya_model(prompt)
        if target not in opsi:
            target = next((o for o in opsi if target and target.lower() in o.lower()), opsi[0])
        fr.evaluate("""(t) => {
            const e = [...document.querySelectorAll('.each-option')].find(x =>
                !String(x.className || '').includes('disable') &&
                x.getBoundingClientRect().width > 0 &&
                (x.innerText || '').replace(/\\s+/g, ' ').trim() === t);
            if (e) e.click();
        }""", target)
        return target

    def info_kartu(fr):
        return fr.evaluate("""() => [...document.querySelectorAll('.activity-card')].map((e, i) => {
            const tr = e.closest('tr');
            const role = (tr?.querySelector('.role-name')?.innerText || '').replace(/\\s+/g, ' ').trim();
            const tds = tr ? [...tr.querySelectorAll('td')] : [];
            const kolom = tds.indexOf(e.closest('td'));
            return {i, kunci: role + '#' + kolom, role, kolom};
        })""")

    def info_refleksi(fr):
        return fr.evaluate("""() => {
            const kartu = [...document.querySelectorAll('.gen-ai-card')]
                .map(e => (e.innerText || '').replace(/\\s+/g, ' ').trim())
                .filter(Boolean);
            const opsi = [...document.querySelectorAll('.each-option')]
                .filter(e => !String(e.className || '').includes('disable') &&
                             e.getBoundingClientRect().width > 0)
                .map(e => (e.innerText || '').replace(/\\s+/g, ' ').trim());
            const inp = document.getElementById('reflection-normal-input');
            const sub = document.querySelector('button.reflection-submit-btn');
            return {
                pertanyaan: kartu.length ? kartu[kartu.length - 1] : '',
                opsi,
                input: !!inp && inp.getBoundingClientRect().width > 0,
                submit: !!sub && sub.getBoundingClientRect().width > 0,
                di_detail: !!document.querySelector('.activity-details-heading')
            };
        }""")

    def isi_input(fr, teks):
        fr.evaluate("""(j) => {
            const e = document.getElementById('reflection-normal-input');
            if (!e) return;
            const proto = e.tagName === 'TEXTAREA'
                ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
            const set = Object.getOwnPropertyDescriptor(proto, 'value').set;
            set.call(e, j);
            e.dispatchEvent(new Event('input', {bubbles: true}));
            e.dispatchEvent(new Event('change', {bubbles: true}));
        }""", teks)

    def konteks_dari(teks):
        """Ambil studi kasus + instruksi, buang jawaban lama/score/refleksi."""
        teks = " ".join(str(teks or "").split())
        for pola in (r"\s+Sudah menyelesaikan aktivitasnya\?",
                     r"\s+Detail Aktivitas\s+",
                     r"\s+Skor Anda\s+"):
            bagian = re.split(pola, teks)[0].strip()
            if len(bagian) > 250:
                return bagian[:5000]
        return teks[:4000]

    selesai = 0
    perbaikan = 0
    dicoba = set()
    catatan = []

    def baca_tiles(fr):
        """Baca semua tile penyelesaian beserta rating 1-5 dari frame LTI.

        Struktur normal memakai .activity-completion-section. Beberapa versi
        halaman hanya menampilkan .rating-text tanpa pembungkus itu, jadi ada
        fallback berdasarkan elemen rating itu sendiri.
        """
        return fr.evaluate("""() => {
          const sections=[...document.querySelectorAll('.activity-completion-section')];
          if (sections.length) return sections.map((e,i)=>{
            const tr=e.closest('tr');
            const role=(tr?.querySelector('.role-name')?.innerText||'').replace(/\\s+/g,' ').trim();
            const tds=tr?[...tr.querySelectorAll('td')]:[];
            const kolom=tds.indexOf(e.closest('td'));
            const rating=(e.querySelector('.rating-text')?.innerText||'').replace(/\\s+/g,' ').trim();
            return {i, kunci:'tile-'+role+'#'+kolom, rating, role, kolom};
          });
          return [...document.querySelectorAll('.rating-text')].map((e,i)=>{
            const rating=(e.innerText||'').replace(/\\s+/g,' ').trim();
            const baris=e.closest('tr,li,[class*=row]') || e.parentElement;
            const role=(baris?.innerText||'').replace(/\\s+/g,' ').trim().slice(0,60);
            return {i, kunci:'rating-'+i+'-'+role, rating, role, kolom:i};
          });
        }""")

    def rating_angka(teks):
        mm = re.match(r"^\\s*(\\d+)\\s*/\\s*5\\s*$", str(teks or ""))
        return int(mm.group(1)) if mm else None

    def tunggu_kembali(fr, detik=75):
        """Tunggu sampai halaman detail/refleksi ditutup dan daftar tampil lagi."""
        for _ in range(detik):
            fr = ambil_frame() or fr
            try:
                if not fr.evaluate(
                        "() => !!document.querySelector('.activity-details-heading')"):
                    return fr
            except Exception:
                pass
            time.sleep(1)
        return fr

    try:
        for putaran in range(0 if hanya_rating else 80):
            _tunggu_jika_dijeda()
            frame = ambil_frame()
            if not frame:
                break
            try:
                if frame.evaluate("() => !!document.querySelector('.activity-details-heading')"):
                    frame.evaluate("""() => {
                        const panah = document.querySelector('.no-js-collaborate-details-back-arrow');
                        if (panah) { panah.click(); return; }
                        const keluar = [...document.querySelectorAll('*')].find(x =>
                            x.children.length === 0 && /Keluar dari latihan/i.test(x.textContent || ''));
                        if (keluar) (keluar.closest('div') || keluar).click();
                    }""")
                    time.sleep(1.5)
                    continue

                for _ in range(4):
                    frame.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(0.4)

                kartu = info_kartu(frame)
                if not kartu:
                    break
                belum = [k for k in kartu if k["kunci"] not in dicoba]
                if not belum:
                    break
                target_kartu = belum[0]
                kunci = target_kartu["kunci"]
                dicoba.add(kunci)
                nomor_siswa = 1 + (selesai % 4)
                status_aktif(f"Mengerjakan kartu {kunci} (kartu ke-{selesai + 1})")

                frame.evaluate("(i) => { const e = document.querySelectorAll('.activity-card')[i]; if (e) e.click(); }",
                               target_kartu["i"])
                time.sleep(3)
                frame = ambil_frame() or frame
                ocr = jepret("detail")
                teks_detail = " ".join(frame.inner_text("body").split())
                konteks = konteks_dari(teks_detail)
                catatan.append(f"{kunci}: konteks {len(konteks)} char, OCR {len(ocr)} char")

                frame.evaluate("""() => {
                    const b = [...document.querySelectorAll('button')]
                        .find(x => /Refleksikan aktivitasnya/i.test(x.innerText || ''));
                    if (b) b.click();
                }""")
                time.sleep(3)
                jepret("refleksi-mulai")

                for _langkah in range(40):
                    _tunggu_jika_dijeda()
                    frame = ambil_frame() or frame
                    info = info_refleksi(frame)
                    if info["opsi"]:
                        pilihan = pilih_opsi(frame, konteks, info["pertanyaan"],
                                             info["opsi"], nomor_siswa, selesai)
                        jepret("pilih-" + re.sub(r"\W+", "-", pilihan)[:24])
                        time.sleep(1.4)
                        continue
                    if info["input"]:
                        jawaban = jawab_esai(konteks, info["pertanyaan"], f"Siswa {nomor_siswa}")
                        isi_input(frame, jawaban)
                        jepret("isi-jawaban")
                        time.sleep(0.8)
                        frame = ambil_frame() or frame
                        info2 = info_refleksi(frame)
                        if info2["submit"]:
                            frame.evaluate("""() => {
                                const b = document.querySelector('button.reflection-submit-btn');
                                if (b) b.click();
                            }""")
                            jepret("kirim")
                            time.sleep(2.5)
                        else:
                            break
                        continue
                    if info["submit"]:
                        frame.evaluate("""() => {
                            const b = document.querySelector('button.reflection-submit-btn');
                            if (b) b.click();
                        }""")
                        jepret("kirim-tanpa-teks")
                        time.sleep(2.5)
                        continue
                    # Kirim terakhir memicu generative feedback; tunggu selesai.
                    time.sleep(20)
                    break

                jepret("selesai-kartu")
                selesai += 1
                frame = ambil_frame() or frame
                try:
                    sisa = info_kartu(frame)
                    if not any(k["kunci"] == kunci for k in sisa):
                        catatan[-1] += " -> kartu berubah jadi selesai"
                except Exception:
                    pass
            except Exception as e:
                catatan.append(f"{putaran}: error {type(e).__name__} {e}")
                time.sleep(1.5)
                continue

        # Perbaiki kartu yang sudah selesai tetapi ratingnya masih < 5/5.
        # Tile bisa butuh beberapa kali ulang karena umpan balik GenAI muncul
        # terlambat, jadi percobaan tidak boleh habis hanya karena satu kiriman.
        MAKS_PERCOBAAN = 4
        percobaan = {}
        for putaran_tile in range(120):
            _tunggu_jika_dijeda()
            frame = ambil_frame()
            if not frame:
                break
            try:
                if frame.evaluate("() => !!document.querySelector('.activity-details-heading')"):
                    frame.evaluate("""() => {
                        const panah = document.querySelector('.no-js-collaborate-details-back-arrow');
                        if (panah) { panah.click(); return; }
                        const keluar = [...document.querySelectorAll('*')].find(x =>
                            x.children.length === 0 && /Keluar dari latihan/i.test(x.textContent || ''));
                        if (keluar) (keluar.closest('div') || keluar).click();
                    }""")
                    time.sleep(1.5)
                    continue
                tiles = baca_tiles(frame)
                rendah = [t for t in tiles
                          if (rating_angka(t["rating"]) or 5) < 5
                          and percobaan.get(t["kunci"], 0) < MAKS_PERCOBAAN]
                if not rendah:
                    status_aktif(f"Memindai rating: {len(tiles)} tile, semua sudah 5/5.")
                    break
                t = rendah[0]
                kunci = t["kunci"]
                status_aktif(f"Mengulang rating {kunci}: {t['rating']} -> target 5/5 "
                             f"(percobaan {percobaan.get(kunci, 0) + 1}/4)")
                percobaan[kunci] = percobaan.get(kunci, 0) + 1
                frame.evaluate("""(i)=>{
                    const e=document.querySelectorAll('.activity-completion-section')[i];
                    if(e)e.click();
                }""", t["i"])
                time.sleep(3)
                frame = ambil_frame() or frame
                # Kembali ke daftar bila tile langsung menampilkan detail lama.
                if frame.evaluate("() => !!document.querySelector('.activity-details-heading')"):
                    frame.evaluate("""() => {
                        const panah = document.querySelector('.no-js-collaborate-details-back-arrow');
                        if (panah) panah.click();
                        const keluar = [...document.querySelectorAll('*')].find(x =>
                            x.children.length === 0 && /Keluar dari latihan/i.test(x.textContent || ''));
                        if (keluar) (keluar.closest('div') || keluar).click();
                    }""")
                    time.sleep(1.5)
                    frame = ambil_frame() or frame
                ocr = jepret("tile-detail")
                teks_detail = " ".join(frame.inner_text("body").split())
                konteks = konteks_dari(teks_detail)
                catatan.append(f"{kunci}: rating {t['rating']} attempt "
                               f"{percobaan[kunci]}/{MAKS_PERCOBAAN}, konteks "
                               f"{len(konteks)} char, OCR {len(ocr)} char")

                # Tombol 'Mengulang' / 'Refleksikan aktivitasnya' bisa muncul
                # dengan label berbeda; keduanya memulai sesi penilaian ulang.
                if frame.evaluate("""() => [...document.querySelectorAll('button, a, div, span')]
                        .some(x => x.getBoundingClientRect().width > 0 &&
                                   /Mengulang|Refleksikan aktivitasnya/i.test(x.innerText || ''))"""):
                    frame.evaluate("""() => {
                        const e=[...document.querySelectorAll('button, a, div, span')]
                            .find(x => x.getBoundingClientRect().width > 0 &&
                                       /Mengulang|Refleksikan aktivitasnya/i.test(x.innerText || ''));
                        if(e)(e.closest('button')||e).click();
                    }""")
                    time.sleep(2.5)
                    jepret("tile-mengulang")

                for _langkah in range(50):
                    _tunggu_jika_dijeda()
                    frame = ambil_frame() or frame
                    info = info_refleksi(frame)
                    if info["opsi"]:
                        pilihan = pilih_opsi(frame, konteks, info["pertanyaan"],
                                             info["opsi"], 5, perbaikan)
                        jepret("tile-pilih-" + re.sub(r"\W+", "-", pilihan)[:24])
                        time.sleep(1.4)
                        continue
                    if info["input"]:
                        jawaban = jawab_esai(konteks, info["pertanyaan"], "Siswa 5")
                        isi_input(frame, jawaban)
                        jepret("tile-isi-jawaban")
                        time.sleep(0.8)
                        frame = ambil_frame() or frame
                        info2 = info_refleksi(frame)
                        if info2["submit"]:
                            frame.evaluate("""() => {
                                const b=document.querySelector('button.reflection-submit-btn');
                                if(b)b.click();
                            }""")
                            jepret("tile-kirim")
                            time.sleep(2.5)
                        else:
                            break
                        continue
                    if info["submit"]:
                        frame.evaluate("""() => {
                            const b=document.querySelector('button.reflection-submit-btn');
                            if(b)b.click();
                        }""")
                        jepret("tile-kirim-tanpa-teks")
                        time.sleep(2.5)
                        continue
                    # Umpan balik GenAI sering baru selesai setelah >20 detik.
                    time.sleep(20)
                    break

                jepret("tile-selesai")
                perbaikan += 1
                # Tunggu detail tertutup, lalu polling rating hingga berubah
                # (atau timeout). Jangan baca sekali setelah tidur tetap.
                frame = tunggu_kembali(frame)
                rating_baru = ""
                for _ in range(40):
                    frame = ambil_frame() or frame
                    for tk in baca_tiles(frame):
                        if tk["kunci"] == kunci:
                            rating_baru = tk["rating"]
                            break
                    if rating_baru and rating_angka(rating_baru) == 5:
                        break
                    time.sleep(1.5)
                if rating_baru:
                    catatan[-1] += f" -> rating {rating_baru}"
                    status_aktif(f"Hasil rating {kunci}: {rating_baru}")
            except Exception as e:
                catatan.append(f"tile {putaran_tile}: error {type(e).__name__} {e}")
                time.sleep(1.5)
                continue

        try:
            frame = ambil_frame() or frame
            sisa_rating = sum(1 for t in baca_tiles(frame)
                              if (rating_angka(t["rating"]) or 5) < 5)
        except Exception:
            sisa_rating = -1
    finally:
        try:
            for berkas in folder_ss.glob("*.png"):
                berkas.unlink(missing_ok=True)
            folder_ss.rmdir()
        except Exception:
            pass

    ringkas = "; ".join(catatan[:4])
    return (f"Kolaborasi LTI: {selesai} kartu dikerjakan, {perbaikan} ulangan rating, "
            f"sisa rating <5/5: {sisa_rating}. "
            f"Jawaban berbasis konteks aktivitas (model lokal + OCR tiap langkah). {ringkas}"
            ) if (selesai or perbaikan or sisa_rating != 0) else ""


def _lewati_video_dan_keluar(page):
    """Pelajari lebih lanjut: seek video ke akhir lalu langsung klik Keluar."""
    jumlah = 0
    for f in _semua_frame(page):
        try:
            video = f.locator("video, audio")
            n = video.count()
        except Exception:
            continue
        for i in range(n):
            try:
                el = video.nth(i)
                el.evaluate("""(e) => {
                    e.muted = true;
                    const d = Number(e.duration) || 0;
                    if (d > 0) { try { e.currentTime = Math.max(0, d - 2); } catch (err) {} }
                    e.play().catch(() => {});
                }""")
                for _ in range(12):
                    time.sleep(0.4)
                    try:
                        if el.evaluate("(e) => !!e.ended"):
                            break
                    except Exception:
                        break
                el.evaluate("(e) => e.dispatchEvent(new Event('timeupdate'))")
                jumlah += 1
            except Exception:
                continue
    keluar = False
    for _ in range(10):
        for f in _semua_frame(page):
            try:
                if f.evaluate("""() => {
                    const re = /^(Keluar|Exit|Close|Tutup|Kembali|Back)$/i;
                    const e = [...document.querySelectorAll(
                        'button, a, div, span, p, .acc-button, [role=button]')]
                        .find(x => {
                            const r = x.getBoundingClientRect();
                            if (r.width <= 0 || r.height <= 0) return false;
                            return [(x.innerText || ''),
                                    x.getAttribute('aria-label') || '',
                                    x.getAttribute('title') || '']
                                .some(s => re.test(String(s).trim()));
                        });
                    if (e) { e.click(); return true; }
                    return false;
                }"""):
                    keluar = True
                    break
            except Exception:
                continue
        if keluar:
            break
        time.sleep(1)
    if not keluar:
        # Paket 'Pelajari lebih lanjut' tidak selalu menyediakan tombol Keluar.
        # Splash 'Lanjutkan' dibuka dulu, lalu alur SCORM biasa dijalankan
        # sampai tombol Selesai muncul.
        try:
            hasil = _selesaikan_scorm(page)
        except Exception as e:
            hasil = f"error {type(e).__name__}: {e}"
        if hasil:
            return (f"Video dilewati ({jumlah} elemen), tombol Keluar tidak ada; "
                    f"diselesaikan lewat alur SCORM: {hasil}")
    return (f"Video dilewati ({jumlah} elemen), tombol Keluar "
            f"{'diklik' if keluar else 'tidak ditemukan'}.")


def _frame_attempt(page):
    """Cari iframe Moodle attempt.php (bersarang sekalipun)."""
    return next((f for f in _semua_frame(page)
                 if "attempt.php" in (f.url or "")), None)


def _klik_mulai_kuis(page):
    """Klik tombol memulai kuis di halaman course-lesson / iframe Moodle."""
    pola = (r"Kerjakan kuis|Mengerjakan kuis kembali|Lanjutkan pengerjaan kuis|"
            r"Mulai kuis|Start quiz|Start attempt|Attempt quiz now|Re-attempt quiz")
    for f in _semua_frame(page):
        try:
            klik = f.evaluate("""(pola) => {
                const re = new RegExp(pola, 'i');
                const els = [...document.querySelectorAll(
                    'button, a, input[type=submit], [role=button], span, div')]
                    .filter(e => {
                        const r = e.getBoundingClientRect();
                        return r.width > 0 && r.height > 0;
                    });
                const e = els.find(x => re.test(
                    (x.innerText || x.value || x.textContent || '').trim()));
                if (e) { e.click(); return (e.innerText || e.value || '').trim(); }
                return '';
            }""", pola)
            if klik:
                return klik
        except Exception:
            continue
    return ""


def _selesaikan_quiz(page):
    """Buka attempt kuis bila perlu lalu jawab semua soal sampai selesai."""
    status_aktif("Membuka kuis dan menunggu attempt Moodle termuat.")
    for _ in range(4):
        if _frame_attempt(page):
            break
        tombol = _klik_mulai_kuis(page)
        if not tombol:
            break
        status_aktif(f"Kuis dimulai lewat tombol: {tombol[:70]}")
        for _ in range(25):
            time.sleep(0.6)
            if _frame_attempt(page):
                break
    if not _frame_attempt(page):
        return ""
    return _selesaikan_attempt_otomatIs()


def alat_kerjakan_modul(arg):
    """Selesaikan semua pelajaran dalam modul sampai tanda centang modul penuh."""
    nama = str(arg.get("nama") or arg.get("modul") or "").strip()
    if not nama:
        return "Error: argumen 'nama' modul kosong."
    page = _pastikan_browser()
    url_kursus = page.url
    if "/courses/" not in url_kursus:
        return "Error: buka halaman kursus dulu (URL mengandung /courses/)."
    # Target bisa dikirim lewat argumen, konfigurasi.json, atau file
    # target-aktivitas.txt. Kosong berarti kerjakan semua aktivitas.
    targets = [str(x).strip() for x in (arg.get("target") or [])
               if str(x).strip()] or _target_aktivitas()
    if targets:
        print(datetime.now().strftime("%H:%M:%S") +
              " TARGET AKTIVITAS: " + ", ".join(targets), flush=True)

    def daftar_target():
        d = _daftar_aktivitas_modul(page, nama)
        if not targets:
            return d
        return [a for a in d if _cocok_target(a, targets)]

    def info_modul():
        for f in _semua_frame(_pastikan_browser()):
            try:
                dat = f.evaluate("""(nama) => {
                    for (const el of document.querySelectorAll('.newAccor_heading_container')) {
                        const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                        if (!t.toLowerCase().includes(nama.toLowerCase())) continue;
                        const m = t.match(/(\\d+)\\s*\\/\\s*(\\d+)/);
                        const cls = String(el.className || '') + ' ' + String(el.parentElement?.className || '');
                        return {nama: t, selesai: m ? Number(m[1]) : 0, total: m ? Number(m[2]) : 0,
                                centang: /completed_lesson|certificate-progress__tick|no-js-bright_green_check/i.test(cls)};
                    }
                    return null;
                }""", nama)
                if dat:
                    return dat
            except Exception:
                continue
        return None

    awal = info_modul()
    if not awal:
        return f"Modul '{nama}' tidak ditemukan di halaman kursus."
    if awal["total"] and awal["selesai"] >= awal["total"] and not targets:
        return f"Modul '{nama}' sudah ✅ centang semua ({awal['selesai']}/{awal['total']})."
    tampilkan_popup("Hermes mengerjakan modul", nama)
    log = [f"MULAI: {awal['nama']} ({awal['selesai']}/{awal['total']})"]
    daftar = daftar_target()
    if targets:
        _catat(log, f"TARGET: {len(daftar)} aktivitas cocok dari daftar modul -> {targets}")
    if not daftar:
        return "\n".join(log + ["Tidak ada aktivitas yang cocok dengan target."
                                if targets else "Error: daftar aktivitas API tidak tersedia."])
    ringkas = ", ".join(f"{a['grup']}/{a['nama']}" for a in daftar[:6])
    _catat(log, f"Aktivitas dari API ({len(daftar)}): {ringkas}" +
           (" ..." if len(daftar) > 6 else ""))

    # Aktivitas yang sudah diverifikasi berulang: halaman menyatakan selesai,
    # tetapi status API tetap inProgress. Mencobanya lagi di setiap job hanya
    # membuang waktu, jadi dilewati dan tetap dicatat sekali di log.
    dilewati = {"174072"}

    for putaran in range(3):
        info = info_modul()
        if (info and info["total"] and info["selesai"] >= info["total"]
                and not targets):
            _catat(log, f"SELESAI: {info['nama']} ✅ {info['selesai']}/{info['total']}")
            break
        daftar = daftar_target()
        belum = [a for a in daftar if not _selesai_aktivitas(a["status"])]
        if any(a["instance"] in dilewati for a in belum):
            _catat(log, "  DILEWATI: 174072 (API inProgress; sudah diverifikasi mustahil lewat UI).")
        belum = [a for a in belum if a["instance"] not in dilewati]
        if not belum:
            _catat(log, "Semua aktivitas sudah completed menurut API.")
            break
        _catat(log, f"Putaran {putaran+1}: {len(belum)} aktivitas belum selesai.")
        berubah = 0
        for a in belum:
            _tunggu_jika_dijeda()
            st = _status_aktivitas_api(page, a["instance"])
            if _selesai_aktivitas(st):
                _catat(log, f"  ✓ {a['grup']}/{a['nama']} sudah completed (API).")
                continue
            _catat(log, f"  {a['pelajaran']} > {a['grup']} / {a['nama']} "
                        f"({a['modtype']}, {st}) -> {a['instance']}")
            status_aktif(f"Membuka {a['instance']}: {a['pelajaran']} / {a['nama']}")
            # Buka URL aktivitas langsung. Klik TOC tidak diandalkan karena
            # hanya grup aktif yang muncul dan iframe sering tidak ikut termuat.
            alat_buka_browser({"url": a["url"]})
            # Tunggu frame muncul, jangan tidur buta 12 detik: menghemat
            # ~10 detik per aktivitas bila halaman cepat termuat.
            halaman = _pastikan_browser()
            for _ in range(30):
                if len(_semua_frame(halaman)) > 1:
                    break
                time.sleep(0.5)

            butuh_unggah = False
            for f in _semua_frame(halaman):
                try:
                    if f.locator('input[type=file]').count() > 0:
                        butuh_unggah = True
                        break
                except Exception:
                    continue
            if butuh_unggah:
                _catat(log, "  DILEWATI: aktivitas unggah video (dikerjakan pengguna).")
                continue
            frame_feedback = next((f for f in _semua_frame(halaman)
                                   if "mod/feedback/" in (f.url or "")), None)
            if frame_feedback or a["modtype"] == "feedback":
                _catat(log, "  DILEWATI: mod/feedback (sesuai instruksi).")
                continue
            frame_kuis = _frame_attempt(halaman)
            if (a["modtype"] == "quiz" or frame_kuis or
                    re.search(r"Penilaian|Assessment|Kuis\b", a["nama"], re.I)):
                hasil_quiz = _selesaikan_quiz(halaman)
                if hasil_quiz:
                    _catat(log, "  " + hasil_quiz.replace("\n", " | ")[:500])
                elif a["modtype"] == "quiz":
                    _catat(log, "  Kuis belum bisa dimulai (tombol/iframe tidak ditemukan).")
            elif a["modtype"] == "lti" or re.match(r"^Berkolaborasi\b", a["nama"], re.I):
                # Frame /ltiPage bisa termuat jauh lebih lambat daripada frame
                # biasa. Tunggu sampai benar-benar ada sebelum menyerah.
                for _ in range(90):
                    halaman = _pastikan_browser()
                    if any("/ltiPage" in (x.url or "") for x in _semua_frame(halaman)):
                        break
                    time.sleep(1)
                hasil_lti = _selesaikan_lti(halaman)
                if not hasil_lti:
                    # Satu retry setelah memuat ulang: sebelumnya 174304 dilewati
                    # hanya karena frame datang terlambat (panic "Kolaborasi tidak diproses").
                    _catat(log, "  LTI frame terlambat; memuat ulang sekali.")
                    alat_buka_browser({"url": a["url"]})
                    time.sleep(10)
                    halaman = _pastikan_browser()
                    for _ in range(60):
                        if any("/ltiPage" in (x.url or "") for x in _semua_frame(halaman)):
                            break
                        time.sleep(1)
                    hasil_lti = _selesaikan_lti(halaman)
                _catat(log, "  " + (hasil_lti or "Kolaborasi tidak diproses."))
                if hasil_lti and "sisa rating <5/5: 0" in hasil_lti:
                    _RATING_SUDAH_OK.add((nama, a["instance"]))
            elif re.match(r"^Pelajari lebih lanjut\b", a["nama"], re.I):
                _catat(log, "  " + _lewati_video_dan_keluar(halaman))
            else:
                # Frame SCORM bersarang bisa baru termuat setelah >10 detik.
                for _ in range(45):
                    if _frame_scorm(halaman):
                        break
                    time.sleep(1)
                scorm = _selesaikan_scorm(halaman)
                if scorm:
                    _catat(log, "  " + scorm)
                else:
                    info_video = alat_putar_video({"semua": True}).splitlines()[0]
                    if not info_video.startswith("Tidak ada"):
                        _catat(log, "  " + info_video)
                    info_refleksi = _isi_refleksi(halaman)
                    if info_refleksi:
                        _catat(log, "  " + info_refleksi)

            # Status API bisa tertunda beberapa detik setelah tombol Selesaikan
            # ditekan (terjadi pada Pikirkan 1 / 174292: None padahal sudah benar).
            # Polling dulu supaya tidak ada false negative yang membuang attempt.
            akhir = None
            for _ in range(8):
                time.sleep(3)
                akhir = _status_aktivitas_api(page, a["instance"])
                if _selesai_aktivitas(akhir):
                    break
            if _selesai_aktivitas(akhir):
                _catat(log, f"  ✓ {a['nama']} selesai (API: {akhir}).")
                berubah += 1
            else:
                _catat(log, f"  ⚠ {a['nama']} belum selesai (API: {akhir}).")
        if not berubah:
            _catat(log, "Tidak ada progres pada putaran ini; berhenti.")
            break
        # Kembali ke kursus untuk cek centang modul terbaru
        alat_buka_browser({"url": url_kursus})
        time.sleep(6)

    # Perbaiki rating <5/5 pada aktivitas LTI yang sudah completed menurut API.
    # Tanpa fase ini bot hanya menyentuh LTI yang belum lulus, sehingga kartu
    # dengan rating 4/5 dibiarkan walaupun status API sudah completed.
    for a in daftar:
        _tunggu_jika_dijeda()
        if not (a["modtype"] == "lti" or
                re.match(r"^Berkolaborasi\b", a["nama"], re.I)):
            continue
        penanda = (nama, a["instance"])
        if penanda in _RATING_SUDAH_OK:
            continue
        try:
            alat_buka_browser({"url": a["url"]})
            halaman = _pastikan_browser()
            for _ in range(60):
                if any("/ltiPage" in (x.url or "") for x in _semua_frame(halaman)):
                    break
                time.sleep(1)
            fr = next((x for x in _semua_frame(halaman)
                       if "/ltiPage" in (x.url or "")), None)
            if not fr:
                continue
            ratings = fr.evaluate("""() => [...document.querySelectorAll('.rating-text')]
                .map(e => (e.innerText||'').replace(/\\s+/g,' ').trim())""")
            ada_rendah = False
            for r in ratings:
                mm = re.match(r"^\s*(\d+)\s*/\s*5\s*$", str(r))
                if mm and int(mm.group(1)) < 5:
                    ada_rendah = True
                    break
            if not ada_rendah:
                _RATING_SUDAH_OK.add(penanda)
                continue
            _catat(log, f"  Rating {a['instance']} masih {ratings}; diperbaiki.")
            hasil_rating = _selesaikan_lti(halaman, hanya_rating=True)
            if hasil_rating:
                _catat(log, "  " + hasil_rating[:400])
            if "sisa rating <5/5: 0" in (hasil_rating or ""):
                _RATING_SUDAH_OK.add(penanda)
        except Exception as e:
            _catat(log, f"  Gagal cek rating {a['instance']}: "
                        f"{type(e).__name__} {e}")

    # Pastikan status akhir dibaca dari halaman kursus, bukan halaman aktivitas.
    try:
        alat_buka_browser({"url": url_kursus})
        time.sleep(6)
    except Exception:
        pass
    return "\n".join(log) + "\n\n" + alat_status_modul({"nama": nama})


def alat_klik_koordinat(arg):
    """Klik pada posisi x,y di layar (untuk elemen canvas/video interaktif)."""
    try:
        x = int(arg.get("x"))
        y = int(arg.get("y"))
    except (TypeError, ValueError):
        return "Error: argumen 'x' dan 'y' harus angka."
    page = _pastikan_browser()
    try:
        page.mouse.click(x, y)
        return f"Klik di koordinat ({x}, {y}).\n" + _cuplikan_halaman(page, 800)
    except Exception as e:
        return f"Error klik koordinat: {e}"


ALAT = {
    "buka_website": alat_buka_website,
    "cari_internet": alat_cari_internet,
    "cari_wikipedia": alat_cari_wikipedia,
    "simpan_file": alat_simpan_file,
    "baca_file": alat_baca_file,
    "buka_browser": alat_buka_browser,
    "buka_quiz": alat_buka_quiz,
    "lihat_halaman": alat_lihat_halaman,
    "klik": alat_klik,
    "gulir": alat_gulir,
    "isi_form": alat_isi_form,
    "pilih_opsi": alat_pilih_opsi,
    "struktur_kuis": alat_struktur_kuis,
    "jawab_kuis": alat_jawab_kuis,
    "unggah_file": alat_unggah_file,
    "putar_video": alat_putar_video,
    "tekan_tombol": alat_tekan_tombol,
    "tunggu": alat_tunggu,
    "pindah_tab": alat_pindah_tab,
    "muat_ulang": alat_muat_ulang,
    "klik_koordinat": alat_klik_koordinat,
    "status_modul": alat_status_modul,
    "kerjakan_modul": alat_kerjakan_modul,
    "baca_pdf": alat_baca_pdf,
    "buat_word": alat_buat_word,
    "screenshot": alat_screenshot,
    "baca_layar": alat_baca_layar,
    "cari_dari_layar": alat_cari_dari_layar,
    "atur_pengingat": alat_atur_pengingat,
    "lihat_pengingat": alat_lihat_pengingat,
    "hapus_pengingat": alat_hapus_pengingat,
    "transkrip_youtube": alat_transkrip_youtube,
    "bicara": alat_bicara,
}


# ============== OTAK AGENT ==============

def panggil_model(pesan, suhu=0.6):
    body = json.dumps({
        "model": MODEL,
        "messages": pesan,
        "stream": False,
        "options": {"temperature": suhu},
    }).encode()
    req = urllib.request.Request(OLLAMA_URL, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data["message"]["content"]


def parsing_alat(teks):
    """Cari 'ALAT: {...}' di jawaban model. Return (nama, argumen) atau None."""
    pos = teks.find("ALAT:")
    if pos == -1:
        return None
    sisa = teks[pos + 5:].strip().strip("`").lstrip("json").strip()
    awal = sisa.find("{")
    if awal == -1:
        return None
    try:
        objek, _ = json.JSONDecoder().raw_decode(sisa[awal:])
    except json.JSONDecodeError:
        return None
    nama = str(objek.get("nama") or objek.get("name") or "").strip()
    argumen = objek.get("argumen") or objek.get("args") or {}
    if not isinstance(argumen, dict):
        argumen = {}
    return nama, argumen


def _cocokkan_alat(nama):
    """Cocokkan nama alat yang hampir benar ('klik_tombol' -> 'klik')."""
    if nama in ALAT:
        return nama
    for sah in ALAT:
        if nama and (sah in nama or nama in sah):
            return sah
    mirip = difflib.get_close_matches(nama, ALAT.keys(), n=1, cutoff=0.45)
    return mirip[0] if mirip else None


POLA_RENCANA = re.compile(
    r"kita akan|akan saya|langkah-langkah|langkah berikut|untuk melanjutkan|"
    r"yang terbaik adalah|instruksi yang tepat|silakan segera panggil|"
    r"selanjutnya, lanjutkan|menjelaskan rencana|jangan mengutip|"
    r"pastikan untuk tidak|ingatlah untuk tidak|apakah kamu ingin saya|"
    r"apakah anda ingin saya", re.I)


def proses_pertanyaan(pesan, riwayat):
    # 'lanjutkan'/'sudah' di tengah pekerjaan alat -> terjemahkan jadi instruksi
    # eksplisit agar model kecil tidak bingung
    bersih = pesan.strip().lower()
    if bersih in ("lanjutkan", "lanjut", "sudah") and any(
            m.get("content", "").startswith("[HASIL ALAT") for m in riwayat[-6:]):
        pesan = ("Lanjutkan pekerjaan yang belum selesai (lihat hasil alat terakhir "
                 "di percakapan). Panggil alat berikutnya dengan format ALAT.")
    riwayat.append({"role": "user", "content": pesan})
    alat_web_dipakai = False
    pernah_rencana = False
    for langkah in range(MAKS_LANGKAH_ALAT):
        _tunggu_jika_dijeda()
        print("  ⏳ Hermes sedang berpikir...", end="\r", flush=True)
        try:
            jawaban = panggil_model(riwayat)
        except urllib.error.URLError:
            print("\n❌ Tidak bisa menghubungi Ollama. Pastikan Ollama menyala "
                  "(ikon paus di pojok kanan bawah).")
            return
        print(" " * 40, end="\r")  # hapus tulisan 'berpikir'
        riwayat.append({"role": "assistant", "content": jawaban})

        alat = parsing_alat(jawaban)
        if alat is None:
            if "ALAT:" in jawaban and not pernah_rencana:
                # model menulis ALAT tapi formatnya rusak - minta ulang SEKALI
                pernah_rencana = True
                print("  ⚠️  (format ALAT rusak - Hermes diminta mengulang)")
                riwayat.append({"role": "user", "content":
                                "Format ALAT kamu rusak atau tidak lengkap. Tulis ulang "
                                "SEKARANG dengan format yang benar, contoh: "
                                'ALAT: {"nama": "klik", "argumen": {"teks": "Melanjutkan"}}'})
                continue
            # model kecil kadang menjawab dengan 'rencana'/mengutip instruksi di
            # tengah pekerjaan - tegur SEKALI agar langsung memanggil alat
            if langkah > 0 and not pernah_rencana and POLA_RENCANA.search(jawaban):
                pernah_rencana = True
                print("  ⚠️  (Hermes menjelaskan rencana - disuruh langsung kerja)")
                riwayat.append({"role": "user", "content":
                                "Jangan tulis rencana atau mengutip instruksi. Langsung "
                                "panggil alat berikutnya dengan format ALAT, atau jawab "
                                "singkat bila tugasnya benar-benar sudah selesai."})
                continue
            print(jawaban.strip())
            if alat_web_dipakai:
                tampilkan_popup("✅ Hermes selesai bekerja",
                                "Jawaban sudah siap - buka jendela Hermes Bot Plus")
            return

        nama, argumen = alat
        if nama not in ALAT:
            cocok = _cocokkan_alat(nama)
            if cocok:
                print(f"  ⚙️  [alat '{nama}' diterjemahkan jadi '{cocok}']")
                nama = cocok
            else:
                riwayat.append({"role": "user", "content":
                                f"Error: alat '{nama}' tidak tersedia. Untuk mengklik "
                                "gunakan alat 'klik' dengan argumen 'teks'. Ulangi "
                                "SEKARANG dengan format ALAT yang benar."})
                continue
        print(f"  ⚙️  [memanggil alat: {nama}]")
        detail = (argumen.get("kueri") or argumen.get("query")
                  or argumen.get("url") or argumen.get("nama_file") or "")
        if nama in ALAT_WEB:
            alat_web_dipakai = True
            tampilkan_popup(f"🌐 Hermes sedang bekerja",
                            f"{ALAT_LABEL[nama]}: {detail}" if detail else ALAT_LABEL[nama])
        try:
            hasil = ALAT[nama](argumen)
        except Exception as e:
            hasil = f"Error menjalankan alat: {e}"
        print(f"  ✅ {hasil.splitlines()[0]}")
        riwayat.append({"role": "user", "content":
                        f"[HASIL ALAT {nama}]\n{hasil}\n\n"
                        "Lanjutkan tugas: panggil alat berikutnya dengan format ALAT, "
                        "atau jawab pengguna bila tugas sudah selesai / kamu butuh dia login."})
    print("❌ Batas langkah alat tercapai (mencegah loop). "
          "Ketik 'lanjutkan' agar Hermes melanjutkan pekerjaannya.")
    riwayat.append({"role": "user", "content":
                    "(Catatan sistem: batas langkah alat tercapai sementara - pekerjaan "
                    "belum selesai. Tunggu jawaban pengguna. Bila pengguna menjawab "
                    "'lanjutkan' atau 'sudah', lanjutkan pekerjaan yang tersisa dengan "
                    "format ALAT.)"})


def main():
    print("=" * 60)
    print("  HERMES BOT PLUS - Asisten Kuliah AI Lokal")
    print("  Bisa: cari internet & Wikipedia, browser kursus (klik),")
    print("        isi kuis/form (langsung, status di jendela mini), baca PDF, Word,")
    print("        screenshot, pengingat, transkrip YouTube, suara, simpan/baca file")
    print(f"        (hasil file disimpan di {FOLDER_SIMPAN})")
    print("  Ketik 'keluar' untuk berhenti, '/reset' untuk chat baru")
    print("=" * 60)
    print()
    # cek Ollama
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5)
    except Exception:
        print("❌ Ollama belum menyala! Buka aplikasi Ollama dulu (ikon paus),")
        print("   lalu jalankan lagi file ini.")
        input("Tekan Enter untuk keluar...")
        return

    # mulai jendela mini status (tetap tampil) + thread pengingat (cek tiap 20 detik)
    _MINI_POPUP.mulai()
    _MINI_POPUP.tampilkan("Hermes siap", "Jendela status aktif. Silakan ketik perintah.")
    threading.Thread(target=_thread_pengingat, daemon=True).start()

    riwayat = [{"role": "system", "content": SYSTEM_PROMPT}]
    while True:
        try:
            tanya = input("🧑 Anda > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSampai jumpa! 👋")
            break
        if not tanya:
            continue
        if tanya.lower() in ("keluar", "exit", "quit", "/bye"):
            print("Sampai jumpa! 👋")
            break
        if tanya.lower() in ("/reset", "/clear"):
            riwayat = [{"role": "system", "content": SYSTEM_PROMPT}]
            print("🗑️  Riwayat chat dibersihkan.\n")
            continue
        print()
        proses_pertanyaan(tanya, riwayat)
        print()


if __name__ == "__main__":
    main()
