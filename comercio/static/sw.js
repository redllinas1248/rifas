const CACHE_NAME = 'comercio-v3';
const URLS_A_CACHEAR = [
  '/comercio/static/css/app.css',
  '/comercio/static/js/app.js',
  '/comercio/static/manifest.json',
  '/comercio/static/img/icon-192.png',
  '/comercio/static/img/icon-512.png'
];

// Instalar — versión resiliente: si un archivo falla, los demás igual se cachean
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return Promise.all(
        URLS_A_CACHEAR.map(url =>
          cache.add(url).catch(err => {
            console.warn('No se pudo cachear:', url, err);
          })
        )
      );
    }).then(() => self.skipWaiting())
  );
});

// Activar — borrar cachés viejos
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// Fetch
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Solo manejar requests GET del mismo origen
  if (event.request.method !== 'GET' || url.origin !== location.origin) {
    return;
  }

  event.respondWith(
    caches.match(event.request).then(cached => {
      const fetchPromise = fetch(event.request).then(response => {
        // Solo cachear estáticos
        if (response.ok && event.request.url.includes('/comercio/static/')) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      }).catch(() => {
        if (event.request.destination === 'document') {
          return caches.match('/comercio/offline');
        }
      });
      return cached || fetchPromise;
    })
  );
});