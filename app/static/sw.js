/**
 * Service Worker - Network First (robust)
 * Cache name bumped to padaria-v2 to force update.
 */

const CACHE_NAME = 'padaria-v2';
const PRECACHE_URLS = [
  '/',
  '/static/manifest.json'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE_URLS))
      .catch(err => {
        // Dev environments may 404 some routes; ignore silently
        console.warn('[SW] precache failed:', err);
      })
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(keys.map(k => {
        if (k !== CACHE_NAME) return caches.delete(k);
      }));
    }).then(() => self.clients.claim())
  );
});

// Helper to decide if request should be handled as navigation
function isNavigationRequest(request) {
  return request.mode === 'navigate' || (request.headers.get('accept') || '').includes('text/html');
}

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);

  // Don't intercept API or non-GET requests; let the page handle them
  if (request.method !== 'GET' || url.pathname.startsWith('/api/') || url.pathname === '/salvar_contagem') {
    // Just attempt network and let it fail through to page JS
    event.respondWith(fetch(request).catch(err => {
      // If network fails for non-GET or APIs, propagate the failure
      return new Response(null, { status: 503, statusText: 'Service Unavailable' });
    }));
    return;
  }

  // Network First strategy
  event.respondWith(
    fetch(request)
      .then(networkResponse => {
        // If request succeeded, update cache and return
        if (networkResponse && networkResponse.status === 200) {
          const clone = networkResponse.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(request, clone));
        }
        return networkResponse;
      })
      .catch(() => {
        // Network failed: try cache
        return caches.match(request).then(cached => {
          if (cached) return cached;
          // If navigation, return cached root or a simple offline page
          if (isNavigationRequest(request)) {
            return caches.match('/').then(rootCached => {
              if (rootCached) return rootCached;
              return new Response('<h1>Você está offline</h1><p>Conteúdo indisponível no momento.</p>', { headers: { 'Content-Type': 'text/html; charset=utf-8' } });
            });
          }
          // For other assets return generic 503
          return new Response('Offline', { status: 503, statusText: 'Offline' });
        });
      })
  );
});
