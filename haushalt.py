"""Zürih Haushaltsbedarf talep analizi: Facebook Marketplace + Ricardo.

Kaynaklar (kullanıcı eklentiyle 2-3 saatte bir ~200 ilan kaydeder):
  Facebook: Zürih 40 km, Haushaltsbedarf, "Neueste zuerst"
  Ricardo:  Zürih 35 km Umkreis, Sonstiger Haushaltsbedarf, "Neueste"

Yöntem (pencere): aynı sayfanın ardışık iki kaydı karşılaştırılır. Yeni kayıtta, eski kayıttaki
bir ilandan daha eski ilanlar hâlâ görünüyor ama o ilan yoksa -> ilan kalkmış (muhtemelen satıldı).
Tutti'de 404 kontrolüyle sınandı: isabet ~%89 (2026-09-28).

Kullanım:  python haushalt.py      -> haushalt_rapor.xlsx + ekran özeti
"""
import sqlite3
import sys
from pathlib import Path

import pandas as pd

from capraz import gunluk_oran, kart_ifadeleri, pencere, pencere_siniri, sayfa_anahtari
from rapor import FIYAT_ALT, FIYAT_UST, TARAYICI_DB

KLASOR = Path(__file__).parent
CIKTI = KLASOR / "haushalt_rapor.xlsx"
MIN_ILAN = 4        # bir ürün ifadesinin tabloya girmesi için en az ilan

sys.stdout.reconfigure(encoding="utf-8")


def veriyi_oku():
    con = sqlite3.connect(TARAYICI_DB)
    try:
        t = pd.read_sql("SELECT * FROM tarayici_ilan", con)
    finally:
        con.close()
    if t.empty:
        return t
    # Eklenti UTC kaydeder -> Zürih saati (Excel saat dilimli tarih yazamaz)
    t["zaman"] = pd.to_datetime(t["zaman"], utc=True).dt.tz_convert("Europe/Zurich").dt.tz_localize(None)
    t["anahtar"] = t["sayfa_url"].map(sayfa_anahtari)
    t["kimlik"] = t["platform"] + ":" + t["id"]
    # Ücretli öne çıkarılanlar tarih sırası dışında durur
    t["reklam"] = t["metin"].fillna("").str.match(r"(Boost|Gesponsert|Sponsored)\b")
    return t


def kayit_listeleri(g):
    """Bir sayfanın kayıtları: [(zaman, [kimlik... ekrandaki sırayla])]"""
    g = g[~g["reklam"]]
    return [(z, list(gg.sort_values("sira")["kimlik"])) for z, gg in g.groupby("zaman")]


def analiz(t):
    ozet, gozlemler, yeni_hiz = [], [], []
    for (platform, anahtar), g in t.groupby(["platform", "anahtar"]):
        kayitlar = kayit_listeleri(g)
        p = pencere(kayitlar)
        ortusen = 0
        for (ta, a), (tb, b) in zip(kayitlar, kayitlar[1:]):
            sinir = pencere_siniri(a, set(b))
            saat = (tb - ta).total_seconds() / 3600
            if sinir >= 0:
                ortusen += 1
                # B'nin başında A'da olmayan ilanlar = aradaki sürede açılan yeni ilanlar
                ilk_ortak = next(i for i, x in enumerate(b) if x in set(a))
                yeni_hiz.append({"platform": platform, "saat": saat, "yeni": ilk_ortak})
        if not p.empty:
            p["platform"], p["sayfa"] = platform, anahtar
            gozlemler.append(p)
        yh = [y for y in yeni_hiz if y["platform"] == platform]
        ozet.append({
            "platform": platform, "sayfa": anahtar,
            "kayıt": len(kayitlar),
            "karşılaştırılabilen çift": f"{ortusen}/{max(len(kayitlar) - 1, 0)}",
            "ilk kayıt": kayitlar[0][0] if kayitlar else None,
            "son kayıt": kayitlar[-1][0] if kayitlar else None,
            "gözlenen ilan": p["id"].nunique() if not p.empty else 0,
            "kaybolan ilan": int(p.loc[p["kayboldu"], "id"].nunique()) if not p.empty else 0,
            "günlük kaybolma %": gunluk_oran(p["kayboldu"].sum(), p["gun"].sum()) if not p.empty else None,
            "saatte yeni ilan": round(sum(y["yeni"] for y in yh) / sum(y["saat"] for y in yh), 1)
                                if yh and sum(y["saat"] for y in yh) > 0 else None,
        })
    goz = pd.concat(gozlemler) if gozlemler else pd.DataFrame(
        columns=["id", "t_a", "t_b", "gun", "kayboldu", "platform", "sayfa"])
    return pd.DataFrame(ozet), goz


def kaybolanlar_tablosu(t, goz):
    if goz.empty or not goz["kayboldu"].any():
        return pd.DataFrame()
    k = goz[goz["kayboldu"]].groupby("id").agg(son_gorulme=("t_a", "max"), yok=("t_b", "min")).reset_index()
    son = t.sort_values("zaman").groupby("kimlik").last()
    ilk = t.groupby("kimlik")["zaman"].min()
    k = k.join(son[["platform", "baslik", "fiyat", "konum", "teklif", "url"]], on="id")
    k["ilk görülme"] = k["id"].map(ilk)
    k["en fazla yayında (saat)"] = ((k["yok"] - k["ilk görülme"]).dt.total_seconds() / 3600).round(1)
    return k.rename(columns={"son_gorulme": "son görüldü", "yok": "yok olduğu kayıt"}).sort_values(
        "yok olduğu kayıt", ascending=False)[["platform", "baslik", "fiyat", "konum", "teklif", "ilk görülme",
                                              "son görüldü", "yok olduğu kayıt", "en fazla yayında (saat)", "url"]]


