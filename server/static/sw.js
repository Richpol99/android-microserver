// Moto Music Ultra-Fast Media Proxy Service Worker
const CACHE_NAME = 'motomusic-offline-tracks';

self.addEventListener('install', (event) => {
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Intercept client-side stream caching
    if (url.pathname.startsWith('/sw-stream-proxy/')) {
        const targetMediaUrl = decodeURIComponent(url.searchParams.get('url') || '');
        const trackId = url.searchParams.get('id') || '';

        if (!targetMediaUrl) {
            return event.respondWith(fetch(event.request));
        }

        event.respondWith((async () => {
            try {
                // Fetch directly from Google CDN bypassing page CORS restrictions
                const mediaResponse = await fetch(targetMediaUrl, {
                    mode: 'cors',
                    credentials: 'omit'
                });

                if (mediaResponse && mediaResponse.ok) {
                    const cache = await caches.open(CACHE_NAME);
                    if (trackId) {
                        cache.put(`/api/music/url?id=${trackId}`, mediaResponse.clone());
                    }
                    return mediaResponse;
                }
            } catch (err) {
                console.warn("SW Direct fetch error:", err);
            }
            return fetch(event.request);
        })());
    }
});
