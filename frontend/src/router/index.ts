import { createRouter, createWebHistory } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { pageTitle } from '@/router/meta';
import { routes } from '@/router/routes';
import { toLobbyFor } from '@/router/unavailable';

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
});

router.beforeEach((to, _from) => {
  const authStore = useAuthStore();
  const isAuthenticated = authStore.isAuthenticated;
  const isOnboarded = authStore.isOnboarded;
  const currentRoomId = authStore.currentRoomId;
  const currentRole = authStore.currentRole;

  // 404 ไม่ต้องล็อกอิน — "ไม่มีหน้านี้" ไม่ได้รั่วข้อมูลใด ๆ และผู้ที่พิมพ์ URL ผิด
  // ควรได้คำตอบทันที ไม่ใช่ถูกพาไปหน้า login เพื่อกลับมาเจอ 404 อีกครั้ง
  const isNotFound = to.name === 'not-found';

  if (to.meta.requiresAuth && !isAuthenticated) {
    return { name: 'login' };
  }
  if (to.path === '/login' && isAuthenticated) {
    return { name: 'lobby' };
  }

  if (isAuthenticated) {
    // 🔓 บังคับออนบอร์ด (กรอกโปรไฟล์) เฉพาะเมื่อเข้าพื้นที่ที่ต้องมีห้อง
    // แต่ lobby / callback / login / 404 ยังเข้าถึงได้ เพื่อให้เลือกห้องก่อน
    const isRoomlessGlobal =
      to.path.startsWith('/lobby') ||
      to.path.startsWith('/auth/') ||
      to.path === '/login' ||
      isNotFound;
    if (!isOnboarded && !isRoomlessGlobal) {
      if (to.name !== 'onboarding') {
        return { name: 'onboarding' };
      }
    } else {
      if (to.name === 'onboarding' && isOnboarded) {
        return { name: 'lobby' };
      }
    }
  }

  // 🌐 เส้นทาง Global (ไม่ต้องมีห้อง): lobby, login, onboarding, OAuth callback, 404
  // (สำคัญ: callback ใช้ผูกบัญชีตอนยังไม่มีห้องได้ — ต้องไม่ถูก redirect ไป lobby)
  const isGlobalRoute =
    to.path.startsWith('/lobby') ||
    to.path === '/login' ||
    to.path === '/onboarding' ||
    to.path.startsWith('/auth/') ||
    isNotFound;
  if (isAuthenticated && (!currentRoomId || !currentRole) && !isGlobalRoute) {
    // 🚧 พกปลายทางเดิมไปด้วย (`/lobby?next=...`) ⇒ เลือกห้องเสร็จกลับมาที่หน้าที่ตั้งใจ
    //    (ต้องผ่าน `safeRedirect()` เท่านั้น — ดู router/unavailable.ts)
    return toLobbyFor(to.fullPath);
  }
});

// ชื่อแท็บเบราว์เซอร์มาจาก `meta.title` ที่เดียว — ทุก route ประกาศไว้แล้ว
// (เทสต์ `router/__tests__/routes.spec.ts` กันไม่ให้มี route ที่ลืม)
router.afterEach((to) => {
  if (typeof document !== 'undefined') {
    document.title = pageTitle(to.meta.title);
  }
});

export default router;
