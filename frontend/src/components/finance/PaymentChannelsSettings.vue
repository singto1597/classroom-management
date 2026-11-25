<script setup lang="ts">
/**
 * 💳 ช่องทางชำระเงิน — แท็บในหน้า `/finance/settings` (FIN-V2 / P2.5)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * 🎯 สิ่งที่ผู้ใช้ต้องทำได้
 * ═══════════════════════════════════════════════════════════════════════════
 * เพิ่ม/แก้/ปิด/ลบช่องทาง, ตั้งตัวหลัก 1 ตัว, ดู PromptPay QR ที่ **server สร้าง**
 * (ยอดฝังได้) — โดยเลขบัญชี/พร้อมเพย์เต็ม **ไม่เคยขึ้นจอและไม่เคยย้อนกลับ backend**
 *
 * ⚠️ กฎที่ห้ามพลาด
 *   1. `*_masked` ที่ได้จาก API เป็นแค่ข้อความแสดง — ห้ามใส่กลับ payload ตอนแก้
 *   2. ฟอร์มแก้ไขช่องความลับเริ่ม **ว่างเสมอ** และ "เว้นว่าง = คงค่าเดิม"
 *      ⇒ ละคีย์ออกจาก payload ไม่ใช่ส่ง `null` (backend `exclude_unset` ตีความ `null` = ล้าง)
 *   3. ปุ่มเขียนใช้ `canManageFinance` (MANAGE_FINANCE) — ตรงกับ backend ไม่ใช่ `isAdmin`
 *   4. QR แสดงผ่าน `<img>` + object URL เท่านั้น (**ห้าม `v-html`**) และต้อง
 *      `revokeObjectURL` ทุกครั้งที่เปลี่ยน/ปิด เพื่อไม่ให้ Blob ค้างในหน่วยความจำ
 *   5. `active ≤ 3` และ `primary` ต้อง active — ตรวจฝั่งจอเพื่อประสบการณ์ แต่ยัง
 *      ต้องรับ 400/409 จาก backend ได้ (มีคนแก้พร้อมกัน)
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import type {
  Account,
  PaymentChannel,
  PaymentChannelCreate,
  PaymentChannelType,
  PaymentChannelUpdate,
  QrMode,
} from '@/types/finance'

import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import AppSheet from '@/components/ui/AppSheet.vue'
import RowActionMenu from '@/components/ui/RowActionMenu.vue'
import type { RowActionItem } from '@/components/ui/RowActionMenu.vue'
import { useDialog } from '@/composables/useDialog'
import { apiStatus } from '@/services/api'
import { downloadBlob } from '@/utils/download'
import { formatAmount, roundMoney } from '@/utils/money'

const authStore = useAuthStore()
const dialog = useDialog()

const roomId = authStore.currentRoomId!
/** 🔒 ปุ่มเขียนตรงกับ `require_permission(MANAGE_FINANCE)` ของ backend */
const canWrite = computed(() => authStore.canManageFinance)

/** 🧮 backend บังคับ 3 ช่องทางที่ **เปิดใช้งาน** ต่อห้อง */
const MAX_ACTIVE_CHANNELS = 3

const CHANNEL_TYPE_LABELS: Record<PaymentChannelType, string> = {
  cash: 'เงินสด',
  bank_transfer: 'โอนเข้าบัญชี',
  promptpay: 'พร้อมเพย์',
  custom_qr: 'QR กำหนดเอง',
}

const QR_MODE_LABELS: Record<QrMode, string> = {
  open: 'ไม่ฝังยอด',
  fixed: 'ฝังยอด',
}

const qrModeLabel = (channel: PaymentChannel): string =>
  channel.qr_mode ? QR_MODE_LABELS[channel.qr_mode] : ''

// ──────────────────────────────── รายการช่องทาง ────────────────────────────────
const channels = ref<PaymentChannel[]>([])
const accounts = ref<Account[]>([])
const isLoading = ref(true)
const hasError = ref(false)
const errorMessage = ref('')
const isDeletingId = ref<number | null>(null)

const activeCount = computed(() => channels.value.filter((ch) => ch.is_active).length)

const describeError = (error: unknown, fallback: string): string =>
  error instanceof Error && error.message ? error.message : fallback

