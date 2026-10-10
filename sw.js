/* ============================================
   学习中心 Service Worker
   策略：
   - 应用本体(index.html/图标等) → 缓存优先，离线可打开
   - B站相关(player.bilibili.com/www.bilibili.com/api) → 完全不拦截，必须联网
   ============================================ */

const CACHE_NAME = "study-center-v1";

// 需要预缓存的本地资源
const PRECACHE = [
  "./",
  "./index.html",
  "./manifest.json",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((c) => c.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      ).then(() => self.clients.claim())
    )
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // 1) B站相关请求：绝不去缓存，直接走网络(视频/弹幕/接口都要实时)
  if (/bilibili\.com$/.test(url.hostname) ||
      /hdslb\.com$/.test(url.hostname) ||
      /bilivideo\.(com|cn)$/.test(url.hostname) ||
      /b23\.tv$/.test(url.hostname)) {
    return; // 不响应，交给浏览器默认网络行为
  }

  // 2) 仅处理同源 GET
  if (event.request.method !== "GET" || url.origin !== self.location.origin) {
    return;
  }

  // 3) 本地资源：缓存优先，后台更新
  event.respondWith(
    caches.match(event.request).then((cached) => {
      const fetching = fetch(event.request)
        .then((res) => {
          if (res && res.ok) {
            const clone = res.clone();
            caches.open(CACHE_NAME).then((c) => c.put(event.request, clone));
          }
          return res;
        })
        .catch(() => cached);

      return cached || fetching;
    })
  );
});
