// Sayfada görünen ilan kartlarını, kullanıcı kaydırdıkça biriktirir.
// Facebook listeyi kaydırınca eski kartları sayfadan sildiği için sürekli toplamak gerekiyor.
(() => {
  const DESENLER = [
    { platform: "facebook", re: /\/marketplace\/item\/(\d+)/ },
    { platform: "ricardo", re: /ricardo\.ch\/(?:de|fr|it|en)\/a\/[^?#]*?(\d{6,})\/?/ },
    { platform: "tutti", re: /tutti\.ch\/(?:de|fr|it)\/vi\/(?:[^?#]*\/)?(\d{6,})/ },
  ];
  // Sayfa değişse de (Ricardo 1. sayfa -> 2. sayfa) liste korunur; sadece "Sıfırla" temizler.
  const DEPO = "__pazar_kartlar";
  const kartlar = new Map();
  try {
    for (const k of JSON.parse(sessionStorage.getItem(DEPO) || "[]")) kartlar.set(k.platform + ":" + k.id, k);
  } catch {}
  const sakla = () => {
    try { sessionStorage.setItem(DEPO, JSON.stringify([...kartlar.values()])); } catch {}
  };

  function kartMetni(a) {
    // Linkin kendisi kısa ise, fiyat/konum da görünsün diye bir-iki üst kutuya çık
    let el = a;
    for (let i = 0; i < 3 && el.parentElement && (el.innerText || "").length < 25; i++) {
      el = el.parentElement;
    }
    return (el.innerText || "").replace(/\s+\n/g, "\n").trim().slice(0, 600);
  }

  function tara() {
    for (const a of document.querySelectorAll("a[href]")) {
      const href = a.href;
      for (const d of DESENLER) {
        const m = href.match(d.re);
        if (!m) continue;
        const anahtar = d.platform + ":" + m[1];
        const metin = kartMetni(a);
        const img = a.querySelector("img");
        const eski = kartlar.get(anahtar);
        if (!eski || metin.length > eski.metin.length) {
          kartlar.set(anahtar, {
            platform: d.platform,
            id: m[1],
            url: href.split("?")[0],
            metin,
            resim_alt: img ? img.alt : null,
          });
        }
        break;
      }
    }
    sakla();
  }

  tara();
  new MutationObserver(() => {
    clearTimeout(window.__pazarZamanlayici);
    window.__pazarZamanlayici = setTimeout(tara, 400);
  }).observe(document.body, { childList: true, subtree: true });

  chrome.runtime.onMessage.addListener((mesaj, _gonderen, cevap) => {
    if (mesaj.komut === "sayi") {
      tara();
      cevap({ sayi: kartlar.size });
    } else if (mesaj.komut === "topla") {
      tara();
      let nextData = null;
      const nd = document.getElementById("__NEXT_DATA__");
      if (nd) nextData = nd.textContent.slice(0, 3_000_000);
      const jsonLd = [...document.querySelectorAll('script[type="application/ld+json"]')]
        .map((s) => s.textContent).slice(0, 20);
      cevap({
        sayfa_url: location.href,
        sayfa_basligi: document.title,
        zaman: new Date().toISOString(),
        ilanlar: [...kartlar.values()],
        sayfa_metni: document.body.innerText.slice(0, 400_000),
        next_data: nextData,
        json_ld: jsonLd,
      });
    } else if (mesaj.komut === "sifirla") {
      kartlar.clear();
      try { sessionStorage.removeItem(DEPO); } catch {}
      cevap({ sayi: 0 });
    }
    return true;
  });
})();
