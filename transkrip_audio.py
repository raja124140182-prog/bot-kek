"""Transkrip file MP3 aktivitas Pikirkan memakai faster-whisper lokal (gratis).

Dipanggil oleh hermes-agent.py lewat Python 3.12:
    py -3.12 transkrip_audio.py <folder_audio> <file_json>
"""
import glob
import json
import os
import sys

from faster_whisper import WhisperModel


def main():
    if len(sys.argv) < 3:
        print("Pemakaian: transkrip_audio.py <folder_audio> <file_json>")
        return
    folder, keluar = sys.argv[1], sys.argv[2]
    hasil = {}
    if os.path.exists(keluar):
        try:
            with open(keluar, encoding="utf-8") as fh:
                hasil = json.load(fh)
        except Exception:
            hasil = {}

    berkas = sorted(glob.glob(os.path.join(folder, "*.mp3")))
    belum = [b for b in berkas if os.path.basename(b) not in hasil]
    if not belum:
        print("Semua audio sudah ditranskrip.")
        return

    print(f"Memuat model whisper... ({len(belum)} audio baru)", flush=True)
    model = WhisperModel("base", device="cpu", compute_type="int8")
    for path in belum:
        nama = os.path.basename(path)
        try:
            segs, info = model.transcribe(path, language="id", beam_size=5)
            teks = " ".join(s.text.strip() for s in segs).strip()
            hasil[nama] = teks
            print(f"{nama} => {teks}", flush=True)
        except Exception as e:
            print(f"{nama} GAGAL: {e}", flush=True)

    os.makedirs(os.path.dirname(keluar) or ".", exist_ok=True)
    with open(keluar, "w", encoding="utf-8") as fh:
        json.dump(hasil, fh, ensure_ascii=False, indent=2)
    print("Tersimpan:", keluar)


if __name__ == "__main__":
    main()
