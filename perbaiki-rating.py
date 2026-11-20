"""Berkolaborasi: satu aktivitas = scan selesai -> langsung kerjakan bila perlu
-> simpan hasil -> lanjut ke aktivitas berikutnya.

Hasil tiap aktivitas ditulis bertahap ke hasil-scan-rating.json supaya bisa
dilanjutkan kapan saja. Entri yang sudah terbukti bagus disimpan di
rating-scan.json (TTL 60 menit) agar tidak dipindai ulang.

Jalankan:
    py -3.15 -u perbaiki-rating.py            # lanjut, pakai cache
    py -3.15 -u perbaiki-rating.py --paksa    # abaikan cache, scan ulang semua
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
    if not entri or entri.get("perlu") or entri.get("kendala"):
        return False
    try:
        return datetime.now() - datetime.fromisoformat(
            entri["waktu"] or entri["t"]) < timedelta(minutes=menit)
    except Exception:
        return False


spesifikasi = importlib.util.spec_from_file_location("hb", SKRIP_UTAMA)
m = importlib.util.module_from_spec(spesifikasi)
spesifikasi.loader.exec_module(m)
cfg = json.loads(KONFIGURASI.read_text(encoding="utf-8"))
m.alat_buka_browser({"url": cfg["url_kursus"]})
page = m._pastikan_browser()

DIAG = {"konsol": [], "gagal": [], "respons": []}
page.on("console", lambda msg: DIAG["konsol"].append(
    f"{msg.type}: {msg.text[:150]}")
    if msg.type in ("error", "warning") else None)
page.on("requestfailed", lambda req: DIAG["gagal"].append(
    f"{req.url[:120]} :: {req.failure}"))
page.on("response", lambda res: DIAG["respons"].append(
    f"{res.status} {res.url[:120]}") if res.status >= 400 else None)


def sesi_habis():
    """Token login kedaluwarsa ditandai 401 dari API Wadhwani."""
    return any(str(x).startswith("401") and "api.opportunity" in str(x)
               for x in DIAG["respons"])


def catat_diag(halaman, inst):
    try:
        cat("  DIAG", inst, "frame:", [x.url[:130] for x in m._semua_frame(halaman)])
    except Exception:
        pass
    try:
        src = halaman.evaluate("""() => {
            const f = document.querySelector('iframe.activity-frame');
            return f ? f.src : '(tidak ada iframe)';
        }""")
        cat("  DIAG src:", src[:160])
    except Exception as e:
        cat("  DIAG src gagal:", type(e).__name__)
    cat("  DIAG konsol:", DIAG["konsol"][-4:])
    cat("  DIAG request gagal:", DIAG["gagal"][-4:])
    cat("  DIAG respons >=400:", DIAG["respons"][-4:])
    for k in ("konsol", "gagal", "respons"):
        DIAG[k].clear()


def semua_lti():
    keluar, terlihat = [], set()
    for nama in cfg["modul"]:
        for a in m._daftar_aktivitas_modul(page, nama):
            if a["modtype"] == "lti" or re.match(r"^Berkolaborasi\b", a["nama"], re.I):
                if a["instance"] in terlihat:
                    continue
                terlihat.add(a["instance"])
                keluar.append(a)
    return keluar


def buka_lti(url):
    """Tunggu launch LTI sampai selesai.

    Penting: jangan memuat ulang saat baru lewat batas pendek. Percobaan
    sebelumnya mengirim OIDC ke api.opportunity dan dibatalkan (ERR_ABORTED)
    setiap kali halaman di-reload, jadi launch tidak pernah selesai.
    Sekarang: satu navigasi, tunggu panjang, reload hanya bila benar mandek.
    """
    halaman = m._pastikan_browser()
    faktor = m._faktor_jaringan(halaman)
    inst = url.rsplit("/", 1)[-1]
    batas_navigasi = int(60000 * min(2.5, faktor))
    try:
        halaman.goto(url, wait_until="domcontentloaded", timeout=batas_navigasi)
    except Exception:
        pass

    batas_tunggu = int(360 * min(2.0, max(1.0, faktor)))  # 6-12 menit
    terakhir_berubah = time.time()
    sebelumnya, sudah_reload = None, False
    for detik in range(batas_tunggu):
        halaman = m._pastikan_browser()
        fr = next((x for x in m._semua_frame(halaman)
                   if "/ltiPage" in (x.url or "")), None)
        if fr:
            return halaman, fr, faktor
        urls = [x.url or "" for x in m._semua_frame(halaman)]
        if urls != sebelumnya:
            sebelumnya = urls
            terakhir_berubah = time.time()
            cat(f"  LTI {inst} detik {detik}: {[u[:95] for u in urls]}")
        if detik and detik % 60 == 0:
            cat(f"  LTI {inst}: masih menunggu frame ({detik}s)")
            m.status_aktif(f"Menunggu LTI {inst} ({detik}s, faktor {faktor})")
        if time.time() - terakhir_berubah > 180 and not sudah_reload:
            cat(f"  LTI {inst}: launch mandek 180s, muat ulang sekali.")
            sudah_reload = True
            try:
                halaman.goto(url, wait_until="domcontentloaded",
                             timeout=batas_navigasi)
            except Exception:
                pass
            terakhir_berubah = time.time()
        time.sleep(1)
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
            for _ in range(180):
                fr = next((y for y in m._semua_frame(m._pastikan_browser())
                           if "/ltiPage" in (y.url or "")), None)
                if fr:
                    return m._pastikan_browser(), fr, faktor
                time.sleep(1)
            break
    return halaman, None, faktor


def baca_rating(fr, faktor=1.0):
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


def entri_baru(a, status, ratings, rendah, perlu=False, kendala="", percobaan=0):
    return {
        "instance": a["instance"], "url": a["url"], "nama": a["nama"],
        "pelajaran": a["pelajaran"],
        "waktu": datetime.now().isoformat(timespec="seconds"),
        "status": status, "ratings": ratings, "rendah": rendah,
        "perlu": perlu, "kendala": kendala, "percobaan": percobaan,
        "dari_cache": False,
    }


def tulis_hasil(hasil):
    simpan_json(HASIL, {"waktu": datetime.now().isoformat(timespec="seconds"),
                        "entri": hasil})


def proses_satu(a, i, total):
    """Scan satu Berkolaborasi, kerjakan bila perlu, lalu kembalikan hasilnya."""
    inst = a["instance"]
    m.status_aktif(f"Memindai Berkolaborasi {i}/{total}: {inst}")
    halaman, frame, faktor = buka_lti(a["url"])
    if not frame:
        m.tampilkan_popup("Hermes menemui kendala",
                          f"{inst}: frame belum muncul setelah ditunggu lama")
        cat(f"[{i}/{total}] {inst}: frame /ltiPage tidak termuat.")
        catat_diag(m._pastikan_browser(), inst)
        return entri_baru(a, None, [], -1, kendala="frame tidak termuat"), False

    ratings, rendah = baca_rating(frame, faktor)
    status = m._status_aktivitas_api(m._pastikan_browser(), inst)
    cat(f"[{i}/{total}] {inst} status={status} rating={ratings} rendah={rendah}")

    if selesai(status) and rendah == 0:
        return entri_baru(a, status, ratings, rendah), False

    hanya_rating = selesai(status) and rendah > 0
    if rendah < 0:
        kendala = "rating tidak terbaca"
        cat(f"  {inst}: rating tidak terbaca; coba perbaikan rating.")
    else:
        kendala = ""
    label = "rating" if hanya_rating or rendah < 0 else "kartu"
    m.status_aktif(f"Mengerjakan {i}/{total}: {inst} ({label})")
    try:
        teks = m._selesaikan_lti(halaman, hanya_rating=hanya_rating or rendah < 0)
        cat(f"  {inst}: {(teks or 'tanpa perubahan')[:280]}")
    except Exception as e:
        cat(f"  {inst}: ERROR kerja {type(e).__name__} {e}")
        m.tampilkan_popup("Hermes menemui kendala", f"{inst}: {type(e).__name__}")
        return entri_baru(a, status, ratings, rendah, perlu=True,
                          kendala=f"error {type(e).__name__}"), False

    _, frame2, faktor2 = buka_lti(a["url"])
    ratings2, rendah2 = baca_rating(frame2, faktor2)
    status2 = m._status_aktivitas_api(m._pastikan_browser(), inst)
    if not frame2:
        kendala = "frame hilang setelah dikerjakan"
    cat(f"  {inst}: sesudah status={status2} rating={ratings2}")
    m.status_aktif(f"Hasil {inst}: status={status2}, rating={ratings2}")
    perlu = (not selesai(status2)) or rendah2 != 0
    return entri_baru(a, status2, ratings2, rendah2, perlu=perlu,
                      kendala=kendala, percobaan=1), True


def jalankan():
    for _ in range(20):
        if sesi_habis():
            break
        time.sleep(1)
    if sesi_habis():
        cat("SESI LOGIN HABIS (401). Bot dihentikan.")
        cat("Silakan login ulang di browser yang terbuka, lalu jalankan lagi.")
        m.tampilkan_popup("Hermes menemui kendala",
                          "Sesi login habis (401). Perlu login ulang di browser.")
        return
    paksa = "--paksa" in sys.argv
    cache = {} if paksa else muat_json(CACHE, {})
    items = semua_lti()
    cat("=== SCAN + KERJA PER AKTIVITAS ===", "total:", len(items),
        "| paksa:", paksa, "| faktor jaringan:", m._faktor_jaringan(page))
    hasil, gagal_berturut = [], 0
    for i, a in enumerate(items, 1):
        inst = a["instance"]
        lama = None if paksa else cache.get(inst)
        if masih_segar(lama):
            e = dict(lama)
            e.update({"instance": inst, "url": a["url"], "nama": a["nama"],
                      "pelajaran": a["pelajaran"], "dari_cache": True})
            hasil.append(e)
            tulis_hasil(hasil)
            cat(f"[{i}/{len(items)}] {inst}: dilewati (cache masih segar).")
            gagal_berturut = 0
            continue
        e, bekerja = proses_satu(a, i, len(items))
        hasil.append(e)
        cache[inst] = dict(e)
        simpan_json(CACHE, cache)
        tulis_hasil(hasil)
        if e.get("kendala") and "frame" in e["kendala"]:
            gagal_berturut += 1
        else:
            gagal_berturut = 0
        if gagal_berturut >= 3:
            cat("HENTI: 3 aktivitas berturut-turut gagal memuat frame. "
                "Kemungkinan sesi LMS habis atau launch dibatasi. "
                "Silakan login ulang di browser lalu jalankan dengan --paksa.")
            m.tampilkan_popup("Hermes menemui kendala",
                              "Frame LTI gagal 3x berturut. Perlu login ulang.")
            break
    perlu = [e for e in hasil if e.get("perlu")]
    kendala = [e for e in hasil if e.get("kendala")]
    cat("SELESAI:", len(hasil), "aktivitas |", len(perlu), "perlu ditindaklanjuti |",
        len(kendala), "kendala | hasil:", HASIL.name)


if __name__ == "__main__":
    jalankan()
