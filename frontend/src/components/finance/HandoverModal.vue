<script setup lang="ts">
/**
 * 👜 HandoverModal — แผ่นเดียวสองโหมดของ “เงินสดรอส่งมอบ” (FIN-V2 / P3.2)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * โหมด `handover` — ส่งมอบเงินระหว่างกระเป๋าผู้ถือกับกระเป๋าหลักของห้อง
 * ═══════════════════════════════════════════════════════════════════════════
 *  • `out` = ผู้ถือ **นำส่งคืน** เข้ากระเป๋าหลัก (Dr หลัก / Cr ผู้ถือ)
 *  • `in`  = เงินจากกระเป๋าหลัก **เข้าผู้ถือ** (Dr ผู้ถือ / Cr หลัก)
 *  ทั้งสองทิศเป็น “โอนสินทรัพย์→สินทรัพย์” ไม่ใช่รายรับ/รายจ่าย (P3.1 รับผิดชอบ)
 *
 * 🔴 idempotency key สร้าง **ตอนเปิดฟอร์ม** (watch `open`) ไม่ใช่ตอนกด submit —
 *    ถ้าเน็ตสะดุดแล้วผู้ใช้กดซ้ำ ต้องได้ key เดิม ไม่งั้นเกิดการส่งมอบซ้ำ
 *    (backend กันซ้ำได้ด้วย key เท่านั้น) ⇒ `regenerateKeyForCurrentForm()`
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * โหมด `movements` — รายการเคลื่อนไหว + ยกเลิกการส่งมอบ
 * ═══════════════════════════════════════════════════════════════════════════
 *  • backend คืนเฉพาะ handover ที่ยัง `active` ⇒ รายการที่ยกเลิกแล้วจะหายจากลิสต์
 *    (ยึดยอดจริง ไม่ยึดประวัติที่ถูกกลับรายการ) — ไม่ใช่บั๊ก
 *  • ยกเลิกได้เฉพาะ `kind` handover และเมื่อ `canManage`; บังคับกรอกเหตุผล
 *  • กรองวันที่ได้ (`from`/`to`) — ใช้ guard ตัวนับรุ่นกันคำตอบเก่าทับใหม่
 *
 * @example
 * <HandoverModal
 *   :open="sheetOpen" :mode="sheetMode" :item="activeItem"
 *   :accounts="mainAccounts" :people="receivePeople" :can-manage="canManageFinance"
 *   @close="sheetOpen = false" @saved="fetchCustody"
 * />
 */
import { computed, ref, watch } from 'vue'

import { FinanceService } from '@/services/finance'
import type { Account, CustodyItem, CustodyMovement, FinancePerson } from '@/types/finance'

import AppSheet from '@/components/ui/AppSheet.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppChip from '@/components/ui/AppChip.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import { useAuthStore } from '@/stores/auth'
import { useDialog } from '@/composables/useDialog'
import { formatMoney, newIdempotencyKey, roundMoney } from '@/utils/money'
import { formatThaiDateTime } from '@/utils/datetime'
import { createLatestGuard } from '@/utils/latest'

const props = withDefaults(
  defineProps<{
    open: boolean
    mode: 'handover' | 'movements'
    item: CustodyItem | null
    /** กระเป๋าหลัก/ธนาคารของห้อง — **ไม่รวม** กระเป๋า custody (ผู้เรียกกรองแล้ว) */
    accounts: Account[]
    /** ผู้เกี่ยวข้องที่มีบทบาท `receive` — ผู้เรียกกรองแล้ว */
    people: FinancePerson[]
    canManage?: boolean
  }>(),
  { canManage: false },
)

const emit = defineEmits<{
  close: []
  saved: []
}>()

const authStore = useAuthStore()
const dialog = useDialog()
const roomId = authStore.currentRoomId!

const KIND_LABELS: Record<CustodyMovement['kind'], string> = {
  handover_in: 'รับมอบเงินเข้า',
  handover_out: 'นำส่งเงินออก',
  expense: 'จ่ายจากกระเป๋า',
  income: 'เงินรับเข้า',
}

