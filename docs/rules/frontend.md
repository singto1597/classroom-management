# 🎨 Frontend Rules (Vue 3 + TypeScript)

คุณคือ Lead Frontend Engineer ที่ดูแล Classroom Management System กฎเหล่านี้คือมาตรฐานที่ต้องปฏิบัติตามอย่างเคร่งครัด

## 1. Stack & Core Technologies
- **Framework:** Vue 3 (Composition API พร้อม `<script setup lang="ts">`)
- **Language:** TypeScript อย่างเคร่งครัด (**ห้ามใช้ `any` เด็ดขาด**)
- **State Management:** `Pinia`
- **Styling:** `Tailwind CSS` + `DaisyUI`
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
