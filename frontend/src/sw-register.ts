// Registers /sw.js (production only) and hands it the asset URLs this page loaded,
// so the app shell is cached after the very first visit.
export function registerServiceWorker() {
  if (!('serviceWorker' in navigator) || import.meta.env.DEV) return
  window.addEventListener('load', async () => {
    try {
      await navigator.serviceWorker.register('/sw.js', { scope: '/' })
      const reg = await navigator.serviceWorker.ready
      const urls = performance
        .getEntriesByType('resource')
        .map((e) => new URL(e.name))
        .filter((u) => u.origin === location.origin && u.pathname.startsWith('/assets/'))
        .map((u) => u.pathname)
      reg.active?.postMessage({ type: 'cache-urls', urls: ['/', ...urls] })
    } catch {
      /* no offline support; the app still works online */
    }
  })
}
