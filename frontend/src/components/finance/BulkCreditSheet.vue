<script setup lang="ts">
/**
 * 💳 BulkCreditSheet — หักเครดิตหลายคนเป็นรอบเดียว (FIN-V2 / P3.5)
 *
 * ════════════════════════════════════════════════════════════════════════════
 * 🎯 1 ครั้งที่กดยืนยัน = 1 คำขอ = 1 transaction = **all-or-nothing**
 * ════════════════════════════════════════════════════════════════════════════
 * 1 นักเรียน = 1 payment event แบบ credit-only (ไม่มี REC/DEP, ไม่แตะกระเป๋าเงิน)
 * — เงินเข้ามาตั้งแต่ตอนเติมเครดิตแล้ว จังหวะนี้เป็นเพียงการจัดสรร
 *
 * 🔴 กฎที่ห้ามพลาด
 *  1. `idempotency_key` ของทั้งรอบสร้าง **ครั้งแรกที่กดยืนยัน** และคงเดิมตอน retry
 *     (สร้างใหม่ตอน retry = รอบใหม่ ⇒ หักเครดิตซ้ำจากเจตนาเดียว)
 *  2. **ส่งเฉพาะคนที่มี allocations จริง** (total_applied > 0) — คนที่ไม่มีบิลค้าง
 *     ต้องไม่ถูกส่งไปให้ backend สร้าง event เปล่า ๆ (ตาราง `skipped` จะว่างเสมอ
 *     ถ้าส่งถูก) และต้องโชว์ให้เห็นว่าคนนั้นถูกข้าม
 *  3. 409 = คีย์นี้เคยใช้กับชุดนักเรียนอื่น ⇒ **ไม่ปิดแผ่นเอง** คงข้อความไว้ให้อ่าน
 *     และโหลดรายชื่อใหม่ (ไม่มีอะไรถูกหัก — all-or-nothing)
 *  4. ข้อเสนอ (`plan`) มาจาก engine ตัวเดียวกับ backend ใช้ลงมือ ⇒ "สิ่งที่เห็น = สิ่งที่ทำ"
 *     ถ้าบิลถูกปิดระหว่างนี้ backend จะหักได้น้อยลงและคืนยอดจริงใน `events`
 */
import { computed, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import { apiStatus } from '@/services/api'
import type {
  CreditApplyPlan,
  CreditPlanItem,
  CreditRoundResponse,
  FinancePerson,
} from '@/types/finance'
import { formatMoney, newIdempotencyKey, roundMoney } from '@/utils/money'
import { formatThaiDate, todayIso } from '@/utils/datetime'

import AppSheet from '@/components/ui/AppSheet.vue'
import AppButton from '@/components/ui/AppButton.vue'

const props = withDefaults(
  defineProps<{
    open: boolean
    /** ข้อเสนอจาก `getCreditPlan` ของนักเรียนที่ติ๊กไว้ */
    plan: CreditApplyPlan | null
    /** ทะเบียนผู้รับเงิน (กรอง active + role receive ให้แล้วหรือยังก็ได้) */
    receiverOptions?: FinancePerson[]
  }>(),
  { receiverOptions: () => [] },
)

const emit = defineEmits<{
  close: []
  applied: [result: CreditRoundResponse]
}>()

const authStore = useAuthStore()

const roomId = computed(() => Number(authStore.currentRoomId ?? 0))
const currentUserName = computed(() => authStore.currentUserName ?? '')
const canWrite = computed(() => authStore.canManageFinance)

// ───────────────────────────────────────────────────── state
const referenceNo = ref('')
const receiverPersonId = ref<number | null>(null)
const receiverName = ref('')
const note = ref('')
const isSubmitting = ref(false)
const errorMessage = ref('')

/** 🔑 คีย์ของทั้งรอบ — สร้างเมื่อกดยืนยันครั้งแรกเท่านั้น (retry ต้องใช้ตัวเดิม) */
const attemptKey = ref<string | null>(null)

// ───────────────────────────────────────────────────── computed
const items = computed<CreditPlanItem[]>(() => props.plan?.items ?? [])

/** คนที่จะถูกส่งจริง — มีบิลให้หักและยอด > 0 เท่านั้น */
const eligibleItems = computed(() =>
  items.value.filter(
    (item) => item.allocations.length > 0 && roundMoney(item.total_applied) > 0,
  ),
)

/** คนที่ถูกข้าม — ต้องโชว์ให้เห็น ไม่ใช่หายเงียบ ๆ */
const skippedItems = computed(() =>
  items.value.filter(
    (item) => !(item.allocations.length > 0 && roundMoney(item.total_applied) > 0),
  ),
)

const totalApplied = computed(() =>
  roundMoney(eligibleItems.value.reduce((sum, item) => sum + roundMoney(item.total_applied), 0)),
)

const totalBills = computed(() =>
  eligibleItems.value.reduce((sum, item) => sum + item.allocations.length, 0),
)

const receivePeople = computed(() =>
  props.receiverOptions.filter((p) => p.is_active && p.roles.includes('receive')),
)

const submitDisabled = computed(
  () =>
    !canWrite.value ||
    isSubmitting.value ||
    eligibleItems.value.length === 0 ||
    !roomId.value,
)

// ───────────────────────────────────────────────────── form lifecycle
const defaultReference = (): string =>
  `รอบหักเครดิต ${formatThaiDate(todayIso())}`

const resetForm = () => {
  referenceNo.value = defaultReference()
  receiverPersonId.value = null
  receiverName.value = ''
  note.value = ''
  errorMessage.value = ''
  attemptKey.value = null
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      resetForm()
    } else {
      attemptKey.value = null
    }
  },
  { immediate: true },
)

