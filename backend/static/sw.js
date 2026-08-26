// 记忆漩涡 MemoryVortex · Service Worker v8
// 缓存策略：全部资源网络优先（保证代码更新即时生效），离线才用缓存
var CACHE_NAME = 'memory-vortex-v8';
var APP_SHELL = [
  './memory-vortex-prototype-v2-api.html',
  './localdb.js',
  './manifest.json',
  './icon.svg',
  './test_data.json'
];

self.addEventListener('install', function(e) {
  e.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.addAll(APP_SHELL).catch(function(err) {
        console.warn('[SW] 部分资源预缓存失败:', err);
      });
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(names) {
      return Promise.all(
        names.filter(function(n) { return n !== CACHE_NAME; })
          .map(function(n) { return caches.delete(n); })
      );
    }).then(function() {
      // 清除所有旧缓存后，再确认当前缓存
      return caches.open(CACHE_NAME);
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', function(e) {
  var url = new URL(e.request.url);

  // 只拦截同源 GET 请求
  if (e.request.method !== 'GET') return;

  // /api/* 和 /uploads/* 请求不走缓存
  if (url.pathname.indexOf('/api/') === 0 || url.pathname.indexOf('/uploads/') === 0) {
    return;
  }

  // ★ 全部资源统一网络优先策略 ★
  // 保证任何代码更新都能即时生效，只在离线时回退缓存
  e.respondWith(
    fetch(e.request).then(function(res) {
      if (res.ok && url.origin === self.location.origin) {
        var clone = res.clone();
        caches.open(CACHE_NAME).then(function(c) { c.put(e.request, clone); });
      }
      return res;
    }).catch(function() {
      return caches.match(e.request).then(function(cached) {
        if (cached) return cached;
        // 离线 + 无缓存 → 回退到主页面
        if (url.pathname === '/' || url.pathname.endsWith('.html')) {
          return caches.match('./memory-vortex-prototype-v2-api.html');
        }
        return new Response('离线且无缓存资源', { status: 503, statusText: 'Offline' });
      });
    })
  );
});
