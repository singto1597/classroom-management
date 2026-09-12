<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { isAxiosError } from 'axios'
import { useAuthStore } from '@/stores/auth'
import StudentService from '@/services/student'
import type { Student, StudentForm, StudentUpdatePayload } from '@/types/student'
import PageHeader from '@/components/ui/PageHeader.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import Swal from 'sweetalert2'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const studentNo = route.params.id as string
const loading = ref(true)
const saving = ref(false)

// 🎯 สถานะควบคุมการเปิด-ปิดฟอร์ม
const isEditMode = ref(false)

const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!

// เช็คว่าคนที่ Login เป็น God Admin ไหม
const isAdmin = computed(() => authStore.isAdmin)

// 🎯 Staff ที่มี MANAGE_STUDENTS แก้ข้อมูลได้ แต่เห็นเฉพาะโซนแก้ไขทั่วไป (ไม่เห็น Admin Zone)
const canManageStudents = computed(
  () => isAdmin.value || authStore.currentPermissions.includes('MANAGE_STUDENTS')
)

// รายการสิทธิ์ย่อยทั้งหมดที่มีในระบบ
const AVAILABLE_PERMISSIONS = [
  { id: 'VIEW_ALL_STUDENTS', label: 'ดูข้อมูลนักเรียนทุกคนแบบเชิงลึก' },
  { id: 'MANAGE_STUDENTS', label: 'จัดการนักเรียน (รับเข้า, ลบ, แก้ไขข้อมูล)' },
  { id: 'EXPORT_STUDENTS', label: 'ดาวน์โหลดข้อมูลออกเป็นไฟล์ Excel' },
  { id: 'MANAGE_FINANCE', label: 'จัดการระบบการเงินของห้อง' },
  { id: 'MANAGE_CLASSROOM_SETTINGS', label: 'ตั้งค่าห้องเรียนขั้นสูง' },
  { id: 'MANAGE_CLASSROOM_TASKS', label: 'จัดการงานและตารางเรียน' }
]

// สมมติว่านักเรียนคนนี้คือเจ้าของโปรไฟล์ (ดึงข้อมูลนักเรียนของตัวเองในห้องนี้มาเทียบ)
const currentUserProfile = ref<Student | null>(null);
const isOwner = computed(() => {
  if (isAdmin.value) return true;
  if (!currentUserProfile.value) return false;
  return String(currentUserProfile.value.student_no) === studentNo;
})

// รวมสิทธิ์: เป็น Admin / Staff ที่ดูแลนักเรียน / หรือเจ้าของโปรไฟล์ ถึงจะกด "เปิดโหมดแก้ไข" ได้
const canEdit = computed(() => canManageStudents.value || isOwner.value)

// 🎯 เพิ่มฟิลด์สำหรับระบบ RBAC และ Moving Target
const form = ref<StudentForm>({
  new_student_no: null,
  is_admin: false,
  permissions: [],
  student_id: null,
  prefix: '',
  first_name: '',
  last_name: '',
  first_name_en: '',
  last_name_en: '',
  nickname: '',
  nickname_en: '',
  birthday: '',
  blood_group: '',
  shirt_size: '',
  food_allergy: '',
  congenital_disease: '',
  phone_number: '',
  phone_number_parent: '',
  phone_number_parent_relation: '',
  line_id: '',
  ig_username: '',
  email: '',
  target_faculty: '',
  cleaning_duty: '',
  olympic_camp: '',
  portfolio: '',
  address_house_no: '',
  address_road: '',
  address_sub_district: '',
  address_district: '',
  address_province: '',
  address_post_code: '',
  class_role: 'student',
  status: 'active'
})