watch(receiverPersonId, (id) => {
  if (id === null) return
  const person = receivePeople.value.find((p) => p.person_id === id)
  if (person) receiverName.value = person.display_name
})

// ───────────────────────────────────────────────────── submit
const errorOf = (error: unknown): string =>
  error instanceof Error && error.message ? error.message : 'เกิดข้อผิดพลาดจาก API'

const submit = async () => {
  if (submitDisabled.value || isSubmitting.value) return

  const key = (attemptKey.value ??= newIdempotencyKey())
  isSubmitting.value = true
  errorMessage.value = ''

  try {
    const res = await FinanceService.createCreditRound(roomId.value, {
      idempotency_key: key,
      student_ids: eligibleItems.value.map((item) => item.student_id),
      reference_no: referenceNo.value.trim() || null,
      receiver_person_id: receiverPersonId.value,
      note: note.value.trim() || null,
      user_name: receiverName.value.trim() || currentUserName.value || null,
    })

    // ✅ สำเร็จ — คีย์หมดหน้าที่แล้ว การเปิดแผ่นครั้งถัดไปคือรอบใหม่จริง ๆ
    attemptKey.value = null
    emit('applied', res)
  } catch (error) {
    // 🔴 409 ≠ ข้อมูลผู้ใช้ผิด — ต้องบอกว่าต้องโหลดรายชื่อใหม่ และ **ไม่ปิดแผ่น**
    //    (ถ้าปิด ผู้ใช้จะไม่เห็นสาเหตุและอาจกดซ้ำด้วยคีย์เดิมอีก)
    //    คง `attemptKey` ไว้โดยเจตนา: ถ้าเป็น error ชั่วคราว กดซ้ำจะได้ผลเดิมไม่ซ้ำซ้อน
    errorMessage.value =
      apiStatus(error) === 409
        ? 'รอบนี้ถูกใช้กับชุดนักเรียนอื่นแล้ว — ปิดแผ่นแล้วโหลดรายชื่อใหม่ (ยังไม่มีใครถูกหัก)'
        : `${errorOf(error)} — ยังไม่มีใครถูกหัก (ยกเลิกทั้งรอบ)`
  } finally {
    isSubmitting.value = false
  }
}

const closeSheet = () => {
  if (isSubmitting.value) return
  attemptKey.value = null
  emit('close')
}
</script>