const load = async () => {
  isLoading.value = true
  hasError.value = false
  try {
    // ⚠️ `includeInactive=true` — หน้า settings ต้องเห็นช่องทางที่ปิดอยู่เพื่อเปิดกลับได้
    const [channelRes, accountRes] = await Promise.all([
      FinanceService.getPaymentChannels(roomId, true),
      FinanceService.getAccounts(roomId),
    ])
    channels.value = channelRes
    accounts.value = accountRes
  } catch (error: unknown) {
    errorMessage.value = describeError(error, 'โหลดช่องทางชำระเงินไม่สำเร็จ')
    hasError.value = true
  } finally {
    isLoading.value = false
  }
}

// ──────────────────────────────── ฟอร์มเพิ่ม/แก้ ────────────────────────────────
interface ChannelForm {
  channel_type: PaymentChannelType
  label: string
  wallet_account_id: number | null
  account_name: string
  bank_name: string
  /** เลขบัญชี **เต็ม** — ว่างเมื่อแก้ (แสดงเฉพาะค่า mask เป็น placeholder) */
  account_number: string
  /** เลขพร้อมเพย์ **เต็ม** — ว่างเมื่อแก้ */
  promptpay_id: string
  qr_mode: QrMode
  is_primary: boolean
  is_active: boolean
}

const sheetOpen = ref(false)
const editing = ref<PaymentChannel | null>(null)
const isSaving = ref(false)
const form = reactive<ChannelForm>({
  channel_type: 'cash',
  label: '',
  wallet_account_id: null,
  account_name: '',
  bank_name: '',
  account_number: '',
  promptpay_id: '',
  qr_mode: 'open',
  is_primary: false,
  is_active: true,
})

const resetForm = () => {
  Object.assign(form, {
    channel_type: 'cash' as PaymentChannelType,
    label: '',
    wallet_account_id: null,
    account_name: '',
    bank_name: '',
    account_number: '',
    promptpay_id: '',
    qr_mode: 'open' as QrMode,
    is_primary: false,
    is_active: true,
  })
}

const handleAdd = () => {
  if (!canWrite.value) return
  if (activeCount.value >= MAX_ACTIVE_CHANNELS) {
    void dialog.alert(
      'ครบ 3 ช่องทางแล้ว',
      `ห้องนี้เปิดใช้งานช่องทางครบ ${MAX_ACTIVE_CHANNELS} ช่องทางแล้ว — ปิดช่องทางหนึ่งก่อนเพิ่มใหม่`,
      'warning',
    )
    return
  }
  editing.value = null
  resetForm()
  sheetOpen.value = true
}

const handleEdit = (channel: PaymentChannel) => {
  if (!canWrite.value) return
  editing.value = channel
  // 🔴 ช่องความลับ **ไม่ prefill** — API ไม่มีค่าเต็มให้ และ mask ที่กลับไปจะถูกเก็บเป็นเลขจริง
  Object.assign(form, {
    channel_type: channel.channel_type,
    label: channel.label,
    wallet_account_id: channel.wallet_account_id,
    account_name: channel.account_name ?? '',
    bank_name: channel.bank_name ?? '',
    account_number: '',
    promptpay_id: '',
    qr_mode: channel.qr_mode ?? 'open',
    is_primary: channel.is_primary,
    is_active: channel.is_active,
  })
  sheetOpen.value = true
}

/** เปิดอยู่ต้องไม่เป็นหลัก (ตรงกับ CHECK/validation ของ backend) */
const onActiveToggle = () => {
  if (!form.is_active) form.is_primary = false
}

const validateForm = (): string | null => {
  if (!form.label.trim()) return 'กรุณากรอกชื่อช่องทาง'
  if (form.is_primary && !form.is_active) return 'ช่องทางหลักต้องเปิดใช้งาน'

  if (form.channel_type === 'bank_transfer') {
    if (!form.bank_name.trim()) return 'กรุณากรอกชื่อธนาคาร'
    if (!form.account_name.trim()) return 'กรุณากรอกชื่อเจ้าของบัญชี'
    // ตอนแก้ ปล่อยเลขบัญชีว่างได้ = คงเลขเดิม
    if (!editing.value && !form.account_number.trim()) return 'กรุณากรอกเลขที่บัญชี'
  }

  if (form.channel_type === 'promptpay') {
    if (!form.account_name.trim()) return 'กรุณากรอกชื่อเจ้าของพร้อมเพย์'
    if (!editing.value && !form.promptpay_id.trim()) {
      return 'กรุณากรอกเบอร์/เลขบัตรประชาชน/e-wallet พร้อมเพย์'
    }
  }

  return null
}

