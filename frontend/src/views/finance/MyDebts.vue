<script setup lang="ts">
/**
 * 💰 ยอดค้างชำระของฉัน — ปลายทางของการ์ด "บิลค้างชำระ" บนหน้าหลัก (P3.2)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ทำไมต้องหน้านี้ (แทนที่จะพาไป `/finance/debtors`)
 * ═══════════════════════════════════════════════════════════════════════════
 * การ์ดนับ "บิลของฉัน" แต่ `/finance/debtors` แสดง *ทุกคนในห้อง* ⇒ กดแล้วจำนวน
 * ไม่ตรงกัน (กฎ "34 กดแล้วเจอ 5") และนักเรียนทั่วไปก็ไม่ควรเห็นหนี้ของเพื่อน
 * หน้านี้เรียก `GET /finance/me/debts` ที่ใช้ predicate ชุดเดียวกับตัวนับ
 * (`SP.status='pending'` + `FC.room_id`) ⇒ จำนวนแถว = ตัวเลขบนการ์ดเสมอ
 *
 * 🔴 404 ในที่นี้ **ไม่ใช่** "ไม่มีหนี้": backend ตอบ 404 เมื่อผู้ใช้ยังไม่มีแถว
 *    `students` ในห้องนี้ (ยังไม่ได้ผูกบัญชี) — ต้องแยกข้อความจาก "ค้างชำระ 0 บิล"
 *    ไม่งั้นนักเรียนใหม่จะอ่านว่า "จ่ายครบแล้ว" ซึ่งผิดคนละเรื่อง
 */
import { computed, onMounted, ref } from 'vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import AppEmptyState from '@/components/ui/AppEmptyState.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import { FinanceService } from '@/services/finance'
import { apiStatus } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import { daysFromThaiToday, formatThaiDate, relativeThaiDay } from '@/utils/datetime'
import { formatMoney } from '@/utils/money'
import type { StudentDebtItem } from '@/types/finance'

const authStore = useAuthStore()
const roomId = authStore.currentRoomId ?? 0

const debts = ref<StudentDebtItem[]>([])
const totalPending = ref(0)
const studentName = ref('')
const isLoading = ref(true)
const hasError = ref(false)
const errorMessage = ref('')
/** 404 = ยังไม่มีโปรไฟล์นักเรียนในห้องนี้ (คนละเรื่องกับ "ไม่มีหนี้") */
const notLinked = ref(false)

const load = async () => {
  isLoading.value = true
  hasError.value = false
  notLinked.value = false
  errorMessage.value = ''
  try {
    const profile = await FinanceService.getMyDebts(roomId)
    debts.value = profile.debts
    totalPending.value = profile.total_pending_amount
    studentName.value = profile.student_name
  } catch (err) {
    if (apiStatus(err) === 404) {
      notLinked.value = true
    } else {
      hasError.value = true
      errorMessage.value =
        err instanceof Error && err.message ? err.message : 'โหลดยอดค้างชำระไม่สำเร็จ'
    }
  } finally {
    isLoading.value = false
  }
}

onMounted(load)

/** ป้ายกำหนดส่ง — "เลยกำหนด"/"วันนี้"/"พรุ่งนี้" ไม่ต้องคำนวณใน template ซ้ำสามรอบ */
const dueBadge = (item: StudentDebtItem): { text: string; classes: string } | null => {
  if (!item.due_date) return null
  const diff = daysFromThaiToday(item.due_date)
  if (diff === null) return null
  if (diff < 0) {
    return {
      text: `เลยกำหนด ${Math.abs(diff)} วัน`,
      classes: 'bg-danger-50 text-danger-700',
    }
  }
  const relative = relativeThaiDay(item.due_date)
  if (!relative) return null
  return { text: `ครบกำหนด${relative}`, classes: 'bg-warn-50 text-warn-800' }
}

const overdueCount = computed(
  () =>
    debts.value.filter((item) => {
      if (!item.due_date) return false
      const diff = daysFromThaiToday(item.due_date)
      return diff !== null && diff < 0
    }).length,
)
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader title="ยอดค้างชำระของฉัน" description="บิลที่ยังไม่ได้ชำระครบของฉันในห้องนี้" />

    <SkeletonRows v-if="isLoading" :rows="3" height="h-16" />

    <StateBlock
      v-else-if="hasError"
      variant="error"
      title="โหลดยอดค้างชำระไม่สำเร็จ"
      :hint="errorMessage"
      @retry="load"
    />

    <AppEmptyState
      v-else-if="notLinked"
      icon="bi-person-badge"
      title="ยังไม่พบรายชื่อนักเรียนของคุณในห้องนี้"
      hint="บัญชีนี้ยังไม่ได้ผูกกับทะเบียนนักเรียน จึงยังไม่มีบิลส่วนตัวให้แสดง — ถ้าเป็นนักเรียน ลองเชื่อมบัญชีผ่าน Discord ด้วยคำสั่ง /sync_room"
    />

    <AppEmptyState
      v-else-if="debts.length === 0"
      icon="bi-check2-circle"
      title="ไม่มีบิลค้างชำระ"
      hint="บิลทุกใบของห้องนี้ที่ถึงคิวของคุณได้รับการชำระครบแล้ว"
    />

    <template v-else>
      <!-- สรุปยอด — ยอดรวมต้องเท่ากับผลรวมของแถวในลิสต์ล่าง (คนละคำขอ แต่ชุดเดียวกัน) -->
      <div class="page-card p-4 sm:p-5">
        <p class="text-[11px] font-bold text-stone-500">ยอดค้างชำระรวม</p>
        <p class="font-display num mt-1 text-3xl font-bold text-danger-600">
          {{ formatMoney(totalPending) }}
        </p>
        <p class="mt-1 text-xs font-bold text-stone-500">
          {{ debts.length }} บิล
          <template v-if="overdueCount > 0"> · เลยกำหนดแล้ว {{ overdueCount }} บิล</template>
        </p>
        <p v-if="studentName" class="mt-2 truncate text-xs text-stone-400">
          ในชื่อ {{ studentName }}
        </p>
      </div>

      <ul class="space-y-2">
        <li v-for="item in debts" :key="item.payment_id">
          <RouterLink
            :to="`/finance/collections/${item.collection_id}`"
            class="block rounded-2xl border border-stone-200 bg-white p-4 transition-colors hover:bg-stone-50"
          >
            <div class="flex flex-wrap items-start justify-between gap-2">
              <p class="min-w-0 flex-1 break-words text-sm font-bold text-stone-900">
                {{ item.title }}
              </p>
              <p class="font-display num shrink-0 text-sm font-bold text-stone-900">
                {{ formatMoney(item.amount) }}
              </p>
            </div>
            <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
              <span
                v-if="dueBadge(item)"
                class="rounded-full px-2 py-0.5 text-[11px] font-bold"
                :class="dueBadge(item)?.classes"
              >
                {{ dueBadge(item)?.text }}
              </span>
              <span class="text-[11px] font-bold text-stone-400">
                กำหนดชำระ {{ formatThaiDate(item.due_date) }}
              </span>
            </div>
          </RouterLink>
        </li>
      </ul>

      <p class="px-1 text-[11px] leading-relaxed text-stone-400">
        การชำระเงินทำผ่านผู้ดูแลการเงินของห้อง — กดบิลเพื่อดูรายละเอียดโปรเจกต์เก็บเงิน
      </p>
    </template>
  </div>
</template>