const MOVEMENT_ICONS: Record<CustodyMovement['kind'], string> = {
  handover_in: 'bi-box-arrow-in-down',
  handover_out: 'bi-box-arrow-up',
  expense: 'bi-cart-dash',
  income: 'bi-cash-coin',
}

// ────────────────────────────── ฟอร์มส่งมอบ ──────────────────────────────
type Direction = 'out' | 'in'

const direction = ref<Direction>('out')
const selectedAccountId = ref<number | null>(null)
// ⚠️ `v-model` บน `<input type="number">` ของ Vue คืน **number** (cast ให้เอง)
//    ⇒ ต้องรับทั้งสองชนิด ไม่งั้น `.trim()` ระเบิดเวลาเทสต์/ผู้ใช้พิมพ์ตัวเลข
const amountInput = ref<string | number>('')
const handedOverBy = ref<number | null>(null)
const receivedBy = ref<number | null>(null)
const note = ref('')
const isSaving = ref(false)
/** 🔑 คีย์ของการเปิดฟอร์มครั้งนี้ — ห้ามสร้างใหม่ตอน submit */
const idempotencyKey = ref('')

const resetForm = () => {
  direction.value = 'out'
  selectedAccountId.value = props.accounts[0]?.id ?? null
  amountInput.value = ''
  handedOverBy.value = null
  receivedBy.value = null
  note.value = ''
  // 🔑 สร้างครั้งเดียวตอนเปิดฟอร์ม — retry ทั้งหมดในฟอร์มนี้ใช้ค่าเดิม
  try {
    idempotencyKey.value = newIdempotencyKey()
  } catch {
    // บราวเซอร์เก่าที่ไม่มี crypto.randomUUID — ยังเปิดฟอร์มได้ แต่บันทึกไม่ได้
    // (ปุ่มบันทึกจะ disabled พร้อมอธิบายเหตุผล)
    idempotencyKey.value = ''
  }
}

/** ค่าที่พิมพ์ (normalize เป็น string — input[type=number] ให้ number ได้) */
const amountText = computed(() => String(amountInput.value ?? '').trim())

const amountNumber = computed(() => {
  const n = Number(amountText.value)
  return Number.isFinite(n) ? roundMoney(n) : 0
})

const amountError = computed(() => {
  if (!amountText.value) return ''
  if (!Number.isFinite(Number(amountText.value))) return 'จำนวนเงินไม่ถูกต้อง'
  if (amountNumber.value <= 0) return 'จำนวนเงินต้องมากกว่าศูนย์'
  if (direction.value === 'out' && props.item && amountNumber.value > props.item.balance) {
    return 'จำนวนเงินมากกว่ายอดที่ผู้ถือมีอยู่'
  }
  return ''
})

const canSubmit = computed(() => {
  if (!props.item || !idempotencyKey.value) return false
  if (amountNumber.value <= 0 || amountError.value) return false
  if (direction.value === 'out') {
    return !!props.item.account_id && selectedAccountId.value !== null
  }
  return selectedAccountId.value !== null && props.item.account_id !== selectedAccountId.value
})

const sourceLabel = computed(() =>
  direction.value === 'out' ? props.item?.account_name ?? '—' : 'กระเป๋าหลักของห้อง',
)
const destinationLabel = computed(() =>
  direction.value === 'out' ? 'กระเป๋าหลักของห้อง' : props.item?.account_name ?? '—',
)

const describeError = (error: unknown, fallback: string): string =>
  error instanceof Error && error.message ? error.message : fallback

const submitHandover = async () => {
  if (isSaving.value || !canSubmit.value || !props.item) return

  const fromId =
    direction.value === 'out' ? props.item.account_id : (selectedAccountId.value as number)
  const toId =
    direction.value === 'out' ? (selectedAccountId.value as number) : props.item.account_id

  isSaving.value = true
  try {
    await FinanceService.createCustodyHandover(roomId, {
      idempotency_key: idempotencyKey.value,
      from_account_id: fromId,
      to_account_id: toId,
      amount: amountNumber.value,
      handed_over_by_person_id: handedOverBy.value,
      received_by_person_id: receivedBy.value,
      note: note.value.trim() || null,
    })
    dialog.notify('บันทึกการส่งมอบแล้ว')
    emit('saved')
    emit('close')
  } catch (error: unknown) {
    // ⚠️ ไม่ปิดฟอร์มและไม่สร้าง key ใหม่ — ผู้ใช้กดบันทึกซ้ำได้อย่างปลอดภัย
    void dialog.alert('ส่งมอบไม่สำเร็จ', describeError(error, 'บันทึกการส่งมอบไม่สำเร็จ'), 'error')
  } finally {
    isSaving.value = false
  }
}

