"""Dua tahap untuk Berkolaborasi/LTI:

1. SCAN  : kunjungi semua aktivitas, simpan hasil ke hasil-scan-rating.json.
2. KERJA : baca file itu, kerjakan HANYA entri yang perlu (belum lulus/rating<5),
           lalu perbarui file yang sama setelah tiap perbaikan.

Jalankan:
    py -3.15 -u perbaiki-rating.py             # scan -> simpan -> kerja
    py -3.15 -u perbaiki-rating.py --scan-saja # scan + simpan saja
    py -3.15 -u perbaiki-rating.py --kerja     # pakai hasil scan yang tersimpan
    py -3.15 -u perbaiki-rating.py --paksa     # abaikan cache, scan ulang semua
"""
import importlib.util
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

FOLDER = Path(__file__).resolve().parent
SKRIP_UTAMA = FOLDER / "hermes-agent.py"
KONFIGURASI = FOLDER / "konfigurasi.json"
LOG = FOLDER / "log-rating.txt"
HASIL = FOLDER / "hasil-scan-rating.json"
CACHE = FOLDER / "rating-scan.json"


def cat(*args):
    teks = datetime.now().strftime("%H:%M:%S") + " " + " ".join(str(x) for x in args)
    print(teks, flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(teks + "\n")
    except Exception:
        pass


def muat_json(path, bawaan):
    try:
        dat = json.loads(path.read_text(encoding="utf-8"))
        return dat if isinstance(dat, (dict, list)) else bawaan
    except Exception:
        return bawaan


def simpan_json(path, dat):
    try:
        path.write_text(json.dumps(dat, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        cat(f"Gagal simpan {path.name}: {e}")


def masih_segar(entri, menit=60):
    """Cache dipakai hanya bila tidak perlu perbaikan dan belum terlalu tua."""
    if not entri or entri.get("perlu"):
        return False
    try:
        waktu = entri.get("waktu") or entri.get("t")
        return datetime.now() - datetime.fromisoformat(waktu) < timedelta(minutes=menit)
    except Exception:
        return False


spesifikasi = importlib.util.spec_from_file_location("hb", SKRIP_UTAMA)
m = importlib.util.module_from_spec(spesifikasi)
spesifikasi.loader.exec_module(m)
cfg = json.loads(KONFIGURASI.read_text(encoding="utf-8"))
m.alat_buka_browser({"url": cfg["url_kursus"]})
page = m._pastikan_browser()


def semua_lti():
    keluar, terlihat = [], set()
    for nama in cfg["modul"]:
        for a in m._daftar_aktivitas_modul(page, nama):
            if a["modtype"] == "lti" or re.match(r"^Berkolaborasi\b", a["nama"], re.I):
                if a["instance"] in terlihat:
                    continue
                terlihat.add(a["instance"])
                keluar.append((nama, a))
    return keluar


def buka_lti(url):
    """Buka aktivitas dengan waktu tunggu yang mengikuti kecepatan jaringan."""
    halaman = m._pastikan_browser()
    faktor = m._faktor_jaringan(halaman)
    tunggu = min(60, max(25, int(50 * faktor)))  # detik per percobaan (dibatasi)
    batas_navigasi = int(45000 * min(2.5, faktor))
    for percobaan in range(2):
        try:
            halaman.goto(url, wait_until="domcontentloaded", timeout=batas_navigasi)
        except Exception:
            pass
        for _ in range(tunggu * 2):
            halaman = m._pastikan_browser()
            fr = next((x for x in m._semua_frame(halaman)
                       if "/ltiPage" in (x.url or "")), None)
            if fr:
                return halaman, fr, faktor
            time.sleep(0.5)
        if percobaan == 0:
            cat(f"  faktor jaringan {faktor}: frame belum muncul, muat ulang sekali.")
            m.status_aktif(f"Jaringan faktor {faktor}; memuat ulang aktivitas")
    # Sama seperti fungsi utama: kartu "Lihat Aktivitas" kadang perlu diklik
    # supaya frame /ltiPage benar-benar diluncurkan.
    for x in m._semua_frame(halaman):
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
            for _ in range(tunggu * 2):
                fr = next((y for y in m._semua_frame(m._pastikan_browser())
                           if "/ltiPage" in (y.url or "")), None)
                if fr:
                    return m._pastikan_browser(), fr, faktor
                time.sleep(0.5)
            break
    return halaman, None, faktor


def baca_rating(fr, faktor=1.0):
    """Baca rating dengan sabar: frame /ltiPage butuh waktu sampai siap."""
    if not fr:
        return [], -1
    ratings = []
    for _ in range(min(14, max(6, int(8 * faktor)))):
        try:
            try:
                fr.wait_for_selector(".rating-text",
                                     timeout=int(2500 * min(2, faktor)))
            except Exception:
                pass
            ratings = fr.evaluate("""() => [...document.querySelectorAll('.rating-text')]
                .map(e => (e.innerText||'').replace(/\\s+/g,' ').trim())""")
        except Exception:
            ratings = []
        if ratings:
            break
        time.sleep(1)
    if not ratings:
        return [], -1
    rendah = 0
    for r in ratings:
        mm = re.match(r"\s*(\d+)\s*/\s*5", str(r))
        if mm and int(mm.group(1)) < 5:
            rendah += 1
    return ratings, rendah


def selesai(status):
    return str(status or "").lower().startswith("completed")


def entri_baru(a, ratings, rendah, status, dari_cache=False):
    return {
        "instance": a["instance"],
        "url": a["url"],
        "nama": a["nama"],
        "pelajaran": a["pelajaran"],
        "waktu": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "ratings": ratings,
        "rendah": rendah,
        "perlu": (not selesai(status)) or (frame_gagal(rendah)) or rendah > 0,
        "dari_cache": dari_cache,
        "percobaan": 0,
    }


def frame_gagal(rendah):
    return rendah == -1


def tulis_hasil(entri):
    simpan_json(HASIL, {"waktu": datetime.now().isoformat(timespec="seconds"),
                        "entri": entri})


def tahap_scan(paksa):
    cache = {} if paksa else muat_json(CACHE, {})
    items = semua_lti()
    cat("=== TAHAP SCAN ===", "total:", len(items), "| paksa:", paksa)
    hasil, dilihat, dilewati, terakhir = [], set(), 0, time.time()
    for i, (nama, a) in enumerate(items, 1):
        inst = a["instance"]
        if inst in dilihat:
            continue
        dilihat.add(inst)
        lama = cache.get(inst)
        if not paksa and masih_segar(lama):
            e = dict(lama)
            e.update({
                "instance": inst, "url": a["url"], "nama": a["nama"],
                "pelajaran": a["pelajaran"], "dari_cache": True,
            })
            hasil.append(e)
            dilewati += 1
            continue
        if time.time() - terakhir > 180:
            cat("WATCHDOG scan: >3 menit tanpa progres; lanjut ke aktivitas berikutnya.")
            m.tampilkan_popup("Hermes menemui kendala",
                              "Scan mandek >3 menit; lanjut ke aktivitas berikutnya.")
            terakhir = time.time()
            continue
        m.status_aktif(f"Memindai rating LTI {i}/{len(items)}: {inst}")
        try:
            _, frame, faktor = buka_lti(a["url"])
            ratings, rendah = baca_rating(frame, faktor)
            status = m._status_aktivitas_api(m._pastikan_browser(), inst)
            e = entri_baru(a, ratings, rendah, status)
            e["percobaan"] = (lama or {}).get("percobaan", 0) or 0
            e["waktu"] = datetime.now().isoformat(timespec="seconds")
            hasil.append(e)
            cache[inst] = e
            simpan_json(CACHE, cache)
            tulis_hasil(hasil)   # tulis bertahap: api tersimpan walau bot mati mendadak
            if len(hasil) % 5 == 0:
                cat(f"  scan {len(hasil)}/{len(items)} ...")
            terakhir = time.time()
        except Exception as ex:
            cat(f"  {inst}: ERROR scan {type(ex).__name__} {ex}")
            m.tampilkan_popup("Hermes menemui kendala", f"Scan {inst}: {type(ex).__name__}")
            e = entri_baru(a, [], -1, None)
            hasil.append(e)
            tulis_hasil(hasil)
    tulis_hasil(hasil)
    butuh = [e for e in hasil if e["perlu"]]
    cat(f"Scan selesai: {len(hasil)} entri, {dilewati} dari cache, "
        f"{len(butuh)} perlu dikerjakan -> {HASIL.name}")
    return hasil


def tahap_kerja(hasil):
    cache = muat_json(CACHE, {})
    cat("=== TAHAP KERJA ===", "entri:", len(hasil),
        "| perlu:", sum(1 for e in hasil if e.get("perlu")))
    for siklus in range(1, 4):
        butuh = [e for e in hasil if e["perlu"]]
        if not butuh:
            break
        cat(f"SIKLUS {siklus}: {len(butuh)} entri perlu dikerjakan")
        for i, e in enumerate(butuh, 1):
            inst, url = e["instance"], e["url"]
            try:
                m.status_aktif(f"Mengerjakan {i}/{len(butuh)}: {inst} "
                               f"(status={e['status']}, rating={e['ratings']})")
                halaman, frame, faktor = buka_lti(url)
                if not frame:
                    cat(f"  {inst}: frame tidak termuat, dicoba lagi siklus berikutnya.")
                    continue
                hanya_rating = selesai(e["status"]) and (e["rendah"] or 0) > 0
                hasil_teks = m._selesaikan_lti(halaman, hanya_rating=hanya_rating)
                cat(f"  {inst}: {(hasil_teks or 'tanpa perubahan')[:300]}")
                _, frame2, faktor2 = buka_lti(url)
                ratings2, rendah2 = baca_rating(frame2, faktor2)
                status2 = m._status_aktivitas_api(m._pastikan_browser(), inst)
                e.update({
                    "waktu": datetime.now().isoformat(timespec="seconds"),
                    "status": status2, "ratings": ratings2, "rendah": rendah2,
                    "perlu": (not selesai(status2)) or rendah2 != 0,
                    "percobaan": (e.get("percobaan") or 0) + 1,
                    "dari_cache": False,
                })
                cache[inst] = dict(e)
                simpan_json(CACHE, cache)
                tulis_hasil(hasil)
                m.status_aktif(f"Hasil {inst}: status={status2}, rating={ratings2}")
            except Exception as ex:
                cat(f"  {inst}: ERROR kerja {type(ex).__name__} {ex}")
                m.tampilkan_popup("Hermes menemui kendala", f"{inst}: {type(ex).__name__}")
                e["perlu"] = True
    sisa = [e["instance"] for e in hasil if e["perlu"]]
    if sisa:
        cat("SISA SETELAH 3 SIKLUS:", ", ".join(sisa))
    else:
        cat("SEMUA BERKOLABORASI LULUS DAN RATING 5/5.")


def jalankan():
    paksa = "--paksa" in sys.argv
    if "--kerja" in sys.argv:
        dat = muat_json(HASIL, {})
        hasil = dat.get("entri") if isinstance(dat, dict) else dat
        if not isinstance(hasil, list) or not hasil:
            cat("Belum ada hasil scan. Jalankan scan dulu.")
            return
        cat("Memakai hasil scan tersimpan:", dat.get("waktu", "?"))
    else:
        hasil = tahap_scan(paksa)
        if "--scan-saja" in sys.argv:
            cat("Hasil scan tersimpan di", HASIL.name,
                "- jalankan dengan --kerja untuk memprosesnya.")
            return
    tahap_kerja(hasil)


if __name__ == "__main__":
    jalankan()