const fetchStudent = async () => {
  try {
    loading.value = true

    // โหลดข้อมูลโปรไฟล์ของคนที่คลิกเข้ามาดู
    const data = await StudentService.getStudentByNo(currentRoomId, studentNo)
    // key มาจาก Object.keys() แบบไดนามิก จึงคัดลอกผ่าน index signature (ชื่อฟิลด์ตรงกับ StudentForm)
    const target: Record<string, unknown> = form.value
    const source: Record<string, unknown> = { ...data }
    Object.keys(form.value).forEach(key => {
      if (key in source) {
        target[key] = source[key] || ''
      }
    })

    // 🎯 โหลดค่าพิเศษ
    form.value.new_student_no = data.student_no
    form.value.is_admin = data.is_admin || false
    form.value.permissions = data.permissions || []

    // โหลดข้อมูลตัวเอง เพื่อเอามาเช็คสิทธิ์การเป็นเจ้าของ (ถ้าไม่ใช่ Admin)
    if (!isAdmin.value) {
        try {
            currentUserProfile.value = await StudentService.getMyProfile(currentRoomId);
        } catch (e) {
            console.log("Not a student in this room", e)
        }
    }

  } catch {
    Swal.fire({ icon: 'error', title: 'เกิดข้อผิดพลาด', text: 'ไม่สามารถโหลดข้อมูลได้' })
    router.push('/students')
  } finally {
    loading.value = false
  }
}

// 🎯 ฟังก์ชันสลับโหมดแก้ไข
const toggleEditMode = () => {
  if (canEdit.value) {
    isEditMode.value = !isEditMode.value
  } else {
    Swal.fire('ปฏิเสธการเข้าถึง', 'คุณสามารถแก้ไขได้เฉพาะข้อมูลของตัวเองเท่านั้น', 'error')
  }
}

// 🎯 ฟังก์ชันเลือกสิทธิ์ย่อย
const togglePermission = (permId: string) => {
  if (!form.value.permissions) form.value.permissions = [];
  const idx = form.value.permissions.indexOf(permId);
  if (idx > -1) form.value.permissions.splice(idx, 1);
  else form.value.permissions.push(permId);
}

const handleSubmit = async () => {
  if (!canEdit.value) return Swal.fire('ไม่มีสิทธิ์', 'คุณแก้ได้เฉพาะข้อมูลตัวเอง', 'error')

  try {
    saving.value = true
    const payload: StudentUpdatePayload = { ...form.value }

    // ล้างข้อมูลก่อนส่งไป Backend — key มาจาก Object.keys() แบบไดนามิก
    const rawPayload: Record<string, unknown> = payload
    Object.keys(payload).forEach(key => {
      const value = rawPayload[key]
      if (typeof value === 'string') {
        const trimmed = value.trim()
        rawPayload[key] = trimmed === '' ? null : trimmed
      }
    })
    // birthday เก็บเป็น '' ตอนยังไม่เลือก → แปลงเป็น null เพื่อไม่ลบของเดิมโดยไม่ตั้งใจ
    if (payload.birthday === '') payload.birthday = null;

    payload.user_name = currentUserName || 'System';

    await StudentService.updateStudent(currentRoomId, studentNo, payload)

    await Swal.fire({
      icon: 'success',
      title: 'สำเร็จ',
      text: 'อัปเดตข้อมูลเรียบร้อยแล้ว',
      timer: 1500,
      showConfirmButton: false
    })

    // 🎯 The Moving Target: Redirect ไปเลขที่ใหม่ทันทีถ้ามีการเปลี่ยนเลขที่
    const finalStudentNo = payload.new_student_no ? payload.new_student_no : studentNo;
    router.push(`/students/${finalStudentNo}`)

  } catch (error: unknown) {
    const apiDetail = isAxiosError<{ detail?: unknown }>(error) && typeof error.response?.data?.detail === 'string'
      ? error.response.data.detail
      : undefined
    const errorMessage = error instanceof Error ? error.message : undefined
    let errorMsg = apiDetail || errorMessage || 'เกิดข้อผิดพลาดในการบันทึกข้อมูล';
    if (isAxiosError(error) && error.response?.status === 422) errorMsg = 'ข้อมูลบางช่องไม่ถูกต้อง กรุณาตรวจสอบอีกครั้ง';
    Swal.fire({ icon: 'error', title: 'บันทึกไม่สำเร็จ', text: errorMsg })
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  fetchStudent()
})
</script>