const buildCreatePayload = (): PaymentChannelCreate => {
  const base = {
    label: form.label.trim(),
    wallet_account_id: form.wallet_account_id,
    is_primary: form.is_primary,
    is_active: form.is_active,
  }

  if (form.channel_type === 'bank_transfer') {
    return {
      ...base,
      channel_type: 'bank_transfer',
      bank_name: form.bank_name.trim(),
      account_name: form.account_name.trim(),
      account_number: form.account_number.trim(),
      promptpay_id: null,
      qr_mode: null,
    }
  }

  if (form.channel_type === 'promptpay') {
    return {
      ...base,
      channel_type: 'promptpay',
      bank_name: null,
      account_name: form.account_name.trim(),
      account_number: null,
      promptpay_id: form.promptpay_id.trim(),
      qr_mode: form.qr_mode,
    }
  }

  return {
    ...base,
    channel_type: 'cash',
    bank_name: null,
    account_name: null,
    account_number: null,
    promptpay_id: null,
    qr_mode: null,
  }
}

/**
 * PATCH เฉพาะคีย์ที่ควรส่ง
 *
 * ⚠️ ช่องความลับว่าง ⇒ **ไม่ใส่คีย์นั้นเลย** (ไม่ใช่ `null`) ไม่งั้น backend จะล้างค่า
 */
const buildUpdatePayload = (): PaymentChannelUpdate => {
  const payload: PaymentChannelUpdate = {
    label: form.label.trim(),
    wallet_account_id: form.wallet_account_id,
    is_primary: form.is_primary,
    is_active: form.is_active,
  }

  if (form.channel_type === 'bank_transfer') {
    payload.bank_name = form.bank_name.trim()
    payload.account_name = form.account_name.trim()
    if (form.account_number.trim()) payload.account_number = form.account_number.trim()
  } else if (form.channel_type === 'promptpay') {
    payload.account_name = form.account_name.trim()
    payload.qr_mode = form.qr_mode
    if (form.promptpay_id.trim()) payload.promptpay_id = form.promptpay_id.trim()
  }

  return payload
}

const saveChannel = async () => {
  if (!canWrite.value) return
  const problem = validateForm()
  if (problem) {
    void dialog.alert('กรอกข้อมูลไม่ครบ', problem, 'warning')
    return
  }

  isSaving.value = true
  try {
    if (editing.value) {
      await FinanceService.updatePaymentChannel(
        roomId,
        editing.value.id,
        buildUpdatePayload(),
      )
      dialog.notify('บันทึกช่องทางชำระเงินแล้ว')
    } else {
      await FinanceService.createPaymentChannel(roomId, buildCreatePayload())
      dialog.notify('เพิ่มช่องทางชำระเงินแล้ว')
    }
    sheetOpen.value = false
    await load()
  } catch (error: unknown) {
    void dialog.alert(
      'บันทึกไม่สำเร็จ',
      describeError(error, 'บันทึกช่องทางชำระเงินไม่สำเร็จ'),
      'error',
    )
    // state จริงอาจเปลี่ยน (มีคนอื่นแก้พร้อมกัน) ⇒ โหลดใหม่ให้ตรงกับ DB
    await load()
  } finally {
    isSaving.value = false
  }
}

// ──────────────────────────────── เปิด/ปิด · หลัก · ลบ ────────────────────────────────
const toggleActive = async (channel: PaymentChannel) => {
  if (!canWrite.value) return
  const next = !channel.is_active
  if (next && activeCount.value >= MAX_ACTIVE_CHANNELS) {
    void dialog.alert(
      'ครบ 3 ช่องทางแล้ว',
      'ห้องนี้เปิดใช้งานช่องทางครบ 3 ช่องทางแล้ว — ปิดช่องทางอื่นก่อน',
      'warning',
    )
    return
  }

  try {
    await FinanceService.updatePaymentChannel(roomId, channel.id, { is_active: next })
    dialog.notify(next ? 'เปิดใช้งานช่องทางแล้ว' : 'ปิดใช้งานช่องทางแล้ว')
    await load()
  } catch (error: unknown) {
    void dialog.alert(
      'บันทึกไม่สำเร็จ',
      describeError(error, 'เปลี่ยนสถานะช่องทางไม่สำเร็จ'),
      'error',
    )
    await load()
  }
}

