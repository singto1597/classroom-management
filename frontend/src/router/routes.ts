/**
 * 🗺️ ตาราง route ทั้งหมด — แยกออกจาก `index.ts` เพื่อให้ **ทดสอบได้**
 *
 * `index.ts` ตอนนี้เหลือแค่: สร้าง router + guard + ตั้งชื่อแท็บเบราว์เซอร์
 * ส่วนไฟล์นี้เป็นข้อมูลล้วน ⇒ เทสต์สามารถ import ไปไล่ตรวจได้ว่า
 * ทุก route มี `title`, เมนูชี้ path ที่มีจริง, และไม่มี path ซ้ำ
 * โดยไม่ต้อง mount layout หรือพึ่ง `createWebHistory`
 *
 * 📌 ชื่อหน้า (`title`) ดึงจาก `constants/nav.ts` → `routeTitles` — ห้ามพิมพ์
 *    ข้อความซ้ำตรงนี้ เพราะจะกลายเป็นสองที่ที่ไม่ตรงกันในอนาคต
 */

import type { RouteRecordRaw } from 'vue-router';
import { routeTitles } from '@/constants/nav';

export const routes: RouteRecordRaw[] = [
  // 🏠 หน้าแรกสาธารณะ — ไม่ต้องล็อกอิน
  {
    path: '/',
    name: 'landing',
    component: () => import('@/views/Landing.vue'),
    meta: { requiresAuth: false, title: routeTitles.landing },
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/auth/Login.vue'),
    meta: { requiresAuth: false, title: routeTitles.login },
  },
  {
    path: '/auth/google/callback',
    name: 'google-callback',
    component: () => import('@/views/auth/GoogleCallback.vue'),
    meta: { requiresAuth: false, title: routeTitles['google-callback'] },
  },
  {
    path: '/auth/discord/callback',
    name: 'discord-callback',
    component: () => import('@/views/auth/DiscordCallback.vue'),
    meta: { requiresAuth: false, title: routeTitles['discord-callback'] },
  },
  {
    /**
     * 🌐 เปลือก "นอกห้องเรียน" — เลือกห้อง · กรอกโปรไฟล์ · บัญชีส่วนกลาง
     *
     * ทุกอย่างข้างในเป็นหน้า **นอกห้องเรียน**: path ลูกเป็น absolute
     * (`/lobby`, `/onboarding`, `/account`, …) ⇒ URL เดิมไม่เปลี่ยน และเพิ่มหน้าใหม่
     * ได้โดยไม่ต้องแตะ path ของผู้ใช้ แต่ละหน้าเข้าถึงได้แม้ยังไม่เลือกห้อง
     * (router guard ปล่อยผ่านด้วย `isRoomlessGlobal` / `isGlobalRoute`)
     *
     * ⚠️ layout เป็น lazy chunk เพราะ `GlobalLayout` import `stores/auth`
     *    ซึ่ง import `router/index` ที่ import ไฟล์นี้ — static import จะเป็นวงจร
     */
    path: '/start',
    component: () => import('@/layouts/GlobalLayout.vue'),
    meta: { requiresAuth: true },
    redirect: '/lobby',
    children: [
      {
        path: '/lobby',
        name: 'lobby',
        component: () => import('@/views/Lobby.vue'),
        meta: { title: routeTitles.lobby, width: 'wide' },
      },
      {
        // 🌟 บังคับกรอกโปรไฟล์ครั้งแรก (ก่อนเข้าห้อง)
        path: '/onboarding',
        name: 'onboarding',
        component: () => import('@/views/auth/Onboarding.vue'),
        meta: { title: routeTitles.onboarding, width: 'form' },
      },
      {
        // 👤 บัญชีส่วนกลาง — profile, การเชื่อมต่อ OAuth, ออกจากระบบ
        //    ไม่ผูกกับห้องใดห้องหนึ่ง ⇒ ใช้ได้ก่อนเลือกห้องและเมื่อมีหลายห้อง
        path: '/account',
        name: 'account',
        component: () => import('@/views/account/AccountView.vue'),
        meta: { title: routeTitles.account, width: 'reading', headerBack: true },
      },
      {
        // ✏️ โหมดแก้ไขของฟอร์มเดียวกัน — ส่งกลับ `/account` หลังบันทึก
        path: '/account/profile',
        name: 'account-profile',
        component: () => import('@/views/auth/Onboarding.vue'),
        meta: { title: routeTitles['account-profile'], width: 'form', headerBack: true },
      },
    ],
  },
  {
    // 🧱 เปลือกแอปอยู่ใต้ `/app` แต่ **path ลูกเป็น absolute** (`/dashboard`, `/students`, …)
    //    ⇒ URL เดิมทั้งหมดไม่เปลี่ยน และ `/` ว่างให้หน้า landing สาธารณะ
    //    (vue-router อนุญาตให้ child path ขึ้นต้นด้วย `/` — path เต็มคือค่าของ child เอง)
    path: '/app',
    component: () => import('@/layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    redirect: '/dashboard',
    children: [
      {
        path: '/dashboard',
        name: 'dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: routeTitles.dashboard, navTab: 'home', width: 'wide' },
      },
      {
        path: '/more',
        name: 'more',
        component: () => import('@/views/More.vue'),
        meta: { title: routeTitles.more, navTab: 'more', width: 'reading' },
      },
      {
        path: '/students',
        name: 'students',
        component: () => import('@/views/students/StudentList.vue'),
        meta: {
          title: routeTitles.students,
          navTab: 'students',
          width: 'wide',
          fab: {
            to: '/students/add',
            label: 'เพิ่มนักเรียน',
            icon: 'bi-person-plus',
            permission: 'MANAGE_STUDENTS',
          },
        },
      },
      {
        path: '/students/add',
        name: 'add-student',
        component: () => import('@/views/students/AddStudent.vue'),
        meta: {
          title: routeTitles['add-student'],
          navTab: 'students',
          headerBack: true,
          width: 'form',
        },
      },
      {
        path: '/students/export',
        name: 'export-students',
        component: () => import('@/views/students/ExportStudent.vue'),
        meta: { title: routeTitles['export-students'], navTab: 'students', headerBack: true },
      },
      {
        path: '/students/:id',
        name: 'student-profile',
        component: () => import('@/views/students/StudentProfile.vue'),
        meta: {
          title: routeTitles['student-profile'],
          navTab: 'students',
          headerBack: true,
          width: 'reading',
        },
      },
      {
        path: '/students/:id/edit',
        name: 'edit-student',
        component: () => import('@/views/students/EditStudent.vue'),
        meta: {
          title: routeTitles['edit-student'],
          navTab: 'students',
          headerBack: true,
          width: 'form',
        },
      },
      {
        path: '/roadmap',
        name: 'roadmap',
        component: () => import('@/views/roadmap/RoadmapView.vue'),
        meta: { title: routeTitles.roadmap, navTab: 'more', width: 'wide' },
      },
      {
        path: '/schedules',
        name: 'schedules',
        component: () => import('@/views/schedules/ScheduleManager.vue'),
        meta: { title: routeTitles.schedules, navTab: 'more', headerBack: true, width: 'wide' },
      },
      {
        path: '/tasks',
        name: 'tasks',
        component: () => import('@/views/tasks/TaskList.vue'),
        meta: {
          title: routeTitles.tasks,
          navTab: 'tasks',
          width: 'wide',
          fab: {
            to: '/tasks/add',
            label: 'สร้างงานใหม่',
            icon: 'bi-plus-lg',
            permission: 'MANAGE_CLASSROOM_TASKS',
          },
        },
      },
      {
        path: '/tasks/add',
        name: 'add-task',
        component: () => import('@/views/tasks/AddTask.vue'),
        meta: {
          title: routeTitles['add-task'],
          navTab: 'tasks',
          headerBack: true,
          width: 'form',
        },
      },
      {
        path: '/tasks/:id/edit',
        name: 'edit-task',
        component: () => import('@/views/tasks/EditTask.vue'),
        meta: {
          title: routeTitles['edit-task'],
          navTab: 'tasks',
          headerBack: true,
          width: 'form',
        },
      },
      {
        path: '/finance',
        name: 'finance-dashboard',
        component: () => import('@/views/finance/FinanceDashboard.vue'),
        meta: {
          title: routeTitles['finance-dashboard'],
          navTab: 'finance',
          width: 'wide',
          fab: {
            to: '/finance/transactions/add',
            label: 'บันทึกรายการเงิน',
            icon: 'bi-plus-lg',
            permission: 'MANAGE_FINANCE',
          },
        },
      },
      {
        path: '/finance/settings',
        name: 'finance-settings',
        component: () => import('@/views/finance/FinanceSettings.vue'),
        meta: {
          title: routeTitles['finance-settings'],
          navTab: 'finance',
          headerBack: true,
          width: 'reading',
        },
      },
      {
        path: '/finance/transactions/add',
        name: 'finance-add-transaction',
        component: () => import('@/views/finance/AddTransaction.vue'),
        meta: {
          title: routeTitles['finance-add-transaction'],
          navTab: 'finance',
          headerBack: true,
          width: 'form',
        },
      },
      {
        path: '/finance/transactions',
        name: 'finance-transaction-history',
        component: () => import('@/views/finance/TransactionHistory.vue'),
        meta: {
          title: routeTitles['finance-transaction-history'],
          navTab: 'finance',
          headerBack: true,
          width: 'wide',
        },
      },
      {
        path: '/finance/collections',
        name: 'finance-collections',
        component: () => import('@/views/finance/CollectionList.vue'),
        meta: {
          title: routeTitles['finance-collections'],
          navTab: 'finance',
          headerBack: true,
          width: 'wide',
        },
      },
      {
        path: '/finance/collections/:id',
        name: 'finance-collection-detail',
        component: () => import('@/views/finance/CollectionDetail.vue'),
        meta: {
          title: routeTitles['finance-collection-detail'],
          navTab: 'finance',
          headerBack: true,
          width: 'wide',
        },
      },
      {
        path: '/finance/debtors',
        name: 'finance-debtors',
        component: () => import('@/views/finance/DebtorList.vue'),
        meta: {
          title: routeTitles['finance-debtors'],
          navTab: 'finance',
          headerBack: true,
          width: 'wide',
        },
      },
      {
        // 💰 หนี้ของ **ตัวเอง** — ปลายทางของการ์ด "บิลค้างชำระ" บนหน้าหลัก (P3.2)
        // ⚠️ ต้องแยกจาก `finance/debtors` (ทุกคนในห้อง) — การ์ดนับเฉพาะบิลของฉัน
        //    ⇒ ปลายทางต้องกรองชุดเดียวกัน ไม่งั้นจำนวนไม่ตรงกับที่กดมา
        path: '/finance/my-debts',
        name: 'finance-my-debts',
        component: () => import('@/views/finance/MyDebts.vue'),
        meta: {
          title: routeTitles['finance-my-debts'],
          navTab: 'finance',
          headerBack: true,
          width: 'wide',
        },
      },
      {
        // 💰 [F4] เงินรับล่วงหน้า — อ่านเปิดให้สมาชิก (ตรงกับ require_member ฝั่ง backend)
        // ส่วนปุ่มเขียน (เติม/หัก/ยกเลิก) gate ด้วย `canManageFinance` ในตัวหน้า
        // ⚠️ ห้าม gate ที่นี่ด้วย `isAdmin` — เหรัญญิกที่มี MANAGE_FINANCE จะเข้าหน้าไม่ได้
        //    (กับดักเดียวกับที่ DebtorList.vue อธิบายไว้เรื่องโมดัลรับเงิน)
        path: '/finance/credits',
        name: 'finance-credits',
        component: () => import('@/views/finance/CreditList.vue'),
        meta: {
          title: routeTitles['finance-credits'],
          navTab: 'finance',
          headerBack: true,
          width: 'wide',
        },
      },
      {
        // งบการเงิน — อ่านอย่างเดียว ไม่มี RBAC gate (ตรงกับ require_member ฝั่ง backend)
        path: '/finance/statements',
        name: 'finance-statements',
        component: () => import('@/views/finance/FinancialStatements.vue'),
        meta: {
          title: routeTitles['finance-statements'],
          navTab: 'finance',
          headerBack: true,
          width: 'wide',
        },
      },
      {
        // งบประมาณ — อ่านเปิดให้สมาชิก ปุ่มเขียน gate ด้วย canManageFinance ในตัวหน้า
        // (backend บังคับ MANAGE_FINANCE อยู่แล้ว — gate ที่นี่เป็นแค่การซ่อนปุ่ม)
        path: '/finance/budgets',
        name: 'finance-budgets',
        component: () => import('@/views/finance/BudgetList.vue'),
        meta: {
          title: routeTitles['finance-budgets'],
          navTab: 'finance',
          headerBack: true,
          width: 'wide',
        },
      },
      {
        // ทะเบียนเอกสาร — อ่านเปิดให้สมาชิก ปุ่มออกเอกสารอยู่ในหน้าที่ยื่นบริบทให้
        // (CollectionDetail สำหรับใบเสร็จ · DebtorList สำหรับใบแจ้งหนี้) ไม่ใช่ที่นี่
        path: '/finance/receipts',
        name: 'finance-receipts',
        component: () => import('@/views/finance/ReceiptList.vue'),
        meta: {
          title: routeTitles['finance-receipts'],
          navTab: 'finance',
          headerBack: true,
          width: 'wide',
        },
      },
      {
        // ⚠️ ต้องประกาศ **หลัง** `finance/receipts` — ไม่งั้น vue-router จะพยายาม
        //    match `receipts` เป็นค่า `:receiptNo` (route แรกที่ตรงกว่าชนะ แต่ลำดับ
        //    ของ static-before-dynamic คือสิ่งที่อ่านแล้วไม่ต้องเดา)
        // `receiptNo` เป็น string รูป REC-2569-0042 — backend validate pattern ให้อีกชั้น
        path: '/finance/receipts/:receiptNo',
        name: 'finance-receipt-detail',
        component: () => import('@/views/finance/ReceiptDetail.vue'),
        meta: {
          title: routeTitles['finance-receipt-detail'],
          navTab: 'finance',
          headerBack: true,
          width: 'wide',
        },
      },
      {
        path: '/discord-connect',
        name: 'DiscordConnect',
        component: () => import('@/components/discord/DiscordConnectGuide.vue'),
        meta: {
          title: routeTitles.DiscordConnect,
          navTab: 'more',
          headerBack: true,
          width: 'reading',
        },
      },
      {
        // 👤 "ของฉัน" — ไทม์ไลน์ส่วนตัว + สถิติ + รายการที่บันทึกไว้ (P3.3 + P3.4)
        //    ปลายทางของ `/me/activity` ที่หน้าแรก/ประกาศลิงก์มา
        path: '/me/activity',
        name: 'my-activity',
        component: () => import('@/views/me/MyActivity.vue'),
        meta: { title: routeTitles['my-activity'], navTab: 'more', width: 'wide' },
      },
      {
        // 📢 หน้ารายการประกาศ — ปลายทางของ deep link ที่ backend สร้างใน
        // `announcement_service.create_announcement` (`url=f"/announcements/{id}"`)
        path: '/announcements',
        name: 'announcements',
        component: () => import('@/views/announcements/AnnouncementList.vue'),
        meta: { title: routeTitles.announcements, navTab: 'more', width: 'wide' },
      },
      {
        path: '/announcements/:id',
        name: 'announcement-detail',
        component: () => import('@/views/announcements/AnnouncementDetail.vue'),
        meta: {
          title: routeTitles['announcement-detail'],
          navTab: 'more',
          headerBack: true,
          width: 'wide',
        },
      },
      {
        // 🔔 ตั้งค่าการแจ้งเตือน — อุปกรณ์นี้ · กลุ่ม · ช่วงงดรบกวน
        path: '/settings/notifications',
        name: 'notification-settings',
        component: () => import('@/views/settings/NotificationSettings.vue'),
        meta: {
          title: routeTitles['notification-settings'],
          navTab: 'more',
          headerBack: true,
          width: 'reading',
        },
      },
      {
        // 🗓️ P5 — ปีการศึกษา/เทอม: ปฏิทินของห้อง ไม่ใช่การย้ายนักเรียนขึ้นชั้น
        //    สมาชิกอ่านได้ทุกคน (ใช้กรองสถิติ) แต่ฟอร์มเขียนซ่อนเมื่อไม่มีสิทธิ์
        path: '/settings/academic-periods',
        name: 'academic-periods',
        component: () => import('@/views/settings/AcademicPeriods.vue'),
        meta: {
          title: routeTitles['academic-periods'],
          navTab: 'more',
          headerBack: true,
          width: 'reading',
        },
      },
      {
        // 🔍 P6.2 — บันทึกกิจกรรม: ต้องมี VIEW_AUDIT_LOGS (backend ตอบ 403 เอง)
        //    อยู่ภายใต้ "เพิ่มเติม" เพราะเป็นหน้าตรวจย้อน ไม่ใช่หน้าใช้งานประจำวัน
        path: '/settings/audit-logs',
        name: 'audit-logs',
        component: () => import('@/views/settings/AuditLogs.vue'),
        meta: {
          title: routeTitles['audit-logs'],
          navTab: 'more',
          headerBack: true,
          width: 'wide',
        },
      },
      {
        path: '/messages',
        name: 'send-message',
        component: () => import('@/views/actions/SendMessage.vue'),
        meta: {
          title: routeTitles['send-message'],
          navTab: 'more',
          headerBack: true,
          width: 'form',
        },
      },
      {
        path: '/activities',
        name: 'activities',
        component: () => import('@/views/activities/ActivityList.vue'),
        meta: {
          title: routeTitles.activities,
          navTab: 'more',
          width: 'wide',
          fab: {
            to: '/activities/create',
            label: 'สร้างกิจกรรม',
            icon: 'bi-plus-lg',
            permission: 'MANAGE_ACTIVITIES',
          },
        },
      },
      {
        path: '/activities/create',
        name: 'create-activity',
        component: () => import('@/views/activities/CreateActivity.vue'),
        meta: {
          title: routeTitles['create-activity'],
          navTab: 'more',
          headerBack: true,
          width: 'form',
        },
      },
      {
        // 🔴 ต้องมาก่อน `activities/:id` ไม่งั้น 'compare' จะถูกตีความเป็น id ของกิจกรรม
        path: '/activities/compare',
        name: 'compare-activities',
        component: () => import('@/views/activities/CompareActivities.vue'),
        meta: {
          title: routeTitles['compare-activities'],
          navTab: 'more',
          headerBack: true,
          width: 'wide',
        },
      },
      {
        path: '/activities/:id/edit',
        name: 'edit-activity',
        component: () => import('@/views/activities/EditActivity.vue'),
        meta: {
          title: routeTitles['edit-activity'],
          navTab: 'more',
          headerBack: true,
          width: 'form',
        },
      },
      {
        path: '/activities/:id/manage',
        name: 'manage-activity',
        component: () => import('@/views/activities/ManageActivity.vue'),
        meta: {
          title: routeTitles['manage-activity'],
          navTab: 'more',
          headerBack: true,
          width: 'wide',
        },
      },
      {
        path: '/activities/:id',
        name: 'activity-detail',
        component: () => import('@/views/activities/ActivityDetail.vue'),
        meta: {
          title: routeTitles['activity-detail'],
          navTab: 'more',
          headerBack: true,
          width: 'wide',
        },
      },
    ],
  },
  // 🕳️ ต้องเป็นรายการสุดท้ายเสมอ — match ทุก path ที่เหลือ
  // (ถ้าอยู่ก่อน route อื่นจะกลืนทุกหน้า ⇒ หน้าจอขาว/404 ทั้งระบบ)
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFound.vue'),
    // เปิดให้เห็นได้แม้ยังไม่ล็อกอิน — การบอกว่า "ไม่มีหน้านี้" ไม่ได้รั่วข้อมูล
    // และผู้ใช้ที่พิมพ์ URL ผิดจะได้คำตอบทันที ไม่ใช่โดนเด้งไปหน้า login
    meta: { requiresAuth: false, title: routeTitles['not-found'] },
  },
];

export default routes;
