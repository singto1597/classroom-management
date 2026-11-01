<script setup lang="ts">
/**
 * 🔗 P4.4 — การ์ดออก/คัดลอก/เพิกถอนลิงก์แชร์กิจกรรม
 *
 * ทำไมต้องเป็นคอมโพเนนต์แยก: หน้ารายละเอียดมีปุ่มจัดการเยอะแล้ว และลิงก์แชร์มีสถานะ
 * ของตัวเอง (มี/ไม่มี) ที่ต้องไม่ปนกับฟอร์มแก้ไข — แยกไว้ให้เทสต์และอ่านง่าย
 *
 * ⚠️ `POST …/share` เรียกซ้ำได้และคืน **ลิงก์เดิม** ⇒ ปุ่ม "คัดลอกลิงก์" ใช้ endpoint
 *    เดียวกันนี้ ไม่ต้องมี endpoint อ่านโทเคนแยก และไม่ทำให้ลิงก์ที่ส่งไปแล้วตาย
 *    (การทำให้ตายต้อง `rotate=true` ซึ่งมีปุ่มยืนยันแยก)
 */
import { computed, ref, watch } from 'vue'
import { ActivityService } from '@/services/activity'
import { useAuthStore } from '@/stores/auth'
import type { ShareLink } from '@/types/activity'
import Swal from 'sweetalert2'
import { UI_COLOR } from '@/constants/theme'

const props = defineProps<{
  roomId: number
  activityId: number
  /** ค่าจาก `activity.has_share_link` ตอนโหลดหน้า */
  hasShareLink: boolean
}>()

const authStore = useAuthStore()
const currentUserName = authStore.currentUserName!

const hasLink = ref(props.hasShareLink)
const isBusy = ref(false)

// หน้ารายละเอียดอาจโหลดข้อมูลใหม่ (เช่น เปลี่ยนสถานะ) ⇒ ตามค่าล่าสุดจาก parent
watch(
  () => props.hasShareLink,
  (next) => {
    hasLink.value = next
  },
)

const Toast = Swal.mixin({
  toast: true,
  position: 'top-end',
  showConfirmButton: false,
  timer: 3000,
  timerProgressBar: true,
})

/** URL เต็ม = origin ของหน้าเว็บ + path ที่ backend ประกอบให้ (ไม่ให้ frontend เดาเอง) */
function absoluteUrl(link: ShareLink): string {
  return `${window.location.origin}${link.path}`
}

/**
 * คัดลอกลงคลิปบอร์ด — ถ้าเบราว์เซอร์ไม่ให้ (http, ไม่ได้โฟกัส) ให้กล่องข้อความ
 * ที่เลือกเองได้แทน **ไม่ใช่ error** เพราะผู้ใช้ยังคัดลอกเองได้
 */
async function copy(url: string) {
  try {
    await navigator.clipboard.writeText(url)
    Toast.fire({ icon: 'success', title: 'คัดลอกลิงก์แล้ว 🔗' })
  } catch {
    await Swal.fire({
      icon: 'info',
      title: 'คัดลอกอัตโนมัติไม่ได้',
      text: 'ลากข้อความด้านล่างเพื่อคัดลอกเอง',
      input: 'text',
      inputValue: url,
      inputAttributes: { readonly: 'readonly' },
      confirmButtonText: 'ปิด',
      confirmButtonColor: UI_COLOR.brand,
    })
  }
}