const setPrimary = async (channel: PaymentChannel) => {
  if (!canWrite.value || !channel.is_active || channel.is_primary) return
  try {
    await FinanceService.updatePaymentChannel(roomId, channel.id, { is_primary: true })
    dialog.notify('ตั้งเป็นช่องทางหลักแล้ว')
    await load()
  } catch (error: unknown) {
    const conflict = apiStatus(error) === 409
    void dialog.alert(
      'ตั้งเป็นช่องทางหลักไม่สำเร็จ',
      conflict
        ? 'มีช่องทางหลักพร้อมกันจากอีกเครื่อง — กำลังโหลดข้อมูลใหม่'
        : describeError(error, 'เปลี่ยนช่องทางหลักไม่สำเร็จ'),
      'error',
    )
    await load()
  }
}

const confirmDelete = async (channel: PaymentChannel) => {
  if (!canWrite.value) return
  const result = await dialog.confirm(
    'ลบช่องทางนี้?',
    `“${channel.label}” จะหายจากรายการ — ใบเก่าที่ออกไปแล้วยังพิมพ์จาก snapshot เดิมได้`,
    { icon: 'warning', danger: true, confirmButtonText: 'ลบทันที' },
  )
  if (!result.isConfirmed) return

  isDeletingId.value = channel.id
  try {
    await FinanceService.deletePaymentChannel(roomId, channel.id)
    dialog.notify('ลบช่องทางชำระเงินแล้ว')
    // backend promote ตัวถัดไปเป็นหลักให้เอง — reload เพื่อเห็นผลจริง
    await load()
  } catch (error: unknown) {
    void dialog.alert(
      'ลบไม่สำเร็จ',
      describeError(error, 'ลบช่องทางชำระเงินไม่สำเร็จ'),
      'error',
    )
  } finally {
    isDeletingId.value = null
  }
}

const channelMenuItems: RowActionItem[] = [
  { key: 'delete', label: 'ลบช่องทาง', icon: 'bi-trash3-fill', tone: 'danger' },
]
const handleChannelAction = (channel: PaymentChannel, key: string) => {
  if (key === 'delete') void confirmDelete(channel)
}

// ──────────────────────────────── PromptPay QR ────────────────────────────────
const qrSheetOpen = ref(false)
const qrChannel = ref<PaymentChannel | null>(null)
const qrAmount = ref('')
const qrUrl = ref<string | null>(null)
const qrBlob = ref<Blob | null>(null)
const isLoadingQr = ref(false)
const qrError = ref('')

const releaseQrUrl = () => {
  if (qrUrl.value) {
    URL.revokeObjectURL(qrUrl.value)
    qrUrl.value = null
  }
}

const closeQr = () => {
  releaseQrUrl()
  qrBlob.value = null
  qrChannel.value = null
  qrAmount.value = ''
  qrError.value = ''
  qrSheetOpen.value = false
}

/** ยอดทดสอบของ QR fixed — ตัวอักษรเท่านั้น (ห้าม `type=number` เพราะล้อเมาส์เปลี่ยนยอด) */
const parseQrAmount = (): number | null => {
  const raw = qrAmount.value.trim()
  if (!raw) return null
  const value = Number(raw)
  if (!Number.isFinite(value) || value <= 0) return null
  // ทศนิยมเกิน 2 ตำแหน่ง → ปัดแล้วไม่เท่าเดิม
  if (Math.abs(value * 100 - Math.round(value * 100)) > 1e-9) return null
  return roundMoney(value)
}

const loadQr = async () => {
  const channel = qrChannel.value
  if (!channel) return

  let amount: number | undefined
  if (channel.qr_mode === 'fixed') {
    const parsed = parseQrAmount()
    if (parsed === null) {
      void dialog.alert(
        'ยอดไม่ถูกต้อง',
        'กรอกยอดที่มากกว่า 0 และมีทศนิยมไม่เกิน 2 ตำแหน่ง',
        'warning',
      )
      return
    }
    amount = parsed
  }

  isLoadingQr.value = true
  qrError.value = ''
  try {
    const blob = await FinanceService.getPaymentChannelQr(roomId, channel.id, amount)
    qrBlob.value = blob
    releaseQrUrl()
    qrUrl.value = URL.createObjectURL(blob)
  } catch (error: unknown) {
    qrError.value = describeError(error, 'สร้าง QR ไม่สำเร็จ')
    void dialog.alert('สร้าง QR ไม่สำเร็จ', qrError.value, 'error')
  } finally {
    isLoadingQr.value = false
  }
}

