"""Rapor: Tutti takip verisi + Ricardo/Facebook elle girilen veriler -> rapor.xlsx

Kullanım:  python rapor.py
"""
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

import pandas as pd

KLASOR = Path(__file__).parent
DB = KLASOR / "veri.db"                # Tutti (GitHub Actions üretir, veri_indir.py ile gelir)
TARAYICI_DB = KLASOR / "tarayici.db"   # FB/Ricardo eklenti kayıtları (sadece bu bilgisayarda)
CIKTI = KLASOR / "rapor.xlsx"

SATIS_MAX_GUN = 21      # bu kadar günde kaybolan ilan "muhtemelen satıldı" sayılır
FIYAT_ALT, FIYAT_UST = 50, 100

sys.stdout.reconfigure(encoding="utf-8")


def tutti_ozet():
    con = sqlite3.connect(DB)
    ilan = pd.read_sql("SELECT * FROM ilan", con, parse_dates=["yayin", "ilk_gorulme", "son_gorulme", "kayboldu"])
    tarama = pd.read_sql("SELECT * FROM tarama", con, parse_dates=["tarih"])
    con.close()
    if ilan.empty:
        return pd.DataFrame(), ilan

    # Aynı satıcı aynı başlıkla yeniden ilan verdiyse, eski ilanın kaybolması satış değildir
    ilan["anahtar"] = ilan["satici"].fillna("") + "|" + ilan["baslik"].str.lower().str.strip()
    ilan = ilan.sort_values("yayin")
    ilan["yeniden_ilan"] = False
    for (_, _), g in ilan.groupby(["kelime", "anahtar"]):
        if len(g) > 1:
            ilan.loc[g.index[:-1], "yeniden_ilan"] = True

    ilan["omur_gun"] = (ilan["kayboldu"] - ilan["yayin"]).dt.days
    ilan["muhtemel_satis"] = (ilan["kayboldu"].notna() & ~ilan["yeniden_ilan"]
                              & (ilan["omur_gun"] <= SATIS_MAX_GUN))

    satirlar = []
    for kelime, g in ilan.groupby("kelime"):
        t = tarama[tarama["kelime"] == kelime]
        ilk, son = t["tarih"].min(), t["tarih"].max()
        gun = max((son - ilk).days, 1)
        aktif = g[g["kayboldu"].isna() & (g["son_gorulme"] == son)]
        yeni = g[g["yayin"] > ilk]
        satis = g[g["muhtemel_satis"]]
        fiyatli = aktif["fiyat"].dropna()
        satirlar.append({
            "ürün": kelime,
            "takip günü": gun,
            "aktif ilan": len(aktif),
            "yeni ilan / gün": round(len(yeni) / gun, 1),
            "muhtemel satış (toplam)": len(satis),
            "TAHMİNİ SATIŞ / AY": round(len(satis) / gun * 30),
            "satış hızı % (satış/aktif, ay)": round(100 * len(satis) / gun * 30 / max(len(aktif), 1)),
            "ort. satılma süresi (gün)": round(satis["omur_gun"].median(), 1) if len(satis) else None,
            "medyan fiyat (aktif)": fiyatli.median() if len(fiyatli) else None,
            "medyan fiyat (satılan)": satis["fiyat"].median() if len(satis) else None,
            f"% {FIYAT_ALT}-{FIYAT_UST} CHF": round(100 * fiyatli.between(FIYAT_ALT, FIYAT_UST).mean()) if len(fiyatli) else None,
            "pro satıcı %": round(100 * aktif["pro"].mean()) if len(aktif) else None,
            "pro satıcı sayısı": aktif.loc[aktif["pro"] == 1, "satici"].nunique(),
            "tarama tam mı": "evet" if t["tam"].iloc[-1] else "kısmi",
        })
    ozet = pd.DataFrame(satirlar).sort_values("TAHMİNİ SATIŞ / AY", ascending=False)
    return ozet, ilan


def csv_oku(ad):
    yol = KLASOR / "manuel" / ad
    try:
        return pd.read_csv(yol, sep=";", encoding="utf-8-sig")
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def ricardo_ozet():
    r = csv_oku("ricardo.csv")
    if r.empty:
        return r
    r["son_30_gun_degerlendirme"] = pd.to_numeric(r["son_30_gun_degerlendirme"], errors="coerce")
    o = r.groupby("urun").agg(
        satici_sayisi=("satici", "nunique"),
        degerlendirme_30_gun=("son_30_gun_degerlendirme", "sum"),
        medyan_fiyat=("fiyat_chf", "median"),
    ).reset_index()
    # Her alıcı değerlendirme bırakmaz: gerçek satış ≈ 1.3–2 x değerlendirme
    o["tahmini satış / ay (alt)"] = (o["degerlendirme_30_gun"] * 1.3).round()
    o["tahmini satış / ay (üst)"] = (o["degerlendirme_30_gun"] * 2).round()
    return o.sort_values("degerlendirme_30_gun", ascending=False)


