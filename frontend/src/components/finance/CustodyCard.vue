<script setup lang="ts">
/**
 * 👜 CustodyCard — การ์ดผู้ถือเงิน “เงินสดรอส่งมอบ” หนึ่งคน (FIN-V2 / P3.2)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * 🔑 กติกาที่ห้ามพลาด
 * ═══════════════════════════════════════════════════════════════════════════
 *  1. **ห้ามตัดตัวเลขเงิน** — `truncate` ใช้ได้เฉพาะชื่อ/ชื่อกระเป๋า
 *     (ดู `docs/skills.md` “✂️ truncate บนบรรทัดที่มีตัวเลขเงิน = ตัวเลขโกหก”)
 *     ⇒ ยอดใช้ `formatMoney` และอยู่นอกคอนเทนเนอร์ที่ `overflow-hidden` แบบตัดคำ
 *  2. `balance` มาจาก server เท่านั้น — การ์ด **ไม่คำนวณยอดคาดการณ์** หลังส่งมอบ
 *     หน้าหลักจะ `getCustody` ใหม่ทั้งชุด (brief P3.2 ข้อตัดสินใจ 4)
 *  3. ปุ่มเขียนแสดงเฉพาะ `canManage` — ตรงกับ `MANAGE_FINANCE` ของ backend
 *  4. การ์ดทั้งใบ **ไม่ใช่ปุ่ม** — มีปุ่มจริงข้างใน 3 ปุ่ม เพื่อให้ screen reader
 *     อ่านและกดด้วยคีย์บอร์ดได้ตามปกติ (ห้ามซ้อน `<button>` ใน `<button>`)
 */
import { computed } from 'vue'

import type { CustodyItem } from '@/types/finance'
import AppCard from '@/components/ui/AppCard.vue'
import AppChip from '@/components/ui/AppChip.vue'
import AppButton from '@/components/ui/AppButton.vue'
import { formatMoney } from '@/utils/money'
import { formatThaiDateTime } from '@/utils/datetime'

const props = defineProps<{
  item: CustodyItem
  /** 🔒 มาจาก `authStore.canManageFinance` — ซ่อนปุ่มเขียนเมื่อ false */
  canManage: boolean
}>()

const emit = defineEmits<{
  handover: [item: CustodyItem]
  movements: [item: CustodyItem]
  manage: [item: CustodyItem]
}>()

const KIND_LABELS = {
  cash: 'เงินสด',
  transfer: 'โอน',
} as const

const kindLabel = computed(() => KIND_LABELS[props.item.account_kind] ?? 'เงินสด')

const lastHandoverLabel = computed(() =>
  props.item.last_handover_at
    ? `ส่งมอบล่าสุด ${formatThaiDateTime(props.item.last_handover_at)}`
    : 'ยังไม่เคยส่งมอบ',
)

const ariaLabel = computed(() => `เงินสดรอส่งมอบของ ${props.item.display_name}`)
</script>

<template>
  <AppCard padding="md" class="flex h-full flex-col gap-3">
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <h3 class="truncate text-base font-bold text-ink-1" :title="item.display_name">
          {{ item.display_name }}
        </h3>
        <p class="truncate text-sm text-ink-3" :title="item.account_name">
          {{ item.account_name }}
        </p>
      </div>
      <AppChip tone="brand" icon="bi-wallet2">{{ kindLabel }}</AppChip>
    </div>

    <div class="rounded-control bg-canvas px-3 py-2.5">
      <p class="text-xs font-bold text-ink-3">ยอดถืออยู่</p>
      <!-- 🔴 ห้ามใส่ `truncate` หรือ `overflow-hidden` ที่บรรทัดนี้ -->
      <p
        data-test="custody-balance"
        class="text-2xl font-bold tabular-nums text-ink-1"
        :aria-label="ariaLabel"
      >
        {{ formatMoney(item.balance) }}
      </p>
      <p class="text-xs text-ink-3">{{ lastHandoverLabel }}</p>
    </div>

    <div class="mt-auto flex flex-wrap items-center gap-2">
      <AppButton variant="quiet" @click="emit('movements', item)">
        <i class="bi bi-clock-history" aria-hidden="true"></i>
        ดูเคลื่อนไหว
      </AppButton>
      <AppButton v-if="canManage" variant="quiet" @click="emit('manage', item)">
        <i class="bi bi-gear" aria-hidden="true"></i>
        จัดการ
      </AppButton>
      <AppButton
        v-if="canManage"
        variant="primary"
        class="ml-auto"
        @click="emit('handover', item)"
      >
        <i class="bi bi-arrow-left-right" aria-hidden="true"></i>
        ส่งมอบ
      </AppButton>
    </div>
  </AppCard>
</template>
