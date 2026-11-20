"""Kunci satu proses browser: cegah dua bot memakai BrowserProfile bersamaan."""
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

FOLDER = Path(__file__).resolve().parent
KUNCI = FOLDER / "bot.lock"


def proses_hidup(pid):
    try:
        pid = int(pid)
    except Exception:
        return False
    try:
        keluar = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True, text=True, timeout=8).stdout
        return str(pid) in keluar
    except Exception:
        return False


def ambil(nama):
    """Return (boleh_jalan, pemilik)."""
    if KUNCI.exists():
        try:
            isi = json.loads(KUNCI.read_text(encoding="utf-8"))
            if proses_hidup(isi.get("pid")):
                return False, isi
        except Exception:
            pass
        KUNCI.unlink(missing_ok=True)
    KUNCI.write_text(json.dumps({
        "nama": nama, "pid": os.getpid(),
        "waktu": datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return True, None


def lepas():
    try:
        isi = json.loads(KUNCI.read_text(encoding="utf-8"))
        if isi.get("pid") == os.getpid():
            KUNCI.unlink(missing_ok=True)
    except Exception:
        pass


def pemilik():
    try:
        return json.loads(KUNCI.read_text(encoding="utf-8"))
    except Exception:
        return None