// ───────────────────────────── รายการเคลื่อนไหว ─────────────────────────────
const movements = ref<CustodyMovement[]>([])
const isLoadingMovements = ref(false)
const movementsError = ref(false)
const fromDate = ref('')
const toDate = ref('')
const voidingSourceId = ref<string | null>(null)

const guard = createLatestGuard()

const loadMovements = async () => {
  if (!props.item) return
  const token = guard.begin()
  isLoadingMovements.value = true
  movementsError.value = false
  try {
    const res = await FinanceService.getCustodyMovements(roomId, props.item.person_id, {
      from: fromDate.value || undefined,
      to: toDate.value || undefined,
    })
    if (!guard.isCurrent(token)) return
    movements.value = res.items
  } catch {
    if (!guard.isCurrent(token)) return
    movementsError.value = true
  } finally {
    if (guard.isCurrent(token)) isLoadingMovements.value = false
  }
}

watch(
  () => [props.open, props.mode, props.item?.person_id] as const,
  ([isOpen, mode]) => {
    if (!isOpen || !props.item) return
    if (mode === 'handover') {
      resetForm()
      return
    }
    fromDate.value = ''
    toDate.value = ''
    movements.value = []
    void loadMovements()
  },
  { immediate: true },
)

// ตัวกรองวันที่ — ใช้ guard ชุดเดียวกับ `loadMovements` (คำตอบเก่าถูกทิ้ง)
watch([fromDate, toDate], () => {
  if (props.open && props.mode === 'movements') void loadMovements()
})

const isHandoverKind = (kind: CustodyMovement['kind']) =>
  kind === 'handover_in' || kind === 'handover_out'

const voidHandover = async (movement: CustodyMovement) => {
  if (!props.canManage || voidingSourceId.value) return

  const res = await dialog.input('ยกเลิกการส่งมอบ', {
    text: 'เงินจะถูกโอนกลับเข้ากระเป๋าต้นทาง — ทำได้เฉพาะเมื่อปลายทางยังไม่ได้ใช้เงินก้อนนี้',
    input: 'textarea',
    inputLabel: 'เหตุผลการยกเลิก',
    inputPlaceholder: 'เช่น บันทึกผิดจำนวน / ส่งผิดคน',
    icon: 'warning',
    danger: true,
    confirmButtonText: 'ยกเลิกการส่งมอบ',
    cancelButtonText: 'ไม่ยกเลิก',
    preConfirm: (value) => {
      if (!value.trim()) throw new Error('กรุณากรอกเหตุผลการยกเลิก')
      return value.trim()
    },
  })
  if (!res.isConfirmed) return

  voidingSourceId.value = movement.source_id
  try {
    await FinanceService.voidCustodyHandover(roomId, Number(movement.source_id), {
      reason: res.value,
    })
    dialog.notify('ยกเลิกการส่งมอบแล้ว')
    emit('saved')
    await loadMovements()
  } catch (error: unknown) {
    void dialog.alert('ยกเลิกไม่สำเร็จ', describeError(error, 'ยกเลิกการส่งมอบไม่สำเร็จ'), 'error')
  } finally {
    voidingSourceId.value = null
  }
}

const sheetTitle = computed(() =>
  props.mode === 'handover' ? 'ส่งมอบเงิน' : 'รายการเคลื่อนไหว',
)
const sheetDescription = computed(() =>
  props.mode === 'handover'
    ? 'โอนเงินระหว่างกระเป๋าผู้ถือเงินกับกระเป๋าหลักของห้อง — ไม่ใช่รายรับ/รายจ่าย'
    : props.item
      ? `กระเป๋าของ ${props.item.display_name} · ${formatMoney(props.item.balance)}`
      : '',
)
</script>

