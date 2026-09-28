"""Çapraz doğrulama: Tutti (doğrudan ölçüm) ile Facebook/Ricardo (kayıt karşılaştırma) uyumu.

Ortak birim: GÜNLÜK KAYBOLMA ORANI (%). Bir ilanın 24 saat içinde yayından kalkma olasılığı.
  lambda = kaybolan ilan / toplam gözlem süresi (gün)  ->  oran = 1 - e^(-lambda)

İki ölçüm yöntemi:
  a) 404 kontrolü (sadece Tutti): ilanın kendi sayfası açılıp "hâlâ var mı" bakılır. GERÇEK DEĞER.
  b) Pencere yöntemi (FB, Ricardo ve sınama için Tutti): "en yeni" sıralı iki kayıt karşılaştırılır.
     B kaydında A'daki bir ilandan daha eski ilanlar hâlâ görünüyor ama o ilan yoksa -> kaybolmuş.

Katman 1 - Yöntem sınaması: (b) yöntemi Tutti'ye uygulanır, (a) ile karşılaştırılır.
Katman 2 - Platform uyumu: aynı ürün ifadesi Tutti'de hızlı gidiyorsa FB/Ricardo'da da hızlı mı?
"""
import math
import sqlite3
from urllib.parse import parse_qsl, urlencode, urlsplit

import pandas as pd

from rapor import DB, TARAYICI_DB, kelimeler

MIN_GOZLEM = 10     # bir ifade için oran hesaplamak üzere gereken en az gözlem


def gunluk_oran(kaybolan, gozlem_gun):
    if not gozlem_gun or gozlem_gun <= 0:
        return None
    return round(100 * (1 - math.exp(-kaybolan / gozlem_gun)), 1)


DILIM = 20


def pencere_siniri(a, bset):
    """A listesinde B ile gerçekten örtüşen bölümün son konumu.
    Tek bir ilanın B'de görünmesi yetmez: yenilenen (bump) eski ilan listenin başına fırlar ve
    'en eski görünen' sanılırsa arada kalan onlarca ilan yanlışlıkla kaybolmuş sayılır.
    Bu yüzden son 20 ilanlık dilimin en az yarısı B'de görünüyorsa o konum örtüşme içinde sayılır."""
    var = [x in bset for x in a]
    sinir = -1
    for i in range(len(a)):
        dilim = var[max(0, i - DILIM + 1):i + 1]
        if var[i] and sum(dilim) / len(dilim) >= 0.5:
            sinir = i
    return sinir


def pencere(kayitlar):
    """kayitlar: [(zaman, [id, ... en yeniden eskiye]), ...]  (zamana göre sıralı)
    Döner: her (ilan, kayıt çifti) için bir gözlem: id, süre (gün), kayboldu."""
    satirlar = []
    for (ta, a), (tb, b) in zip(kayitlar, kayitlar[1:]):
        bset = set(b)
        sinir = pencere_siniri(a, bset)
        if sinir < 0:
            continue  # kayıtlar örtüşmüyor: çok seyrek kayıt
        gun = (tb - ta).total_seconds() / 86400
        for x in a[:sinir + 1]:
            satirlar.append({"id": x, "t_a": ta, "t_b": tb, "gun": gun, "kayboldu": x not in bset})
    return pd.DataFrame(satirlar)


def ifade_oranlari(gozlem, ifadeler):
    """gozlem: id, gun, kayboldu  |  ifadeler: id -> set(ifade)"""
    if gozlem.empty:
        return pd.DataFrame(columns=["ifade", "gozlem", "kaybolan", "oran"])
    g = gozlem.copy()
    g["ifade"] = g["id"].map(lambda i: ifadeler.get(i, set()))
    g = g.explode("ifade").dropna(subset=["ifade"])
    o = g.groupby("ifade").agg(gozlem=("id", "nunique"), kaybolan=("kayboldu", "sum"), gun=("gun", "sum"))
    o = o[o["gozlem"] >= MIN_GOZLEM]
    o["oran"] = [gunluk_oran(k, d) for k, d in zip(o["kaybolan"], o["gun"])]
    return o.reset_index()[["ifade", "gozlem", "kaybolan", "oran"]]


# ---------------------------------------------------------------- Tutti

def tutti_verisi(con):
    k = pd.read_sql("SELECT id, kategori, baslik, ilk_gorulme, son_kontrol, kayboldu, kontrol_sayisi FROM kat_ilan",
                    con, parse_dates=["ilk_gorulme", "son_kontrol", "kayboldu"])
    try:
        gor = pd.read_sql("SELECT * FROM kat_gorunum ORDER BY zaman, kategori, sira", con, parse_dates=["zaman"])
    except Exception:
        gor = pd.DataFrame(columns=["zaman", "kategori", "sira", "id"])
    return k, gor


