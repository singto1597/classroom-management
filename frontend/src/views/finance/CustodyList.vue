<script setup lang="ts">
/**
 * 👜 เงินสดรอส่งมอบ — ยอดที่ผู้ถือเงินรับไปแล้วยังไม่นำส่ง (FIN-V2 / P3.2)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * 🎯 หลักคิด
 * ═══════════════════════════════════════════════════════════════════════════
 * กระเป๋า custody เป็น **กระเป๋าปกติ** ของห้อง (P3.1) ⇒ ยอดบนหน้านี้คือ
 * `finance_accounts.balance` จริง ไม่ใช่ตัวเลขประมาณการ ⇒ หลัง mutation ทุกครั้ง
 * เรียก `getCustody` ใหม่ทั้งชุด (**ห้ามบวก/ลบยอดเองฝั่งจอ**)
 *
 * 🔓 อ่าน: สมาชิกทุกคน (`require_member`) · 🔒 เขียน: `MANAGE_FINANCE`
 *    ⇒ ซ่อนปุ่มเขียนด้วย `canManageFinance` และยังรับ 403 จาก backend ได้
 *
 * 🧩 หน้าเดียว + แผ่นสองโหมด (ส่งมอบ / เคลื่อนไหว) — ไม่มีหน้า detail แยก
 *    (brief P3.2 บันทึกการตัดสินใจข้อ 1)
 */
import { computed, onMounted, reactive, ref } from 'vue'

import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import type {
  Account,
  CustodyAccountKind,
  CustodyItem,
  CustodyListResponse,
  FinancePerson,
} from '@/types/finance'

import PageIntro from '@/components/ui/PageIntro.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppSheet from '@/components/ui/AppSheet.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import CustodyCard from '@/components/finance/CustodyCard.vue'
import HandoverModal from '@/components/finance/HandoverModal.vue'
import { useDialog } from '@/composables/useDialog'
import { createLatestGuard } from '@/utils/latest'
import { formatMoney } from '@/utils/money'

const authStore = useAuthStore()
const dialog = useDialog()
const roomId = authStore.currentRoomId!
const canManageFinance = computed(() => authStore.canManageFinance)

const custody = ref<CustodyListResponse | null>(null)
const accounts = ref<Account[]>([])
const people = ref<FinancePerson[]>([])
const isLoading = ref(true)
const hasError = ref(false)

const guard = createLatestGuard()

const describeError = (error: unknown, fallback: string): string =>
  error instanceof Error && error.message ? error.message : fallback

const fetchCustody = async () => {
  const token = guard.begin()
  isLoading.value = true
  hasError.value = false
  try {
    const [custodyRes, accountRes, peopleRes] = await Promise.all([
      FinanceService.getCustody(roomId),
      FinanceService.getAccounts(roomId),
      FinanceService.getPeople(roomId, { active: true }),
    ])
    if (!guard.isCurrent(token)) return
    custody.value = custodyRes
    accounts.value = accountRes
    people.value = peopleRes
  } catch {
    if (!guard.isCurrent(token)) return
    hasError.value = true
  } finally {
    if (guard.isCurrent(token)) isLoading.value = false
  }
}

onMounted(fetchCustody)

const items = computed<CustodyItem[]>(() => custody.value?.items ?? [])
const totalHeld = computed(() => custody.value?.total_held ?? 0)

/** 🔒 กระเป๋าที่ใช้ใน select ของแผ่นส่งมอบ — ต้องไม่ใช่กระเป๋า custody ใด ๆ */
const custodyAccountIds = computed(() => new Set(items.value.map((i) => i.account_id)))
const mainAccounts = computed(() =>
  accounts.value.filter((a) => !custodyAccountIds.value.has(a.id)),
)

/** ผู้มีสิทธิ์ถือเงิน — ตามบทบาท `receive` ในทะเบียนผู้เกี่ยวข้อง */
const receivePeople = computed(() =>
  people.value.filter((p) => p.roles.includes('receive')),
)

// ─────────────────────────── แผ่นส่งมอบ / เคลื่อนไหว ───────────────────────────
const sheetOpen = ref(false)
const sheetMode = ref<'handover' | 'movements'>('handover')
const activeItem = ref<CustodyItem | null>(null)

const openSheet = (item: CustodyItem, mode: 'handover' | 'movements') => {
  activeItem.value = item
  sheetMode.value = mode
  sheetOpen.value = true
}

const closeSheet = () => {
  sheetOpen.value = false
}

// ─────────────────────────────── ตั้งกระเป๋าให้ผู้ถือ ───────────────────────────────
const accountSheetOpen = ref(false)
const isSavingAccount = ref(false)
const accountForm = reactive<{ owner_person_id: number | null; account_kind: CustodyAccountKind }>(
  { owner_person_id: null, account_kind: 'cash' },
)

const custodyPersonIds = computed(() => new Set(items.value.map((i) => i.person_id)))
const eligiblePeople = computed(() =>
  receivePeople.value.filter((p) => !custodyPersonIds.value.has(p.person_id)),
)

const openAccountSheet = () => {
  accountForm.owner_person_id = eligiblePeople.value[0]?.person_id ?? null
  accountForm.account_kind = 'cash'
  accountSheetOpen.value = true
}