def facebook_ozet():
    f = csv_oku("facebook.csv")
    if f.empty:
        return f
    f["durum"] = f["durum"].fillna("").str.lower().str.strip()
    kontrol = f[f["durum"] != ""]
    o = kontrol.groupby("urun").agg(
        takip_edilen=("link", "count"),
        satildi=("durum", lambda s: (s == "satildi").sum()),
        silindi=("durum", lambda s: (s == "silindi").sum()),
        medyan_fiyat=("fiyat_chf", "median"),
    ).reset_index()
    o["satılma oranı %"] = (100 * (o["satildi"] + o["silindi"]) / o["takip_edilen"]).round()
    return o.sort_values("satılma oranı %", ascending=False)


DURAK = set("""und mit für von der die das den dem des ein eine einer eines zum zur neu neue neuer neues
gut sehr top set stk stück grösse gr cm mm für inkl original alt alte alter aus auf bei ohne nur wie
the and for with pour avec les des une und/oder oder gratis versand consegna gratuita livraison
gratuite kostenlos schweiz suisse svizzera abholung neuwertig zustand chf sfr
verkaufen verkaufe verkauft gebraucht guter gutem gute sehr jahre jahr wenig benutzt unbenutzt
weiss weiß schwarz grau blau grün braun beige rosa gelb silber gold farbe
holz metall massiv leder glas gross grosse klein kleine""".split())


def kelimeler(baslik):
    """Başlıktaki tek kelimeler + art arda gelen iki kelimelik ifadeler."""
    t = [w for w in re.findall(r"[a-zäöüéèàçß]{3,}", (baslik or "").lower()) if w not in DURAK]
    return {w for w in t if len(w) >= 4} | {f"{a} {b}" for a, b in zip(t, t[1:])}


def kategori_ozet():
    con = sqlite3.connect(DB)
    try:
        k = pd.read_sql("SELECT * FROM kat_ilan", con, parse_dates=["ilk_gorulme", "kayboldu", "son_kontrol"])
        kt = pd.read_sql("SELECT * FROM kat_tarama", con, parse_dates=["zaman"])
    except Exception:
        return pd.DataFrame(), pd.DataFrame()
    finally:
        con.close()
    if k.empty:
        return pd.DataFrame(), pd.DataFrame()

    k["kontrol_edildi"] = k["kontrol_sayisi"] > 0
    k["gitti"] = k["kayboldu"].notna()
    k["gozlem_gun"] = ((k["kayboldu"].fillna(k["son_kontrol"]) - k["ilk_gorulme"]).dt.total_seconds() / 86400)

    kat_satir, kat_gun, kat_oran = [], {}, {}
    for kat, g in k.groupby("kategori"):
        t = kt[kt["kategori"] == kat]
        gun = max((t["zaman"].max() - t["zaman"].min()).total_seconds() / 86400, 0.5)
        yeni = g[g["yeni"] == 1]
        kontrol = g[g["kontrol_edildi"]]
        oran = kontrol["gitti"].mean() if len(kontrol) else None
        kat_gun[kat], kat_oran[kat] = (gun if len(t) > 1 else None), oran
        kat_satir.append({
            "kategori": kat,
            "takip günü": round(gun, 1),
            "toplam ilan (sitede)": int(t["toplam"].iloc[-1]),
            "yeni ilan / gün": round(len(yeni) / gun) if len(t) > 1 else None,
            "kontrol edilen": len(kontrol),
            "kaybolan": int(kontrol["gitti"].sum()),
            "kaybolma oranı %": round(100 * oran) if oran is not None else None,
            "ort. gözlem (gün)": round(kontrol["gozlem_gun"].mean(), 1) if len(kontrol) else None,
            "TAHMİNİ SATIŞ / AY": round(len(yeni) / gun * 30 * oran) if (oran is not None and len(t) > 1) else None,
            "medyan fiyat": g["fiyat"].median(),
            f"% {FIYAT_ALT}-{FIYAT_UST} CHF": round(100 * g["fiyat"].between(FIYAT_ALT, FIYAT_UST).mean()),
            "pro satıcı %": round(100 * g["pro"].mean()),
        })

    # Keşif: başlıklarda geçen kelime/ifadeler. Hangisi çok ve hızlı satıyor?
    k["kel"] = k["baslik"].map(kelimeler)
    k["neu"] = k["baslik"].str.contains(r"\bneu|\bnew\b|\bneuf|\bnuovo|originalverpackt|\bovp\b", case=False, regex=True)
    patlak = k.explode("kel").dropna(subset=["kel"])
    kes = []
    for (kat, kel), g in patlak.groupby(["kategori", "kel"]):
        if len(g) < 8:
            continue
        kontrol = g[g["kontrol_edildi"]]
        yeni = g[g["yeni"] == 1]
        # Oran: ifadenin kendi örneklemi yeterliyse o, değilse kategori ortalaması
        if len(kontrol) >= 10:
            oran, kaynak = kontrol["gitti"].mean(), "kendi"
        else:
            oran, kaynak = kat_oran.get(kat), "kategori"
        gun = kat_gun.get(kat)
        tahmin = round(len(yeni) / gun * 30 * oran) if (gun and oran is not None) else None
        en_buyuk = g["satici"].value_counts(normalize=True).iloc[0] if g["satici"].notna().any() else None
        kes.append({
            "kategori": kat, "ifade": kel, "ilan": len(g), "yeni ilan": len(yeni),
            "kontrol": len(kontrol), "kaybolan": int(kontrol["gitti"].sum()),
            "kaybolma %": round(100 * oran) if oran is not None else None, "oran kaynağı": kaynak,
            "TAHMİNİ SATIŞ / AY": tahmin,
            "medyan fiyat": g["fiyat"].median(),
            f"% {FIYAT_ALT}-{FIYAT_UST} CHF": round(100 * g["fiyat"].between(FIYAT_ALT, FIYAT_UST).mean()),
            "% yeni ürün": round(100 * g["neu"].mean()),
            "pro satıcı %": round(100 * g["pro"].mean()),
            "satıcı sayısı": g["satici"].nunique(),
            "en büyük satıcı payı %": round(100 * en_buyuk) if en_buyuk is not None else None,
        })
    kesif = pd.DataFrame(kes)
    if not kesif.empty:
        kesif = kesif.sort_values(["TAHMİNİ SATIŞ / AY", "ilan"], ascending=False, na_position="last")
    return pd.DataFrame(kat_satir), kesif


