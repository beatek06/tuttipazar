"""Tarayıcı eklentisinin kaydettiği dosyaları (İndirilenler/pazar-veri/*.json) tarayici.db'ye aktarır.

Kullanım:  python ice_aktar.py
Aynı dosya iki kez aktarılmaz. Ham dosyaların bir kopyası ham/ klasörüne alınır.
"""
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

KLASOR = Path(__file__).parent
DB = KLASOR / "tarayici.db"   # sadece bu bilgisayarda; GitHub'a gönderilmez
GELEN = Path.home() / "Downloads" / "pazar-veri"
HAM = KLASOR / "ham"

sys.stdout.reconfigure(encoding="utf-8")

FIYAT_RE = re.compile(r"(?:CHF|Fr\.?|SFr\.?)\s*([\d'’.,]+)|([\d'’.,]+)\s*(?:CHF|Fr\.|\.–|\.-)", re.I)
DURUM_RE = {
    "satildi": re.compile(r"\b(verkauft|sold|vendu|venduto)\b", re.I),
    "rezerve": re.compile(r"\b(reserviert|ausstehend|pending|réservé|riservato)\b", re.I),
}
TEKLIF_RE = re.compile(r"(\d+)\s*(?:Gebote?|bids?|offres?|offerte)", re.I)


def fiyat_bul(metin):
    m = FIYAT_RE.search(metin or "")
    if not m:
        return None
    ham = (m.group(1) or m.group(2)).replace("'", "").replace("’", "").replace(",", ".")
    ham = ham.rstrip(".")
    try:
        return float(ham)
    except ValueError:
        return None


RICARDO_SAYI = re.compile(r"^[\d'’]+\.\d{2}$")
RICARDO_ATLA = {"boost", "neuheit", "|", "sofort kaufen", "oder preis vorschlagen", "beliebt"}
# Facebook kartının başındaki durum etiketleri (başlık değil): alıcı bulundu / satıldı
FB_DURUM = {"reserviert": "rezerve", "ausstehend": "rezerve", "pending": "rezerve",
            "verkauft": "satildi", "sold": "satildi"}
KONUM_RE = re.compile(r",\s*[A-Z]{2}$")


def sayi(s):
    return float(s.replace("'", "").replace("’", ""))


def ricardo_coz(metin):
    """Ricardo kartı: başlık, (açık artırma fiyatı + teklif), (hemen al fiyatı), bitiş."""
    satirlar = [s.strip() for s in metin.split("\n") if s.strip()]
    baslik = next((s for s in satirlar if s.lower() not in RICARDO_ATLA and not RICARDO_SAYI.match(s)), None)
    hemen = teklif_fiyat = None
    for i, s in enumerate(satirlar):
        if not RICARDO_SAYI.match(s):
            continue
        sonraki = satirlar[i + 1].lower() if i + 1 < len(satirlar) else ""
        if sonraki.startswith("sofort kaufen"):
            hemen = sayi(s)
        elif "gebot" in sonraki:
            teklif_fiyat = sayi(s)
    # "Beliebt": Ricardo'nun çok ilgi gören ilanlara koyduğu rozet (talep sinyali)
    rozet = "beliebt" if any(s.lower() == "beliebt" for s in satirlar) else None
    return dict(baslik=baslik, fiyat=hemen if hemen is not None else teklif_fiyat,
                fiyat_hemen=hemen, fiyat_teklif=teklif_fiyat, konum=None, rozet=rozet)


def facebook_coz(metin):
    """Facebook kartı: 1. satır fiyat (ör. '20 CHF', 'Kostenlos'), sonra başlık, en sonda 'Şehir, ZH'."""
    satirlar = [s.strip() for s in metin.split("\n") if s.strip()]
    rozet = next((FB_DURUM[s.lower()] for s in satirlar if s.lower() in FB_DURUM), None)
    satirlar = [s for s in satirlar if s.lower() not in FB_DURUM and s not in ("·", "•")]
    fiyat = None
    fiyat_satiri = [s for s in satirlar if FIYAT_RE.search(s) or s.lower() in ("kostenlos", "gratis", "free")]
    if fiyat_satiri:
        fiyat = 0.0 if fiyat_satiri[0].lower() in ("kostenlos", "gratis", "free") else fiyat_bul(fiyat_satiri[0])
    konum = next((s for s in reversed(satirlar) if KONUM_RE.search(s)), None)
    baslik = next((s for s in satirlar if s not in fiyat_satiri and s != konum), None)
    return dict(baslik=baslik, fiyat=fiyat, fiyat_hemen=None, fiyat_teklif=None, konum=konum, rozet=rozet)


