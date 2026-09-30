const durum = (t) => (document.getElementById("durum").textContent = t);

// Takip edilen iki sayfa: kayıtlar ancak bu ayarlarla birbiriyle karşılaştırılabilir
const HEDEF = {
  facebook: {
    ad: "Facebook",
    url: "https://www.facebook.com/marketplace/zurich/search?sortBy=creation_time_descend&query=Haushaltsbedarf&category_id=753380185098614&exact=false",
    kosullar: [["category_id=753380185098614", "kategori Haushaltsbedarf değil"],
               ["sortBy=creation_time_descend", "sıralama 'Neueste zuerst' değil"]],
  },
  ricardo: {
    ad: "Ricardo",
    url: "https://www.ricardo.ch/de/c/sonstigen-haushalts-bedarf-40519/?range=35&sort=newest&zip_code=8000",
    kosullar: [["sonstigen-haushalts-bedarf-40519", "kategori Sonstiger Haushaltsbedarf değil"],
               ["sort=newest", "sıralama 'Neueste' değil"],
               ["range=35", "Umkreis 35 km değil"],
               ["zip_code=8000", "konum Zürich (8000) değil"]],
  },
};
const MAX_ARALIK_SAAT = 4;  // bundan uzun aralıkta kayıtlar örtüşmez

async function sekme() {
  const [t] = await chrome.tabs.query({ active: true, currentWindow: true });
  return t;
}

function platformu(url) {
  if (/facebook\.com\/marketplace/.test(url)) return "facebook";
  if (/ricardo\.ch/.test(url)) return "ricardo";
  return null;
}

async function gonder(komut) {
  const t = await sekme();
  try {
    return await chrome.tabs.sendMessage(t.id, { komut });
  } catch {
    durum("Bu sayfada çalışmıyor. Facebook Marketplace veya Ricardo'da olmalısın (sayfayı yenile).");
    return null;
  }
}

function zamanDamgasi() {
  const d = new Date(), p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

function sonKayitSaat(platform) {
  try {
    const z = Number(localStorage.getItem("son_" + platform));
    return z ? (Date.now() - z) / 3.6e6 : null;
  } catch { return null; }
}

function sonKayitlariGoster() {
  const satir = Object.keys(HEDEF).map((p) => {
    const s = sonKayitSaat(p);
    if (s === null) return `${HEDEF[p].ad}: henüz kayıt yok`;
    const uyar = s > MAX_ARALIK_SAAT ? " ⚠ uzun ara: bu kayıt yeni başlangıç olur" : "";
    return `${HEDEF[p].ad}: son kayıt ${s < 1 ? Math.round(s * 60) + " dk" : s.toFixed(1) + " saat"} önce${uyar}`;
  });
  document.getElementById("son").innerHTML = satir.join("<br>");
}

async function ayarKontrol() {
  const t = await sekme();
  const p = platformu(t.url || "");
  const kaydet = document.getElementById("kaydet");
  if (!p) return p;
  const eksik = HEDEF[p].kosullar.filter(([parca]) => !t.url.includes(parca)).map(([, neden]) => neden);
  document.getElementById("uyari").style.display = eksik.length ? "block" : "none";
  document.getElementById("uyariMetin").textContent = eksik.join(", ") + ".";
  kaydet.disabled = eksik.length > 0;
  document.getElementById("duzelt").onclick = () => chrome.tabs.update(t.id, { url: HEDEF[p].url }).then(() => window.close());
  return p;
}

document.getElementById("acFb").onclick = async () => {
  await chrome.tabs.update((await sekme()).id, { url: HEDEF.facebook.url }); window.close();
};
document.getElementById("acRi").onclick = async () => {
  await chrome.tabs.update((await sekme()).id, { url: HEDEF.ricardo.url }); window.close();
};

(async () => {
  sonKayitlariGoster();
  await ayarKontrol();
  const c = await gonder("sayi");
  if (c) document.getElementById("sayi").textContent = c.sayi;
})();

document.getElementById("kaydet").onclick = async () => {
  const veri = await gonder("topla");
  if (!veri) return;
  const platform = new URL(veri.sayfa_url).hostname.replace("www.", "").split(".")[0];
  const blob = new Blob([JSON.stringify(veri)], { type: "application/json" });
  await chrome.downloads.download({
    url: URL.createObjectURL(blob),
    filename: `pazar-veri/${platform}_${zamanDamgasi()}.json`,
    conflictAction: "uniquify",
  });
  try { localStorage.setItem("son_" + platformu(veri.sayfa_url), String(Date.now())); } catch {}
  sonKayitlariGoster();
  document.getElementById("sayi").textContent = veri.ilanlar.length;
  durum(`Kaydedildi: ${veri.ilanlar.length} ilan → İndirilenler/pazar-veri`);
};

document.getElementById("sifirla").onclick = async () => {
  const c = await gonder("sifirla");
  if (c) {
    document.getElementById("sayi").textContent = 0;
    durum("Sıfırlandı.");
  }
};
