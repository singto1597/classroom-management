<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { isAxiosError } from 'axios'
import { useAuthStore } from '@/stores/auth'
import StudentService from '@/services/student'
import type { Student } from '@/types/student'
import { displayName } from '@/utils/name'
import PageHeader from '@/components/ui/PageHeader.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import Swal from 'sweetalert2'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const studentNo = route.params.id as string
const student = ref<Student | null>(null)
const loading = ref(true)

// ให้ StateBlock มีสถานะผิดพลาดของตัวเอง (เดิมพึ่ง Swal อย่างเดียว)
const hasError = ref(false)

const currentRoomId = authStore.currentRoomId!

// 🏷️ แปลง class_role → ภาษาไทย (ให้ตรงกับ StudentList)
const ROLE_LABELS: Record<string, string> = {
  student: 'นักเรียน',
  president: 'หัวหน้าห้อง',
  vice_president: 'รองหัวหน้าห้อง',
  secretary: 'เลขานุการ (เรขา)',
  vice_academic: 'รองวิชาการ',
  vice_activity: 'รองกิจกรรม',
  vice_discipline: 'รองระเบียบวินัย',
  vice_reception: 'รองปฏิคม',
  vice_pr: 'รองประชาสัมพันธ์',
  vice_sanitation: 'รองสุขาภิบาล',
  staff_academic: 'กรรมการวิชาการ',
  staff_activity: 'กรรมการกิจกรรม',
  staff_discipline: 'กรรมการระเบียบวินัย',
  staff_reception: 'กรรมการปฏิคม',
  staff_pr: 'กรรมการประชาสัมพันธ์',
  staff_sanitation: 'กรรมการสุขาภิบาล',
  treasurer: 'เหรัญญิก'
};

const roleLabel = (role: string) => ROLE_LABELS[role] || role || 'นักเรียน';

// 🏠 ประกอบที่อยู่จากส่วนที่มีข้อมูลจริง — ไม่ปล่อยให้เหลือ "ถ.- ต.- อ.-" เมื่อฟิลด์ว่าง
const addressText = computed(() => {
  const s = student.value
  if (!s) return ''
  return [
    s.address_house_no,
    s.address_road ? `ถ.${s.address_road}` : '',
    s.address_sub_district ? `ต.${s.address_sub_district}` : '',
    s.address_district ? `อ.${s.address_district}` : '',
    s.address_province ? `จ.${s.address_province}` : '',
    s.address_post_code
  ].filter(Boolean).join(' ')
})

// 🎯 เงื่อนไขสำหรับแสดงปุ่ม "แก้ไขข้อมูล"
const canEdit = computed(() => {
  return authStore.isAdmin ||
         authStore.currentPermissions.includes('MANAGE_STUDENTS') ||
         String(student.value?.user_id) === String(authStore.userId);
})

// ดึงข้อความ error จาก backend แบบปลอดภัย (catch ได้ unknown) — คงรูปแบบเดิมของโปรเจค
// ที่อ่าน detail จาก response ของ axios ไว้
const apiErrorDetail = (error: unknown): string | undefined => {
  if (!isAxiosError<{ detail?: unknown }>(error)) return undefined;
  const detail = error.response?.data?.detail;
  return typeof detail === 'string' ? detail : undefined;
};

const fetchStudent = async () => {
  try {
    loading.value = true
    hasError.value = false
    if (!currentRoomId) throw new Error('ไม่พบข้อมูลเซิร์ฟเวอร์ กรุณาเลือกห้องเรียนก่อน')

    student.value = await StudentService.getStudentByNo(currentRoomId, studentNo)
  } catch (error: unknown) {
    hasError.value = true
    console.error('Error fetching student:', error)
    Swal.fire({
      icon: 'error',
      title: 'เกิดข้อผิดพลาด',
      text: apiErrorDetail(error) || 'ไม่สามารถโหลดข้อมูลนักเรียนได้',
      confirmButtonColor: '#1d4ed8'
    })
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchStudent()
})
</script>

