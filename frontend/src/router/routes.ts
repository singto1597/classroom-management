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
  // 🌟 เพิ่มหน้า Onboarding (บังคับกรอกชื่อ)
  {
    path: '/onboarding',
    name: 'onboarding',
    component: () => import('@/views/auth/Onboarding.vue'),
    meta: { requiresAuth: true, title: routeTitles.onboarding },
  },
  {
    path: '/lobby',
    // 🧩 layout เป็น lazy chunk ด้วยเหตุผลเดียวกับ view — แต่ **บังคับ** ที่นี่:
    //    `MainLayout` import `stores/auth` ซึ่ง import `router/index` ที่ import ไฟล์นี้
    //    ⇒ ถ้า import แบบ static จะเกิดวงจรและ `routes` เป็น undefined ตอน `createRouter()`
    //    (รีโปนี้เจอบั๊กนี้จริงตอนเพิ่มเทสต์ router — ดู docs/skills.md)
    component: () => import('@/layouts/GlobalLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'lobby',
        component: () => import('@/views/Lobby.vue'),
        meta: { title: routeTitles.lobby },
      },
    ],
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    meta: { requiresAuth: true },
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: routeTitles.dashboard, navTab: 'home' },
      },
      {
        path: 'students',
        name: 'students',
        component: () => import('@/views/students/StudentList.vue'),
        meta: { title: routeTitles.students, navTab: 'students' },
      },
      {
        path: 'students/add',
        name: 'add-student',
        component: () => import('@/views/students/AddStudent.vue'),
        meta: { title: routeTitles['add-student'], navTab: 'students', headerBack: true },
      },
      {
        path: 'students/export',
        name: 'export-students',
        component: () => import('@/views/students/ExportStudent.vue'),
        meta: { title: routeTitles['export-students'], navTab: 'students', headerBack: true },
      },
      {
        path: 'students/:id',
        name: 'student-profile',
        component: () => import('@/views/students/StudentProfile.vue'),
        meta: { title: routeTitles['student-profile'], navTab: 'students', headerBack: true },
      },
      {
        path: 'students/:id/edit',
        name: 'edit-student',
        component: () => import('@/views/students/EditStudent.vue'),
        meta: { title: routeTitles['edit-student'], navTab: 'students', headerBack: true },
      },
      {
        path: 'roadmap',
        name: 'roadmap',
        component: () => import('@/views/roadmap/RoadmapView.vue'),
        meta: { title: routeTitles.roadmap, navTab: 'more' },
      },
      {
        path: 'schedules',
        name: 'schedules',
        component: () => import('@/views/schedules/ScheduleManager.vue'),
        meta: { title: routeTitles.schedules, navTab: 'more', headerBack: true },
      },
      {
        path: 'tasks',
        name: 'tasks',
        component: () => import('@/views/tasks/TaskList.vue'),
        meta: { title: routeTitles.tasks, navTab: 'tasks' },
      },
      {
        path: 'tasks/add',
        name: 'add-task',
        component: () => import('@/views/tasks/AddTask.vue'),
        meta: { title: routeTitles['add-task'], navTab: 'tasks', headerBack: true },
      },
      {
        path: 'tasks/:id/edit',
        name: 'edit-task',
        component: () => import('@/views/tasks/EditTask.vue'),
        meta: { title: routeTitles['edit-task'], navTab: 'tasks', headerBack: true },
      },
      {
        path: 'finance',
        name: 'finance-dashboard',
        component: () => import('@/views/finance/FinanceDashboard.vue'),
        meta: { title: routeTitles['finance-dashboard'], navTab: 'finance' },
      },
      {
        path: 'finance/settings',
        name: 'finance-settings',
        component: () => import('@/views/finance/FinanceSettings.vue'),
        meta: { title: routeTitles['finance-settings'], navTab: 'finance', headerBack: true },
      },
      {
        path: 'finance/transactions/add',
        name: 'finance-add-transaction',
        component: () => import('@/views/finance/AddTransaction.vue'),
        meta: { title: routeTitles['finance-add-transaction'], navTab: 'finance', headerBack: true },
      },
      {
        path: 'finance/transactions',
        name: 'finance-transaction-history',
        component: () => import('@/views/finance/TransactionHistory.vue'),
        meta: { title: routeTitles['finance-transaction-history'], navTab: 'finance', headerBack: true },
      },
      {
        path: 'finance/collections',
        name: 'finance-collections',
        component: () => import('@/views/finance/CollectionList.vue'),
        meta: { title: routeTitles['finance-collections'], navTab: 'finance', headerBack: true },
      },
      {
        path: 'finance/collections/:id',
        name: 'finance-collection-detail',
        component: () => import('@/views/finance/CollectionDetail.vue'),
        meta: { title: routeTitles['finance-collection-detail'], navTab: 'finance', headerBack: true },
      },
      {
        path: 'finance/debtors',
        name: 'finance-debtors',
        component: () => import('@/views/finance/DebtorList.vue'),
        meta: { title: routeTitles['finance-debtors'], navTab: 'finance', headerBack: true },
      },
      {
        // 💰 [F4] เงินรับล่วงหน้า — อ่านเปิดให้สมาชิก (ตรงกับ require_member ฝั่ง backend)
        // ส่วนปุ่มเขียน (เติม/หัก/ยกเลิก) gate ด้วย `canManageFinance` ในตัวหน้า
        // ⚠️ ห้าม gate ที่นี่ด้วย `isAdmin` — เหรัญญิกที่มี MANAGE_FINANCE จะเข้าหน้าไม่ได้
        //    (กับดักเดียวกับที่ DebtorList.vue อธิบายไว้เรื่องโมดัลรับเงิน)
        path: 'finance/credits',
        name: 'finance-credits',
        component: () => import('@/views/finance/CreditList.vue'),
        meta: { title: routeTitles['finance-credits'], navTab: 'finance', headerBack: true },
      },
      {
        // งบการเงิน — อ่านอย่างเดียว ไม่มี RBAC gate (ตรงกับ require_member ฝั่ง backend)
        path: 'finance/statements',
        name: 'finance-statements',
        component: () => import('@/views/finance/FinancialStatements.vue'),
        meta: { title: routeTitles['finance-statements'], navTab: 'finance', headerBack: true },
      },
      {
        // งบประมาณ — อ่านเปิดให้สมาชิก ปุ่มเขียน gate ด้วย canManageFinance ในตัวหน้า
        // (backend บังคับ MANAGE_FINANCE อยู่แล้ว — gate ที่นี่เป็นแค่การซ่อนปุ่ม)
        path: 'finance/budgets',
        name: 'finance-budgets',
        component: () => import('@/views/finance/BudgetList.vue'),
        meta: { title: routeTitles['finance-budgets'], navTab: 'finance', headerBack: true },
      },
      {
        // ทะเบียนเอกสาร — อ่านเปิดให้สมาชิก ปุ่มออกเอกสารอยู่ในหน้าที่ยื่นบริบทให้
        // (CollectionDetail สำหรับใบเสร็จ · DebtorList สำหรับใบแจ้งหนี้) ไม่ใช่ที่นี่
        path: 'finance/receipts',
        name: 'finance-receipts',
        component: () => import('@/views/finance/ReceiptList.vue'),
        meta: { title: routeTitles['finance-receipts'], navTab: 'finance', headerBack: true },
      },
      {
        // ⚠️ ต้องประกาศ **หลัง** `finance/receipts` — ไม่งั้น vue-router จะพยายาม
        //    match `receipts` เป็นค่า `:receiptNo` (route แรกที่ตรงกว่าชนะ แต่ลำดับ
        //    ของ static-before-dynamic คือสิ่งที่อ่านแล้วไม่ต้องเดา)
        // `receiptNo` เป็น string รูป REC-2569-0042 — backend validate pattern ให้อีกชั้น
        path: 'finance/receipts/:receiptNo',
        name: 'finance-receipt-detail',
        component: () => import('@/views/finance/ReceiptDetail.vue'),
        meta: { title: routeTitles['finance-receipt-detail'], navTab: 'finance', headerBack: true },
      },
      {
        path: 'discord-connect',
        name: 'DiscordConnect',
        component: () => import('@/components/discord/DiscordConnectGuide.vue'),
        meta: { title: routeTitles.DiscordConnect, navTab: 'more', headerBack: true },
      },
      {
        path: 'messages',
        name: 'send-message',
        component: () => import('@/views/actions/SendMessage.vue'),
        meta: { title: routeTitles['send-message'], navTab: 'more' },
      },
      {
        path: 'activities',
        name: 'activities',
        component: () => import('@/views/activities/ActivityList.vue'),
        meta: { title: routeTitles.activities, navTab: 'more' },
      },
      {
        path: 'activities/create',
        name: 'create-activity',
        component: () => import('@/views/activities/CreateActivity.vue'),
        meta: { title: routeTitles['create-activity'], navTab: 'more', headerBack: true },
      },
      {
        // 🔴 ต้องมาก่อน `activities/:id` ไม่งั้น 'compare' จะถูกตีความเป็น id ของกิจกรรม
        path: 'activities/compare',
        name: 'compare-activities',
        component: () => import('@/views/activities/CompareActivities.vue'),
        meta: { title: routeTitles['compare-activities'], navTab: 'more', headerBack: true },
      },
      {
        path: 'activities/:id/edit',
        name: 'edit-activity',
        component: () => import('@/views/activities/EditActivity.vue'),
        meta: { title: routeTitles['edit-activity'], navTab: 'more', headerBack: true },
      },
      {
        path: 'activities/:id/manage',
        name: 'manage-activity',
        component: () => import('@/views/activities/ManageActivity.vue'),
        meta: { title: routeTitles['manage-activity'], navTab: 'more', headerBack: true },
      },
      {
        path: 'activities/:id',
        name: 'activity-detail',
        component: () => import('@/views/activities/ActivityDetail.vue'),
        meta: { title: routeTitles['activity-detail'], navTab: 'more', headerBack: true },
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
