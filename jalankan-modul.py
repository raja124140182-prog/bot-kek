"""Jalankan semua modul yang tercantum di konfigurasi.json.

Paket ini portable: semua jalur dihitung relatif terhadap folder script, dan
URL kursus diambil dari konfigurasi.json. Untuk kursus lain, cukup edit
`url_kursus` dan daftar `modul` di file tersebut.

Sebelum menjalankan:
  1. Pastikan sudah login manual di browser Hermes (profil dibuat otomatis).
  2. Jangan menjalankan dua proses sekaligus: satu profil browser hanya boleh
     dipakai satu context.

Aktivitas unggah file dan mod/feedback sengaja dilewati dan dicatat di log.
Tiap modul diverifikasi ulang; bila belum centang penuh, diulang maksimal 3x.
"""
import importlib.util
import json
import time
from datetime import datetime
from pathlib import Path

FOLDER = Path(__file__).resolve().parent
SKRIP_UTAMA = FOLDER / "hermes-agent.py"
KONFIGURASI = FOLDER / "konfigurasi.json"


def cat(*args):
    print(datetime.now().strftime("%H:%M:%S"), *args, flush=True)


def muat_konfigurasi():
    if not KONFIGURASI.exists():
        raise SystemExit(f"File konfigurasi tidak ditemukan: {KONFIGURASI}")
    try:
        cfg = json.loads(KONFIGURASI.read_text(encoding="utf-8"))
    except Exception as e:
        raise SystemExit(f"konfigurasi.json rusak: {e}")
    url = str(cfg.get("url_kursus") or "").strip()
    if "/courses/" not in url:
        raise SystemExit("Isi 'url_kursus' di konfigurasi.json dengan URL kursus asli.")
    modul = [str(x).strip() for x in (cfg.get("modul") or []) if str(x).strip()]
    if not modul:
        raise SystemExit("Daftar 'modul' di konfigurasi.json masih kosong.")
    try:
        jeda_mulai = max(0, int(cfg.get("jeda_mulai", 5)))
        jeda_ulang = max(0, int(cfg.get("jeda_ulang", 3)))
    except (TypeError, ValueError):
        jeda_mulai, jeda_ulang = 5, 3
    return url, modul, jeda_mulai, jeda_ulang


basis, modul, jeda_mulai, jeda_ulang = muat_konfigurasi()

if not SKRIP_UTAMA.exists():
    raise SystemExit(f"File otak bot tidak ditemukan: {SKRIP_UTAMA}")

spesifikasi = importlib.util.spec_from_file_location("hb", SKRIP_UTAMA)
m = importlib.util.module_from_spec(spesifikasi)
spesifikasi.loader.exec_module(m)

m.alat_buka_browser({"url": basis})


def _sudah_login():
    """Cek apakah sesi manual sudah tersimpan di profil browser ini."""
    try:
        halaman = m._pastikan_browser()
        if "/courses/" not in (halaman.url or ""):
            return False
        token = halaman.evaluate("() => localStorage.getItem('@accessToken')")
        uid = halaman.evaluate(
            "() => (JSON.parse(localStorage.getItem('@user') || '{}')"
            ".userValue || {}).filteredUserId || ''")
        return bool(token and uid)
    except Exception:
        return False


if not _sudah_login():
    m.tampilkan_popup(
        "Hermes menunggu login",
        "Silakan login SENDIRI di jendela browser yang terbuka.")
    cat("Perlu login manual: silakan login di jendela browser Hermes. Bot menunggu maksimal 10 menit.")
    for _ in range(120):
        time.sleep(5)
        if _sudah_login():
            cat("Login terdeteksi. Melanjutkan ke modul.")
            break
    else:
        raise SystemExit("Login tidak terdeteksi. Jalankan ulang setelah login manual.")

time.sleep(jeda_mulai)

for nama in modul:
    cat("\n" + "=" * 80)
    cat("MODUL:", nama)
    cat("SEBELUM:", m.alat_status_modul({"nama": nama}))
    for attempt in range(1, 4):
        hasil = m.alat_kerjakan_modul({"nama": nama})
        cat(f"  ATTEMPT {attempt}: {hasil}")
        status = m.alat_status_modul({"nama": nama})
        cat("  STATUS:", status)
        if "SELESAI" in status:
            break
        m.alat_buka_browser({"url": basis})
        time.sleep(jeda_ulang)
    cat("AKHIR:", m.alat_status_modul({"nama": nama}))

cat("\nSELESAI SEMUA MODUL.")