def kart_coz(platform, metin):
    if platform == "ricardo":
        return ricardo_coz(metin)
    if platform == "facebook":
        return facebook_coz(metin)
    satirlar = [s for s in metin.split("\n") if s.strip()]
    return dict(baslik=satirlar[0] if satirlar else None, fiyat=fiyat_bul(metin),
                fiyat_hemen=None, fiyat_teklif=None, konum=None, rozet=None)


def db_ac():
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS tarayici_kayit (
        dosya TEXT PRIMARY KEY, platform TEXT, sayfa_url TEXT, sayfa_basligi TEXT,
        zaman TEXT, ilan_sayisi INTEGER);
    CREATE TABLE IF NOT EXISTS tarayici_ilan (
        dosya TEXT, platform TEXT, id TEXT, url TEXT, metin TEXT, fiyat REAL,
        durum TEXT, teklif INTEGER, sayfa_url TEXT, zaman TEXT,
        PRIMARY KEY (dosya, platform, id));
    """)
    mevcut = [r[1] for r in con.execute("PRAGMA table_info(tarayici_ilan)")]
    for kolon, tip in [("sira", "INTEGER"),  # ekrandaki sıra (0 = en üst)
                       ("baslik", "TEXT"), ("konum", "TEXT"),
                       ("fiyat_hemen", "REAL"), ("fiyat_teklif", "REAL"),
                       ("rozet", "TEXT")]:  # FB: rezerve/satildi, Ricardo: beliebt
        if kolon not in mevcut:
            con.execute(f"ALTER TABLE tarayici_ilan ADD COLUMN {kolon} {tip}")
    return con


def main():
    if not GELEN.exists():
        print(f"Klasör yok: {GELEN}  (eklentiyle henüz kayıt yapılmamış)")
        return
    HAM.mkdir(exist_ok=True)
    con = db_ac()
    toplam = 0
    for yol in sorted(GELEN.glob("*.json")):
        if con.execute("SELECT 1 FROM tarayici_kayit WHERE dosya=?", (yol.name,)).fetchone():
            continue
        v = json.loads(yol.read_text(encoding="utf-8"))
        platform = yol.name.split("_")[0]
        for sira, i in enumerate(v.get("ilanlar", [])):
            metin = i.get("metin") or ""
            durum = next((d for d, r in DURUM_RE.items() if r.search(metin)), None)
            t = TEKLIF_RE.search(metin)
            k = kart_coz(i["platform"], metin)
            con.execute("""INSERT OR REPLACE INTO tarayici_ilan
                (dosya, platform, id, url, metin, fiyat, durum, teklif, sayfa_url, zaman, sira,
                 baslik, konum, fiyat_hemen, fiyat_teklif, rozet)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (yol.name, i["platform"], i["id"], i["url"], metin, k["fiyat"],
                         durum, int(t.group(1)) if t else None, v["sayfa_url"], v["zaman"], sira,
                         k["baslik"], k["konum"], k["fiyat_hemen"], k["fiyat_teklif"], k["rozet"]))
        con.execute("INSERT INTO tarayici_kayit VALUES (?,?,?,?,?,?)",
                    (yol.name, platform, v["sayfa_url"], v.get("sayfa_basligi"), v["zaman"],
                     len(v.get("ilanlar", []))))
        con.commit()
        shutil.copy2(yol, HAM / yol.name)
        toplam += 1
        print(f"  {yol.name}: {len(v.get('ilanlar', []))} ilan  ({v['sayfa_url'][:80]})")
    print(f"{toplam} yeni dosya aktarıldı.")
    con.close()


if __name__ == "__main__":
    main()
