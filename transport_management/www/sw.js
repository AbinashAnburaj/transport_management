// Driver Dashboard — service worker (Phase A).
// Network-first for the page; fall back to cache when offline.
// Scope is root because Frappe serves www/ files at the website root.

const CACHE = 'tms-driver-v1';
const SHELL = ['/driver_dashboard'];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  // Only handle the driver dashboard shell; let everything else hit the network.
  if (url.origin !== self.location.origin) return;
  if (url.pathname !== '/driver_dashboard') return;

  e.respondWith(
    fetch(req)
      .then((resp) => {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
        return resp;
      })
      .catch(() =>
        caches.match(req).then((r) => r || caches.match('/driver_dashboard'))
      )
  );
});
