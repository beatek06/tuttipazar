"""Tutti takip: günde 1-2 kez çalıştır.

1) Kelime modu  (urunler.txt):    kelimenin TÜM ilanları taranır, kaybolanlar tespit edilir.
2) Kategori modu (kategoriler.txt): kategoriye YENİ gelen ilanların hepsi kaydedilir,
   eski kayıtlardan bir örneklem "hâlâ yayında mı?" diye kontrol edilir.

Kullanım:  python tutti_takip.py            (ikisi birden)
           python tutti_takip.py kelime     (sadece kelime modu)
           python tutti_takip.py kategori   (sadece kategori modu)
Veriler:   veri.db (SQLite), log: takip.log
"""
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import quote, urljoin

import requests
import urllib3

from capraz import pencere_siniri

KLASOR = Path(__file__).parent
DB = KLASOR / "veri.db"
URUNLER = KLASOR / "urunler.txt"
KATEGORILER = KLASOR / "kategoriler.txt"
KATEGORI_AGACI = KLASOR / "tutti_kategoriler.json"

MAX_SAYFA = 34            # kelime başına en fazla ~1000 ilan
KAT_MAX_SAYFA = 80        # kategori başına bir taramada en fazla ~2400 yeni ilan
KAT_KONTROL = 40          # kategori başına her taramada kontrol edilecek eski ilan sayısı
BEKLEME = 1.5             # istekler arası saniye (siteyi yormamak için)
H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept-Language": "de-CH,de;q=0.9",
}

sys.stdout.reconfigure(encoding="utf-8")
oturum = requests.Session()
oturum.headers.update(H)
HAM_HTTP = urllib3.PoolManager()
ZURIH = ZoneInfo("Europe/Zurich")


def zurih_simdi():
    """Yerel bilgisayarda da GitHub (UTC) sunucusunda da aynı saat: Zürih saati, saat dilimi eki olmadan."""
    return datetime.now(ZURIH).replace(tzinfo=None, microsecond=0)


