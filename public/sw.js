/* Caribe — service worker: abre al instante desde el teléfono y se actualiza solo.
   __BUILD__ lo reemplaza el servidor por una huella de la app, así cada despliegue renueva la caché. */
const VERSION = 'caribe-__BUILD__';
const CORE = ['/', '/index.html', '/manifest.webmanifest', '/icon-192.png', '/icon-512.png'];
self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(VERSION).then(c => Promise.all(CORE.map(u => fetch(u, { cache: 'reload' }).then(r => r.ok && c.put(u, r)).catch(() => {})))));
});
self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;   // la API siempre en vivo
  e.respondWith((async () => {
    const cache = await caches.open(VERSION);
    const cached = await cache.match(e.request, { ignoreSearch: true });
    if (url.pathname.startsWith('/media/') && cached) return cached;                                           // fotos: nunca cambian
    const refresh = fetch(e.request).then(r => { if (r && r.ok) cache.put(e.request, r.clone()); return r; }).catch(() => null);
    if (cached) { e.waitUntil(refresh); return cached; }                                                        // abre YA; actualiza en segundo plano
    return (await refresh) || (await cache.match('/index.html')) || new Response('Sin conexión', { status: 503 });
  })());
});
