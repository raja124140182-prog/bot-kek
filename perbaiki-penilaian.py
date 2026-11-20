"""Kerjakan semua kuis/penilaian Wadhwani (termasuk 'Modul Penilaian - ...').

Jalankan:
    py -3.15 -u perbaiki-penilaian.py

Modul Penilaian sering tidak tercantum di daftar `modul` konfigurasi, jadi
script ini mengambil daftar kuis langsung dari API kursus.
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
LOG = FOLDER / "log-penilaian.txt"


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


def semua_kuis():
    dat = m._data_konten_kursus(page, paksa=True)
    mods = dat.get("data", {}).get("contents", {}).get("modules") or []
    byid = {str(x.get("sectionid")): x for x in mods}
    basis = re.sub(r"(/courses/[^/]+).*", r"\1", page.url)

    def rantai(sid, kedalaman=0):
        x = byid.get(str(sid))
        if not x or kedalaman > 8:
            return []
        return rantai(x.get("perent"), kedalaman + 1) + [str(x.get("sectionid"))]

    hasil = []
    for induk in mods:
        if str(induk.get("perent")) != "0":
            continue
        for les in mods:
            if str(les.get("perent")) != str(induk.get("sectionid")):
                continue
            for sub in mods:
                if str(sub.get("perent")) != str(les.get("sectionid")):
                    continue
                for a in sub.get("modules") or []:
                    if str(a.get("modtype") or "") != "quiz":
                        continue
                    hasil.append({
                        "instance": str(a.get("instance") or ""),
                        "nama": str(a.get("name") or ""),
                        "status": str(a.get("userStatus") or ""),
                        "modul": str(induk.get("name") or ""),
                        "pelajaran": str(les.get("name") or ""),
                        "url": f"{basis}/course-lesson/{les['sectionid']}/{a['instance']}",
                    })
            # Quiz bisa langsung di bawah lesson tanpa grup 'sub'.
            for a in les.get("modules") or []:
                if str(a.get("modtype") or "") != "quiz":
                    continue
                hasil.append({
                    "instance": str(a.get("instance") or ""),
                    "nama": str(a.get("name") or ""),
                    "status": str(a.get("userStatus") or ""),
                    "modul": str(induk.get("name") or ""),
                    "pelajaran": str(les.get("name") or ""),
                    "url": f"{basis}/course-lesson/{les['sectionid']}/{a['instance']}",
                })
    # Buang duplikat instance.
    unik, terlihat = [], set()
    for q in hasil:
        if q["instance"] and q["instance"] not in terlihat:
            unik.append(q)
            terlihat.add(q["instance"])
    return unik


def jalankan():
    daftar = semua_kuis()
    cat("TOTAL KUIS/PENILAIAN:", len(daftar))
    for q in daftar:
        cat(f"  {q['instance']} | {q['status']} | {q['modul']} | {q['nama']}")
    sasaran = [q for q in daftar if not m._selesai_aktivitas(q["status"])]
    cat("Perlu dikerjakan:", len(sasaran))
    for siklus in range(1, 4):
        cat(f"=== SIKLUS {siklus} ===")
        tersisa = []
        for i, q in enumerate(sasaran, 1):
            try:
                halaman = m._pastikan_browser()
                halaman.goto(q["url"], wait_until="domcontentloaded", timeout=45000)
                time.sleep(2)
                cat(f"[{i}/{len(sasaran)}] {q['instance']} {q['nama']}")
                hasil = m._selesaikan_quiz(halaman)
                cat("  ", (hasil or "tidak ada soal attempt yang dikerjakan")[:500])
                st = m._status_aktivitas_api(m._pastikan_browser(), q["instance"])
                cat(f"  status API: {st}")
                if not m._selesai_aktivitas(st):
                    tersisa.append(q)
            except Exception as e:
                cat(f"  ERROR {type(e).__name__}: {e}")
                tersisa.append(q)
        if not tersisa:
            cat("SEMUA KUIS/PENILAIAN SELESAI.")
            return
        cat("Masih perlu perbaikan:", len(tersisa))
        sasaran = tersisa
    cat("SISA SETELAH 3 SIKLUS:", len(sasaran))
    for q in sasaran:
        cat("  ", q["instance"], q["nama"])


if __name__ == "__main__":
    jalankan()