<template>
  <AppSheet
    :open="open"
    :label="sheetTitle"
    :title="sheetTitle"
    :description="sheetDescription"
    size="form"
    :dismissible="!isSaving"
    @close="emit('close')"
  >
    <!-- ═════════════════════════ โหมดส่งมอบ ═════════════════════════ -->
    <form v-if="mode === 'handover'" class="grid grid-cols-1 gap-4" @submit.prevent="submitHandover">
      <div>
        <span class="field-label">ทิศทาง</span>
        <div class="flex flex-wrap gap-2">
          <button
            type="button"
            class="chip transition-colors"
            :class="direction === 'out' ? 'bg-brand-700 text-white' : 'bg-canvas text-ink-2'"
            :aria-pressed="direction === 'out'"
            @click="direction = 'out'"
          >
            <i class="bi bi-box-arrow-in-down" aria-hidden="true"></i>
            ผู้ถือนำส่งคืน
          </button>
          <button
            type="button"
            class="chip transition-colors"
            :class="direction === 'in' ? 'bg-brand-700 text-white' : 'bg-canvas text-ink-2'"
            :aria-pressed="direction === 'in'"
            @click="direction = 'in'"
          >
            <i class="bi bi-box-arrow-up" aria-hidden="true"></i>
            เงินเข้าผู้ถือ
          </button>
        </div>
      </div>

      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label class="field-label" for="handoverSource">ต้นทาง</label>
          <select
            v-if="direction === 'in'"
            id="handoverSource"
            v-model="selectedAccountId"
            class="field"
            :disabled="isSaving"
          >
            <option :value="null">— เลือกกระเป๋าหลัก —</option>
            <option v-for="acc in accounts" :key="acc.id" :value="acc.id">
              {{ acc.account_name }}
            </option>
          </select>
          <p v-else class="field bg-canvas text-ink-2">{{ sourceLabel }}</p>
        </div>

        <div>
          <label class="field-label" for="handoverDestination">ปลายทาง</label>
          <select
            v-if="direction === 'out'"
            id="handoverDestination"
            v-model="selectedAccountId"
            class="field"
            :disabled="isSaving"
          >
            <option :value="null">— เลือกกระเป๋าหลัก —</option>
            <option v-for="acc in accounts" :key="acc.id" :value="acc.id">
              {{ acc.account_name }}
            </option>
          </select>
          <p v-else class="field bg-canvas text-ink-2">{{ destinationLabel }}</p>
        </div>
      </div>

      <div>
        <label class="field-label" for="handoverAmount">จำนวนเงิน (บาท)</label>
        <input
          id="handoverAmount"
          v-model="amountInput"
          type="number"
          min="0.01"
          step="0.01"
          inputmode="decimal"
          class="field tabular-nums"
          placeholder="0.00"
          :disabled="isSaving"
          :aria-invalid="!!amountError"
          :aria-describedby="amountError ? 'handoverAmountError' : undefined"
        />
        <p v-if="amountError" id="handoverAmountError" class="mt-1 text-sm text-danger-700">
          {{ amountError }}
        </p>
      </div>

      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label class="field-label" for="handoverFromPerson">ผู้ส่งมอบ (ไม่บังคับ)</label>
          <select
            id="handoverFromPerson"
            v-model="handedOverBy"
            class="field"
            :disabled="isSaving"
          >
            <option :value="null">— ไม่ระบุ —</option>
            <option v-for="p in people" :key="p.person_id" :value="p.person_id">
              {{ p.display_name }}
            </option>
          </select>
        </div>
        <div>
          <label class="field-label" for="handoverToPerson">ผู้รับเงิน (ไม่บังคับ)</label>
          <select
            id="handoverToPerson"
            v-model="receivedBy"
            class="field"
            :disabled="isSaving"
          >
            <option :value="null">— ไม่ระบุ —</option>
            <option v-for="p in people" :key="p.person_id" :value="p.person_id">
              {{ p.display_name }}
            </option>
          </select>
        </div>
      </div>

      <div>
        <label class="field-label" for="handoverNote">หมายเหตุ (ไม่บังคับ)</label>
        <textarea
          id="handoverNote"
          v-model="note"
          class="field min-h-[4rem]"
          maxlength="500"
          placeholder="เช่น นำส่งเงินสดจากงานกีฬาสี"
          :disabled="isSaving"
        ></textarea>
      </div>

      <p v-if="!idempotencyKey" class="text-sm text-danger-700">
        เบราว์เซอร์นี้สร้างรหัสกันบันทึกซ้ำไม่ได้ — กรุณาอัปเดตเบราว์เซอร์ก่อนทำรายการเงิน
      </p>
    </form>

    <!-- ═══════════════════════ โหมดเคลื่อนไหว ═══════════════════════ -->
    <div v-else class="space-y-4">
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label class="field-label" for="custodyFromDate">ตั้งแต่วันที่</label>
          <input id="custodyFromDate" v-model="fromDate" type="date" class="field" />
        </div>
        <div>
          <label class="field-label" for="custodyToDate">ถึงวันที่</label>
          <input id="custodyToDate" v-model="toDate" type="date" class="field" />
        </div>
      </div>

      <SkeletonRows v-if="isLoadingMovements" :rows="4" height="h-14" />
      <StateBlock
        v-else-if="movementsError"
        variant="error"
        title="โหลดรายการเคลื่อนไหวไม่สำเร็จ"
        @retry="loadMovements"
      />
      <StateBlock
        v-else-if="!movements.length"
        variant="empty"
        icon="bi-inbox"
        title="ยังไม่มีความเคลื่อนไหว"
        hint="เมื่อมีการส่งมอบหรือใช้จ่ายจากกระเป๋านี้ รายการจะแสดงที่นี่"
      />
      <ul v-else class="divide-y divide-line">
        <li
          v-for="m in movements"
          :key="`${m.kind}-${m.source_id}`"
          class="flex flex-wrap items-start justify-between gap-2 py-2.5"
        >
          <div class="min-w-0">
            <p class="flex items-center gap-1.5 text-sm font-bold text-ink-1">
              <i :class="['bi', MOVEMENT_ICONS[m.kind]]" aria-hidden="true"></i>
              {{ KIND_LABELS[m.kind] }}
            </p>
            <p class="text-xs text-ink-3">{{ formatThaiDateTime(m.occurred_at) }}</p>
            <p v-if="m.description" class="truncate text-sm text-ink-2" :title="m.description">
              {{ m.description }}
            </p>
            <p v-if="m.reference_no" class="text-xs text-ink-3">อ้างอิง {{ m.reference_no }}</p>
          </div>
          <div class="flex flex-col items-end gap-1">
            <span
              class="text-sm font-bold tabular-nums"
              :class="m.amount < 0 ? 'text-danger-700' : 'text-ok-700'"
            >
              {{ formatMoney(m.amount) }}
            </span>
            <AppButton
              v-if="canManage && isHandoverKind(m.kind)"
              variant="quiet"
              :loading="voidingSourceId === m.source_id"
              :aria-label="`ยกเลิกการส่งมอบ ${formatMoney(m.amount)}`"
              @click="voidHandover(m)"
            >
              ยกเลิกการส่งมอบ
            </AppButton>
            <AppChip v-if="isHandoverKind(m.kind)" tone="brand">ยังไม่นำส่ง</AppChip>
          </div>
        </li>
      </ul>

      <p v-if="movements.length >= 500" class="text-xs text-ink-3">
        แสดงไม่เกิน 500 รายการล่าสุด — ปรับช่วงวันที่เพื่อดูรายการที่เก่ากว่า
      </p>
    </div>

    <template #footer>
      <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <AppButton variant="secondary" block class="sm:w-auto" :disabled="isSaving" @click="emit('close')">
          ปิด
        </AppButton>
        <AppButton
          v-if="mode === 'handover'"
          variant="primary"
          block
          class="sm:w-auto"
          :loading="isSaving"
          :disabled="!canSubmit"
          @click="submitHandover"
        >
          บันทึกการส่งมอบ
        </AppButton>
      </div>
    </template>
  </AppSheet>
</template>
