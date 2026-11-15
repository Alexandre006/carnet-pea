/* Carnet PEA — fonctionnement hors ligne.
   Page et icônes : réseau d'abord (nouvelle version dès qu'elle existe), sinon copie locale.
   Cours (data/) : réseau d'abord, sinon derniers cours connus. */
const CACHE = 'carnet-pea-v202611151010';
const SHELL = ['./', './index.html', './manifest.webmanifest', './icons/apple-touch-icon.png', './icons/icon-192.png', './icons/icon-512.png', './data/universe.json'];
self.addEventListener('install', e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== location.origin) return;
  e.respondWith(fetch(req).then(res => {
    if (res && res.ok) { const copy = res.clone(); const key = new URL(req.url); key.search = ''; caches.open(CACHE).then(c => c.put(key.toString(), copy)); }
    return res;
  }).catch(() => { const key = new URL(req.url); key.search = ''; return caches.match(key.toString()).then(r => r || caches.match('./index.html')); }));
});
