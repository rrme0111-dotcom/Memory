// 记忆漩涡 MemoryVortex · Service Worker
// 缓存策略：app shell 预缓存，test_data.json 运行时缓存，IndexedDB 提供数据
var CACHE_NAME = 'memory-vortex-v1';
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
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', function(e) {
  var url = new URL(e.request.url);

  // 只拦截同源 GET 请求
  if (e.request.method !== 'GET') return;

  // /api/* 和 /uploads/* 请求不走缓存（由 localdb.js 的 fetch 拦截处理）
  if (url.pathname.indexOf('/api/') === 0 || url.pathname.indexOf('/uploads/') === 0) {
    return;
  }

  // test_data.json：网络优先，失败回退缓存
  if (url.pathname.indexOf('test_data.json') >= 0) {
    e.respondWith(
      fetch(e.request).then(function(res) {
        var clone = res.clone();
        caches.open(CACHE_NAME).then(function(c) { c.put(e.request, clone); });
        return res;
      }).catch(function() {
        return caches.match(e.request);
      })
    );
    return;
  }

  // 其他同源请求：缓存优先，回退网络
  e.respondWith(
    caches.match(e.request).then(function(cached) {
      return cached || fetch(e.request).then(function(res) {
        // 缓存新资源（仅同源）
        if (res.ok && url.origin === self.location.origin) {
          var clone = res.clone();
          caches.open(CACHE_NAME).then(function(c) { c.put(e.request, clone); });
        }
        return res;
      }).catch(function() {
        // 离线回退到主页面
        if (url.pathname.endsWith('.html') || url.pathname === '/') {
          return caches.match('./memory-vortex-prototype-v2-api.html');
        }
      });
    })
  );
});