<template>
  <div class="space-y-4 sm:space-y-5">

    <PageHeader
      eyebrow="Student Profile"
      title="โปรไฟล์นักเรียน"
      description="ข้อมูลส่วนตัว การติดต่อ และข้อมูลสุขภาพ"
    >
      <template #actions>
        <button type="button" class="btn-ghost-ui w-full sm:w-auto" @click="router.push('/students')">
          <i class="bi bi-arrow-left" aria-hidden="true"></i> กลับหน้ารายชื่อ
        </button>
        <RouterLink
          v-if="canEdit && student"
          :to="`/students/${student.student_no}/edit`"
          class="btn-primary w-full sm:w-auto"
        >
          <i class="bi bi-pencil-square" aria-hidden="true"></i> แก้ไขข้อมูล
        </RouterLink>
      </template>
    </PageHeader>

    <!-- โหลด -->
    <SkeletonRows v-if="loading" :rows="4" height="h-24" />

    <!-- ผิดพลาด -->
    <StateBlock v-else-if="hasError" variant="error" @retry="fetchStudent">
      <button type="button" class="btn-ghost-ui" @click="router.push('/students')">
        <i class="bi bi-arrow-left" aria-hidden="true"></i> กลับหน้ารายชื่อ
      </button>
    </StateBlock>

    <!-- ไม่พบข้อมูล -->
    <StateBlock
      v-else-if="!student"
      variant="empty"
      title="ไม่พบข้อมูลนักเรียน"
      hint="ไม่สามารถแสดงโปรไฟล์ของนักเรียนคนนี้ได้"
    />

    <template v-else>

      <!-- ========================================== -->
      <!-- Profile Hero                                -->
      <!-- ========================================== -->
      <div class="page-card overflow-hidden">
        <div class="flex items-center justify-between gap-3 border-b border-stone-200 bg-stone-50/70 px-4 py-3 sm:px-5">
          <p class="text-[11px] font-bold text-stone-400">เลขที่ในห้อง</p>
          <span class="num font-display text-lg font-bold text-brand-700">#{{ student.student_no }}</span>
        </div>

        <div class="p-4 sm:p-5">
          <div class="flex items-start gap-3.5">
            <div
              class="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-brand-50 font-display text-xl font-bold text-brand-700 sm:h-16 sm:w-16 sm:text-2xl"
              aria-hidden="true"
            >
              {{ displayName(student).charAt(0) || '?' }}
            </div>

            <div class="min-w-0 flex-1">
              <h2 class="font-display text-xl font-bold leading-tight text-stone-900 sm:text-2xl">
                {{ student.prefix }}{{ displayName(student) }}
              </h2>

              <p class="num mt-1 text-sm text-stone-500">
                <i class="bi bi-person-vcard me-1 text-stone-400" aria-hidden="true"></i>
                {{ student.student_id || 'ไม่ระบุรหัส' }}
                <span v-if="student.nickname || student.nickname_en"> · ชื่อเล่น: {{ student.nickname || student.nickname_en }}</span>
              </p>

              <div class="mt-2.5 flex flex-wrap items-center gap-1.5">
                <span
                  class="chip"
                  :class="student.status === 'active' ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-700'"
                >
                  <i
                    class="bi"
                    :class="student.status === 'active' ? 'bi-check-circle-fill' : 'bi-x-circle-fill'"
                    aria-hidden="true"
                  ></i>
                  {{ student.status === 'active' ? 'กำลังศึกษา' : 'พ้นสภาพ' }}
                </span>

                <span class="chip bg-brand-50 text-brand-700">{{ roleLabel(student.class_role) }}</span>

                <span v-if="student.is_admin" class="chip bg-amber-50 text-amber-700">
                  <i class="bi bi-shield-lock-fill" aria-hidden="true"></i> ผู้ดูแลระบบ
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ========================================== -->
      <!-- Layout Grid (Sidebar + Main)                -->
      <!-- ========================================== -->
      <div class="grid grid-cols-1 items-start gap-4 sm:gap-5 lg:grid-cols-12">

        <!-- LEFT COLUMN -->
        <div class="space-y-4 sm:space-y-5 lg:col-span-4">

          <!-- ข้อมูลการติดต่อ -->
          <section class="page-card overflow-hidden">
            <div class="flex items-center gap-2.5 border-b border-stone-200 bg-stone-50/70 px-4 py-3 sm:px-5">
              <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
                <i class="bi bi-link-45deg" aria-hidden="true"></i>
              </span>
              <h3 class="section-title">ช่องทางการติดต่อ</h3>
            </div>

            <div class="px-4 py-1.5 sm:px-5">
              <div class="flex items-start justify-between gap-3 border-b border-stone-100 py-2.5">
                <span class="shrink-0 text-xs font-bold text-stone-500">เบอร์โทรศัพท์</span>
                <span v-if="student.phone_number === '🔒 ไม่มีสิทธิ์เข้าถึง'" class="text-xs font-bold text-stone-400">
                  <i class="bi bi-lock-fill" aria-hidden="true"></i> ปิดบังข้อมูล
                </span>
                <span v-else class="num min-w-0 truncate text-right text-sm font-bold text-stone-800">
                  {{ student.phone_number || '-' }}
                </span>
              </div>

              <div class="flex items-start justify-between gap-3 border-b border-stone-100 py-2.5">
                <span class="shrink-0 text-xs font-bold text-stone-500">Line ID</span>
                <span class="min-w-0 truncate text-right text-sm font-bold text-stone-800">{{ student.line_id || '-' }}</span>
              </div>

              <div class="flex items-start justify-between gap-3 py-2.5">
                <span class="shrink-0 text-xs font-bold text-stone-500">Instagram</span>
                <span class="min-w-0 truncate text-right text-sm font-bold text-stone-800">{{ student.ig_username || '-' }}</span>
              </div>
            </div>
          </section>

          <!-- ผู้ติดต่อฉุกเฉิน -->
          <section class="page-card overflow-hidden">
            <div class="flex items-center gap-2.5 border-b border-stone-200 bg-stone-50/70 px-4 py-3 sm:px-5">
              <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-red-50 text-red-600">
                <i class="bi bi-shield-plus" aria-hidden="true"></i>
              </span>
              <h3 class="section-title">ผู้ติดต่อฉุกเฉิน</h3>
            </div>

            <div class="px-4 py-1.5 sm:px-5">
              <div class="flex items-start justify-between gap-3 border-b border-stone-100 py-2.5">
                <span class="shrink-0 text-xs font-bold text-stone-500">เกี่ยวข้องเป็น</span>
                <span v-if="student.phone_number_parent_relation === '🔒 ไม่มีสิทธิ์เข้าถึง'" class="text-xs font-bold text-stone-400">
                  <i class="bi bi-lock-fill" aria-hidden="true"></i> ปกปิด
                </span>
                <span v-else class="min-w-0 truncate text-right text-sm font-bold text-stone-800">
                  {{ student.phone_number_parent_relation || 'ผู้ปกครอง' }}
                </span>
              </div>

              <div class="flex items-start justify-between gap-3 py-2.5">
                <span class="shrink-0 text-xs font-bold text-stone-500">เบอร์โทรศัพท์</span>
                <span v-if="student.phone_number_parent === '🔒 ไม่มีสิทธิ์เข้าถึง'" class="text-xs font-bold text-stone-400">
                  <i class="bi bi-lock-fill" aria-hidden="true"></i> ไม่มีสิทธิ์
                </span>
                <a
                  v-else
                  :href="'tel:' + student.phone_number_parent"
                  class="num min-w-0 truncate text-right font-display text-base font-bold text-brand-700 transition-colors hover:text-brand-800"
                >
                  {{ student.phone_number_parent || '-' }}
                </a>
              </div>
            </div>
          </section>

        </div>

        <!-- RIGHT COLUMN -->
        <div class="space-y-4 sm:space-y-5 lg:col-span-8">

          <!-- ข้อมูลสุขภาพ -->
          <section class="page-card overflow-hidden">
            <div class="flex items-center gap-2.5 border-b border-stone-200 bg-stone-50/70 px-4 py-3 sm:px-5">
              <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
                <i class="bi bi-info-circle-fill" aria-hidden="true"></i>
              </span>
              <h3 class="section-title">ข้อมูลสุขภาพ</h3>
            </div>

            <div class="p-4 sm:p-5">
              <div class="grid grid-cols-2 gap-3">
                <div class="rounded-xl border border-stone-200 bg-stone-50/60 p-3">
                  <p class="text-[11px] font-bold uppercase tracking-[0.12em] text-stone-400">กรุ๊ปเลือด</p>
                  <p v-if="student.blood_group === '🔒 ไม่มีสิทธิ์เข้าถึง'" class="mt-0.5 text-xs font-bold text-stone-400">
                    <i class="bi bi-lock-fill" aria-hidden="true"></i> ปกปิดข้อมูล
                  </p>
                  <p v-else class="num font-display text-lg font-bold text-red-600">{{ student.blood_group || '-' }}</p>
                </div>

                <div class="rounded-xl border border-stone-200 bg-stone-50/60 p-3">
                  <p class="text-[11px] font-bold uppercase tracking-[0.12em] text-stone-400">ไซส์เสื้อ</p>
                  <p v-if="student.shirt_size === '🔒 ไม่มีสิทธิ์เข้าถึง'" class="mt-0.5 text-xs font-bold text-stone-400">
                    <i class="bi bi-lock-fill" aria-hidden="true"></i> ปกปิดข้อมูล
                  </p>
                  <p v-else class="num font-display text-lg font-bold text-brand-700">{{ student.shirt_size || '-' }}</p>
                </div>
              </div>

              <div class="mt-3 rounded-xl border border-stone-200 bg-stone-50/60 p-3">
                <p class="text-[11px] font-bold uppercase tracking-[0.12em] text-stone-400">แพ้อาหาร / โรคประจำตัว</p>
                <p v-if="student.food_allergy === '🔒 ไม่มีสิทธิ์เข้าถึง'" class="mt-0.5 text-xs font-bold text-stone-400">
                  <i class="bi bi-lock-fill" aria-hidden="true"></i> ปกปิดข้อมูล
                </p>
                <p v-else class="mt-0.5 text-sm font-bold text-stone-800">{{ student.food_allergy || 'ไม่มีประวัติ' }}</p>
              </div>
            </div>
          </section>

          <!-- ที่อยู่ตามทะเบียนบ้าน -->
          <section class="page-card overflow-hidden">
            <div class="flex items-center gap-2.5 border-b border-stone-200 bg-stone-50/70 px-4 py-3 sm:px-5">
              <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
                <i class="bi bi-geo-alt-fill" aria-hidden="true"></i>
              </span>
              <h3 class="section-title">ที่อยู่ตามทะเบียนบ้าน</h3>
            </div>

            <div class="p-4 sm:p-5">
              <template v-if="student.address_house_no === '🔒 ไม่มีสิทธิ์เข้าถึง'">
                <p class="flex items-center gap-1.5 rounded-xl border border-stone-200 bg-stone-50/60 p-3 text-sm font-bold text-stone-400">
                  <i class="bi bi-shield-lock-fill" aria-hidden="true"></i> สงวนสิทธิ์การเข้าถึงข้อมูล
                </p>
              </template>
              <template v-else>
                <p class="rounded-xl border border-stone-200 bg-stone-50/60 p-3 text-sm font-medium leading-relaxed text-stone-700">
                  {{ addressText || 'ยังไม่มีข้อมูลที่อยู่' }}
                </p>
              </template>
            </div>
          </section>

          <!-- วิชาการและผลงาน -->
          <section class="page-card overflow-hidden">
            <div class="flex items-center gap-2.5 border-b border-stone-200 bg-stone-50/70 px-4 py-3 sm:px-5">
              <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-700">
                <i class="bi bi-mortarboard-fill" aria-hidden="true"></i>
              </span>
              <h3 class="section-title">วิชาการและผลงาน</h3>
            </div>

            <div class="space-y-4 p-4 sm:p-5">
              <div>
                <p class="text-[11px] font-bold uppercase tracking-[0.12em] text-stone-400">คณะที่ใฝ่ฝัน</p>
                <p v-if="student.target_faculty === '🔒 ไม่มีสิทธิ์เข้าถึง'" class="mt-1 text-sm font-bold text-stone-400">
                  <i class="bi bi-lock-fill" aria-hidden="true"></i> ปกปิดข้อมูล
                </p>
                <p v-else class="mt-1 rounded-xl border border-stone-200 bg-stone-50/60 p-3 text-sm font-bold text-stone-800">
                  {{ student.target_faculty || 'ยังไม่ได้ระบุ' }}
                </p>
              </div>

              <div class="grid grid-cols-1 gap-3 border-t border-stone-100 pt-3 sm:gap-4 sm:pt-4 md:grid-cols-2">
                <div>
                  <p class="text-[11px] font-bold uppercase tracking-[0.12em] text-stone-400">สอวน. / ค่ายวิชาการ</p>
                  <p class="mt-1.5 whitespace-pre-line rounded-xl border border-stone-200 bg-stone-50/60 p-3 text-sm font-medium leading-relaxed text-stone-700 md:min-h-[100px]">
                    {{ student.olympic_camp || '-' }}
                  </p>
                </div>

                <div>
                  <p class="text-[11px] font-bold uppercase tracking-[0.12em] text-stone-400">ผลงาน / รางวัล</p>
                  <p class="mt-1.5 whitespace-pre-line rounded-xl border border-stone-200 bg-stone-50/60 p-3 text-sm font-medium leading-relaxed text-stone-700 md:min-h-[100px]">
                    {{ student.portfolio || '-' }}
                  </p>
                </div>
              </div>
            </div>
          </section>

        </div>
      </div>

    </template>
  </div>
</template>