def tutti_gercek(k):
    """404 kontrolünden gözlem tablosu: her kontrol edilmiş ilan için süre ve sonuç."""
    kt = k[k["kontrol_sayisi"] > 0].copy()
    bitis = kt["kayboldu"].fillna(kt["son_kontrol"])
    kt["gun"] = (bitis - kt["ilk_gorulme"]).dt.total_seconds() / 86400
    kt["kayboldu_mu"] = kt["kayboldu"].notna()
    return kt[kt["gun"] > 0]


def tutti_pencere(gor):
    parca = []
    for kat, g in gor.groupby("kategori"):
        kayitlar = [(z, list(gg.sort_values("sira")["id"])) for z, gg in g.groupby("zaman")]
        p = pencere(kayitlar)
        if not p.empty:
            p["kategori"] = kat
            parca.append(p)
    return pd.concat(parca) if parca else pd.DataFrame(columns=["id", "t_a", "t_b", "gun", "kayboldu", "kategori"])


def yontem_sinamasi(k, gor):
    """Katman 1: pencere yöntemi Tutti'de gerçeği ne kadar iyi tahmin ediyor?"""
    gercek = tutti_gercek(k)
    pen = tutti_pencere(gor)
    durum = k.set_index("id")
    satir = []
    for kat in sorted(set(gercek["kategori"]) | set(pen.get("kategori", []))):
        gg, pp = gercek[gercek["kategori"] == kat], pen[pen["kategori"] == kat]
        # İsabet: pencere "kayboldu" dedi, 404 kontrolü ne diyor?
        pk = pp[pp["kayboldu"]]
        dogru = sum(1 for i, tb in zip(pk["id"], pk["t_b"])
                    if i in durum.index and pd.notna(durum.at[i, "kayboldu"]))
        yanlis = sum(1 for i, tb in zip(pk["id"], pk["t_b"])
                     if i in durum.index and pd.isna(durum.at[i, "kayboldu"])
                     and pd.notna(durum.at[i, "son_kontrol"]) and durum.at[i, "son_kontrol"] >= tb)
        satir.append({
            "kategori": kat,
            "404: gözlem": len(gg), "404: günlük kaybolma %": gunluk_oran(gg["kayboldu_mu"].sum(), gg["gun"].sum()),
            "pencere: gözlem": len(pp),
            "pencere: günlük kaybolma %": gunluk_oran(pp["kayboldu"].sum(), pp["gun"].sum()) if len(pp) else None,
            "pencere 'kayboldu' dedi": len(pk),
            "doğrulandı (404)": dogru, "yanlış alarm (ilan hâlâ var)": yanlis,
            "isabet %": round(100 * dogru / (dogru + yanlis)) if dogru + yanlis else None,
        })
    df = pd.DataFrame(satir)
    if not df.empty:
        df["kalibrasyon (404 / pencere)"] = (df["404: günlük kaybolma %"] / df["pencere: günlük kaybolma %"]).round(2)
    return df


# ---------------------------------------------------------------- Facebook / Ricardo

GECICI_PARAM = {"page", "referral_ui_component", "locale", "exact", "ref", "tracking", "fbclid"}


def sayfa_anahtari(url):
    """Aynı kategori/arama = aynı anahtar. Facebook'ta kategori adresin ?parametrelerinde,
    Ricardo'da sayfa numarası (?page=) atılır ki 1., 2. sayfa aynı listeye düşsün."""
    s = urlsplit(url)
    kalici = sorted(p for p in parse_qsl(s.query) if p[0] not in GECICI_PARAM)
    return s.netloc + s.path.rstrip("/") + ("?" + urlencode(kalici) if kalici else "")


def tarayici_verisi(con):
    try:
        t = pd.read_sql("SELECT * FROM tarayici_ilan", con, parse_dates=["zaman"])
    except Exception:
        return pd.DataFrame()
    if t.empty or "sira" not in t:
        return pd.DataFrame()
    t["anahtar"] = t["sayfa_url"].map(sayfa_anahtari)
    return t


def kart_ifadeleri(t):
    """Kart başlığından ifadeler (başlık yoksa tüm kart metni); kartların >%20'sinde geçen şablon kelimeler atılır."""
    metin = t["baslik"].fillna(t["metin"]) if "baslik" in t else t["metin"]
    ham = {i: kelimeler(m) for i, m in zip(t["platform"] + ":" + t["id"], metin)}
    say = pd.Series([w for s in ham.values() for w in s]).value_counts()
    gurultu = set(say[say > 0.2 * max(len(ham), 1)].index)
    return {i: s - gurultu for i, s in ham.items()}


def platform_pencere(t, platform):
    tp = t[t["platform"] == platform]
    # Ücretli öne çıkarılan ilanlar ("Boost") tarih sırasının dışında durur, pencereyi bozar
    tp = tp[~tp["metin"].fillna("").str.match(r"(Boost|Gesponsert|Sponsored)\b")]
    parca = []
    for anahtar, g in tp.groupby("anahtar"):
        kayitlar = [(z, list(platform + ":" + gg.sort_values("sira")["id"])) for z, gg in g.groupby("zaman")]
        p = pencere(kayitlar)
        if not p.empty:
            p["sayfa"] = anahtar
            parca.append(p)
    return pd.concat(parca) if parca else pd.DataFrame(columns=["id", "t_a", "t_b", "gun", "kayboldu", "sayfa"])


