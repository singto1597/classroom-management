<script setup lang="ts">
/**
 * 👤 บัญชีรายบุคคล (FIN-V2 / P1.4)
 *
 * รวม "ผู้ค้างชำระ" + "เงินรับล่วงหน้า" ที่เคยแยกเป็นสองหน้า ให้เป็น **รายชื่อเดียว**
 * ที่นักเรียน 1 คนมีตัวเลขครบ: ค้างทั้งหมด · เกินกำหนด · ยังไม่ถึงกำหนด · เครดิต
 *
 * 🔓 หน้านี้ **อ่านอย่างเดียว** และสมาชิกห้องอ่านได้ (backend `require_member`)
 *    ⇒ ห้าม gate ด้วย `isAdmin`/`canManageFinance` ทั้งหน้า — ปุ่ม "รับเงิน" จะมาใน P2.3
 *
 * 🔢 ตัวโหลดมี guard ตัวเดียว — หน้าเดียว ไม่มีคำขอคู่ขนานแบบ DebtorList
 *
 * ⚠️ เงินจาก API เป็น string 2 ตำแหน่ง ⇒ `formatMoney(Number(x))` ทุกช่อง
 */
import { ref, computed, onMounted, watch, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import type {
  FundType,
  IndividualAccountItem,
  IndividualAccountQuery,
  IndividualAccountStatus,
} from '@/types/finance'
import { createLatestGuard } from '@/utils/latest'
import { formatMoney } from '@/utils/money'
import { formatThaiDate } from '@/utils/datetime'

import PageIntro from '@/components/ui/PageIntro.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import { useDialog } from '@/composables/useDialog'

const router = useRouter()
const authStore = useAuthStore()
const dialog = useDialog()
const currentRoomId = authStore.currentRoomId!

const items = ref<IndividualAccountItem[]>([])
const asOf = ref('')
const isLoading = ref(true)
const hasError = ref(false)

// '' = ไม่ส่งตัวกรอง (backend default = all) — เก็บเป็น string เพื่อให้ `v-model` ของ select ตรงชนิด
const statusFilter = ref<'' | IndividualAccountStatus>('')
const fundTypeFilter = ref<'' | FundType>('')
const searchInput = ref('')

const listGuard = createLatestGuard()

const money = (value: string) => formatMoney(Number(value))
const isPositive = (value: string) => Number(value) > 0

const buildQuery = (): IndividualAccountQuery => {
  const query: IndividualAccountQuery = {}
  if (statusFilter.value) query.status = statusFilter.value
  if (fundTypeFilter.value) query.fund_type = fundTypeFilter.value
  const search = searchInput.value.trim()
  if (search) query.q = search
  return query
}

const hasFilters = computed(
  () => !!statusFilter.value || !!fundTypeFilter.value || !!searchInput.value.trim()
)

const loadAccounts = async () => {
  const token = listGuard.begin()
  isLoading.value = true
  hasError.value = false
  try {
    const res = await FinanceService.getIndividualAccounts(currentRoomId, buildQuery())
    if (!listGuard.isCurrent(token)) return
    items.value = res.items
    asOf.value = res.as_of
  } catch {
    if (!listGuard.isCurrent(token)) return
    hasError.value = true
    void dialog.alert('เกิดข้อผิดพลาด', 'โหลดบัญชีรายบุคคลไม่สำเร็จ', 'error')
  } finally {
    if (listGuard.isCurrent(token)) isLoading.value = false
  }
}

// ⏱️ ค้นหา debounce 300ms — รูปแบบเดียวกับ FineList (พิมพ์เร็วแล้วยิงคำขอทุกตัวอักษรไม่ไหว)
let searchTimer: ReturnType<typeof setTimeout> | null = null
watch(searchInput, () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => void loadAccounts(), 300)
})

// ตัวกรอง select เปลี่ยนแล้วโหลดทันที (ไม่มี debounce)
watch([statusFilter, fundTypeFilter], () => void loadAccounts())

onBeforeUnmount(() => {
  if (searchTimer) clearTimeout(searchTimer)
})

const openAccount = (studentId: number) => {
  void router.push({
    name: 'finance-individual-account-detail',
    params: { studentId },
  })
}

onMounted(loadAccounts)
</script>

