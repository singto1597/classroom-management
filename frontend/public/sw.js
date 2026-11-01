/**
 * 🔔 SYNCROOM Service Worker — เปลือกแอป + รับ push
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ขอบเขตที่ตั้งใจให้แคบ
 * ═══════════════════════════════════════════════════════════════════════════
 *   ✅ แคช "เปลือกแอป" — index.html + ไฟล์ /assets/* ที่มี hash (เปลี่ยนชื่อทุก build)
 *   ✅ แสดง notification จาก push + จัดการคลิก (deep link)
 *   ⛔ **ห้ามแคช /api/ เด็ดขาด** — เครื่องอาจถูกใช้ร่วมกัน (ห้องคอมพิวเตอร์)
 *      ถ้าแคช response ที่มีข้อมูลผู้ใช้ไว้ ผู้ใช้คนถัดไปที่ล็อกอินจะอ่านของคนก่อนได้
 *   ⛔ ไม่มี offline cache ของข้อมูล (ตั้งใจ — ดู P2 ในแผน: A7 = non-goal)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ทำไมใช้ network-first กับทุก navigation
 * ═══════════════════════════════════════════════════════════════════════════
 * `index.html` ชี้ไปยัง `/assets/<hash>.js` ที่เปลี่ยนทุก deploy ⇒ ถ้าเสิร์ฟ
 * index.html เก่าจากแคชหลัง deploy ผู้ใช้จะขอไฟล์ที่เซิร์ฟเวอร์ไม่มีแล้ว (404)
 * ⇒ เอาของเน็ตก่อนเสมอ แล้วค่อยอัปเดตแคชเงียบ ๆ · ใช้แคชเฉพาะตอนออฟไลน์
 *
 * ⚠️ ไฟล์นี้ **ไม่มี bundler แตะ** (อยู่ใน public/) — ห้าม import/ใช้ syntax ที่
 *    เบราว์เซอร์เก่าไม่รองรับ และต้องอ่านได้ด้วยตาว่ามันแคชอะไรบ้าง
 */

const SW_VERSION = 'v1';

/* ชื่อ cache มีเวอร์ชันในชื่อ ⇒ activate ลบของรุ่นก่อนได้แบบเหมารวม */
const SHELL_CACHE = `syncroom-shell-${SW_VERSION}`;
const STATIC_CACHE = `syncroom-static-${SW_VERSION}`;

/* คีย์คงที่ของเปลือกแอป — แม้ผู้ใช้เข้าที่ /dashboard แคชจะเก็บที่คีย์เดียว */
const SHELL_URL = '/index.html';

/* ไฟล์ที่ต้องมีก่อนเปิดแอปได้ (เส้นทางสั้นและไม่ขึ้นกับ build hash) */
const PRECACHE_URLS = [SHELL_URL, '/manifest.webmanifest', '/icons/icon-192.png'];

/* ═══════════════════════════════════════════════════════════════════════════
 * install / activate
 * ═══════════════════════════════════════════════════════════════════════════ */
self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL_CACHE);
      // addAll ล้มทั้งชุดถ้าไฟล์ใดไฟล์หนึ่งพัง ⇒ ใส่ทีละไฟล์แล้วทนที่พลาด
      await Promise.all(
        PRECACHE_URLS.map((url) =>
          cache.add(new Request(url, { cache: 'reload' })).catch((err) => {
            console.warn('[sw] precache ไม่สำเร็จ:', url, err);
          }),
        ),
      );
      // รับงานทันทีไม่ต้องรอแท็บเก่าปิด — ตัว push handler ต้องเป็นรุ่นล่าสุดเสมอ
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keep = new Set([SHELL_CACHE, STATIC_CACHE]);
      const names = await caches.keys();
      await Promise.all(names.filter((n) => !keep.has(n)).map((n) => caches.delete(n)));
      await self.clients.claim();
    })(),
  );
});

/* หน้าเว็บสั่งให้รุ่นใหม่เข้าทำงาน (ปุ่ม "อัปเดต") — เผื่ออนาคตไม่ต้องรอปิดแท็บ */
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting();
});

/* ═══════════════════════════════════════════════════════════════════════════
 * fetch — แคชเฉพาะ "ของที่ไม่ใช่ข้อมูลผู้ใช้"
 * ═══════════════════════════════════════════════════════════════════════════ */
self.addEventListener('fetch', (event) => {
  const request = event.request;

  // เฉพาะ GET เท่านั้น — POST/PATCH/DELETE ห้ามแคชแม้แต่คิด
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // ต้นทางอื่น (Google Fonts ฯลฯ) ปล่อยให้เบราว์เซอร์จัดการ
  if (url.origin !== self.location.origin) return;

  // ★ เส้นแบ่งที่สำคัญที่สุดของไฟล์นี้
  if (url.pathname.startsWith('/api/')) return;

  // ตัว SW เองต้องไม่ถูกแคช (nginx ตั้ง no-store ให้แล้ว)
  if (url.pathname === '/sw.js') return;

  if (request.mode === 'navigate') {
    event.respondWith(networkFirstShell(request));
    return;
  }

  // ไฟล์ build มี hash ในชื่อ ⇒ เนื้อหาเปลี่ยนไม่ได้ เก็บได้ตลอด
  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(cacheFirst(request, STATIC_CACHE));
    return;
  }

  // รูป/ไอคอน/manifest — ของเก่าใช้ได้ ถ้ามีของใหม่ก็อัปเดตเงียบ ๆ
  event.respondWith(staleWhileRevalidate(request, STATIC_CACHE));
});