<template>
  <div class="space-y-4 sm:space-y-5">

    <PageHeader
      eyebrow="Student Record"
      title="จัดการข้อมูลโปรไฟล์"
      :description="`รหัสนักเรียน #${studentNo}`"
    >
      <template #actions>
        <button type="button" class="btn-ghost-ui" :disabled="saving" @click="router.back()">
          <i class="bi bi-arrow-left" aria-hidden="true"></i> กลับ
        </button>

        <template v-if="canEdit">
          <!-- 🎯 ปุ่มเปิด-ปิดโหมด -->
          <button type="button" class="btn-ghost-ui" :disabled="saving" @click="toggleEditMode">
            <i :class="isEditMode ? 'bi bi-x-lg' : 'bi bi-pencil-square'" aria-hidden="true"></i>
            {{ isEditMode ? 'ยกเลิกการแก้ไข' : 'เปิดโหมดแก้ไข' }}
          </button>

          <!-- 🎯 ปุ่ม Save (desktop) — ผูกกับฟอร์มผ่าน id เพราะอยู่นอก <form> -->
          <button
            v-if="isEditMode"
            type="submit"
            form="edit-student-form"
            class="btn-primary hidden sm:inline-flex"
            :disabled="saving"
          >
            <span
              v-if="saving"
              class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"
              aria-hidden="true"
            ></span>
            <i v-else class="bi bi-floppy2-fill" aria-hidden="true"></i>
            บันทึกการเปลี่ยนแปลง
          </button>
        </template>
        <div
          v-else
          class="flex items-center gap-2 rounded-xl border border-stone-200 bg-stone-50 px-4 py-2.5 text-sm font-bold text-stone-400"
        >
          <i class="bi bi-lock-fill" aria-hidden="true"></i> สิทธิ์จำกัด
        </div>
      </template>
    </PageHeader>

    <SkeletonRows v-if="loading" :rows="5" height="h-24" />

    <form v-else id="edit-student-form" class="space-y-4 sm:space-y-5" @submit.prevent="handleSubmit">

      <!-- 🚀 ADMIN CONTROL PANEL (เห็นเฉพาะ Admin ตัวจริง เมื่อเปิดโหมด Edit) -->
      <section v-if="isAdmin && isEditMode" class="page-card overflow-hidden border-brand-200">
        <div class="flex flex-wrap items-center justify-between gap-2 border-b border-stone-200 bg-brand-50/60 px-4 py-3.5 sm:px-5">
          <h2 class="flex items-center gap-2.5 font-display text-base font-bold text-stone-900">
            <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-700 text-white">
              <i class="bi bi-shield-lock-fill" aria-hidden="true"></i>
            </span>
            ผู้ดูแลระบบ (Admin Zone)
          </h2>
          <span class="chip shrink-0 bg-red-50 text-red-700">
            <i class="bi bi-exclamation-triangle-fill" aria-hidden="true"></i> Danger Zone
          </span>
        </div>

        <div class="space-y-5 p-4 sm:p-6">
          <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <label class="field-label" for="newStudentNo">เปลี่ยนเลขที่นักเรียน</label>
              <input id="newStudentNo" v-model="form.new_student_no" type="number" class="field" />
              <p class="mt-1.5 text-xs text-stone-400">
                <i class="bi bi-info-circle" aria-hidden="true"></i> เปลี่ยนแล้วระบบจะทำการย้ายข้อมูลทั้งหมดไปที่เลขที่ใหม่
              </p>
            </div>

            <div>
              <label class="field-label" for="studentStatus">สถานะนักเรียน</label>
              <select id="studentStatus" v-model="form.status" class="field">
                <option value="active">✅ กำลังเรียน (Active)</option>
                <option value="pending">⏳ รออนุมัติ (Pending)</option>
                <option value="inactive">🚫 พ้นสภาพ (Inactive)</option>
              </select>
              <p class="mt-1.5 text-xs text-stone-400">
                <i class="bi bi-info-circle" aria-hidden="true"></i> pending = ยังไม่ได้อนุมัติเข้าเรียน, inactive = พ้นสภาพ/ย้ายออก
              </p>
            </div>

            <div>
              <label class="field-label" for="classRole">ป้ายตำแหน่ง (Cosmetic)</label>
              <select id="classRole" v-model="form.class_role" class="field">
                <option value="student">🧑‍🎓 นักเรียนทั่วไป (Student)</option>
                <option value="president">👑 หัวหน้าห้อง (President)</option>
                <option value="vice_president">👑 รองหัวหน้าห้อง (Vice President)</option>
                <option value="secretary">📋 เลขานุการ/เรขา (Secretary)</option>
                <option value="vice_academic">📖 รองฯ วิชาการ</option>
                <option value="vice_activity">🎭 รองฯ กิจกรรม</option>
                <option value="vice_discipline">⚖️ รองฯ ระเบียบวินัย</option>
                <option value="vice_reception">🤝 รองฯ ปฏิคม</option>
                <option value="vice_pr">📣 รองฯ ประชาสัมพันธ์</option>
                <option value="vice_sanitation">🧹 รองฯ สุขาภิบาล</option>
                <option value="staff_academic">📝 กรรมการวิชาการ</option>
                <option value="staff_activity">🎪 กรรมการกิจกรรม</option>
                <option value="staff_discipline">🛡️ กรรมการระเบียบวินัย</option>
                <option value="staff_reception">🎀 กรรมการปฏิคม</option>
                <option value="staff_pr">📣 กรรมการประชาสัมพันธ์</option>
                <option value="staff_sanitation">🧹 กรรมการสุขาภิบาล</option>
                <option value="treasurer">💰 เหรัญญิก</option>
              </select>
              <p class="mt-1.5 text-xs text-stone-400">
                <i class="bi bi-info-circle" aria-hidden="true"></i> แสดงผลบนหน้าเว็บเท่านั้น ไม่มีผลกับสิทธิ์
              </p>
            </div>
          </div>

          <div class="rounded-xl border border-stone-200 bg-stone-50/60 p-4">
            <label class="flex cursor-pointer items-start gap-3 border-b border-stone-200 pb-4">
              <input v-model="form.is_admin" type="checkbox" class="peer sr-only" />
              <span
                class="relative mt-0.5 h-7 w-12 shrink-0 rounded-full bg-stone-300 transition-colors after:absolute after:left-[2px] after:top-[2px] after:h-6 after:w-6 after:rounded-full after:bg-white after:transition-all after:content-[''] peer-checked:bg-brand-700 peer-checked:after:translate-x-5"
                aria-hidden="true"
              ></span>
              <span class="min-w-0">
                <span class="block font-display text-base font-bold text-stone-900">GOD MODE (มอบสิทธิ์ผู้ดูแลระบบสูงสุด)</span>
                <span class="mt-0.5 block text-xs text-stone-500">
                  หากเปิดโหมดนี้ นักเรียนคนนี้จะสามารถทำได้ทุกอย่างในห้องโดยไม่ต้องสนใจสิทธิ์ย่อยด้านล่าง
                </span>
              </span>
            </label>

            <div class="mt-4 space-y-3" :class="{ 'pointer-events-none opacity-40': form.is_admin }">
              <p class="flex items-center gap-2 text-sm font-bold text-stone-700">
                <i class="bi bi-ui-checks-grid text-brand-700" aria-hidden="true"></i> กำหนดสิทธิ์ย่อย (Custom Permissions):
              </p>
              <div class="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
                <label
                  v-for="perm in AVAILABLE_PERMISSIONS"
                  :key="perm.id"
                  class="flex cursor-pointer items-start gap-2.5 rounded-xl border border-stone-200 bg-white p-3 transition-colors hover:border-stone-300"
                >
                  <span class="relative mt-0.5 inline-flex shrink-0 items-center">
                    <input
                      type="checkbox"
                      class="peer sr-only"
                      :checked="form.permissions?.includes(perm.id)"
                      @change="togglePermission(perm.id)"
                    />
                    <span class="flex h-4 w-4 items-center justify-center rounded border-2 border-stone-300 transition-colors peer-checked:border-brand-700 peer-checked:bg-brand-700">
                      <i
                        v-if="form.permissions?.includes(perm.id)"
                        class="bi bi-check text-[10px] font-black leading-none text-white"
                        aria-hidden="true"
                      ></i>
                    </span>
                  </span>
                  <span class="text-xs font-bold leading-relaxed text-stone-600">{{ perm.label }}</span>
                </label>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 📝 FORM CONTENT (ล็อกการแก้ไขไว้จนกว่าจะเปิดโหมด) -->
      <div
        class="grid grid-cols-1 gap-4 sm:gap-5 lg:grid-cols-2"
        :class="{ 'pointer-events-none': !isEditMode }"
      >

        <!-- Personal Info -->
        <section class="page-card overflow-hidden">
          <div class="flex items-center gap-2.5 border-b border-stone-200 bg-stone-50/70 px-4 py-3.5 sm:px-5">
            <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
              <i class="bi bi-person-fill" aria-hidden="true"></i>
            </span>
            <h3 class="section-title">ข้อมูลส่วนตัว</h3>
          </div>

          <div class="space-y-4 p-4 sm:p-5">
            <div>
              <label class="field-label" for="studentId">รหัสนักเรียน (ประจำตัว)</label>
              <input id="studentId" :disabled="!isEditMode" v-model="form.student_id" type="text" class="field" />
            </div>

            <div>
              <label class="field-label" for="birthday">วันเกิด</label>
              <input id="birthday" :disabled="!isEditMode" v-model="form.birthday" type="date" class="field" />
            </div>

            <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label class="field-label" for="prefix">คำนำหน้า</label>
                <input id="prefix" :disabled="!isEditMode" v-model="form.prefix" type="text" class="field" />
              </div>
              <div>
                <label class="field-label" for="nickname">ชื่อเล่น</label>
                <input id="nickname" :disabled="!isEditMode" v-model="form.nickname" type="text" class="field" />
              </div>
              <div>
                <label class="field-label" for="nicknameEn">ชื่อเล่น (อังกฤษ)</label>
                <input id="nicknameEn" :disabled="!isEditMode" v-model="form.nickname_en" type="text" class="field" />
              </div>
            </div>

            <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label class="field-label" for="firstName">ชื่อจริง <span class="text-red-500">*</span></label>
                <input id="firstName" :disabled="!isEditMode" v-model="form.first_name" type="text" class="field" required />
              </div>
              <div>
                <label class="field-label" for="lastName">นามสกุล <span class="text-red-500">*</span></label>
                <input id="lastName" :disabled="!isEditMode" v-model="form.last_name" type="text" class="field" required />
              </div>
              <div>
                <label class="field-label" for="firstNameEn">
                  ชื่อจริง (อังกฤษ) <span class="font-normal text-stone-400">ไม่บังคับ</span>
                </label>
                <input id="firstNameEn" :disabled="!isEditMode" v-model="form.first_name_en" type="text" class="field" />
              </div>
              <div>
                <label class="field-label" for="lastNameEn">
                  นามสกุล (อังกฤษ) <span class="font-normal text-stone-400">ไม่บังคับ</span>
                </label>
                <input id="lastNameEn" :disabled="!isEditMode" v-model="form.last_name_en" type="text" class="field" />
              </div>
            </div>
          </div>
        </section>

        <!-- Health Info -->
        <section class="page-card overflow-hidden">
          <div class="flex items-center gap-2.5 border-b border-stone-200 bg-stone-50/70 px-4 py-3.5 sm:px-5">
            <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
              <i class="bi bi-heart-pulse-fill" aria-hidden="true"></i>
            </span>
            <h3 class="section-title">ข้อมูลสุขภาพ</h3>
          </div>

          <div class="space-y-4 p-4 sm:p-5">
            <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label class="field-label" for="bloodGroup">กรุ๊ปเลือด</label>
                <input id="bloodGroup" :disabled="!isEditMode" v-model="form.blood_group" type="text" class="field" placeholder="A, B, O, AB" />
              </div>
              <div>
                <label class="field-label" for="shirtSize">ไซส์เสื้อ</label>
                <input id="shirtSize" :disabled="!isEditMode" v-model="form.shirt_size" type="text" class="field" placeholder="S, M, L, XL" />
              </div>
            </div>

            <div>
              <label class="field-label" for="foodAllergy">โรคประจำตัว / แพ้อาหาร</label>
              <input id="foodAllergy" :disabled="!isEditMode" v-model="form.food_allergy" type="text" class="field" placeholder="ถ้าไม่มีให้ระบุ 'ไม่มี'" />
            </div>

            <div>
              <label class="field-label" for="congenitalDisease">โรคประจำตัว</label>
              <input id="congenitalDisease" :disabled="!isEditMode" v-model="form.congenital_disease" type="text" class="field" placeholder="เช่น โรคหัวใจ, หอบหืด, เบาหวาน" />
            </div>
          </div>
        </section>

        <!-- Contact Info -->
        <section class="page-card overflow-hidden">
          <div class="flex items-center gap-2.5 border-b border-stone-200 bg-stone-50/70 px-4 py-3.5 sm:px-5">
            <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
              <i class="bi bi-telephone-fill" aria-hidden="true"></i>
            </span>
            <h3 class="section-title">ข้อมูลการติดต่อ</h3>
          </div>

          <div class="space-y-4 p-4 sm:p-5">
            <div>
              <label class="field-label" for="phoneNumber">เบอร์โทรศัพท์ (ตัวเอง)</label>
              <input id="phoneNumber" :disabled="!isEditMode" v-model="form.phone_number" type="text" class="field" />
            </div>

            <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label class="field-label" for="phoneParent">เบอร์ผู้ปกครอง</label>
                <input id="phoneParent" :disabled="!isEditMode" v-model="form.phone_number_parent" type="text" class="field" />
              </div>
              <div>
                <label class="field-label" for="phoneParentRelation">เกี่ยวข้องเป็น</label>
                <input id="phoneParentRelation" :disabled="!isEditMode" v-model="form.phone_number_parent_relation" type="text" class="field" placeholder="เช่น บิดา, มารดา" />
              </div>
            </div>

            <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label class="field-label" for="lineId">Line ID</label>
                <input id="lineId" :disabled="!isEditMode" v-model="form.line_id" type="text" class="field" />
              </div>
              <div>
                <label class="field-label" for="igUsername">IG Username</label>
                <input id="igUsername" :disabled="!isEditMode" v-model="form.ig_username" type="text" class="field" />
              </div>
              <div>
                <label class="field-label" for="email">อีเมล</label>
                <input id="email" :disabled="!isEditMode" v-model="form.email" type="email" class="field" placeholder="example@email.com" />
              </div>
            </div>
          </div>
        </section>

        <!-- Academic Info -->
        <section class="page-card overflow-hidden">
          <div class="flex items-center gap-2.5 border-b border-stone-200 bg-stone-50/70 px-4 py-3.5 sm:px-5">
            <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
              <i class="bi bi-book-half" aria-hidden="true"></i>
            </span>
            <h3 class="section-title">วิชาการและหน้าที่</h3>
          </div>

          <div class="flex flex-col gap-4 p-4 sm:p-5">
            <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label class="field-label" for="targetFaculty">คณะที่ใฝ่ฝัน</label>
                <input id="targetFaculty" :disabled="!isEditMode" v-model="form.target_faculty" type="text" class="field" />
              </div>
              <div>
                <label class="field-label" for="cleaningDuty">เวรทำความสะอาด</label>
                <input id="cleaningDuty" :disabled="!isEditMode" v-model="form.cleaning_duty" type="text" class="field" placeholder="เช่น วันจันทร์" />
              </div>
            </div>

            <div class="flex flex-grow flex-col">
              <label class="field-label" for="olympicCamp">สอวน. / ค่ายวิชาการ</label>
              <textarea
                id="olympicCamp"
                :disabled="!isEditMode"
                v-model="form.olympic_camp"
                class="field h-full min-h-[120px] resize-none leading-relaxed"
                placeholder="ระบุค่ายวิชาการที่เคยเข้าร่วม (เว้นบรรทัดได้)"
              ></textarea>
            </div>
          </div>
        </section>

        <!-- Portfolio -->
        <section class="page-card overflow-hidden lg:col-span-2">
          <div class="flex items-center gap-2.5 border-b border-stone-200 bg-stone-50/70 px-4 py-3.5 sm:px-5">
            <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
              <i class="bi bi-trophy-fill" aria-hidden="true"></i>
            </span>
            <h3 class="section-title">ผลงาน / รางวัลที่ประทับใจ</h3>
          </div>

          <div class="p-4 sm:p-5">
            <textarea
              :disabled="!isEditMode"
              v-model="form.portfolio"
              class="field min-h-[160px] resize-none leading-relaxed"
              placeholder="เล่าผลงานเด่นๆ หรือรางวัลที่ประทับใจของคุณที่นี่..."
            ></textarea>
          </div>
        </section>

        <!-- Address -->
        <section class="page-card overflow-hidden lg:col-span-2">
          <div class="flex items-center gap-2.5 border-b border-stone-200 bg-stone-50/70 px-4 py-3.5 sm:px-5">
            <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
              <i class="bi bi-house-door-fill" aria-hidden="true"></i>
            </span>
            <h3 class="section-title">ที่อยู่ตามทะเบียนบ้าน</h3>
          </div>

          <div class="p-4 sm:p-5">
            <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <label class="field-label" for="addressHouseNo">บ้านเลขที่/หมู่/ซอย</label>
                <input id="addressHouseNo" :disabled="!isEditMode" v-model="form.address_house_no" type="text" class="field" />
              </div>
              <div>
                <label class="field-label" for="addressRoad">ถนน</label>
                <input id="addressRoad" :disabled="!isEditMode" v-model="form.address_road" type="text" class="field" />
              </div>
              <div>
                <label class="field-label" for="addressSubDistrict">ตำบล / แขวง</label>
                <input id="addressSubDistrict" :disabled="!isEditMode" v-model="form.address_sub_district" type="text" class="field" />
              </div>
              <div>
                <label class="field-label" for="addressDistrict">อำเภอ / เขต</label>
                <input id="addressDistrict" :disabled="!isEditMode" v-model="form.address_district" type="text" class="field" />
              </div>
              <div class="sm:col-span-1 lg:col-span-2">
                <label class="field-label" for="addressProvince">จังหวัด</label>
                <input id="addressProvince" :disabled="!isEditMode" v-model="form.address_province" type="text" class="field" />
              </div>
              <div class="sm:col-span-1 lg:col-span-2">
                <label class="field-label" for="addressPostCode">รหัสไปรษณีย์</label>
                <input id="addressPostCode" :disabled="!isEditMode" v-model="form.address_post_code" type="text" class="field" />
              </div>
            </div>
          </div>
        </section>

      </div>

      <!-- 📌 แถบบันทึกติดล่าง (มือถือ) — โผล่เฉพาะตอนเปิดโหมดแก้ไข -->
      <div
        v-if="isEditMode"
        class="sticky bottom-4 z-30 flex gap-2 rounded-2xl border border-stone-200 bg-white p-3 sm:hidden"
      >
        <button type="button" class="btn-ghost-ui flex-1" :disabled="saving" @click="toggleEditMode">
          <i class="bi bi-x-lg" aria-hidden="true"></i> ยกเลิก
        </button>
        <button type="submit" class="btn-primary flex-1" :disabled="saving">
          <span
            v-if="saving"
            class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white"
            aria-hidden="true"
          ></span>
          <i v-else class="bi bi-floppy2-fill" aria-hidden="true"></i>
          บันทึก
        </button>
      </div>

    </form>
  </div>
</template>