<template>
  <div class="space-y-3">
    <PageIntro
      description="ยอดค้าง เครดิต และรายการเดินบัญชีของนักเรียนแต่ละคน — รวมผู้ค้างชำระและเงินรับล่วงหน้าไว้ที่เดียว"
    >
      <template #actions>
        <RouterLink to="/finance/aging" class="btn-ghost-ui">
          <i class="bi bi-graph-up" aria-hidden="true"></i>
          รายงานอายุหนี้
        </RouterLink>
        <RouterLink to="/finance/credits" class="btn-ghost-ui">
          <i class="bi bi-piggy-bank" aria-hidden="true"></i>
          เงินรับล่วงหน้า
        </RouterLink>
      </template>
    </PageIntro>

    <!-- ══════════════════════ ตัวกรอง ══════════════════════ -->
    <div class="flex flex-wrap items-center gap-2">
      <select
        v-model="statusFilter"
        class="field w-auto min-w-36 text-sm"
        aria-label="กรองสถานะบัญชี"
      >
        <option value="">ทุกสถานะ</option>
        <option value="outstanding">ค้างชำระ</option>
        <option value="credit">มีเครดิต</option>
        <option value="settled">จ่ายครบ</option>
      </select>

      <select
        v-model="fundTypeFilter"
        class="field w-auto min-w-36 text-sm"
        aria-label="กรองประเภทเงิน"
      >
        <option value="">ทุกประเภทเงิน</option>
        <option value="room_fund">เงินห้อง</option>
        <option value="pass_through">เก็บแทน / ผ่านมือ</option>
      </select>

      <input
        v-model="searchInput"
        type="search"
        class="field w-full text-sm sm:w-56"
        placeholder="ค้นหาชื่อ / เลขที่นักเรียน"
        aria-label="ค้นหาบัญชีรายบุคคล"
      />

      <p v-if="asOf && !isLoading" class="ms-auto text-caption text-ink-3">
        <i class="bi bi-calendar-check me-1" aria-hidden="true"></i>
        ข้อมูล ณ {{ formatThaiDate(asOf) }}
      </p>
    </div>

    <SkeletonRows v-if="isLoading" :rows="5" height="h-20" />

    <StateBlock
      v-else-if="hasError"
      variant="error"
      title="โหลดบัญชีรายบุคคลไม่สำเร็จ"
      @retry="loadAccounts"
    />

    <StateBlock
      v-else-if="!items.length"
      variant="empty"
      icon="bi-emoji-smile"
      title="ไม่พบบัญชีที่ตรงกับตัวกรอง"
      :hint="hasFilters ? 'ลองปรับตัวกรองหรือคำค้น' : 'ห้องนี้ยังไม่มีนักเรียนที่มีรายการการเงิน'"
    />

    <template v-else>
      <!-- ══════════════════════ 📱 มือถือ: การ์ด ══════════════════════ -->
      <div class="space-y-2.5 lg:hidden">
        <RouterLink
          v-for="item in items"
          :key="item.student_id"
          :to="{ name: 'finance-individual-account-detail', params: { studentId: item.student_id } }"
          class="page-card block p-4 transition-colors hover:bg-canvas active:scale-[0.99]"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="flex min-w-0 items-center gap-2">
              <span class="chip num shrink-0 bg-canvas text-ink-2">#{{ item.student_no }}</span>
              <h2 class="font-display min-w-0 truncate text-base font-bold text-ink-1">
                {{ item.name }}
              </h2>
            </div>
            <div class="shrink-0 text-right">
              <p class="text-xs font-bold text-ink-3">ค้างทั้งหมด</p>
              <p
                class="font-display num mt-0.5 whitespace-nowrap text-lg font-bold"
                :class="isPositive(item.outstanding_total) ? 'text-danger-600' : 'text-ok-600'"
              >
                {{ money(item.outstanding_total) }}
              </p>
            </div>
          </div>

          <div class="mt-2.5 grid grid-cols-3 gap-2 border-t border-line pt-2.5">
            <div>
              <p class="text-caption font-bold text-ink-3">เกินกำหนด</p>
              <p
                class="num mt-0.5 text-sm font-bold"
                :class="isPositive(item.overdue_total) ? 'text-danger-700' : 'text-ink-2'"
              >
                {{ money(item.overdue_total) }}
              </p>
            </div>
            <div>
              <p class="text-caption font-bold text-ink-3">ยังไม่ถึงกำหนด</p>
              <p class="num mt-0.5 text-sm font-bold text-ink-2">
                {{ money(item.upcoming_total) }}
              </p>
            </div>
            <div>
              <p class="text-caption font-bold text-ink-3">เครดิต</p>
              <p
                class="num mt-0.5 text-sm font-bold"
                :class="isPositive(item.credit_balance) ? 'text-ok-700' : 'text-ink-2'"
              >
                {{ money(item.credit_balance) }}
              </p>
            </div>
          </div>
        </RouterLink>
      </div>

      <!-- ══════════════════════ 🖥️ เดสก์ท็อป: ตาราง ══════════════════════ -->
      <div class="page-card hidden overflow-hidden lg:block">
        <div class="overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th class="w-20">เลขที่</th>
                <th>ชื่อนักเรียน</th>
                <th class="text-right">ค้างทั้งหมด</th>
                <th class="text-right">เกินกำหนด</th>
                <th class="text-right">ยังไม่ถึงกำหนด</th>
                <th class="text-right">เครดิตคงเหลือ</th>
                <th class="text-right">ใช้ได้</th>
                <th class="w-16 text-right">จัดการ</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in items"
                :key="item.student_id"
                class="cursor-pointer"
                @click="openAccount(item.student_id)"
              >
                <td class="num font-bold text-ink-3">#{{ item.student_no }}</td>
                <td class="font-bold text-ink-1">{{ item.name }}</td>
                <td class="whitespace-nowrap text-right">
                  <span
                    class="num font-bold"
                    :class="isPositive(item.outstanding_total) ? 'text-danger-600' : 'text-ok-600'"
                  >
                    {{ money(item.outstanding_total) }}
                  </span>
                </td>
                <td class="whitespace-nowrap text-right">
                  <span
                    class="num font-bold"
                    :class="isPositive(item.overdue_total) ? 'text-danger-700' : 'text-ink-2'"
                  >
                    {{ money(item.overdue_total) }}
                  </span>
                </td>
                <td class="num whitespace-nowrap text-right text-ink-2">
                  {{ money(item.upcoming_total) }}
                </td>
                <td class="num whitespace-nowrap text-right">
                  <span
                    class="font-bold"
                    :class="isPositive(item.credit_balance) ? 'text-ok-700' : 'text-ink-2'"
                  >
                    {{ money(item.credit_balance) }}
                  </span>
                </td>
                <td class="num whitespace-nowrap text-right text-ink-2">
                  {{ money(item.ready_to_apply) }}
                </td>
                <td class="text-right">
                  <RouterLink
                    :to="{
                      name: 'finance-individual-account-detail',
                      params: { studentId: item.student_id },
                    }"
                    class="btn-ghost-ui"
                    :aria-label="`เปิดบัญชีของ ${item.name}`"
                    @click.stop
                  >
                    <i class="bi bi-chevron-right" aria-hidden="true"></i>
                  </RouterLink>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>