const openQr = (channel: PaymentChannel) => {
  if (!channel.has_qr) return
  closeQr()
  qrChannel.value = channel
  qrSheetOpen.value = true
  // QR open ไม่มียอด → สร้างได้ทันที; fixed ต้องรอผู้ใช้กรอกยอดทดสอบก่อน
  if (channel.qr_mode !== 'fixed') void loadQr()
}

const downloadQr = () => {
  if (!qrBlob.value || !qrChannel.value) return
  downloadBlob(qrBlob.value, `promptpay-${qrChannel.value.id}.svg`)
}

onMounted(load)
onBeforeUnmount(closeQr)
</script>

<template>
  <div class="space-y-4">
    <!-- ═══════════════════════════════════════════════════════════════
         💳 รายการช่องทางชำระเงิน -->
    <div class="page-card overflow-hidden">
      <div
        class="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-canvas px-4 py-3 sm:px-5"
      >
        <div class="min-w-0">
          <h2 class="section-title flex flex-wrap items-center gap-2">
            <i class="bi bi-credit-card-2-front text-brand-700" aria-hidden="true"></i>
            <span class="truncate">ช่องทางชำระเงิน</span>
            <span class="chip bg-surface text-ink-2">
              <span class="num">{{ activeCount }}/{{ MAX_ACTIVE_CHANNELS }}</span>
              เปิดใช้งาน
            </span>
          </h2>
          <p class="mt-0.5 text-sm text-ink-3">
            ช่องทางที่ผู้ปกครองใช้จ่ายเงิน — ใช้แสดงในใบแจ้งหนี้และหน้าจอรับเงิน
          </p>
        </div>
        <button
          v-if="canWrite"
          type="button"
          class="btn-primary shrink-0"
          :disabled="activeCount >= MAX_ACTIVE_CHANNELS"
          @click="handleAdd"
        >
          <i class="bi bi-plus-lg" aria-hidden="true"></i>
          เพิ่มช่องทาง
        </button>
      </div>

      <div class="p-4 sm:p-5">
        <SkeletonRows v-if="isLoading" :rows="3" height="h-20" />

        <StateBlock
          v-else-if="hasError"
          variant="error"
          :hint="errorMessage"
          @retry="load"
        />

        <StateBlock
          v-else-if="channels.length === 0"
          variant="empty"
          icon="bi-credit-card-2-front"
          title="ยังไม่มีช่องทางชำระเงิน"
          hint="เพิ่มเงินสดหรือบัญชีธนาคารของห้อง เพื่อบอกผู้ปกครองว่าจะจ่ายเงินได้อย่างไร"
        >
          <button v-if="canWrite" type="button" class="btn-primary" @click="handleAdd">
            <i class="bi bi-plus-lg" aria-hidden="true"></i>
            เพิ่มช่องทางแรก
          </button>
        </StateBlock>

        <div v-else class="space-y-2.5">
          <div
            v-for="channel in channels"
            :key="channel.id"
            class="group flex flex-wrap items-start justify-between gap-3 rounded-control border border-line p-3 transition-colors hover:border-ink-3/30"
          >
            <div class="min-w-0 flex-1">
              <p class="flex flex-wrap items-center gap-2">
                <span class="truncate font-bold text-ink-1">{{ channel.label }}</span>
                <span class="chip bg-canvas text-ink-2">
                  {{ CHANNEL_TYPE_LABELS[channel.channel_type] }}
                </span>
                <span v-if="channel.is_primary" class="chip bg-brand-tint text-brand">
                  <i class="bi bi-star-fill" aria-hidden="true"></i>
                  หลัก
                </span>
                <span v-if="!channel.is_active" class="chip bg-canvas text-ink-3">
                  ปิดใช้งาน
                </span>
              </p>

              <p
                v-if="channel.channel_type === 'bank_transfer'"
                class="mt-1 flex flex-wrap items-center gap-x-2 text-sm text-ink-3"
              >
                <span v-if="channel.bank_name">{{ channel.bank_name }}</span>
                <span v-if="channel.account_number_masked" class="num">
                  {{ channel.account_number_masked }}
                </span>
                <span v-if="channel.account_name">· {{ channel.account_name }}</span>
              </p>

              <p
                v-else-if="channel.channel_type === 'promptpay'"
                class="mt-1 flex flex-wrap items-center gap-x-2 text-sm text-ink-3"
              >
                <span v-if="channel.account_name">{{ channel.account_name }}</span>
                <span v-if="channel.promptpay_id_masked" class="num">
                  {{ channel.promptpay_id_masked }}
                </span>
                <span v-if="channel.qr_mode" class="chip bg-canvas text-ink-2">
                  QR {{ qrModeLabel(channel) }}
                </span>
              </p>

              <p v-if="channel.wallet_account_name" class="mt-1 text-xs text-ink-3">
                เข้ากระเป๋า: {{ channel.wallet_account_name }}
              </p>
            </div>

            <div class="flex shrink-0 items-center gap-1">
              <!-- 🔓 ดู QR ได้ทุกสมาชิกห้อง (backend `require_member`) — เฉพาะช่องทางที่มี QR -->
              <button
                v-if="channel.has_qr"
                type="button"
                class="flex h-11 w-11 items-center justify-center rounded-control text-ink-3 transition-colors hover:bg-canvas hover:text-brand-700"
                title="ดู QR"
                :aria-label="`ดู QR ของ ${channel.label}`"
                @click="openQr(channel)"
              >
                <i class="bi bi-qr-code" aria-hidden="true"></i>
              </button>

              <template v-if="canWrite">
                <button
                  type="button"
                  class="flex h-11 w-11 items-center justify-center rounded-control transition-colors hover:bg-canvas"
                  :class="
                    channel.is_primary
                      ? 'text-brand-700'
                      : 'text-ink-3 hover:text-brand-700 disabled:cursor-not-allowed disabled:opacity-40'
                  "
                  title="ตั้งเป็นช่องทางหลัก"
                  :aria-label="`ตั้ง ${channel.label} เป็นช่องทางหลัก`"
                  :disabled="!channel.is_active || channel.is_primary"
                  @click="setPrimary(channel)"
                >
                  <i
                    :class="channel.is_primary ? 'bi bi-star-fill' : 'bi bi-star'"
                    aria-hidden="true"
                  ></i>
                </button>

                <button
                  type="button"
                  class="flex h-11 w-11 items-center justify-center rounded-control text-ink-3 transition-colors hover:bg-canvas hover:text-brand-700"
                  :title="channel.is_active ? 'ปิดใช้งาน' : 'เปิดใช้งาน'"
                  :aria-label="`${channel.is_active ? 'ปิด' : 'เปิด'}ใช้งาน ${channel.label}`"
                  @click="toggleActive(channel)"
                >
                  <i
                    :class="channel.is_active ? 'bi bi-toggle-on' : 'bi bi-toggle-off'"
                    aria-hidden="true"
                  ></i>
                </button>

                <button
                  type="button"
                  class="flex h-11 w-11 items-center justify-center rounded-control text-ink-3 transition-colors hover:bg-canvas hover:text-brand-700"
                  title="แก้ไข"
                  :aria-label="`แก้ไข ${channel.label}`"
                  @click="handleEdit(channel)"
                >
                  <i class="bi bi-pencil-square" aria-hidden="true"></i>
                </button>

                <RowActionMenu
                  :label="`ตัวเลือกของ ${channel.label}`"
                  :items="channelMenuItems"
                  @select="handleChannelAction(channel, $event)"
                />
              </template>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════════════════════════════════════════
         📝 ฟอร์มเพิ่ม/แก้ช่องทาง -->
    <AppSheet
      :open="sheetOpen"
      :label="editing ? 'แก้ไขช่องทางชำระเงิน' : 'เพิ่มช่องทางชำระเงิน'"
      :title="editing ? 'แก้ไขช่องทางชำระเงิน' : 'เพิ่มช่องทางชำระเงิน'"
      size="form"
      :dismissible="!isSaving"
      @close="sheetOpen = false"
    >
      <div class="space-y-4">
        <div>
          <label class="field-label" for="channelType">ชนิดช่องทาง</label>
          <select
            id="channelType"
            v-model="form.channel_type"
            class="field"
            :disabled="editing !== null"
          >
            <option value="cash">เงินสด</option>
            <option value="bank_transfer">โอนเข้าบัญชี</option>
            <option value="promptpay">พร้อมเพย์</option>
            <option value="custom_qr" disabled>QR กำหนดเอง (ยังไม่รองรับ)</option>
          </select>
          <p v-if="editing" class="mt-1 text-xs text-ink-3">
            แก้ไขอยู่ — เปลี่ยนชนิดไม่ได้ (ข้อมูลของชนิดเดิมจะค้าง)
          </p>
        </div>

        <div>
          <label class="field-label" for="channelLabel">
            ชื่อช่องทาง <span class="text-danger-600">*</span>
          </label>
          <input
            id="channelLabel"
            v-model="form.label"
            type="text"
            class="field"
            maxlength="100"
            placeholder="เช่น เงินสดครูเอ, บัญชีห้อง ม.2/1"
          />
        </div>

        <div>
          <label class="field-label" for="channelWallet">กระเป๋าปลายทาง</label>
          <select id="channelWallet" v-model="form.wallet_account_id" class="field">
            <option :value="null">— ให้ผู้รับเลือกตอนรับเงิน —</option>
            <option v-for="acc in accounts" :key="acc.id" :value="acc.id">
              {{ acc.account_name }}
            </option>
          </select>
        </div>

        <!-- 🏦 โอนเข้าบัญชี -->
        <template v-if="form.channel_type === 'bank_transfer'">
          <div>
            <label class="field-label" for="channelBank">
              ธนาคาร <span class="text-danger-600">*</span>
            </label>
            <input
              id="channelBank"
              v-model="form.bank_name"
              type="text"
              class="field"
              maxlength="200"
              placeholder="เช่น ธ.กรุงไทย"
            />
          </div>
          <div>
            <label class="field-label" for="channelAccountName">
              ชื่อเจ้าของบัญชี <span class="text-danger-600">*</span>
            </label>
            <input
              id="channelAccountName"
              v-model="form.account_name"
              type="text"
              class="field"
              maxlength="200"
              placeholder="ชื่อ-นามสกุลเจ้าของบัญชี"
            />
          </div>
          <div>
            <label class="field-label" for="channelAccountNo">
              เลขที่บัญชี
              <span v-if="!editing" class="text-danger-600">*</span>
            </label>
            <input
              id="channelAccountNo"
              v-model="form.account_number"
              type="text"
              inputmode="numeric"
              class="field num"
              maxlength="50"
              :placeholder="editing?.account_number_masked ?? 'เช่น 123-4-56789-0'"
            />
            <p v-if="editing" class="mt-1 text-xs text-ink-3">
              เว้นว่าง = คงเลขเดิม (ระบบไม่คืนเลขเต็มมาให้แก้)
            </p>
          </div>
        </template>

        <!-- 📱 พร้อมเพย์ -->
        <template v-if="form.channel_type === 'promptpay'">
          <div>
            <label class="field-label" for="channelPromptpayName">
              ชื่อเจ้าของพร้อมเพย์ <span class="text-danger-600">*</span>
            </label>
            <input
              id="channelPromptpayName"
              v-model="form.account_name"
              type="text"
              class="field"
              maxlength="200"
              placeholder="ชื่อ-นามสกุลหรือชื่อที่ลงทะเบียนพร้อมเพย์"
            />
          </div>
          <div>
            <label class="field-label" for="channelPromptpayId">
              เบอร์ / เลขบัตรประชาชน / e-wallet
              <span v-if="!editing" class="text-danger-600">*</span>
            </label>
            <input
              id="channelPromptpayId"
              v-model="form.promptpay_id"
              type="tel"
              inputmode="numeric"
              class="field num"
              maxlength="30"
              :placeholder="editing?.promptpay_id_masked ?? 'เช่น 081-234-5678'"
            />
            <p v-if="editing" class="mt-1 text-xs text-ink-3">
              เว้นว่าง = คงเลขเดิม (ระบบไม่คืนเลขเต็มมาให้แก้)
            </p>
          </div>
          <div>
            <label class="field-label" for="channelQrMode">รูปแบบ QR</label>
            <select id="channelQrMode" v-model="form.qr_mode" class="field">
              <option value="open">ไม่ฝังยอด (ผู้จ่ายพิมพ์ยอดเอง)</option>
              <option value="fixed">ฝังยอด (ระบุจำนวนเงินตอนสร้าง QR)</option>
            </select>
          </div>
        </template>

        <div class="space-y-2 rounded-control border border-line bg-canvas p-3">
          <label class="flex cursor-pointer items-center gap-2 text-sm font-bold text-ink-1">
            <input
              v-model="form.is_active"
              type="checkbox"
              class="h-4 w-4 rounded border-line text-brand-700"
              @change="onActiveToggle"
            />
            เปิดใช้งาน (นับรวมไม่เกิน {{ MAX_ACTIVE_CHANNELS }} ช่องทาง)
          </label>
          <label
            class="flex items-center gap-2 text-sm font-bold"
            :class="form.is_active ? 'cursor-pointer text-ink-1' : 'cursor-not-allowed text-ink-3'"
          >
            <input
              v-model="form.is_primary"
              type="checkbox"
              class="h-4 w-4 rounded border-line text-brand-700"
              :disabled="!form.is_active"
            />
            ตั้งเป็นช่องทางหลัก (ใช้แสดงคู่กับใบแจ้งหนี้)
          </label>
        </div>
      </div>

      <template #footer>
        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            type="button"
            class="btn-ghost-ui"
            :disabled="isSaving"
            @click="sheetOpen = false"
          >
            ยกเลิก
          </button>
          <button type="button" class="btn-primary" :disabled="isSaving" @click="saveChannel">
            <span
              v-if="isSaving"
              class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
              aria-hidden="true"
            ></span>
            <template v-else><i class="bi bi-check-lg" aria-hidden="true"></i> บันทึก</template>
          </button>
        </div>
      </template>
    </AppSheet>

    <!-- ═══════════════════════════════════════════════════════════════
         📱 PromptPay QR (server สร้าง — payload ไม่เคยออกจาก backend) -->
    <AppSheet
      :open="qrSheetOpen"
      :label="`QR ของ ${qrChannel?.label ?? 'ช่องทาง'}`"
      :title="qrChannel ? `PromptPay QR — ${qrChannel.label}` : 'PromptPay QR'"
      description="สแกนด้วยแอปธนาคารเพื่อโอนเข้าบัญชีพร้อมเพย์ของห้อง"
      size="dialog"
      @close="closeQr"
    >
      <div class="space-y-4">
        <div v-if="qrChannel?.qr_mode === 'fixed'">
          <label class="field-label" for="qrAmount">
            ยอดทดสอบ (฿) <span class="text-danger-600">*</span>
          </label>
          <div class="flex gap-2">
            <input
              id="qrAmount"
              v-model="qrAmount"
              type="text"
              inputmode="decimal"
              class="field num"
              placeholder="เช่น 250.00"
              @keydown.enter.prevent="loadQr"
            />
            <button
              type="button"
              class="btn-ghost-ui shrink-0"
              :disabled="isLoadingQr"
              @click="loadQr"
            >
              สร้าง QR
            </button>
          </div>
          <p class="mt-1 text-xs text-ink-3">
            ช่องทางนี้เป็น QR ฝังยอด — ต้องระบุยอดก่อนสร้าง (PDF ใบแจ้งหนี้จะฝังยอดบิลเอง)
          </p>
        </div>

        <div class="flex min-h-[240px] items-center justify-center">
          <p v-if="isLoadingQr" class="text-sm text-ink-3">กำลังสร้าง QR…</p>
          <StateBlock
            v-else-if="qrError"
            variant="error"
            :hint="qrError"
            @retry="loadQr"
          />
          <div v-else-if="qrUrl" class="flex flex-col items-center gap-2">
            <img
              :src="qrUrl"
              :alt="qrChannel ? `PromptPay QR ของ ${qrChannel.label}` : 'PromptPay QR'"
              width="240"
              height="240"
              class="rounded-control border border-line bg-white p-2"
            />
            <p v-if="qrChannel?.qr_mode === 'fixed' && qrAmount" class="num text-sm text-ink-2">
              ฿{{ formatAmount(Number(qrAmount)) }}
            </p>
          </div>
          <p v-else class="text-center text-sm text-ink-3">
            กรอกยอดทดสอบแล้วกด “สร้าง QR”
          </p>
        </div>
      </div>

      <template #footer>
        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button type="button" class="btn-ghost-ui" @click="closeQr">ปิด</button>
          <button
            v-if="qrBlob"
            type="button"
            class="btn-primary"
            @click="downloadQr"
          >
            <i class="bi bi-download" aria-hidden="true"></i>
            ดาวน์โหลด SVG
          </button>
        </div>
      </template>
    </AppSheet>
  </div>
</template>
