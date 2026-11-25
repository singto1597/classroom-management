<script setup lang="ts">
/**
 * 🚀 QuickActions — ทางลัดจากรายการที่ backend กำหนด (FIN-V2 / P6.4)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * 🔑 กติกาที่ห้ามพลาด
 * ═══════════════════════════════════════════════════════════════════════════
 *  1. backend กำหนด "มีอะไรบ้าง" (`quick_actions`) — FE ถือ route เพราะ backend
 *     ไม่ควรรู้ URL ของ SPA
 *  2. action ที่ FE ไม่รู้จัก → **ข้าม** (ห้าม throw) เพื่อให้เพิ่มฝั่ง server ได้
 *     ก่อน deploy FE
 *  3. ลิงก์ใช้ `<RouterLink>` — ไม่ใช้ `router.push` ใน click handler (คลิกกลาง/
 *     open-in-new-tab ต้องทำงาน)
 *  4. `actions` ว่าง / ไม่มี action ที่รู้จัก → ไม่ render บล็อก
 *
 * @example
 * <QuickActions :actions="ownership?.quick_actions ?? []" />
 */
import { computed } from 'vue'

const props = defineProps<{
  actions: string[]
}>()

interface ActionMeta {
  label: string
  icon: string
  to: string
}

const ACTION_META: Readonly<Record<string, ActionMeta>> = {
  receive: { label: 'รับเงิน', icon: 'bi-cash-coin', to: '/finance/individual-accounts' },
  expense: { label: 'จ่ายเงิน', icon: 'bi-wallet2', to: '/finance/transactions/add' },
  income: { label: 'รับรายได้', icon: 'bi-graph-up-arrow', to: '/finance/transactions/add' },
  handover: { label: 'ส่งมอบเงิน', icon: 'bi-arrow-left-right', to: '/finance/custody' },
  report: { label: 'ปิดงบเดือน', icon: 'bi-clipboard2-check', to: '/finance/monthly-reports' },
}

// ⚠️ ถ้า `actions` มีค่าซ้ำ ให้แสดงครั้งเดียว (backend อาจส่งซ้ำได้ในอนาคต)
const knownActions = computed<ActionMeta[]>(() => {
  const seen = new Set<string>()
  const result: ActionMeta[] = []
  for (const action of props.actions) {
    const meta = ACTION_META[action]
    if (!meta || seen.has(action)) continue
    seen.add(action)
    result.push(meta)
  }
  return result
})
</script>

<template>
  <div v-if="knownActions.length > 0" class="page-card p-4 sm:p-5">
    <h2 class="section-title mb-3 flex items-center gap-2">
      <i class="bi bi-lightning-charge text-brand-700" aria-hidden="true"></i>
      ทางลัด
    </h2>
    <div class="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
      <RouterLink
        v-for="action in knownActions"
        :key="action.to + action.label"
        :to="action.to"
        class="flex flex-col items-center gap-1.5 rounded-control border border-line px-2 py-2.5 text-center transition-colors hover:bg-canvas active:scale-[0.97]"
      >
        <span class="flex h-9 w-9 items-center justify-center rounded-control bg-brand-50 text-brand-700">
          <i :class="['bi', action.icon, 'text-xl']" aria-hidden="true"></i>
        </span>
        <span class="text-xs font-bold text-ink-3">{{ action.label }}</span>
      </RouterLink>
    </div>
  </div>
</template>
