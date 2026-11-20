"""Scan modul reguler (Pra-Kelas / Di Kelas / Pasca Kelas) satu per satu.

Tidak mengerjakan apa pun secara default — hanya membaca status dari API dan
menyimpan daftar yang benar-benar belum selesai.

Jalankan:
    py -3.15 -u scan-modul.py
    py -3.15 -u scan-modul.py --modul=Manajemen Diri
    py -3.15 -u scan-modul.py --paksa
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
LOG = FOLDER / "log-modul-scan.txt"
HASIL = FOLDER / "hasil-scan-modul.json"
CACHE = FOLDER / "modul-scan.json"


def cat(*args):
    teks = datetime.now().strftime("%H:%M:%S") + " " + " ".join(str(x) for x in args)
    print(teks, flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(teks + "\n")
    except Exception:
        pass


def muat(path, bawaan):
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, (dict, list)) else bawaan
    except Exception:
        return bawaan


def simpan(path, dat):
    try:
        path.write_text(json.dumps(dat, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        cat("Gagal simpan", path.name, e)


def segar(entri, menit=60):
    if not entri or entri.get("perlu"):
        return False
    try:
        return datetime.now() - datetime.fromisoformat(
            entri["waktu"]) < timedelta(minutes=menit)
    except Exception:
        return False


def dilewati(a):
    nama = str(a.get("nama") or "")
    url = str(a.get("url") or "")
    if re.match(r"^Berkolaborasi\b", nama, re.I) or a.get("modtype") == "lti":
        return "Berkolaborasi (ditangani script rating)"
    if re.search(r"mod/feedback|Umpan Balik Pelatihan", nama + " " + url, re.I):
        return "feedback / Umpan Balik Pelatihan"
    if "174072" in url:
        return "174072 (dicatat, dilewati)"
    if re.search(r"Modul Penilaian|Penilaian Sum", nama, re.I):
        return "Penilaian (ditangani script penilaian)"
    if re.search(r"unggah|upload", nama, re.I):
        return "unggah video/file"
    return ""


sp = importlib.util.spec_from_file_location("hb", SKRIP_UTAMA)
m = importlib.util.module_from_spec(sp)
sp.loader.exec_module(m)
cfg = json.loads(KONFIGURASI.read_text(encoding="utf-8"))
m.alat_buka_browser({"url": cfg["url_kursus"]})
halaman = m._pastikan_browser()


def jalankan():
    paksa = "--paksa" in sys.argv
    pilih = next((x.split("=", 1)[1] for x in sys.argv
                  if x.startswith("--modul=")), None)
    uji = "--uji" in sys.argv
    cache = {} if paksa else muat(CACHE, {})
    modul = cfg["modul"]
    if pilih:
        modul = [x for x in modul if pilih.lower() in str(x).lower()]
        if not modul:
            cat("Modul tidak ditemukan:", pilih)
            return
    if uji:
        modul = modul[:1]

    cat("=== SCAN MODUL REGULER ===", "modul:", len(modul), "| paksa:", paksa)
    hasil, dilewati_count = [], 0
    for nama_modul in modul:
        daftar = []
        try:
            daftar = m._daftar_aktivitas_modul(halaman, nama_modul)
        except Exception as e:
            cat("Gagal daftar", nama_modul, type(e).__name__, e)
        for a in daftar:
            inst = a["instance"]
            alasan = dilewati(a)
            if alasan:
                dilewati_count += 1
                continue
            lama = None if paksa else cache.get(inst)
            if segar(lama):
                e = dict(lama)
                e.update({"instance": inst, "url": a["url"], "nama": a["nama"],
                          "modul": nama_modul, "dari_cache": True})
                hasil.append(e)
                simpan(HASIL, {"waktu": e["waktu"], "entri": hasil})
                continue
            m.status_aktif(f"Memindai {nama_modul}: {a['nama'][:45]}")
            status = m._status_aktivitas_api(halaman, inst)
            sudah = str(status or "").lower().startswith("completed")
            e = {
                "instance": inst, "url": a["url"], "nama": a["nama"],
                "modul": nama_modul, "pelajaran": a.get("pelajaran", ""),
                "modtype": a.get("modtype", ""),
                "waktu": datetime.now().isoformat(timespec="seconds"),
                "status": status, "perlu": not sudah,
                "alasan": "" if sudah else "belum completed menurut API",
                "dari_cache": False,
            }
            hasil.append(e)
            cache[inst] = dict(e)
            simpan(CACHE, cache)
            simpan(HASIL, {"waktu": e["waktu"], "entri": hasil})
            cat(f"{nama_modul} | {inst} | {a['nama'][:42]} | {status} | "
                f"perlu={e['perlu']}")
            time.sleep(0.2)
    belum = [e for e in hasil if e["perlu"]]
    cat("SELESAI:", len(hasil), "aktivitas reguler |", len(belum),
        "belum selesai |", dilewati_count, "dilewati | hasil:", HASIL.name)
    for e in belum[:20]:
        cat("  PERLU:", e["modul"], "|", e["instance"], "|", e["nama"][:50])


if __name__ == "__main__":
    try:
        from kunci_bot import ambil as ambil_kunci, lepas as lepas_kunci
    except ImportError:
        ambil_kunci = lepas_kunci = None
    if ambil_kunci:
        boleh, pemilik = ambil_kunci("modul")
        if not boleh:
            cat("DILEWATI: bot lain sedang memakai browser:",
                pemilik.get("nama"), "PID", pemilik.get("pid"))
            raise SystemExit(0)
    try:
        jalankan()
    finally:
        if lepas_kunci:
            lepas_kunci()
