<script setup lang="ts">
/**
 * 📊 MoneyOwnershipCards — "ห้องมีเงินของตัวเองเท่าไหร่" (FIN-V2 / P6.4)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * 🔑 กติกาที่ห้ามพลาด
 * ═══════════════════════════════════════════════════════════════════════════
 *  1. **ตัวเลขทุกตัวมาจาก `ownership`** — component นี้ **ห้ามรวม/ลบเอง**
 *     (สมการเป็นความรับผิดชอบของ backend ที่อ่าน snapshot ใน transaction เดียว)
 *  2. **ไม่ clamp ค่าติดลบ** — `net_room_money < 0` คือสัญญาณว่าเครดิตค้างมากกว่า
 *     เงินสด (ข้อมูลผิด) ⇒ แสดงสี danger + คำเตือน ไม่ใช่ซ่อนเป็นศูนย์
 *  3. `total_cash = 0` **ต้องแสดง ฿0.00** ไม่ใช่ซ่อนการ์ด — ห้องใหม่ต้องเห็นว่า
 *     ยังไม่มีเงิน (การซ่อนทำให้เข้าใจผิดว่า "โหลดไม่ขึ้น")
 *  4. `truncate` ใช้ได้เฉพาะชื่อผู้รับ — **ห้ามตัดตัวเลขเงิน**
 *  5. "เครดิตค้าง" กับ "ยังค้างรับ" **ไม่ใช่เงินสด** — ต้องมีคำอธิบายกำกับทุกการ์ด
 *
 * โครง 3 ชั้น: สมการเงินของห้อง → เงินสด (กระเป๋า/ผู้ถือ) → ภาระ/ลูกหนี้ (ไม่ใช่เงินสด)
 *
 * @example
 * <MoneyOwnershipCards :ownership="ownership" :is-loading="isLoading" />
 */
import { computed } from 'vue'

import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import { formatMoney } from '@/utils/money'
import type { MoneyOwnership } from '@/types/finance'

const props = defineProps<{
  ownership: MoneyOwnership | null
  isLoading: boolean
}>()

/** แสดงผู้ถือเงินได้สูงสุด 3 คนก่อน ที่เหลือพับใน `<details>` (ไม่ตัดชื่อทิ้ง) */
const VISIBLE_RECEIVERS = 3

const visibleReceivers = computed(() =>
  (props.ownership?.by_receiver ?? []).slice(0, VISIBLE_RECEIVERS),
)

const hiddenReceivers = computed(() =>
  (props.ownership?.by_receiver ?? []).slice(VISIBLE_RECEIVERS),
)

const isNegative = computed(() => (props.ownership?.net_room_money ?? 0) < 0)
</script>