def tarayici_ozet():
    con = sqlite3.connect(TARAYICI_DB)
    try:
        t = pd.read_sql("SELECT * FROM tarayici_ilan", con)
    except Exception:
        return pd.DataFrame()
    finally:
        con.close()
    if t.empty:
        return t
    return t.groupby(["platform", "sayfa_url"]).agg(
        kayit=("dosya", "nunique"), ilan=("id", "nunique"),
        satildi_isaretli=("durum", lambda s: (s == "satildi").sum()),
        medyan_fiyat=("fiyat", "median"), ilk=("zaman", "min"), son=("zaman", "max"),
    ).reset_index()


def main():
    tutti, ilanlar = tutti_ozet()
    ricardo, facebook = ricardo_ozet(), facebook_ozet()
    kategori, kesif = kategori_ozet()
    hedef = pd.DataFrame()
    if not kesif.empty:
        hedef = kesif[kesif["medyan fiyat"].between(30, 150)
                      & (kesif["pro satıcı %"] <= 40)
                      & (kesif["en büyük satıcı payı %"] <= 30)
                      & (kesif["satıcı sayısı"] >= 5)].head(100)
    tarayici = tarayici_ozet()
    from capraz import capraz_analiz
    sinama, uyum, korelasyon, platform_bilgi = capraz_analiz()

    with pd.ExcelWriter(CIKTI) as xl:
        for ad, df in [("Tutti kelime", tutti), ("Tutti kategori", kategori), ("EN ÇOK SATANLAR", kesif), ("Filtreli 30-150 CHF az rekabet", hedef),
                        ("Ricardo elle", ricardo), ("Facebook elle", facebook), ("Eklenti kayıtları", tarayici),
                        ("Popülerlik uyumu - özet", korelasyon), ("Popülerlik uyumu - ürünler", uyum),
                        ("Platformlar", platform_bilgi),
                        ("Çapraz - yöntem sınaması", sinama)]:
            (df if not df.empty else pd.DataFrame({"bilgi": ["henüz veri yok"]})).to_excel(xl, sheet_name=ad, index=False)
        if not ilanlar.empty:
            ilanlar.drop(columns=["anahtar"]).to_excel(xl, sheet_name="Tutti ilanlar", index=False)

    print(f"Rapor: {CIKTI}  ({date.today()})\n")
    pd.set_option("display.width", 200, "display.max_columns", 20)
    for ad, df in [("TUTTI KELİME", tutti), ("TUTTI KATEGORİ", kategori), ("EN ÇOK SATANLAR (ilk 30, filtresiz)", kesif.head(30)),
                    ("RICARDO (elle)", ricardo), ("FACEBOOK (elle)", facebook), ("EKLENTİ KAYITLARI", tarayici),
                    ("PLATFORMLAR", platform_bilgi), ("POPÜLERLİK UYUMU (Tutti ↔ Ricardo/FB)", korelasyon),
                    ("ÜRÜNLER: POPÜLERLİK UYUMU (ilk 20)", uyum.head(20)), ("YÖNTEM SINAMASI", sinama)]:
        print(f"== {ad} ==")
        print(df.to_string(index=False) if not df.empty else "henüz veri yok")
        print()


if __name__ == "__main__":
    main()
