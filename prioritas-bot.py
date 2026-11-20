"""Pemilih prioritas bot. Hanya satu tahap yang boleh memakai browser.

Contoh:
    py -3.15 prioritas-bot.py --status
    py -3.15 prioritas-bot.py --pilih rating --paksa
    py -3.15 prioritas-bot.py --pilih modul --modul="Manajemen Diri"
    py -3.15 prioritas-bot.py --pilih penilaian
    py -3.15 prioritas-bot.py --pilih penuh
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

FOLDER = Path(__file__).resolve().parent
STATUS = FOLDER / "status-prioritas.json"

TAHAP = {
    "rating": {
        "label": "Berkolaborasi: pindai + perbaiki rating ke 5/5",
        "script": "perbaiki-rating.py",
        "hasil": "hasil-scan-rating.json",
    },
    "modul": {
        "label": "Modul reguler: Pra-Kelas / Di Kelas / Pasca Kelas",
        "script": "scan-modul.py",
        "hasil": "hasil-scan-modul.json",
    },
    "penilaian": {
        "label": "Modul Penilaian: audit + kuis (ambang 90)",
        "script": "perbaiki-penilaian.py",
        "hasil": "modul-penilaian.txt",
    },
    "penuh": {
        "label": "Bot mode penuh (semua modul)",
        "script": "hermes-agent.py",
        "hasil": None,
    },
}


def muat_json(path, bawaan):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return bawaan


def hitung(nama):
    info = TAHAP[nama]
    if not info["hasil"]:
        return {"perlu": "-", "entri": "-", "catatan": " Jalankan manual lewat toggle-bot.ps1"}
    path = FOLDER / info["hasil"]
    if not path.exists():
        return {"perlu": "-", "entri": "-", "catatan": " belum pernah dijalankan"}
    if path.suffix == ".json":
        dat = muat_json(path, {})
        entri = dat.get("entri", []) if isinstance(dat, dict) else []
        perlu = sum(1 for e in entri if e.get("perlu"))
        return {"perlu": perlu, "entri": len(entri), "catatan": ""}
    isi = path.read_text(encoding="utf-8", errors="replace")
    perlu = sum(1 for baris in isi.splitlines() if "belum" in baris.lower())
    return {"perlu": perlu, "entri": len(isi.splitlines()), "catatan": ""}


def status():
    keluar = {"waktu": datetime.now().isoformat(timespec="seconds"), "tahap": {}}
    for nama, info in TAHAP.items():
        h = hitung(nama)
        keluar["tahap"][nama] = {"label": info["label"], **h}
    STATUS.write_text(json.dumps(keluar, ensure_ascii=False, indent=1), encoding="utf-8")
    print("URUTAN PRIORITAS:")
    for i, (nama, h) in enumerate(keluar["tahap"].items(), 1):
        print(f" {i}. {nama:10s} perlu={h['perlu']!s:4s} entri={h['entri']!s:4s} "
              f"- {h['label']}{h['catatan']}")
    return keluar


def main():
    ap = argparse.ArgumentParser(description="Pemilih prioritas bot Hermes")
    ap.add_argument("--status", action="store_true", help="tampilkan progres tiap tahap")
    ap.add_argument("--pilih", choices=list(TAHAP), help="jalankan satu tahap")
    ap.add_argument("--paksa", action="store_true", help="abaikan urutan prioritas")
    ap.add_argument("--modul", help="filter nama modul untuk tahap modul")
    ap.add_argument("--uji", action="store_true", help="hanya sebagian kecil untuk uji")
    args = ap.parse_args()

    keadaan = status()
    if args.status or not args.pilih:
        return

    if not args.paksa:
        rating = keadaan["tahap"]["rating"]["perlu"]
        modul = keadaan["tahap"]["modul"]["perlu"]
        if args.pilih in ("penilaian", "penuh") and rating not in (0, "-"):
            print(f"DITUNDA: rating masih {rating} perlu. Selesaikan dulu "
                  f"'rating' atau gunakan --paksa.")
            return
        if args.pilih == "penuh" and modul not in (0, "-"):
            print(f"DITUNDA: modul reguler masih {modul} perlu. "
                  f"Gunakan --paksa untuk tetap melanjutkan.")
            return

    perintah = [sys.executable, "-u", str(FOLDER / TAHAP[args.pilih]["script"])]
    if args.paksa:
        perintah.append("--paksa")
    if args.modul:
        perintah.append("--modul=" + args.modul)
    if args.uji:
        perintah.append("--uji")
    if args.pilih == "penuh":
        print("Mode penuh sebaiknya dijalankan lewat toggle-bot.ps1.")
        return
    print("MENJALANKAN:", " ".join(perintah), flush=True)
    subprocess.run(perintah, cwd=str(FOLDER), check=False)


if __name__ == "__main__":
    main()
