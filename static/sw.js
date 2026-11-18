const CACHE = 'assi-v8';
/* HTML не кэшируем: страница должна всегда приходить с сервера, иначе после сбоя сети
   остаётся старая версия интерфейса и «нет связи» не снимается. */
const SHELL = ['/manifest.webmanifest', '/icon-192.png?v=4', '/icon-512.png?v=4', '/favicon.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))));
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith('/api/')) return;                 // сеть как есть
  if (url.pathname === '/' || url.pathname.endsWith('.html')) return; // всегда сеть
  e.respondWith(
    caches.match(e.request).then(hit => hit || fetch(e.request).then(r => {
      const copy = r.clone();
      caches.open(CACHE).then(c => c.put(e.request, copy)).catch(() => {});
      return r;
    }))
  );
});