<template>
  <AppSheet
    :open="open"
    label="หักเครดิตหลายคน"
    title="ยืนยันหักเครดิตหลายคน"
    description="1 รอบ = ทั้งหมดหรือไม่หักเลย · ไม่มีเงินเคลื่อนไหว (เครดิตไม่ใช่เงินสด)"
    size="form"
    :dismissible="!isSubmitting"
    @close="closeSheet"
  >
    <div class="space-y-4">
      <!-- 📊 สรุปยอด -->
      <div class="grid grid-cols-3 gap-2 rounded-control bg-canvas p-3 text-center">
        <div>
          <p class="text-caption text-ink-3">นักเรียน</p>
          <p class="num text-lg font-bold text-ink">{{ eligibleItems.length }} คน</p>
        </div>
        <div>
          <p class="text-caption text-ink-3">บิลที่จะปิด</p>
          <p class="num text-lg font-bold text-ink">{{ totalBills }} รายการ</p>
        </div>
        <div>
          <p class="text-caption text-ink-3">เครดิตที่จะหัก</p>
          <p class="num text-lg font-bold text-ink">{{ formatMoney(totalApplied) }}</p>
        </div>
      </div>

      <!-- 🚧 คนที่ถูกข้าม -->
      <div
        v-if="skippedItems.length"
        data-test="credit-round-skip"
        class="rounded-control border border-line px-3 py-2 text-caption text-ink-2"
      >
        <p class="font-bold text-ink-3">จะถูกข้าม (ไม่มีบิลค้างหรือเครดิตไม่พอ)</p>
        <p>{{ skippedItems.map((item) => item.student_name ?? `#${item.student_id}`).join(' · ') }}</p>
      </div>

      <!-- 📋 ต่อคน: เครดิตก่อน → หัก → เหลือ -->
      <div class="max-h-64 space-y-2 overflow-y-auto">
        <div
          v-for="item in eligibleItems"
          :key="item.student_id"
          class="rounded-control border border-line p-3"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <p class="truncate font-bold text-ink">
                {{ item.student_name ?? `#${item.student_id}` }}
              </p>
              <p class="text-caption text-ink-3">
                เครดิตก่อนหัก {{ formatMoney(item.balance_before) }}
              </p>
            </div>
            <div class="shrink-0 text-right">
              <p class="num font-bold text-ink">−{{ formatMoney(item.total_applied) }}</p>
              <p class="text-caption text-ink-3">เหลือ {{ formatMoney(item.balance_after) }}</p>
            </div>
          </div>
          <ul class="mt-2 space-y-1 border-t border-line pt-2">
            <li
              v-for="a in item.allocations"
              :key="a.payment_id"
              class="flex items-start justify-between gap-3 text-caption"
            >
              <span class="min-w-0 truncate text-ink-2">
                {{ a.title ?? 'รายการชำระเงิน' }}
                <span v-if="a.due_date" class="text-ink-3">({{ a.due_date }})</span>
              </span>
              <span class="num shrink-0 font-bold text-ink">{{ formatMoney(a.apply_amount) }}</span>
            </li>
          </ul>
        </div>
      </div>

      <!-- 🧾 ข้อมูลของรอบ -->
      <div class="space-y-3">
        <div>
          <label class="field-label" for="credit-round-reference">เลขที่รอบ</label>
          <input
            id="credit-round-reference"
            v-model="referenceNo"
            class="field"
            maxlength="128"
            :disabled="isSubmitting || attemptKey !== null"
          />
          <p v-if="attemptKey !== null" class="mt-1 text-caption text-ink-3">
            ล็อกเลขนี้แล้วเพื่อกันทำซ้ำ — กดยืนยันซ้ำได้อย่างปลอดภัย
          </p>
        </div>

        <div>
          <label class="field-label" for="credit-round-receiver">ผู้บันทึก / ผู้รับ</label>
          <select
            id="credit-round-receiver"
            class="field"
            :value="receiverPersonId ?? ''"
            :disabled="isSubmitting"
            @change="
              receiverPersonId = ($event.target as HTMLSelectElement).value
                ? Number(($event.target as HTMLSelectElement).value)
                : null
            "
          >
            <option value="">— ใช้ชื่อผู้บันทึก —</option>
            <option v-for="p in receivePeople" :key="p.person_id" :value="p.person_id">
              {{ p.display_name }}
            </option>
          </select>
          <p v-if="receiverPersonId !== null" class="mt-1 text-caption text-ink-3">
            ชื่อในรายการจะบันทึกเป็น {{ receiverName }}
          </p>
        </div>

        <div>
          <label class="field-label" for="credit-round-note">หมายเหตุ (ไม่บังคับ)</label>
          <input
            id="credit-round-note"
            v-model="note"
            class="field"
            maxlength="255"
            placeholder="เช่น หักเครดิตทดสอบของเดือนนี้"
            :disabled="isSubmitting"
          />
        </div>
      </div>

      <p
        v-if="errorMessage"
        data-test="credit-round-error"
        class="rounded-control border border-danger-200 bg-danger-50 px-3 py-2 text-sm text-danger-700"
      >
        {{ errorMessage }}
      </p>

      <p
        v-if="!canWrite"
        class="rounded-control border border-line px-3 py-2 text-sm text-ink-3"
      >
        บัญชีนี้ไม่มีสิทธิ์หักเครดิต (ต้องมีสิทธิ์ MANAGE_FINANCE)
      </p>

      <p class="rounded-control bg-canvas p-3 text-caption text-ink-2">
        การหักเครดิต <b>ไม่มีเงินเคลื่อนไหว</b> และ <b>ไม่ออกใบเสร็จใหม่</b> —
        หลักฐานคือใบรับเงินล่วงหน้าที่ออกไว้แล้ว · ถ้าบิลถูกปิดไปก่อนหน้านี้
        ระบบจะหักได้น้อยลงตามจริงและแจ้งผลในรอบนี้
      </p>
    </div>

    <template #footer>
      <div class="flex gap-2">
        <AppButton variant="secondary" block :disabled="isSubmitting" @click="closeSheet">
          ยกเลิก
        </AppButton>
        <!-- 🔒 ไม่มี MANAGE_FINANCE ⇒ ไม่เรนเดอร์ปุ่มเขียนเลย (ไม่ใช่แค่ disable) -->
        <AppButton
          v-if="canWrite"
          data-test="credit-round-submit"
          variant="primary"
          block
          :loading="isSubmitting"
          :disabled="submitDisabled"
          @click="submit"
        >
          หักเครดิต {{ eligibleItems.length }} คน
        </AppButton>
      </div>
    </template>
  </AppSheet>
</template>