async function networkFirstShell(request) {
  const cache = await caches.open(SHELL_CACHE);
  try {
    const response = await fetch(request);
    // เก็บเฉพาะ response ปกติ — `cache.put` โยน TypeError ทันทีถ้า response
    // ผ่านการ redirect มา (`redirected === true`) จึงต้องเช็คก่อน
    if (response && response.ok && response.type === 'basic' && !response.redirected) {
      cache.put(SHELL_URL, response.clone()).catch(() => {});
    }
    return response;
  } catch (err) {
    const cached = await cache.match(SHELL_URL);
    if (cached) return cached;
    return new Response(
      '<!doctype html><html lang="th"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
        '<title>ออฟไลน์ — SYNCROOM</title>' +
        '<body style="margin:0;display:grid;place-items:center;min-height:100vh;font-family:sans-serif;background:#FAFAF9;color:#1C1917">' +
        '<div style="text-align:center;padding:24px"><h1 style="font-size:18px">ยังต่ออินเทอร์เน็ตไม่ได้</h1>' +
        '<p style="color:#57534E;font-size:14px">SYNCROOM ต้องใช้อินเทอร์เน็ตในการโหลดข้อมูลของห้อง</p></div></body></html>',
      { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } },
    );
  }
}

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response && response.ok) cache.put(request, response.clone()).catch(() => {});
  return response;
}

async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  const network = fetch(request)
    .then((response) => {
      if (response && response.ok) cache.put(request, response.clone()).catch(() => {});
      return response;
    })
    .catch(() => cached);
  return cached || network;
}

/* ═══════════════════════════════════════════════════════════════════════════
 * push — แสดงการแจ้งเตือนบนอุปกรณ์
 * ═══════════════════════════════════════════════════════════════════════════
 * payload มาจาก `backend/services/push_service.build_payload()`:
 *   { id, title, body, url, tag, group, priority, created_at }
 */
self.addEventListener('push', (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch (err) {
    // payload ไม่ใช่ JSON — แสดงเป็นข้อความดิบดีกว่าเงียบหาย
    payload = { body: event.data ? event.data.text() : '' };
  }

  const title = payload.title || 'SYNCROOM';
  const options = {
    body: payload.body || '',
    icon: '/icons/icon-192.png',
    badge: '/icons/icon-192.png',
    // deep link ต้องเป็นเส้นทางภายใน origin เดียวกันเท่านั้น (กัน open redirect)
    data: { url: safePath(payload.url) },
    tag: payload.tag || undefined,
    requireInteraction: payload.priority === 'urgent',
  };

  // renotify ใช้ได้เฉพาะเมื่อมี tag เท่านั้น ไม่งั้น Chrome โยน TypeError
  if (payload.tag) options.renotify = true;

  event.waitUntil(self.registration.showNotification(title, options));
});

/**
 * รับเฉพาะ path ภายใน origin — คืน '/' เมื่อรูปทรงไม่ถูก
 * (`//evil.com` และ `https://evil.com` ต้องไม่ผ่าน)
 */
function safePath(raw) {
  if (typeof raw !== 'string' || raw.length === 0) return '/';
  if (!raw.startsWith('/') || raw.startsWith('//')) return '/';
  return raw;
}

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = new URL(safePath(event.notification.data && event.notification.data.url), self.location.origin);

  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      const existing = windows.find((client) => new URL(client.url).origin === target.origin);
      if (existing) {
        await existing.focus();
        // ให้แอปพาไปหน้าที่ลิงก์ชี้โดยไม่ต้องโหลดใหม่ทั้งแอป
        if ('navigate' in existing) {
          try {
            await existing.navigate(target.href);
          } catch (err) {
            /* navigate ถูกบล็อกได้ในบางเบราว์เซอร์ — focus เฉย ๆ ก็เพียงพอ */
          }
        }
        return;
      }
      await self.clients.openWindow(target.href);
    })(),
  );
});

/* ═══════════════════════════════════════════════════════════════════════════
 * subscription เปลี่ยน (เบราว์เซอร์หมุน endpoint เอง)
 * ═══════════════════════════════════════════════════════════════════════════
 * SW สร้าง subscription ใหม่เองไม่ได้ถ้าไม่มี VAPID key (และไม่ควรถือ key)
 * ⇒ บอกหน้าเว็บที่เปิดอยู่ให้ลงทะเบียนใหม่ด้วยคีย์ที่ดึงจาก backend
 */
self.addEventListener('pushsubscriptionchange', (event) => {
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      windows.forEach((client) => client.postMessage({ type: 'PUSH_SUBSCRIPTION_CHANGED' }));
    })(),
  );
});
