const durum = (t) => (document.getElementById("durum").textContent = t);

async function sekme() {
  const [t] = await chrome.tabs.query({ active: true, currentWindow: true });
  return t;
}

async function gonder(komut) {
  const t = await sekme();
  try {
    return await chrome.tabs.sendMessage(t.id, { komut });
  } catch {
    durum("Bu sayfada çalışmıyor. Ricardo, Tutti veya Facebook Marketplace'te olmalısın (sayfayı yenile).");
    return null;
  }
}

function zamanDamgasi() {
  const d = new Date(), p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

(async () => {
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
