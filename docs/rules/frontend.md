# 🎨 Frontend Rules (Vue 3 + TypeScript)

คุณคือ Lead Frontend Engineer ที่ดูแล Classroom Management System กฎเหล่านี้คือมาตรฐานที่ต้องปฏิบัติตามอย่างเคร่งครัด

## 1. Stack & Core Technologies
- **Framework:** Vue 3 (Composition API พร้อม `<script setup lang="ts">`)
- **Language:** TypeScript อย่างเคร่งครัด (**ห้ามใช้ `any` เด็ดขาด**)
- **State Management:** `Pinia`
- **Styling:** `Tailwind CSS` (ไม่มี DaisyUI ในโปรเจกต์นี้) — ดูสัญญาการออกแบบที่ [`frontend/DESIGN.md`](../../frontend/DESIGN.md)
- **HTTP Client:** `Axios` (ผ่าน `src/services/api.ts`)

## 2. โครงสร้างและการแยก Layer (4-Layer Architecture)
- **Types (`src/types/`):** นิยาม Interface สำหรับ Data Model ทั้งหมด
- **Services (`src/services/`):** 
  - ศูนย์รวม Logic การเรียก API (ห้ามเรียก `api.get/post` ใน View โดยตรง)
  - จัดการข้อมูลก่อนส่งหรือหลังรับจาก Backend
- **Views (`src/views/`):** จัดการ UI Logic, Lifecycle และการแสดงผล
- **Components (`src/components/`):** UI ชิ้นส่วนที่ใช้ซ้ำได้

## 3. Data Flow & API Standard
- **No Direct DB Access:** ห้ามเชื่อมต่อ Database โดยตรง ต้องผ่าน API ของ Backend เท่านั้น
- **Axios Interceptors:** ใช้ `src/services/api.ts` ซึ่งจัดการ Auth Token และ Error 401/422 ไว้ให้แล้ว
- **Response Handling:** Backend ส่งข้อมูลในรูปแบบ JSON โดย Error จะอยู่ในฟิลด์ `detail`

## 4. UI/UX & Feedback Rules
- **Loading State:** ทุกครั้งที่มีการดึงข้อมูล ต้องมี `const isLoading = ref(true)` และแสดง Spinner หรือ Skeleton Screen
- **Notifications:** การแจ้งเตือน Error/Success/Confirm **ต้องใช้ `SweetAlert2` (`Swal.fire`) เท่านั้น** ห้ามใช้ `alert()` หรือ `toast` อื่นๆ
- **Timezone:** แสดงผลเวลาเป็นภาษาไทย และจัดการให้เป็น `Asia/Bangkok` (UTC+7)

## 5. Coding Standards
- **Component Naming:** ใช้ `PascalCase` สำหรับชื่อไฟล์ Component
- **Variable Naming:** ใช้ `camelCase` สำหรับตัวแปรและฟังก์ชัน
- **Props/Emits:** ต้องนิยาม Type ให้ชัดเจนด้วย `defineProps<{...}>()` และ `defineEmits<{...}>()`
- **Reactive State:** ใช้ `ref()` เป็นหลักสำหรับ Primitive และ `reactive()` สำหรับ Objects ขนาดใหญ่

## 6. CSS & Theme
- ใช้ Utility Classes ของ Tailwind เป็นหลัก
- ห้ามเขียน Inline Style หรือ `<style>` ในไฟล์ `.vue` หากไม่จำเป็นจริงๆ เพื่อรักษาความสะอาดของโค้ด
- **Design System บังคับ:** ทุกหน้าใหม่/ที่แก้ไข ต้องเป็นไปตาม [`frontend/DESIGN.md`](../../frontend/DESIGN.md) — ธีม "Academic Ledger" (กระดาษ `stone-*` + น้ำเงินเข้ม `brand-*` สีเดียว + เส้นบาง hairline)
  - ใช้คลาสกลางใน `src/assets/main.css`: `.page-card`, `.btn-primary`, `.btn-ghost-ui`, `.btn-danger`, `.field`, `.field-label`, `.data-table`, `.chip`, `.eyebrow`, `.page-title`, `.section-title`, `.num`, `.page-wrap`
  - ใช้คอมโพเนนต์กลางใน `src/components/ui/`: `PageHeader`, `StateBlock`, `SkeletonRows`
  - **ห้ามใช้:** `bg-gradient-*`, `backdrop-blur*`, `blur-[*]`, `shadow-{color}`, `rounded-[2rem]`, `animate-bounce`, `animate-ping`, และสี `slate/gray/zinc/neutral/indigo/violet/purple/blue` (ใช้ `stone-*` กับ `brand-*` แทน)
  - ทุก view ที่มี fetch ต้องมีครบ 3 สถานะ: `SkeletonRows` → `StateBlock variant="error"` → `StateBlock variant="empty"`

## 7. Routing & Navigation
- **แหล่งเดียวของชื่อหน้า/เมนู:** `src/constants/nav.ts` — `routeTitles` (ชื่อหน้า ต่อจากชื่อ route) · `NAV_ITEMS` (เมนูหลัก) · `NAV_TABS` (แท็บบนมือถือ)
  - ทุก route ต้องมี `name` และ `meta.title` (อ้างจาก `routeTitles`); `router/index.ts` ตั้ง `document.title` ให้เองจาก meta
  - ห้ามเขียนรายการเมนูซ้ำใน layout — ใช้ `NAV_ITEMS` / `NAV_TABS` / `MORE_NAV_ITEMS`
- **สัญญาของ `route.meta`** ประกาศไว้ที่ `src/router/meta.ts` (`title`, `navTab`, `headerBack`, `headerHidden`, `fullscreen`) — เพิ่มฟิลด์ใหม่ต้องประกาศใน interface ก่อน
- **`router/routes.ts` เป็นข้อมูลล้วน:** import layout/component ด้วย `() => import()` เท่านั้น ไม่งั้นเทสต์/router จะชน import cycle (ดู `docs/skills.md`)
- **catch-all `/:pathMatch(.*)*` → `views/NotFound.vue` ต้องเป็นรายการสุดท้ายเสมอ** และห้ามมีมากกว่าหนึ่งตัว
- **ปลายทางหลัง redirect:** ค่าที่มาจาก URL (`?next=`) ต้องผ่าน `safeRedirect()` จาก `src/router/redirect.ts` — **ห้าม `router.push()` หรือ `window.location` กับค่าดิบจาก query เด็ดขาด**
- **อ่าน HTTP status:** ใช้ `apiStatus(error)` จาก `services/api.ts` (คืน `number | undefined`) — ห้ามไล่ `isAxiosError` เองในวิว
- **เทสต์บังคับ:** `src/router/__tests__/routes.spec.ts` ตรวจ title ครบ / เมนูชี้ path จริง/catch-all อยู่ท้าย — เพิ่มหน้าใหม่แล้ว CI แดงคือสิ่งที่ถูกต้อง
