{% load static %}
// Keeps the offline app's page and files on the phone so it opens with no signal.
const VERSION = "mitra-app-v1";
const SHELL = [
  "{% url 'field:app' %}",
  "{% static 'field/app.js' %}",
  "{% static 'field/app.css' %}",
  "{% static 'field/icon.svg' %}",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(VERSION).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== location.origin || url.pathname.includes("/api/")) return;
  if (!SHELL.includes(url.pathname)) return;
  // Try the network first so updates arrive, fall back to the saved copy with no signal.
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(VERSION).then((cache) => cache.put(request, copy));
        }
        return response;
      })
      .catch(() => caches.match(request))
  );
});