# ---------------------------------------------------------------- Katman 2: uyum

def platform_uyumu(k, t):
    gercek = tutti_gercek(k)
    tutti_ifade = {i: kelimeler(b) for i, b in zip(k["id"], k["baslik"])}
    tg = gercek.rename(columns={"kayboldu_mu": "kayboldu_b"})[["id", "gun", "kayboldu_b"]].rename(
        columns={"kayboldu_b": "kayboldu"})
    tablo = ifade_oranlari(tg, tutti_ifade).rename(
        columns={"gozlem": "Tutti gözlem", "kaybolan": "Tutti kaybolan", "oran": "Tutti günlük %"})

    korelasyon = []
    if not t.empty:
        ifadeler = kart_ifadeleri(t)
        for platform, ad in [("facebook", "Facebook"), ("ricardo", "Ricardo")]:
            p = platform_pencere(t, platform)
            o = ifade_oranlari(p, ifadeler).rename(
                columns={"gozlem": f"{ad} gözlem", "kaybolan": f"{ad} kaybolan", "oran": f"{ad} günlük %"})
            tablo = tablo.merge(o, on="ifade", how="outer")
            ortak = tablo.dropna(subset=["Tutti günlük %", f"{ad} günlük %"])
            # Spearman = sıralamaların Pearson korelasyonu (scipy gerektirmez)
            rho = (ortak["Tutti günlük %"].rank().corr(ortak[f"{ad} günlük %"].rank())
                   if len(ortak) >= 5 else None)
            korelasyon.append({"karşılaştırma": f"Tutti ↔ {ad}", "ortak ifade": len(ortak),
                               "sıralama uyumu (Spearman ρ)": round(rho, 2) if rho is not None else None,
                               "yorum": yorum(rho, len(ortak))})

    # Her platformda: ifade o platformun medyanının üstünde mi (hızlı) altında mı (yavaş)?
    oran_sut = [c for c in tablo.columns if c.endswith("günlük %")]
    for c in oran_sut:
        med = tablo[c].median()
        tablo[c.replace("günlük %", "hız")] = tablo[c].map(
            lambda v: None if pd.isna(v) else ("hızlı" if v > med else "yavaş"))
    hiz_sut = [c for c in tablo.columns if c.endswith(" hız")]

    def uyum(r):
        h = [r[c] for c in hiz_sut if isinstance(r[c], str)]
        if len(h) < 2:
            return "tek platform"
        if all(x == "hızlı" for x in h):
            return "✓ her yerde hızlı"
        if all(x == "yavaş" for x in h):
            return "✓ her yerde yavaş"
        return "⚠ çelişki"
    tablo["uyum"] = tablo.apply(uyum, axis=1) if not tablo.empty else []
    sira = {"✓ her yerde hızlı": 0, "⚠ çelişki": 1, "tek platform": 2, "✓ her yerde yavaş": 3}
    if not tablo.empty:
        tablo = tablo.sort_values(["uyum", "Tutti günlük %"], key=lambda s: s.map(sira) if s.name == "uyum" else -s.fillna(-1))
    return tablo, pd.DataFrame(korelasyon)


def yorum(rho, n):
    if rho is None:
        return f"yetersiz veri ({n} ortak ifade, en az 5 gerekli)"
    if rho >= 0.5:
        return "güçlü uyum: platformlar aynı ürünleri hızlı satıyor"
    if rho >= 0.2:
        return "zayıf-orta uyum"
    if rho > -0.2:
        return "uyum yok: platformlar farklı davranıyor ya da veri gürültülü"
    return "ters ilişki: kontrol et"


def capraz_analiz():
    con = sqlite3.connect(DB)
    try:
        k, gor = tutti_verisi(con)
    finally:
        con.close()
    con = sqlite3.connect(TARAYICI_DB)
    try:
        t = tarayici_verisi(con)
    finally:
        con.close()
    sinama = yontem_sinamasi(k, gor) if not k.empty else pd.DataFrame()
    uyum, korelasyon = platform_uyumu(k, t) if not k.empty else (pd.DataFrame(), pd.DataFrame())
    return sinama, uyum, korelasyon


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    pd.set_option("display.width", 220, "display.max_columns", 20)
    s, u, kor = capraz_analiz()
    for ad, df in [("YÖNTEM SINAMASI", s), ("PLATFORM UYUMU (ilk 30)", u.head(30)), ("KORELASYON", kor)]:
        print(f"== {ad} ==")
        print(df.to_string(index=False) if not df.empty else "henüz veri yok")
        print()