async function issue(rotate: boolean) {
  if (rotate) {
    const result = await Swal.fire({
      icon: 'warning',
      title: 'สร้างลิงก์ใหม่ใช่ไหม?',
      text: 'ลิงก์เดิมจะเปิดไม่ได้ทันที — คนที่ได้รับลิงก์เก่าต้องขอลิงก์ใหม่',
      showCancelButton: true,
      confirmButtonText: 'สร้างลิงก์ใหม่',
      cancelButtonText: 'ยกเลิก',
      confirmButtonColor: UI_COLOR.brand,
      cancelButtonColor: UI_COLOR.neutral,
    })
    if (!result.isConfirmed) return
  }

  isBusy.value = true
  try {
    const link = await ActivityService.issueShareLink(
      props.roomId,
      props.activityId,
      currentUserName,
      rotate,
    )
    hasLink.value = true
    await copy(absoluteUrl(link))
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'สร้างลิงก์ไม่สำเร็จ'
    Swal.fire({
      icon: 'error',
      title: 'ข้อผิดพลาด',
      text: msg,
      confirmButtonColor: UI_COLOR.brand,
    })
  } finally {
    isBusy.value = false
  }
}

async function revoke() {
  const result = await Swal.fire({
    icon: 'warning',
    title: 'เพิกถอนลิงก์แชร์ไหม?',
    text: 'ทุกคนที่ถือลิงก์นี้จะเปิดดูไม่ได้อีก — ข้อมูลในระบบไม่ถูกลบ',
    showCancelButton: true,
    confirmButtonText: 'เพิกถอนลิงก์',
    cancelButtonText: 'ยกเลิก',
    confirmButtonColor: UI_COLOR.danger,
    cancelButtonColor: UI_COLOR.neutral,
  })
  if (!result.isConfirmed) return

  isBusy.value = true
  try {
    const res = await ActivityService.revokeShareLink(props.roomId, props.activityId, currentUserName)
    hasLink.value = false
    Toast.fire({
      icon: 'success',
      title: res.revoked ? 'เพิกถอนลิงก์แล้ว' : 'ไม่มีลิงก์ที่ใช้งานอยู่',
    })
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : 'เพิกถอนลิงก์ไม่สำเร็จ'
    Swal.fire({
      icon: 'error',
      title: 'ข้อผิดพลาด',
      text: msg,
      confirmButtonColor: UI_COLOR.brand,
    })
  } finally {
    isBusy.value = false
  }
}

const busyClass = computed(() => (isBusy.value ? 'opacity-60' : ''))
</script>

<template>
  <section class="page-card p-4 sm:p-5">
    <h2 class="section-title flex items-center gap-2">
      <i class="bi bi-link-45deg text-brand-700" aria-hidden="true"></i> ลิงก์แชร์กิจกรรม
    </h2>
    <p class="mt-1.5 text-xs leading-relaxed text-stone-500">
      ใครมีลิงก์เปิดดูได้โดยไม่ต้องเข้าสู่ระบบ — เห็นเฉพาะข้อมูลงาน
      <strong>ไม่มีรายชื่อผู้เข้าร่วม</strong> และเพิกถอนได้ทุกเมื่อ
    </p>

    <div class="mt-3 flex flex-wrap gap-2" :class="busyClass">
      <button
        v-if="!hasLink"
        type="button"
        class="btn-primary"
        :disabled="isBusy"
        @click="issue(false)"
      >
        <i class="bi bi-link-45deg" aria-hidden="true"></i> สร้างลิงก์แชร์
      </button>
      <template v-else>
        <button type="button" class="btn-primary" :disabled="isBusy" @click="issue(false)">
          <i class="bi bi-clipboard" aria-hidden="true"></i> คัดลอกลิงก์
        </button>
        <button type="button" class="btn-ghost-ui" :disabled="isBusy" @click="issue(true)">
          <i class="bi bi-arrow-repeat" aria-hidden="true"></i> สร้างลิงก์ใหม่
        </button>
        <button
          type="button"
          class="btn-ghost-ui text-danger-700"
          :disabled="isBusy"
          @click="revoke"
        >
          <i class="bi bi-x-circle" aria-hidden="true"></i> เพิกถอน
        </button>
      </template>
    </div>

    <p v-if="hasLink" class="mt-2.5 inline-flex items-center gap-1.5 text-xs font-bold text-ok-700">
      <i class="bi bi-check-circle-fill" aria-hidden="true"></i> มีลิงก์ที่เปิดใช้งานอยู่
    </p>
  </section>
</template>
