"""Perbaiki aktivitas Berkolaborasi/LTI yang belum lulus atau ratingnya <5/5.

Jalankan:
    py -3.15 -u perbaiki-rating.py

Satu proses melakukan audit + perbaikan + verifikasi ulang. Semua lokal:
profil browser yang sudah login dan model Ollama hermes-bot.
"""
import importlib.util
import json
import re
import time
from datetime import datetime
from pathlib import Path

FOLDER = Path(__file__).resolve().parent
SKRIP_UTAMA = FOLDER / "hermes-agent.py"
KONFIGURASI = FOLDER / "konfigurasi.json"
LOG = FOLDER / "log-rating.txt"


def cat(*args):
    teks = datetime.now().strftime("%H:%M:%S") + " " + " ".join(str(x) for x in args)
    print(teks, flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(teks + "\n")
    except Exception:
        pass


spesifikasi = importlib.util.spec_from_file_location("hb", SKRIP_UTAMA)
m = importlib.util.module_from_spec(spesifikasi)
spesifikasi.loader.exec_module(m)
cfg = json.loads(KONFIGURASI.read_text(encoding="utf-8"))
m.alat_buka_browser({"url": cfg["url_kursus"]})
page = m._pastikan_browser()


def semua_lti():
    keluar = []
    for nama in cfg["modul"]:
        for a in m._daftar_aktivitas_modul(page, nama):
            if a["modtype"] == "lti" or re.match(r"^Berkolaborasi\b", a["nama"], re.I):
                keluar.append((nama, a))
    return keluar


def buka_lti(url):
    """Navigasi cepat: jangan tunggu networkidle (SPA sering tidak pernah idle)."""
    halaman = m._pastikan_browser()
    try:
        halaman.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception:
        return halaman, None
    for _ in range(60):
        halaman = m._pastikan_browser()
        fr = next((x for x in m._semua_frame(halaman)
                   if "/ltiPage" in (x.url or "")), None)
        if fr:
            return halaman, fr
        time.sleep(0.5)
    return halaman, None


def baca_rating(fr):
    if not fr:
        return [], -1
    try:
        ratings = fr.evaluate("""() => [...document.querySelectorAll('.rating-text')]
            .map(e => (e.innerText||'').replace(/\\s+/g,' ').trim())""")
    except Exception:
        return [], -1
    rendah = 0
    for r in ratings:
        mm = re.match(r"\s*(\d+)\s*/\s*5", str(r))
        if mm and int(mm.group(1)) < 5:
            rendah += 1
    return ratings, rendah


def selesai(status):
    return str(status or "").lower().startswith("completed")


def proses(inst, url,estimasi=""):
    halaman, frame = buka_lti(url)
    ratings, rendah = baca_rating(frame)
    status = m._status_aktivitas_api(m._pastikan_browser(), inst)
    if frame is None:
        cat(f"{inst} | frame /ltiPage tidak tersedia; "
            f"{'lewat' if selesai(status) else 'akan dicoba lagi'}.")
        return (not selesai(status)), status, ratings
    if selesai(status) and rendah == 0:
        return False, status, ratings
    hanya_rating = selesai(status) and rendah > 0
    cat(f"{inst} | status={status} rating={ratings} -> "
        f"{'perbaiki rating' if hanya_rating else 'kerjakan aktivitas'} {estimasi}")
    hasil = m._selesaikan_lti(halaman, hanya_rating=hanya_rating)
    cat("  hasil:", (hasil or "tidak ada perubahan")[:450])
    halaman2, frame2 = buka_lti(url)
    ratings2, rendah2 = baca_rating(frame2)
    status2 = m._status_aktivitas_api(m._pastikan_browser(), inst)
    cat(f"{inst} | sesudah status={status2} rating={ratings2}")
    return (not selesai(status2) or rendah2 > 0), status2, ratings2


def jalankan():
    items = semua_lti()
    cat("TOTAL LTI/BERKOLABORASI:", len(items))
    # Prioritaskan yang jelas bermasalah berdasarkan status API dulu.
    sasaran = []
    for nama, a in items:
        st = m._status_aktivitas_api(page, a["instance"])
        if not selesai(st):
            sasaran.append((a["instance"], a["url"]))
    cat("Prioritas belum completed:", len(sasaran))
    for siklus in range(1, 4):
        cat(f"=== SIKLUS {siklus} ===")
        tersisa = []
        for i, (inst, url) in enumerate(sasaran, 1):
            try:
                perlu, _, _ = proses(inst, url, f"[{i}/{len(sasaran)}]")
                if perlu:
                    tersisa.append((inst, url))
            except Exception as e:
                cat(f"  {inst}: ERROR {type(e).__name__} {e}")
                tersisa.append((inst, url))
        # Setelah status beres, cek semua LTI untuk rating <5/5.
        if not tersisa and siklus == 1:
            cat("=== CEK RATING SEMUA LTI ===")
            for i, (nama, a) in enumerate(items, 1):
                inst = a["instance"]
                if any(x[0] == inst for x in tersisa):
                    continue
                try:
                    halaman, frame = buka_lti(a["url"])
                    ratings, rendah = baca_rating(frame)
                    if rendah > 0:
                        cat(f"[{i}/{len(items)}] {inst} rating rendah {ratings}")
                        perlu, _, _ = proses(inst, a["url"])
                        if perlu:
                            tersisa.append((inst, a["url"]))
                    elif i % 10 == 0:
                        cat(f"  cek rating {i}/{len(items)} ...")
                except Exception as e:
                    cat(f"  {inst}: ERROR cek rating {type(e).__name__} {e}")
                    tersisa.append((inst, a["url"]))
        if not tersisa:
            cat("SEMUA BERKOLABORASI LULUS DAN RATING 5/5.")
            return
        cat("Masih perlu perbaikan:", len(tersisa))
        sasaran = tersisa
    cat("SISA SETELAH 3 SIKLUS:", len(sasaran))
    for inst, url in sasaran:
        cat("  ", inst, url)


if __name__ == "__main__":
    jalankan()