def urunler_tablosu(t, goz):
    """Ürün ifadesi (başlıktaki kelime / ikili) bazında talep göstergeleri."""
    ifadeler = kart_ifadeleri(t)
    son = t.sort_values("zaman").groupby("kimlik").last()
    satirlar = []
    tum_ilan = pd.Series([(w, i) for i, s in ifadeler.items() for w in s], dtype=object)
    if tum_ilan.empty:
        return pd.DataFrame()
    ilan_df = pd.DataFrame(tum_ilan.tolist(), columns=["ifade", "kimlik"]).drop_duplicates()
    ilan_df = ilan_df.join(son[["platform", "fiyat"]], on="kimlik")
    goz_id = goz.groupby("id").agg(kayboldu=("kayboldu", "max"), gun=("gun", "sum")) if not goz.empty else None
    for ifade, g in ilan_df.groupby("ifade"):
        if len(g) < MIN_ILAN:
            continue
        satir = {"ürün ifadesi": ifade, "ilan": len(g),
                 "Facebook ilan": int((g["platform"] == "facebook").sum()),
                 "Ricardo ilan": int((g["platform"] == "ricardo").sum())}
        if goz_id is not None:
            gg = goz_id.reindex(g["kimlik"]).dropna()
            satir.update({
                "gözlenen": len(gg),
                "KAYBOLAN": int(gg["kayboldu"].sum()),
                "kaybolma %": round(100 * gg["kayboldu"].mean()) if len(gg) else None,
                "günlük kaybolma %": gunluk_oran(gg["kayboldu"].sum(), gg["gun"].sum()) if len(gg) else None,
            })
        f = g["fiyat"].dropna()
        satir.update({"medyan fiyat": f.median() if len(f) else None,
                      f"% {FIYAT_ALT}-{FIYAT_UST} CHF": round(100 * f.between(FIYAT_ALT, FIYAT_UST).mean()) if len(f) else None})
        satirlar.append(satir)
    df = pd.DataFrame(satirlar)
    if df.empty:
        return df
    sirala = ["KAYBOLAN", "kaybolma %", "ilan"] if "KAYBOLAN" in df else ["ilan"]
    return df.sort_values(sirala, ascending=False)


def ricardo_teklifler(t):
    """Ricardo'da teklif almış açık artırmalar: süre bitince satış kesinleşir (doğrudan talep sinyali)."""
    r = t[(t["platform"] == "ricardo") & (t["teklif"].fillna(0) >= 1)]
    if r.empty:
        return r
    r = r.sort_values("zaman").groupby("kimlik").last()
    bitis = r["metin"].str.extract(r"\n((?:Mo|Di|Mi|Do|Fr|Sa|So), \d+ \w+\.?, \d\d:\d\d|Heute, \d\d:\d\d|Morgen, \d\d:\d\d)")[0]
    return r.assign(bitiş=bitis).sort_values("teklif", ascending=False)[
        ["baslik", "fiyat_teklif", "fiyat_hemen", "teklif", "bitiş", "url"]]


def main():
    t = veriyi_oku()
    if t.empty:
        print("Henüz eklenti kaydı yok. Önce: python ice_aktar.py")
        return
    ozet, goz = analiz(t)
    kaybolan = kaybolanlar_tablosu(t, goz)
    urunler = urunler_tablosu(t, goz)
    teklif = ricardo_teklifler(t)

    with pd.ExcelWriter(CIKTI) as xl:
        for ad, df in [("Özet", ozet), ("Ürünler (talep)", urunler), ("Kaybolan ilanlar", kaybolan),
                       ("Ricardo teklifli", teklif)]:
            (df if not df.empty else pd.DataFrame({"bilgi": ["henüz veri yok"]})).to_excel(
                xl, sheet_name=ad, index=ad == "Ricardo teklifli")

    pd.set_option("display.width", 220, "display.max_columns", 20, "display.max_colwidth", 45)
    print(f"Rapor: {CIKTI}\n")
    print("== ÖZET ==")
    print(ozet.drop(columns=["sayfa"]).to_string(index=False))
    print("\n== ÜRÜNLER: en çok kaybolan (ilk 25) ==")
    print(urunler.head(25).to_string(index=False) if not urunler.empty else "henüz veri yok")
    print("\n== SON KAYBOLAN İLANLAR (ilk 15) ==")
    print(kaybolan.drop(columns=["url"]).head(15).to_string(index=False) if not kaybolan.empty
          else "henüz yok (en az 2 örtüşen kayıt gerekli)")
    print(f"\n== RICARDO: teklif almış açık artırmalar: {len(teklif)} ==")
    if not teklif.empty:
        print(teklif.drop(columns=["url"]).head(10).to_string(index=False))


if __name__ == "__main__":
    main()