def db_ac():
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS ilan (
        id TEXT, kelime TEXT, baslik TEXT, fiyat REAL, kanton TEXT,
        satici TEXT, pro INTEGER, yayin TEXT,
        ilk_gorulme TEXT, son_gorulme TEXT, kayboldu TEXT,
        PRIMARY KEY (id, kelime));
    CREATE TABLE IF NOT EXISTS tarama (
        tarih TEXT, kelime TEXT, toplam INTEGER, taranan INTEGER, tam INTEGER,
        PRIMARY KEY (tarih, kelime));
    CREATE TABLE IF NOT EXISTS kat_ilan (
        id INTEGER PRIMARY KEY, kategori TEXT, baslik TEXT, fiyat REAL, kanton TEXT,
        satici TEXT, pro INTEGER, yayin TEXT, yeni INTEGER,
        ilk_gorulme TEXT, son_kontrol TEXT, kontrol_sayisi INTEGER DEFAULT 0, kayboldu TEXT);
    CREATE TABLE IF NOT EXISTS kat_tarama (
        zaman TEXT, kategori TEXT, toplam INTEGER, yeni_kayit INTEGER, kontrol INTEGER,
        kaybolan INTEGER, PRIMARY KEY (zaman, kategori));
    CREATE TABLE IF NOT EXISTS kat_baz (
        kategori TEXT PRIMARY KEY, baz_id INTEGER, son_zaman TEXT);
    CREATE TABLE IF NOT EXISTS kat_gorunum (
        zaman TEXT, kategori TEXT, sira INTEGER, id INTEGER,
        PRIMARY KEY (zaman, kategori, sira));
    """)
    return con


# ---------------------------------------------------------------- ortak

def next_data(html):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    return json.loads(m.group(1)) if m else None


def getir(url):
    """Tutti bazı yönlendirmelerde 'ö' harfini ham latin-1 gönderiyor; requests buna takılıyor.
    O durumda yönlendirme adresi urllib3 ile okunup düzgün kodlanarak devam edilir."""
    for _ in range(5):
        try:
            return oturum.get(url, timeout=30)
        except UnicodeDecodeError:
            r0 = HAM_HTTP.request("GET", url, headers=H, redirect=False, timeout=30)
            url = urljoin(url, quote(r0.headers["location"], safe=":/?=&%#"))
    raise requests.RequestException(f"yönlendirme çözülemedi: {url}")


def sayfa_getir(url, deneme=3):
    for i in range(deneme):
        try:
            r = getir(url)
            r.raise_for_status()
            break
        except requests.RequestException:
            if i == deneme - 1:
                raise
            time.sleep(10 * (i + 1))
    d = next_data(r.text)
    ilanlar = d["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["listings"]
    return r.url.split("?")[0], ilanlar


def fiyat_coz(metin):
    if not metin:
        return None
    rakam = re.sub(r"[^\d.]", "", metin.replace("'", "")).rstrip(".")
    try:
        return float(rakam) if rakam else None
    except ValueError:
        return None


def ilan_hala_var_mi(ilan_id):
    r = getir(f"https://www.tutti.ch/de/vi/{ilan_id}")
    if r.status_code in (404, 410):
        return False
    return f'"listingID":"{ilan_id}"' in r.text


def ilan_alanlari(n):
    satici = n.get("sellerInfo") or {}
    yer = n.get("postcodeInformation") or {}
    return dict(
        id=n["listingID"], baslik=n["localization"]["title"],
        fiyat=fiyat_coz(n.get("formattedPrice")),
        kanton=(yer.get("canton") or {}).get("shortName"),
        satici=satici.get("alias"), pro=1 if satici.get("subscriptionInfo") else 0,
        yayin=n["timestamp"][:19],
    )


# ---------------------------------------------------------------- kelime modu

def urunleri_oku():
    liste = []
    for satir in URUNLER.read_text(encoding="utf-8").splitlines():
        satir = satir.strip()
        if not satir or satir.startswith("#"):
            continue
        kelime, _, filtre = satir.partition("|")
        filtreler = [f.strip().lower() for f in filtre.split(",") if f.strip()]
        liste.append((kelime.strip(), filtreler))
    return liste


def kelime_tara(con, kelime, filtreler, bugun):
    url, veri = sayfa_getir(f"https://www.tutti.ch/de/q/suche?query={quote(kelime)}")
    toplam = veri.get("totalCount", 0)
    kenarlar = list(veri["edges"])
    sayfa = 1
    while len(kenarlar) < toplam and sayfa < MAX_SAYFA:
        sayfa += 1
        time.sleep(BEKLEME)
        _, v = sayfa_getir(f"{url}?page={sayfa}")
        if not v["edges"]:
            break
        kenarlar += v["edges"]
    tam = len(kenarlar) >= toplam

    gorulen, en_eski = set(), None
    for e in kenarlar:
        a = ilan_alanlari(e["node"])
        if filtreler and not any(f in a["baslik"].lower() for f in filtreler):
            continue
        en_eski = min(en_eski or a["yayin"], a["yayin"])
        gorulen.add(a["id"])
        con.execute("""
            INSERT INTO ilan VALUES (?,?,?,?,?,?,?,?,?,?,NULL)
            ON CONFLICT(id, kelime) DO UPDATE SET
              son_gorulme=excluded.son_gorulme, fiyat=excluded.fiyat, kayboldu=NULL""",
            (a["id"], kelime, a["baslik"], a["fiyat"], a["kanton"], a["satici"],
             a["pro"], a["yayin"], bugun, bugun))

    con.execute("INSERT OR REPLACE INTO tarama VALUES (?,?,?,?,?)",
                (bugun, kelime, toplam, len(kenarlar), int(tam)))

    # Bugün görünmeyen ilanlar: tarama tamsa hepsi, değilse sadece taranan aralıktakiler
    eksikler = con.execute("""
        SELECT id, yayin FROM ilan
        WHERE kelime=? AND kayboldu IS NULL AND son_gorulme < ?""", (kelime, bugun)).fetchall()
    kaybolan = 0
    for ilan_id, yayin in eksikler:
        if not tam and en_eski and yayin < en_eski:
            continue  # tarama penceresinin dışında, bilinmiyor
        time.sleep(BEKLEME)
        if not ilan_hala_var_mi(ilan_id):
            con.execute("UPDATE ilan SET kayboldu=? WHERE id=? AND kelime=?", (bugun, ilan_id, kelime))
            kaybolan += 1
    con.commit()
    return toplam, len(gorulen), tam, kaybolan


def kelime_modu(con):
    bugun = zurih_simdi().date().isoformat()
    print("-- Kelime modu --")
    for kelime, filtreler in urunleri_oku():
        try:
            toplam, eslesen, tam, kaybolan = kelime_tara(con, kelime, filtreler, bugun)
            not_ = "" if tam else "  (kısmi tarama: sadece en yeni ilanlar)"
            print(f"  {kelime:22} toplam {toplam:5}  eşleşen {eslesen:4}  bugün kaybolan {kaybolan:3}{not_}")
        except Exception as hata:
            print(f"  {kelime:22} HATA: {hata}")
        time.sleep(BEKLEME)


# ---------------------------------------------------------------- kategori modu

def kategorileri_oku():
    agac = {k["id"]: k for k in json.loads(KATEGORI_AGACI.read_text(encoding="utf-8"))}
    liste = []
    for satir in KATEGORILER.read_text(encoding="utf-8").splitlines():
        kat = satir.split("#")[0].strip()
        if kat:
            if kat not in agac:
                print(f"  bilinmeyen kategori: {kat}")
                continue
            liste.append(agac[kat])
    return liste


def kategori_tara(con, kat, simdi):
    kid = kat["id"]
    baz = con.execute("SELECT baz_id, son_zaman FROM kat_baz WHERE kategori=?", (kid,)).fetchone()
    ilk_tarama = baz is None
    son_zaman = baz[1] if baz else None

    # 1) Yeni ilanlar: en yeniden geriye, bir önceki taramaya ulaşana kadar
    url = f"https://www.tutti.ch/de/q/x/{kat['token']}"
    url, veri = sayfa_getir(url)
    toplam = veri.get("totalCount", 0)
    kenarlar, sayfa = list(veri["edges"]), 1
    sinir = KAT_MAX_SAYFA if not ilk_tarama else 10
    while sayfa < sinir and kenarlar:
        # En az 6 sayfa (~180 ilan): önceki taramayla örtüşsün diye (çapraz doğrulama için)
        if sayfa >= 6 and son_zaman and kenarlar[-1]["node"]["timestamp"][:19] < son_zaman:
            break
        sayfa += 1
        time.sleep(BEKLEME)
        _, v = sayfa_getir(f"{url}?page={sayfa}")
        if not v["edges"]:
            break
        kenarlar += v["edges"]

    ilanlar = [ilan_alanlari(e["node"]) for e in kenarlar]
    # Ekranda görünen sıra: Facebook/Ricardo'daki "kayıt karşılaştırma" yöntemini Tutti'de sınamak için
    con.executemany("INSERT OR IGNORE INTO kat_gorunum VALUES (?,?,?,?)",
                    [(simdi, kid, s, int(a["id"])) for s, a in enumerate(ilanlar)])
    if ilk_tarama:
        # Başlangıç çizgisi: bundan büyük ilan numaraları "gerçekten yeni" sayılır
        baz_id = max(int(a["id"]) for a in ilanlar)
        con.execute("INSERT INTO kat_baz VALUES (?,?,?)", (kid, baz_id, None))
    else:
        baz_id = baz[0]

    yeni_kayit = 0
    for a in ilanlar:
        c = con.execute("""INSERT OR IGNORE INTO kat_ilan
            (id, kategori, baslik, fiyat, kanton, satici, pro, yayin, yeni, ilk_gorulme)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (int(a["id"]), kid, a["baslik"], a["fiyat"], a["kanton"], a["satici"], a["pro"],
             a["yayin"], int(int(a["id"]) > baz_id), simdi))
        yeni_kayit += c.rowcount
    en_yeni = max((a["yayin"] for a in ilanlar), default=son_zaman)
    con.execute("UPDATE kat_baz SET son_zaman=? WHERE kategori=?", (en_yeni, kid))
    con.commit()

    # 2) Örneklem kontrolü: en az 1 saat önce görülmüş, en uzun süredir kontrol edilmemiş ilanlar
    #    (kısa eşik: birkaç saatte satılan hızlı ürünleri de yakalamak için)
    esik = (datetime.fromisoformat(simdi) - timedelta(hours=1)).isoformat(timespec="seconds")
    simdi_gorulen = {int(a["id"]) for a in ilanlar}  # şu an listede görünüyor = zaten yayında
    ornek = [i for (i,) in con.execute("""
        SELECT id FROM kat_ilan
        WHERE kategori=? AND kayboldu IS NULL AND ilk_gorulme <= ?
        ORDER BY yeni DESC, COALESCE(son_kontrol, '') ASC, RANDOM()
        LIMIT ?""", (kid, esik, KAT_KONTROL * 3)) if i not in simdi_gorulen][:KAT_KONTROL]
    # Pencere yönteminin "kayboldu" dediği ilanlar önce kontrol edilir -> yöntemin isabeti ölçülür
    onceki = con.execute("SELECT MAX(zaman) FROM kat_gorunum WHERE kategori=? AND zaman < ?",
                         (kid, simdi)).fetchone()[0]
    pencere_adaylari = []
    if onceki:
        a = [i for (i,) in con.execute(
            "SELECT id FROM kat_gorunum WHERE kategori=? AND zaman=? ORDER BY sira", (kid, onceki))]
        sinir = pencere_siniri(a, simdi_gorulen)
        pencere_adaylari = [i for i in a[:sinir + 1] if i not in simdi_gorulen][:KAT_KONTROL]
    adaylar = [(i,) for i in dict.fromkeys(pencere_adaylari + ornek)]
    kaybolan = 0
    for (ilan_id,) in adaylar:
        time.sleep(BEKLEME)
        try:
            var = ilan_hala_var_mi(ilan_id)
        except requests.RequestException:
            continue
        if var:
            con.execute("UPDATE kat_ilan SET son_kontrol=?, kontrol_sayisi=kontrol_sayisi+1 WHERE id=?",
                        (simdi, ilan_id))
        else:
            con.execute("UPDATE kat_ilan SET son_kontrol=?, kontrol_sayisi=kontrol_sayisi+1, kayboldu=? WHERE id=?",
                        (simdi, simdi, ilan_id))
            kaybolan += 1
    con.execute("INSERT OR REPLACE INTO kat_tarama VALUES (?,?,?,?,?,?)",
                (simdi, kid, toplam, yeni_kayit, len(adaylar), kaybolan))
    con.commit()
    return toplam, yeni_kayit, len(adaylar), kaybolan


def kategori_modu(con):
    simdi = zurih_simdi().isoformat()
    print("-- Kategori modu --")
    for kat in kategorileri_oku():
        try:
            toplam, yeni, kontrol, kaybolan = kategori_tara(con, kat, simdi)
            print(f"  {kat['ad']:28} toplam {toplam:6}  yeni kayıt {yeni:5}  kontrol {kontrol:4}  kaybolan {kaybolan:3}")
        except Exception as hata:
            print(f"  {kat['ad']:28} HATA: {hata}")
        time.sleep(BEKLEME)


def main():
    mod = sys.argv[1] if len(sys.argv) > 1 else "hepsi"
    con = db_ac()
    print(f"Tutti taraması başladı: {zurih_simdi():%Y-%m-%d %H:%M}")
    if mod in ("hepsi", "kelime"):
        kelime_modu(con)
    if mod in ("hepsi", "kategori"):
        kategori_modu(con)
    con.close()
    print(f"Bitti: {zurih_simdi():%Y-%m-%d %H:%M}")


if __name__ == "__main__":
    main()
