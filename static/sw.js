// Service worker: keeps the app shell on the phone so it opens instantly.
// Commands (/api/...) always go to the Pi live and are never cached.
const CACHE = "spooky-v12";
const SHELL = [
  "/remote", "/",
  "/static/style.css", "/static/remote.css", "/static/remote.js", "/static/app.js", "/static/collapse.js",
  "/manifest.webmanifest",
  "/static/icons/icon-192.png", "/static/icons/apple-touch-icon.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  // Network first so updates show up right away; fall back to the cached copy if the Pi is unreachable.
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      })
      .catch(() => caches.match(e.request, { ignoreSearch: true }))
  );
});
