self.addEventListener('install', event => {
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys => Promise.all(keys.map(k => caches.delete(k))))
            .then(() => self.registration.unregister())
    );
    self.clients.claim();
});

self.addEventListener('fetch', event => {
    // Network direct for all requests - no caching
    return;
});
