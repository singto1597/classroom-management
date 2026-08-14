import { createRouter, createWebHistory } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import MainLayout from '@/layouts/MainLayout.vue';
import GlobalLayout from '@/layouts/GlobalLayout.vue';

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/auth/Login.vue'),
      meta: { requiresAuth: false }
    },
    {
      path: '/auth/google/callback',
      name: 'google-callback',
      component: () => import('@/views/auth/GoogleCallback.vue'), 
      meta: { requiresAuth: false }
    },
    {
      path: '/auth/discord/callback',
      name: 'discord-callback',
      component: () => import('@/views/auth/DiscordCallback.vue'), 
      meta: { requiresAuth: false }
    },
    // 🌟 เพิ่มหน้า Onboarding (บังคับกรอกชื่อ)
    {
      path: '/onboarding',
      name: 'onboarding',
      component: () => import('@/views/auth/Onboarding.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/lobby',
      component: GlobalLayout,
      meta: { requiresAuth: true },
      children: [
        {
          path: '',
          name: 'lobby',
          component: () => import('@/views/Lobby.vue'),
        }
      ]
    },
    {
      path: '/',
      component: MainLayout,
      meta: { requiresAuth: true },
      redirect: '/dashboard',
      children: [
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('@/views/Dashboard.vue'),
        },
        {
          path: 'students',
          name: 'students', 
          component: () => import('@/views/students/StudentList.vue'),
        },
        {
          path: 'students/add',
          name: 'add-student',
          component: () => import('@/views/students/AddStudent.vue'),
        },
        {
          path: 'students/export',
          name: 'export-students',
          component: () => import('@/views/students/ExportStudent.vue'),
        },
        {
          path: 'students/:id',
          name: 'student-profile',
          component: () => import('@/views/students/StudentProfile.vue'),
        },
        {
          path: 'students/:id/edit',
          name: 'edit-student',
          component: () => import('@/views/students/EditStudent.vue'),
        },
        {
          path: 'roadmap',
          name: 'roadmap',
          component: () => import('@/views/roadmap/RoadmapView.vue'),
        },
        {
          path: 'schedules',
          name: 'schedules',
          component: () => import('@/views/schedules/ScheduleManager.vue'),
        },
        {
          path: 'tasks',
          name: 'tasks',
          component: () => import('@/views/tasks/TaskList.vue'),
        },
        {
          path: 'tasks/add',
          name: 'add-task',
          component: () => import('@/views/tasks/AddTask.vue'),
        },
        {
          path: 'tasks/:id/edit',
          name: 'edit-task',
          component: () => import('@/views/tasks/EditTask.vue'),
        },
        {
          path: 'finance',
          name: 'finance-dashboard',
          component: () => import('@/views/finance/FinanceDashboard.vue'),
        },
        {
          path: 'finance/settings',
          name: 'finance-settings',
          component: () => import('@/views/finance/FinanceSettings.vue'),
        },
        {
          path: 'finance/transactions/add',
          name: 'finance-add-transaction',
          component: () => import('@/views/finance/AddTransaction.vue'),
        },
        {
          path: 'finance/transactions',
          name: 'finance-transaction-history',
          component: () => import('@/views/finance/TransactionHistory.vue'),
        },
        {
          path: 'finance/collections',
          name: 'finance-collections',
          component: () => import('@/views/finance/CollectionList.vue'),
        },
        {
          path: 'finance/collections/:id',
          name: 'finance-collection-detail',
          component: () => import('@/views/finance/CollectionDetail.vue'),
        },
        {
          path: 'finance/debtors',
          name: 'finance-debtors',
          component: () => import('@/views/finance/DebtorList.vue'),
        },
        {
          path: 'discord-connect',
          name: 'DiscordConnect',
          component: () => import('@/components/discord/DiscordConnectGuide.vue'),
        },
        {
          path: 'messages',
          name: 'send-message',
          component: () => import('@/views/actions/SendMessage.vue'),
        },
        {
          path: 'activities',
          name: 'activities',
          component: () => import('@/views/activities/ActivityList.vue'),
        },
        {
          path: 'activities/create',
          name: 'create-activity',
          component: () => import('@/views/activities/CreateActivity.vue'),
        },
        {
          path: 'activities/:id',
          name: 'activity-detail',
          component: () => import('@/views/activities/ActivityDetail.vue'),
        },
      ]
    }
  ],
});

router.beforeEach((to, from) => {
  const authStore = useAuthStore();
  const isAuthenticated = authStore.isAuthenticated;
  const isOnboarded = authStore.isOnboarded;
  const currentRoomId = authStore.currentRoomId;
  const currentRole = authStore.currentRole; 

  if (to.meta.requiresAuth && !isAuthenticated) {
    return { name: 'login' };
  }
  if (to.path === '/login' && isAuthenticated) {
    return { name: 'lobby' };
  }

  if (isAuthenticated) {
    // 🔓 บังคับออนบอร์ด (กรอกโปรไฟล์) เฉพาะเมื่อเข้าพื้นที่ที่ต้องมีห้อง
    // แต่ lobby / callback / login ยังเข้าถึงได้ เพื่อให้เลือกห้องก่อน
    const isRoomlessGlobal = to.path.startsWith('/lobby') || to.path.startsWith('/auth/') || to.path === '/login';
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

  // 🌐 เส้นทาง Global (ไม่ต้องมีห้อง): lobby, login, onboarding, OAuth callback
  // (สำคัญ: callback ใช้ผูกบัญชีตอนยังไม่มีห้องได้ — ต้องไม่ถูก redirect ไป lobby)
  const isGlobalRoute = to.path.startsWith('/lobby') || to.path === '/login' || to.path === '/onboarding' || to.path.startsWith('/auth/');
  if (isAuthenticated && (!currentRoomId || !currentRole) && !isGlobalRoute) {
    return { name: 'lobby' };
  }
});

export default router;