const saveAccount = async () => {
  if (isSavingAccount.value || !accountForm.owner_person_id) return
  isSavingAccount.value = true
  try {
    await FinanceService.createCustodyAccount(roomId, {
      owner_person_id: accountForm.owner_person_id,
      account_kind: accountForm.account_kind,
    })
    dialog.notify('ตั้งกระเป๋าเงินสดรอส่งมอบแล้ว')
    accountSheetOpen.value = false
    await fetchCustody()
  } catch (error: unknown) {
    void dialog.alert(
      'ตั้งกระเป๋าไม่สำเร็จ',
      describeError(error, 'สร้างกระเป๋าเงินสดรอส่งมอบไม่สำเร็จ'),
      'error',
    )
  } finally {
    isSavingAccount.value = false
  }
}
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro
      description="ยอดเงินที่ผู้ถือเงินรับไปและยังไม่ได้นำส่ง / ใช้จ่าย — โอนเข้า-ออกได้โดยไม่นับเป็นรายรับหรือรายจ่าย"
    >
      <template #actions>
        <AppButton variant="quiet" :loading="isLoading" @click="fetchCustody">
          <i class="bi bi-arrow-clockwise" aria-hidden="true"></i>
          รีเฟรช
        </AppButton>
        <AppButton v-if="canManageFinance" variant="primary" @click="openAccountSheet">
          <i class="bi bi-wallet2" aria-hidden="true"></i>
          ตั้งกระเป๋าให้ผู้ถือเงิน
        </AppButton>
      </template>
    </PageIntro>

    <!-- สรุปยอดถือรวม -->
    <AppCard padding="md" class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <p class="text-xs font-bold text-ink-3">เงินสดรอส่งมอบทั้งห้อง</p>
        <p class="text-2xl font-bold tabular-nums text-ink-1">{{ formatMoney(totalHeld) }}</p>
      </div>
      <p class="text-sm text-ink-2">
        ผู้ถือเงิน {{ items.length }} คน
      </p>
    </AppCard>

    <SkeletonRows v-if="isLoading" :rows="4" height="h-32" />
    <StateBlock
      v-else-if="hasError"
      variant="error"
      title="โหลดเงินสดรอส่งมอบไม่สำเร็จ"
      @retry="fetchCustody"
    />
    <StateBlock
      v-else-if="!items.length"
      variant="empty"
      icon="bi-wallet2"
      title="ยังไม่มีผู้ถือเงิน"
      hint="ตั้งกระเป๋าให้ผู้ที่มีบทบาทรับเงิน เพื่อเริ่มติดตามเงินสดที่ยังไม่นำส่ง"
    >
      <AppButton v-if="canManageFinance" variant="primary" @click="openAccountSheet">
        ตั้งกระเป๋าให้ผู้ถือเงิน
      </AppButton>
    </StateBlock>
    <div v-else class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <CustodyCard
        v-for="item in items"
        :key="item.account_id"
        :item="item"
        :can-manage="canManageFinance"
        @handover="openSheet($event, 'handover')"
        @movements="openSheet($event, 'movements')"
        @manage="openAccountSheet"
      />
    </div>

    <!-- แผ่นส่งมอบ / เคลื่อนไหว — ตัวเดียวสองโหมด -->
    <HandoverModal
      :open="sheetOpen"
      :mode="sheetMode"
      :item="activeItem"
      :accounts="mainAccounts"
      :people="receivePeople"
      :can-manage="canManageFinance"
      @close="closeSheet"
      @saved="fetchCustody"
    />

    <!-- ตั้งกระเป๋าให้ผู้ถือเงิน -->
    <AppSheet
      :open="accountSheetOpen"
      label="ตั้งกระเป๋าเงินสดรอส่งมอบ"
      title="ตั้งกระเป๋าให้ผู้ถือเงิน"
      description="หนึ่งคนมีได้กระเป๋าเดียว — ยอดเริ่มต้น ฿0.00 แล้วรับเงินเข้าจากช่องทางรับเงินหรือการส่งมอบ"
      size="form"
      :dismissible="!isSavingAccount"
      @close="accountSheetOpen = false"
    >
      <div v-if="!eligiblePeople.length" class="space-y-2">
        <StateBlock
          variant="empty"
          icon="bi-person-check"
          title="ไม่มีผู้ถือเงินที่รอตั้งกระเป๋า"
          hint="เพิ่มผู้เกี่ยวข้องที่มีบทบาท “ผู้รับเงิน” ในหน้าตั้งค่าระบบการเงินก่อน"
        />
      </div>
      <form v-else class="grid grid-cols-1 gap-4" @submit.prevent="saveAccount">
        <div>
          <label class="field-label" for="custodyOwner">ผู้ถือเงิน</label>
          <select
            id="custodyOwner"
            v-model="accountForm.owner_person_id"
            class="field"
            :disabled="isSavingAccount"
          >
            <option :value="null">— เลือกผู้ถือเงิน —</option>
            <option v-for="p in eligiblePeople" :key="p.person_id" :value="p.person_id">
              {{ p.display_name }}
            </option>
          </select>
        </div>
        <div>
          <label class="field-label" for="custodyKind">ชนิดกระเป๋า</label>
          <select
            id="custodyKind"
            v-model="accountForm.account_kind"
            class="field"
            :disabled="isSavingAccount"
          >
            <option value="cash">เงินสด</option>
            <option value="transfer">โอน</option>
          </select>
        </div>
      </form>

      <template #footer>
        <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <AppButton
            variant="secondary"
            block
            class="sm:w-auto"
            :disabled="isSavingAccount"
            @click="accountSheetOpen = false"
          >
            ยกเลิก
          </AppButton>
          <AppButton
            variant="primary"
            block
            class="sm:w-auto"
            :loading="isSavingAccount"
            :disabled="!accountForm.owner_person_id"
            @click="saveAccount"
          >
            บันทึก
          </AppButton>
        </div>
      </template>
    </AppSheet>
  </div>
</template>
