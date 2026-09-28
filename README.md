# tuttipazar

İsviçre ikinci el / pazar yeri talep araştırması: **hangi ürünler gerçekten satılıyor?**
Tutti.ch'deki eşya kategorileri düzenli taranır; yayından kalkan ilanlar tek tek doğrulanır
ve ürün bazında satış hızı tahmin edilir. Sonuçlar Ricardo ve Facebook Marketplace ile karşılaştırılır.

## Nasıl çalışır

| Parça | Nerede | Ne yapar |
|---|---|---|
| `tutti_takip.py` | GitHub Actions, 4 saatte bir | `kategoriler.txt`'deki 57 kategoriye gelen yeni ilanları kaydeder; eski ilanlardan örneklemi `/vi/<id>` sayfasıyla kontrol eder (404 = kalktı) |
| `veri.db` | Release `veri` → `veri.db.gz` | SQLite veritabanı, her taramada güncellenir |
| `eklenti/` | Chrome/Edge | Ricardo ve Facebook'ta gezinirken ekrandaki ilanları kaydeder |
| `ice_aktar.py` | Yerel | Eklenti kayıtlarını `tarayici.db`'ye aktarır (GitHub'a gönderilmez) |
| `rapor.py`, `capraz.py` | Yerel | `rapor.xlsx`: en çok satanlar, kategori özetleri, platformlar arası ürün popülerliği uyumu |

## Yerelde rapor

```
pip install -r requirements.txt
python veri_indir.py   # güncel Tutti verisi
python ice_aktar.py    # eklenti kayıtları
python rapor.py        # rapor.xlsx
```

Windows'ta hepsi için `calistir.bat`.

## Nezaket kuralları

İstekler arasında en az 1,5 sn beklenir, tek seferde tek istek atılır, sadece herkese açık ilan sayfaları okunur.
Ricardo'nun bot koruması aşılmaz; Facebook'a otomatik giriş yapılmaz. Bu iki platformun verisi yalnızca
kullanıcının kendi gezinmesinden eklentiyle gelir.
