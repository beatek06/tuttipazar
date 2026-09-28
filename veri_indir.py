"""GitHub Actions'ın ürettiği en güncel Tutti veritabanını indirir (veri.db).

Kullanım:  python veri_indir.py
Rapordan önce çalıştır. FB/Ricardo verileri (tarayici.db) bundan etkilenmez.
"""
import gzip
import shutil
import sys
import urllib.request
from pathlib import Path

KLASOR = Path(__file__).parent
URL = "https://github.com/beatek06/tuttipazar/releases/download/veri/veri.db.gz"

sys.stdout.reconfigure(encoding="utf-8")


def main():
    gecici = KLASOR / "veri.db.indiriliyor"
    with urllib.request.urlopen(URL, timeout=120) as cevap, gzip.open(cevap) as gz, open(gecici, "wb") as f:
        shutil.copyfileobj(gz, f)
    gecici.replace(KLASOR / "veri.db")
    print(f"veri.db güncellendi ({(KLASOR / 'veri.db').stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
