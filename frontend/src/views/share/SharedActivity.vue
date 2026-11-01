<script setup lang="ts">
/**
 * 🌐 P4.4 — หน้าสาธารณะของลิงก์แชร์กิจกรรม (`/share/activity/:token`)
 *
 * ผู้อ่านคือผู้ปกครอง/นักเรียนที่ **ไม่มีบัญชีในระบบและไม่รู้ room_id** ⇒ หน้านี้
 * อยู่นอก `MainLayout` ไม่มีเมนู ไม่ต้องล็อกอิน และเรียก endpoint เดียวเท่านั้น
 *
 * 🔒 ข้อมูลที่เห็นคือสิ่งที่ backend ส่งใน `SharedActivity` เท่านั้น — ไม่มีรายชื่อ
 *    ผู้เข้าร่วม ไม่มีเบอร์โทร ไม่มีรหัสนักเรียน (backend ไม่ SELECT ออกมาแต่แรก)
 *
 * ⚠️ 404 = ลิงก์ถูกเพิกถอน / กิจกรรมถูกลบ / โทเคนไม่ถูกต้อง — ทั้งสามกรณีตอบข้อความ
 *    เดียวกันโดยเจตนา (ไม่บอกว่าโทเคน "เคยมี" หรือไม่)
 */
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ActivityService } from '@/services/activity'
import type { SharedActivity } from '@/types/activity'
import { formatThaiDate } from '@/utils/datetime'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'

defineOptions({ name: 'SharedActivityView' })

const route = useRoute()
const token = String(route.params.token ?? '')

const activity = ref<SharedActivity | null>(null)
const isLoading = ref(true)
const hasError = ref(false)
const errorMessage = ref('')

async function load() {
  isLoading.value = true
  hasError.value = false
  try {
    activity.value = await ActivityService.getSharedActivity(token)
  } catch (error: unknown) {
    hasError.value = true
    errorMessage.value =
      error instanceof Error && error.message
        ? error.message
        : 'ลิงก์นี้ใช้ไม่ได้แล้ว — อาจถูกเพิกถอนหรือกิจกรรมถูกลบ'
  } finally {
    isLoading.value = false
  }
}

onMounted(load)

/** `null` = ไม่จำกัดที่นั่ง (แยกจาก "เหลือ 0 ที่นั่ง") */
function seatsText(act: SharedActivity): string {
  if (act.seats_left === null) return 'ไม่จำกัดที่นั่ง'
  if (act.seats_left <= 0) return 'ที่นั่งเต็มแล้ว'
  return `เหลือ ${act.seats_left} ที่นั่ง`
}
</script>

<template>
  <div class="flex min-h-screen min-h-dvh flex-col bg-paper font-sans text-ink">
    <header class="border-b border-stone-200 bg-white">
      <div class="page-wrap flex h-14 items-center px-4 sm:h-16 sm:px-6 lg:px-8">
        <span class="flex min-w-0 items-center gap-2.5">
          <span
            class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-700 text-white"
          >
            <i class="bi bi-calendar-heart-fill text-base" aria-hidden="true"></i>
          </span>
          <span class="font-display truncate text-lg font-bold tracking-[0.2em] text-stone-900">
            SYNC<span class="font-normal text-stone-500">ROOM</span>
          </span>
        </span>
      </div>
    </header>

    <main class="mx-auto w-full max-w-2xl flex-1 px-4 py-6 sm:px-6 sm:py-10">
      <SkeletonRows v-if="isLoading" :rows="3" height="h-32" />

      <StateBlock
        v-else-if="hasError"
        variant="error"
        icon="bi-link-45deg"
        title="เปิดลิงก์นี้ไม่ได้"
        :hint="errorMessage"
        @retry="load"
      />

      <article v-else-if="activity" class="space-y-4">
        <div>
          <p class="text-xs font-bold text-brand-700">รายละเอียดกิจกรรม</p>
          <h1 class="font-display mt-1 text-2xl font-bold leading-snug text-stone-900 sm:text-3xl">
            {{ activity.title }}
          </h1>
          <p v-if="activity.room_name" class="mt-1 text-sm text-stone-500">
            ห้อง {{ activity.room_name }}
          </p>
        </div>

        <div class="flex flex-wrap gap-2">
          <span class="chip bg-brand-50 text-brand-700">{{ activity.status_label }}</span>
          <span v-if="activity.category_label" class="chip bg-stone-100 text-stone-600">
            <i class="bi bi-tag" aria-hidden="true"></i>
            {{ activity.category_label }}
          </span>
          <span
            class="chip"
            :class="
              activity.is_registration_open
                ? 'bg-ok-50 text-ok-700'
                : 'bg-stone-100 text-stone-500'
            "
          >
            <i
              class="bi"
              :class="activity.is_registration_open ? 'bi-check-circle' : 'bi-x-circle'"
              aria-hidden="true"
            ></i>
            {{ activity.is_registration_open ? 'เปิดรับลงทะเบียน' : 'ปิดรับลงทะเบียนแล้ว' }}
          </span>
        </div>

        <div class="page-card divide-y divide-stone-100 p-4 sm:p-5">
          <dl class="space-y-3">
            <div class="flex items-baseline justify-between gap-3">
              <dt class="text-sm text-stone-500">วันที่จัดกิจกรรม</dt>
              <dd class="num text-sm font-bold text-stone-900">
                {{ formatThaiDate(activity.activity_date, 'long') }}
              </dd>
            </div>
            <div class="flex items-baseline justify-between gap-3 pt-3">
              <dt class="text-sm text-stone-500">ชั่วโมงกิจกรรม</dt>
              <dd class="num text-sm font-bold text-stone-900">{{ activity.base_hours }} ชม.</dd>
            </div>
            <div
              v-if="activity.registration_deadline"
              class="flex items-baseline justify-between gap-3 pt-3"
            >
              <dt class="text-sm text-stone-500">ปิดรับลงทะเบียน</dt>
              <dd class="num text-sm font-bold text-stone-900">
                {{ formatThaiDate(activity.registration_deadline, 'long') }}
              </dd>
            </div>
            <div class="flex items-baseline justify-between gap-3 pt-3">
              <dt class="text-sm text-stone-500">ที่นั่ง</dt>
              <dd class="text-sm font-bold text-stone-900">
                {{ seatsText(activity) }}
                <span v-if="activity.capacity !== null" class="num font-normal text-stone-500">
                  (จาก {{ activity.capacity }})
                </span>
              </dd>
            </div>
          </dl>
        </div>

        <div v-if="activity.description" class="page-card p-4 sm:p-5">
          <h2 class="section-title mb-2">รายละเอียด</h2>
          <p class="whitespace-pre-wrap text-sm leading-relaxed text-stone-600">
            {{ activity.description }}
          </p>
        </div>

        <p class="text-center text-xs leading-relaxed text-stone-500">
          ลิงก์นี้อ่านได้อย่างเดียว — การลงทะเบียน/แก้ไขข้อมูลทำผ่านช่องทางของห้องเรียน
          <br />
          หากไม่ควรเปิดเผยแล้ว ผู้ดูแลกิจกรรมเพิกถอนลิงก์ได้ทุกเมื่อ
        </p>
      </article>
    </main>
  </div>
</template>