<template>
  <SkeletonRows v-if="isLoading" :rows="3" height="h-24" />

  <div v-else-if="ownership" class="space-y-3">
    <!-- ชั้น 1: เงินของห้อง (คำตอบของคำถามหลัก) -->
    <div
      class="page-card border-s-4 p-4 sm:p-5"
      :class="isNegative ? 'border-s-danger-700' : 'border-s-brand-700'"
    >
      <p class="text-caption font-bold text-ink-3">เงินของห้อง (ใช้ได้จริง)</p>
      <p
        class="num mt-2 break-words text-3xl font-bold sm:text-4xl"
        :class="isNegative ? 'text-danger-700' : 'text-ink'"
      >
        {{ formatMoney(ownership.net_room_money) }}
      </p>
      <p class="mt-2 text-xs text-ink-3">
        เงินสดรวม {{ formatMoney(ownership.total_cash) }} − เครดิตค้าง
        {{ formatMoney(ownership.credit_liability) }}
      </p>
      <p v-if="isNegative" class="mt-2 rounded-control bg-danger-50 px-3 py-2 text-xs font-bold text-danger-700">
        เครดิตที่ติดค้างมากกว่าเงินสดที่มีอยู่ — ตรวจสอบยอดเครดิตและกระเป๋าเงิน
      </p>
    </div>

    <!-- ชั้น 2: เงินสดในมือ — แยกกระเป๋ากับผู้ถือ -->
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <div class="page-card p-4 sm:p-5">
        <p class="flex items-center gap-1.5 text-caption font-bold text-ink-3">
          <i class="bi bi-credit-card-2-front text-brand-700" aria-hidden="true"></i>
          เงินสดในกระเป๋า
        </p>
        <p class="num mt-2 break-words text-2xl font-bold text-ink sm:text-3xl">
          {{ formatMoney(ownership.room_wallets) }}
        </p>
        <p class="mt-1 text-xs text-ink-3">เงินสดรวมทั้งห้อง {{ formatMoney(ownership.total_cash) }}</p>
      </div>

      <div class="page-card p-4 sm:p-5">
        <p class="flex items-center gap-1.5 text-caption font-bold text-ink-3">
          <i class="bi bi-person-badge text-warn-600" aria-hidden="true"></i>
          ผู้รับเงินถืออยู่
        </p>
        <p class="num mt-2 break-words text-2xl font-bold text-ink sm:text-3xl">
          {{ formatMoney(ownership.custody_held) }}
        </p>
        <p class="mt-1 text-xs text-ink-3">ยังไม่ได้ส่งมอบเข้าเงินของห้อง</p>
      </div>
    </div>

    <!-- รายชื่อผู้ถือเงิน — แสดงชื่อจริง ไม่ตัดทิ้ง -->
    <div v-if="visibleReceivers.length > 0" class="page-card p-4 sm:p-5">
      <h3 class="section-title mb-2 flex items-center gap-2">
        <i class="bi bi-people text-ink-3" aria-hidden="true"></i>
        ใครถือเงินอยู่
      </h3>
      <ul class="divide-y divide-line">
        <li
          v-for="receiver in visibleReceivers"
          :key="receiver.receiver_id"
          class="flex items-center justify-between gap-3 py-2"
        >
          <span class="min-w-0 truncate text-sm text-ink-2">{{ receiver.name }}</span>
          <span class="num shrink-0 text-sm font-bold text-ink tabular-nums">
            {{ formatMoney(receiver.held) }}
          </span>
        </li>
      </ul>
      <details v-if="hiddenReceivers.length > 0" class="mt-1">
        <summary class="cursor-pointer py-2 text-xs font-bold text-brand-700">
          และอีก {{ hiddenReceivers.length }} คน
        </summary>
        <ul class="divide-y divide-line">
          <li
            v-for="receiver in hiddenReceivers"
            :key="receiver.receiver_id"
            class="flex items-center justify-between gap-3 py-2"
          >
            <span class="min-w-0 truncate text-sm text-ink-2">{{ receiver.name }}</span>
            <span class="num shrink-0 text-sm font-bold text-ink tabular-nums">
              {{ formatMoney(receiver.held) }}
            </span>
          </li>
        </ul>
      </details>
    </div>

    <!-- ชั้น 3: สิ่งที่ไม่ใช่เงินสด — ภาระและลูกหนี้ -->
    <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <div class="page-card p-4 sm:p-5">
        <p class="flex items-center gap-1.5 text-caption font-bold text-ink-3">
          <i class="bi bi-piggy-bank text-warn-600" aria-hidden="true"></i>
          เครดิตค้างให้นักเรียน
        </p>
        <p class="num mt-2 break-words text-2xl font-bold text-warn-700 sm:text-3xl">
          {{ formatMoney(ownership.credit_liability) }}
        </p>
        <p class="mt-1 text-xs text-ink-3">
          ไม่ใช่เงินสด — ห้องติดค้างนักเรียน และอาจต้องคืนหรือหักค่าของนักเรียน
        </p>
      </div>

      <div class="page-card p-4 sm:p-5">
        <p class="flex items-center gap-1.5 text-caption font-bold text-ink-3">
          <i class="bi bi-hourglass-split text-ink-3" aria-hidden="true"></i>
          ยังค้างรับจากนักเรียน
        </p>
        <p class="num mt-2 break-words text-2xl font-bold text-ink-2 sm:text-3xl">
          {{ formatMoney(ownership.receivable_total) }}
        </p>
        <p class="mt-1 text-xs text-ink-3">
          ไม่ใช่เงินสด — ยังไม่ได้รับเงิน รวมบิลที่ถูกตัดจำหน่ายแล้วหักออก
        </p>
      </div>
    </div>
  </div>
</template>
