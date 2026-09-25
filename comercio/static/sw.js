const CACHE_NAME = 'comercio-v3';
const URLS_A_CACHEAR = [
  '/comercio/static/css/app.css',
  '/comercio/static/js/app.js',
  '/comercio/static/manifest.json',
  '/comercio/static/img/icon-192.png',
  '/comercio/static/img/icon-512.png'
];

// ===== INSTALAR =====
// Cachea archivo por archivo. Si uno falla, los demás siguen.
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

// ===== ACTIVAR =====
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// ===== FETCH =====
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  if (event.request.method !== 'GET' || url.origin !== location.origin) {
    return;
  }

  event.respondWith(
    caches.match(event.request).then(cached => {
      const fetchPromise = fetch(event.request).then(response => {
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

// ===== NOTIFICACIONES PUSH =====
self.addEventListener('push', function(event) {
  let data = {
    title: 'Nueva transmisión en vivo',
    body: '¡Estamos en vivo!',
    icon: '/comercio/static/img/icon-192.png',
    url: '/comercio/transmisiones'
  };

  try {
    if (event.data) {
      const parsed = event.data.json();
      data = { ...data, ...parsed };
    }
  } catch (e) {}

  const options = {
    body: data.body,
    icon: data.icon,
    badge: '/comercio/static/img/icon-192.png',
    data: {
      url: data.url
    }
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  const url = event.notification.data.url || '/comercio/transmisiones';

  event.waitUntil(
    clients.matchAll({ type: 'window' }).then(windowClients => {
      for (let client of windowClients) {
        if (client.url === url && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(url);
      }
    })
  );
});