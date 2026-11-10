// Leads service worker: caches the app shell and the floor list so the phone page opens
// without signal. Taps are queued in localStorage by the page itself (src/lib/offlineQueue.ts).
const SHELL = 'leads-shell-v1'
const DATA = 'leads-data-v1'
const PRECACHE = ['/', '/index.html', '/manifest.webmanifest', '/icon.svg']

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(PRECACHE).catch(() => undefined)).then(() => self.skipWaiting()))
})

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL && k !== DATA).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('message', (e) => {
  if (e.data && e.data.type === 'cache-urls' && Array.isArray(e.data.urls)) {
    e.waitUntil(caches.open(SHELL).then((c) => Promise.all(e.data.urls.map((u) => c.add(u).catch(() => undefined)))))
  }
})

const okToCache = (res) => res && res.ok && res.type === 'basic' && !res.redirected

// API reads worth having offline: the floor list, the current user and the show list.
const OFFLINE_API = [/^\/api\/me$/, /^\/api\/conventions$/, /^\/api\/conventions\/[^/]+$/, /^\/api\/conventions\/[^/]+\/floor\//]

self.addEventListener('fetch', (e) => {
  const req = e.request
  if (req.method !== 'GET') return
  const url = new URL(req.url)
  if (url.origin !== self.location.origin) return

  // hashed build assets: cache first
  if (url.pathname.startsWith('/assets/')) {
    e.respondWith(
      caches.match(req).then(
        (hit) =>
          hit ||
          fetch(req).then((res) => {
            if (okToCache(res)) {
              const copy = res.clone()
              caches.open(SHELL).then((c) => c.put(req, copy))
            }
            return res
          }),
      ),
    )
    return
  }

  if (url.pathname.startsWith('/api/')) {
    if (!OFFLINE_API.some((r) => r.test(url.pathname))) return
    e.respondWith(
      fetch(req)
        .then((res) => {
          if (okToCache(res)) {
            const copy = res.clone()
            caches.open(DATA).then((c) => c.put(req, copy))
          }
          return res
        })
        .catch(() => caches.match(req).then((hit) => hit || Response.error())),
    )
    return
  }

  // SPA navigations: network first, fall back to the cached shell
  if (req.mode === 'navigate') {
    e.respondWith(
      fetch(req)
        .then((res) => {
          if (okToCache(res)) {
            const copy = res.clone()
            caches.open(SHELL).then((c) => c.put('/index.html', copy))
          }
          return res
        })
        .catch(() => caches.match('/index.html').then((hit) => hit || caches.match('/'))),
    )
  }
})
