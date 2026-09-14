<script setup lang="ts">
/**
 * BudgetList — หน้า "งบประมาณ" (F2) ตั้งวงเงินต่อหมวด แล้วดูว่าใช้ไปเท่าไร
 *
 * 🔓 อ่านเปิดให้สมาชิกทุกคน (ตรงกับ `require_member` ฝั่ง backend)
 *    ✍️ เขียน (สร้าง/แก้/ลบ) ต้องมี `MANAGE_FINANCE` → `canManageFinance`
 *    gate ฝั่งหน้าจอเป็นแค่การซ่อนปุ่ม ตัวจริงคือ backend (ลืม gate = 403 ไม่ใช่ data leak)
 *
 * 📌 ที่หน้านี้ไม่ต้องมีตัวเลือกรายรับ/รายจ่าย: backend คืนงบทุกระเภทมาแล้ว
 *    และตัวเลข `used` ของแต่ละงบคิดจาก `category_type` ของหมวดนั้นเองอยู่แล้ว
 *    ⇒ การเพิ่มตัวกรองประเภทจะเป็นการกรอง "ที่ตา" ไม่ใช่ที่ยอด จึงไม่ทำ
 *
 * ⚠️ `used` ที่ได้จาก overview คือยอดของ **ช่วงของตัวงบเอง** (clamp ด้วย GREATEST/LEAST)
 *    ไม่ใช่ช่วงที่ผู้ใช้เลือกด้านบน — งบที่คาบเกี่ยวแค่บางส่วนจึงได้ยอดเฉพาะส่วนที่คาบเกี่ยว
 *    ⇒ `total_used` มาจาก backend เท่านั้น ห้ามบวก `used` ของทุกแถวเองแล้วเอาไปเทียบ
 *    (จะไม่เท่ากันเมื่อมีงบคาบเกี่ยวบางส่วน — และนั่นไม่ใช่บั๊ก)
 */
import { computed, onMounted, ref, watch } from 'vue';
import Swal from 'sweetalert2';

import PageHeader from '@/components/ui/PageHeader.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import PeriodPicker from '@/components/finance/PeriodPicker.vue';

import { FinanceService } from '@/services/finance';
import { useAuthStore } from '@/stores/auth';
import { createLatestGuard } from '@/utils/latest';
import {
  describePeriod,
  formatThaiDate,
  isRangeReversed,
  toRange,
  todayThaiYearMonth,
  type PeriodValue,
} from '@/utils/period';
import type {
  Budget,
  BudgetItem,
  BudgetOverview,
  BudgetUpdatePayload,
  Category,
} from '@/types/finance';

const authStore = useAuthStore();
const currentRoomId = authStore.currentRoomId!;
const currentUserName = authStore.currentUserName ?? '—';

// ✍️ สิทธิ์เขียน — ตรงกับ require_permission(..., "MANAGE_FINANCE") ฝั่ง backend
const canManageFinance = computed(() => authStore.canManageFinance);

// 🌏 ค่าเริ่มต้น = เดือนนี้ตามเวลาไทย (ดู utils/period.todayThaiYearMonth)
//    โหมด asof ไม่มีในหน้านี้ (โหมดของ PeriodPicker ถูกจำกัดไว้ที่ month/range แล้ว)
const initial = todayThaiYearMonth();
const period = ref<PeriodValue>({ mode: 'month', month: initial.month, year: initial.year });

const overview = ref<BudgetOverview | null>(null);
const allBudgets = ref<Budget[]>([]);
const categories = ref<Category[]>([]);

const isLoading = ref(true);
const hasError = ref(false);
// 🏁 กันคำตอบของคำขอเก่ามาทับคำตอบของคำขอใหม่ (ดู utils/latest.ts)
const guard = createLatestGuard();

const rangeOf = (p: PeriodValue): { startDate: string; endDate: string } | null =>
  p.mode === 'asof' ? null : toRange(p);

/**
 * เงินทุกตัวในหน้านี้ผ่านฟังก์ชันเดียว — เติม `฿` เสมอ และดึงเครื่องหมายลบออกมาข้างหน้า
 * (`−฿1,234.00`) ตามแบบเดียวกับ FinancialStatements.vue
 */
const formatMoney = (value: number): string =>
  `${value < 0 ? '−' : ''}฿${Math.abs(value).toLocaleString('th-TH', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const load = async () => {
  // ช่วงวันที่กลับด้าน — PeriodPicker แสดง error inline อยู่แล้ว ไม่ต้องยิง API (backend จะ 400)
  if (isRangeReversed(period.value)) return;

  const range = rangeOf(period.value);
  if (!range) return;

  // 🏁 ผู้ใช้กวาดเดือนไปเรื่อย ๆ ได้ ⇒ มีคำขอซ้อนกัน และคำตอบไม่ได้กลับตามลำดับที่ส่ง
  //    ทั้งสามคำขอเป็น `Promise.all` ชุดเดียวกัน จึงต้องทิ้ง **ทั้งชุด** ไม่ใช่ทีละตัว
  //    ไม่งั้น `overview` กับ `allBudgets` อาจมาจากเดือนคนละเดือน แล้วยอด "ใช้ไป"
  //    จะถูกตัดสินด้วยชุดหมวดของอีกช่วงหนึ่ง (แถม `is_over` ก็เพี้ยนตาม)
  const token = guard.begin();

  isLoading.value = true;
  hasError.value = false;
  try {
    const [overviewRes, budgetsRes, categoriesRes] = await Promise.all([
      FinanceService.getBudgetOverview(currentRoomId, range.startDate, range.endDate),
      FinanceService.getBudgets(currentRoomId),
      FinanceService.getCategories(currentRoomId),
    ]);
    if (!guard.isCurrent(token)) return;
    overview.value = overviewRes;
    allBudgets.value = budgetsRes;
    categories.value = categoriesRes;
  } catch (error) {
    // error ของคำขอเก่าไม่ควรขึ้นจอ ถ้าคำขอใหม่กว่าไปถึงแล้ว
    if (!guard.isCurrent(token)) return;
    console.error('Failed to load budgets:', error);
    hasError.value = true;
  } finally {
    if (guard.isCurrent(token)) isLoading.value = false;
  }
};

watch(period, () => {
  void load();
});

onMounted(() => {
  void load();
});

// ==========================================
// 📊 KPI
// ==========================================

const items = computed<BudgetItem[]>(() => overview.value?.items ?? []);

const isEmpty = computed(() => items.value.length === 0);

/** คงเหลือรวม = งบรวม − ใช้ไป (ติดลบได้เมื่อใช้เกินทั้งห้อง) */
const totalRemaining = computed(
  () => (overview.value?.total_budget ?? 0) - (overview.value?.total_used ?? 0),
);

/** ใช้ไปเกิน 100% ของ "งบรวมทั้งห้อง" — คนละเรื่องกับ over_count ที่นับรายงบ */
const isTotalOver = computed(() => totalRemaining.value < 0);

// ==========================================
// ✍️ ฟอร์มสร้าง/แก้ไข (modal เดียวใช้ทั้งสองโหมด)
// ==========================================

/** null = โหมดสร้างใหม่, มีค่า = โหมดแก้ไขงบนั้น */
const editingId = ref<number | null>(null);
const isModalOpen = ref(false);
const isSaving = ref(false);

// ช่อง input เป็น string ทั้งหมด (ค่าดิบจาก DOM) แล้วค่อยแปลงตอน submit
const formCategoryId = ref('');
const formAmount = ref('');
const formStart = ref('');
const formEnd = ref('');
const formNote = ref('');

const isEditing = computed(() => editingId.value !== null);

/** หมวดที่มีงบอยู่แล้วในช่วงที่เลือก — เตือนก่อนกด ไม่ใช่ให้ backend ตีกลับเป็น 400 */
const budgetedCategoryIds = computed(() => new Set(allBudgets.value.map((b) => b.category_id)));

const categoryOptions = computed(() =>
  categories.value.map((c) => ({
    id: c.id,
    label: `${c.category_name} (${c.category_type === 'income' ? 'รายรับ' : 'รายจ่าย'})`,
    // หมวดที่มีงบอยู่แล้วยังเลือกได้ (แก้ช่วงให้ไม่ทับก็ได้) แค่ติดป้ายบอกไว้
    alreadyBudgeted: budgetedCategoryIds.value.has(c.id),
  })),
);

/** ฟอร์มไม่ครบ/ผิดรูป — ปุ่มบันทึกถูกปิด ไม่ต้องรอ backend ตีกลับ */
const formError = computed<string | null>(() => {
  if (!formCategoryId.value) return 'กรุณาเลือกหมวดหมู่';
  const amount = Number(formAmount.value);
  if (!formAmount.value || Number.isNaN(amount) || amount <= 0) return 'วงเงินต้องมากกว่า 0';
  if (!formStart.value || !formEnd.value) return 'กรุณาระบุวันเริ่มต้นและวันสิ้นสุด';
  if (formEnd.value < formStart.value) return 'วันสิ้นสุดต้องไม่ก่อนวันเริ่มต้น';
  return null;
});

/**
 * เตือน (ไม่บล็อก) เมื่อกรอกซ้ำกับงบที่มีอยู่แล้ว **ตรงเป๊ะทั้งหมวดและช่วงวันที่**
 *
 * เตือนอย่างเดียวไม่บล็อก เพราะรายการนี้เป็น snapshot จากตอนโหลดหน้า — ถ้ามีคนสร้างงบไปแล้ว
 * จากแท็บอื่น ข้อมูลเราจะเก่า การบล็อกจะกลายเป็นดักผู้ใช้ผิด ๆ ⇒ ปล่อยให้ backend ตัดสิน
 * (unique index `(room_id, category_id, start_date, end_date)` จะตีกลับเป็น 400 อยู่ดี)
 *
 * ⚠️ เงื่อนไขต้องเป็น "ตรงเป๊ะ" ไม่ใช่ "คาบเกี่ยว" เพราะตัวกันซ้ำฝั่ง DB เป็น exact range
 *    งบสองใบที่คาบเกี่ยวกันบางส่วนถูกต้องตามสคีมา — เตือนว่า "ซ้ำ" ในเคสนั้นคือการโกหก
 */
const formWarning = computed<string | null>(() => {
  if (!formCategoryId.value || !formStart.value || !formEnd.value) return null;
  const duplicate = allBudgets.value.some(
    (b) =>
      b.category_id === Number(formCategoryId.value) &&
      b.start_date === formStart.value &&
      b.end_date === formEnd.value,
  );
  return duplicate
    ? 'มีงบของหมวดนี้ในช่วงวันที่เดียวกันอยู่แล้ว — บันทึกแล้วระบบจะแจ้งว่าซ้ำ'
    : null;
});

const canSubmit = computed(() => formError.value === null && !isSaving.value);

const resetForm = () => {
  const range = rangeOf(period.value);
  formCategoryId.value = '';
  formAmount.value = '';
  // ตั้งต้นที่ช่วงที่กำลังดูอยู่ — ผู้ใช้ตั้งงบของเดือนที่เห็นบนจอเป็นหลักอยู่แล้ว
  formStart.value = range?.startDate ?? '';
  formEnd.value = range?.endDate ?? '';
  formNote.value = '';
};

const openCreate = () => {
  editingId.value = null;
  resetForm();
  isModalOpen.value = true;
};

const openEdit = (item: BudgetItem) => {
  editingId.value = item.budget_id;
  formCategoryId.value = String(item.category_id);
  formAmount.value = String(item.amount);
  // ⚠️ ใช้ period_start/period_end (ช่วงจริงที่คิดยอด) ไม่ใช่ช่วงที่ผู้ใช้กรองอยู่
  formStart.value = item.period_start;
  formEnd.value = item.period_end;
  formNote.value = item.note ?? '';
  isModalOpen.value = true;
};

const closeModal = () => {
  isModalOpen.value = false;
  editingId.value = null;
};

const submit = async () => {
  if (!canSubmit.value) return;
  // จับโหมดไว้ก่อน — `closeModal()` เซ็ต editingId เป็น null ⇒ อ่าน isEditing หลังปิดจะได้ false เสมอ
  const editing = isEditing.value;
  isSaving.value = true;
  try {
    const note = formNote.value.trim();
    if (editingId.value === null) {
      await FinanceService.createBudget(currentRoomId, {
        category_id: Number(formCategoryId.value),
        amount: Number(formAmount.value),
        start_date: formStart.value,
        end_date: formEnd.value,
        ...(note ? { note } : {}),
        user_name: currentUserName,
      });
    } else {
      // ส่งเฉพาะฟิลด์ที่ผู้ใช้แก้ได้ — ไม่ส่ง category_id เพราะ backend ไม่รองรับให้ย้ายหมวด
      const payload: BudgetUpdatePayload = {
        amount: Number(formAmount.value),
        start_date: formStart.value,
        end_date: formEnd.value,
        note: note,
        user_name: currentUserName,
      };
      await FinanceService.updateBudget(currentRoomId, editingId.value, payload);
    }

    closeModal();
    Swal.fire({
      icon: 'success',
      title: editing ? 'อัปเดตงบแล้ว' : 'ตั้งงบแล้ว',
      timer: 1500,
      showConfirmButton: false,
    });
    await load();
  } catch (error: unknown) {
    Swal.fire(
      'บันทึกไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    );
  } finally {
    isSaving.value = false;
  }
};

const confirmDelete = async (item: BudgetItem) => {
  if (!canManageFinance.value) return;

  const result = await Swal.fire({
    icon: 'warning',
    title: 'ลบงบประมาณนี้?',
    html: `งบของ <b>${item.category_name}</b> ช่วง ${formatThaiDate(item.period_start)} – ${formatThaiDate(item.period_end)}<br><span class="text-sm">รายการจะหายจากหน้าจอ แต่ประวัติยังอยู่</span>`,
    showCancelButton: true,
    confirmButtonText: 'ลบงบ',
    cancelButtonText: 'ยกเลิก',
    confirmButtonColor: '#dc2626',
  });
  if (!result.isConfirmed) return;

  try {
    await FinanceService.deleteBudget(currentRoomId, item.budget_id, currentUserName);
    Swal.fire({ icon: 'success', title: 'ลบแล้ว', timer: 1200, showConfirmButton: false });
    await load();
  } catch (error: unknown) {
    Swal.fire(
      'ลบไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    );
  }
};

// ==========================================
// 🎨 หน้าตาของแถบความคืบหน้า
// ==========================================

/** แถบ progress ธรรมดา (div) — ไม่ใช้ไลบรารี chart และไม่ใช้ gradient */
const barClass = (item: BudgetItem): string => {
  if (item.is_over) return 'bg-red-500';
  if (item.is_near) return 'bg-amber-500';
  return 'bg-emerald-500';
};

const barWidth = (item: BudgetItem): string => {
  // กว้างสุด 100% เสมอ — เกินงบสื่อด้วยสี ไม่ใช่ด้วยความยาวที่ล้นออกนอกการ์ด
  const pct = Math.min(Math.max(item.usage_pct ?? 0, 0), 100);
  return `${pct}%`;
};

const pctLabel = (item: BudgetItem): string =>
  item.usage_pct === null
    ? '—'
    : `${item.usage_pct.toLocaleString('th-TH', { maximumFractionDigits: 1 })}%`;

// 🏷️ ป้ายสถานะ — เขียนเป็น Record เพื่อให้เพิ่มสถานะใหม่แล้ว type-check จับว่าลืมใส่
const STATUS_CHIP: Record<'over' | 'near' | 'ok', { label: string; cls: string; icon: string }> = {
  over: { label: 'เกินงบ', cls: 'bg-red-50 text-red-700', icon: 'bi-exclamation-octagon-fill' },
  near: {
    label: 'ใกล้เต็ม',
    cls: 'bg-amber-50 text-amber-700',
    icon: 'bi-exclamation-triangle-fill',
  },
  ok: { label: 'ปกติ', cls: 'bg-emerald-50 text-emerald-700', icon: 'bi-check-circle-fill' },
};

const statusOf = (item: BudgetItem) => (item.is_over ? 'over' : item.is_near ? 'near' : 'ok');
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader
      eyebrow="Budget Control"
      title="งบประมาณ"
      :description="`วงเงินและยอดใช้จริง — ${describePeriod(period)}`"
    >
      <template #actions>
        <button
          v-if="canManageFinance"
          type="button"
          class="btn-primary w-full sm:w-auto"
          @click="openCreate"
        >
          <i class="bi bi-plus-lg" aria-hidden="true"></i>
          ตั้งงบประมาณ
        </button>
        <RouterLink to="/finance" class="btn-ghost-ui" title="กลับหน้าภาพรวม">
          <i class="bi bi-arrow-left" aria-hidden="true"></i>
          กลับหน้าภาพรวม
        </RouterLink>
      </template>
    </PageHeader>

    <!-- ตัวเลือกช่วงเวลา — เต็มความกว้างในเนื้อหา ไม่ยัดใน header เพราะมี 2 ช่องวันที่ -->
    <div class="page-card p-3.5 sm:p-4">
      <PeriodPicker v-model="period" :modes="['month', 'range']" label="ช่วงที่ต้องการดูงบ" />
      <p class="mt-2 text-xs text-stone-400">
        แสดงเฉพาะงบที่คาบเกี่ยวกับช่วงนี้ — ยอด "ใช้ไป" ของแต่ละแถวคิดจากช่วงของงบนั้นเอง
      </p>
    </div>

    <SkeletonRows v-if="isLoading" :rows="4" height="h-24" />

    <StateBlock v-else-if="hasError" variant="error" @retry="load" />

    <StateBlock
      v-else-if="isEmpty"
      variant="empty"
      icon="bi-piggy-bank"
      title="ยังไม่มีงบประมาณในช่วงนี้"
      :hint="
        canManageFinance
          ? 'กดปุ่ม “ตั้งงบประมาณ” ด้านบนเพื่อกำหนดวงเงินของหมวดที่ต้องการคุม'
          : 'เมื่อเหรัญญิกตั้งงบของช่วงนี้แล้ว จะมาแสดงที่นี่'
      "
    />

    <template v-else>
      <!-- KPI: งบรวม / ใช้ไป / คงเหลือ / เกินงบ -->
      <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div class="page-card p-3.5 sm:p-5">
          <p class="text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400">งบรวม</p>
          <p
            class="font-display num mt-2 break-words text-2xl font-bold text-stone-900 sm:text-3xl"
          >
            {{ formatMoney(overview?.total_budget ?? 0) }}
          </p>
          <p class="mt-1 text-xs font-bold text-stone-400">{{ items.length }} รายการ</p>
        </div>

        <div class="page-card p-3.5 sm:p-5">
          <p class="text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400">ใช้ไป</p>
          <p
            class="font-display num mt-2 break-words text-2xl font-bold text-brand-700 sm:text-3xl"
          >
            {{ formatMoney(overview?.total_used ?? 0) }}
          </p>
          <p class="mt-1 text-xs font-bold text-stone-400">เฉพาะงบที่แสดงอยู่</p>
        </div>

        <div class="page-card p-3.5 sm:p-5">
          <p class="text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400">คงเหลือ</p>
          <p
            class="font-display num mt-2 break-words text-2xl font-bold sm:text-3xl"
            :class="isTotalOver ? 'text-red-600' : 'text-emerald-600'"
          >
            {{ formatMoney(totalRemaining) }}
          </p>
          <p class="mt-1 text-xs font-bold text-stone-400">
            {{ isTotalOver ? 'ใช้เกินงบรวมแล้ว' : 'งบรวม − ใช้ไป' }}
          </p>
        </div>

        <div
          class="page-card p-3.5 sm:p-5"
          :class="(overview?.over_count ?? 0) > 0 ? 'border-s-4 border-s-red-500' : ''"
        >
          <p class="text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400">เกินงบ</p>
          <p
            class="font-display num mt-2 text-2xl font-bold sm:text-3xl"
            :class="(overview?.over_count ?? 0) > 0 ? 'text-red-600' : 'text-stone-900'"
          >
            {{ overview?.over_count ?? 0 }}
            <span class="text-base font-bold text-stone-400">รายการ</span>
          </p>
          <p class="mt-1 text-xs font-bold text-stone-400">
            ใกล้เต็มอีก {{ overview?.warning_count ?? 0 }} รายการ
          </p>
        </div>
      </div>

      <!-- 📱 มือถือ: การ์ด -->
      <div class="space-y-2.5 lg:hidden">
        <div
          v-for="item in items"
          :key="item.budget_id"
          class="page-card p-4"
          :class="item.is_over ? 'border-s-4 border-s-red-500' : ''"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <h2 class="font-display min-w-0 truncate text-base font-bold text-stone-900">
                {{ item.category_name }}
              </h2>
              <p class="num mt-0.5 truncate text-[11px] font-bold text-stone-400">
                {{ formatThaiDate(item.period_start) }} – {{ formatThaiDate(item.period_end) }}
              </p>
            </div>
            <span class="chip shrink-0" :class="STATUS_CHIP[statusOf(item)].cls">
              <i class="bi" :class="STATUS_CHIP[statusOf(item)].icon" aria-hidden="true"></i>
              {{ STATUS_CHIP[statusOf(item)].label }}
            </span>
          </div>

          <div class="mt-3">
            <div class="flex items-baseline justify-between gap-2">
              <p class="font-display num text-lg font-bold text-stone-900">
                {{ formatMoney(item.used) }}
              </p>
              <p class="num shrink-0 text-xs font-bold text-stone-400">
                / {{ formatMoney(item.amount) }}
              </p>
            </div>
            <div class="mt-2 h-2 w-full overflow-hidden rounded-full bg-stone-100">
              <div
                class="h-full rounded-full transition-[width]"
                :class="barClass(item)"
                :style="{ width: barWidth(item) }"
              ></div>
            </div>
            <div class="mt-1.5 flex items-center justify-between gap-2">
              <span class="num text-[11px] font-bold text-stone-400">{{ pctLabel(item) }}</span>
              <span
                class="num text-[11px] font-bold"
                :class="item.remaining < 0 ? 'text-red-600' : 'text-stone-500'"
              >
                คงเหลือ {{ formatMoney(item.remaining) }}
              </span>
            </div>
          </div>

          <p
            v-if="item.note"
            class="mt-2.5 border-t border-stone-100 pt-2.5 text-xs text-stone-500"
          >
            {{ item.note }}
          </p>

          <div v-if="canManageFinance" class="mt-3 flex gap-2 border-t border-stone-100 pt-3">
            <button type="button" class="btn-ghost-ui min-w-0 flex-1" @click="openEdit(item)">
              <i class="bi bi-pencil" aria-hidden="true"></i>
              แก้ไข
            </button>
            <button
              type="button"
              class="btn-ghost-ui min-w-0 flex-1 text-red-600"
              @click="confirmDelete(item)"
            >
              <i class="bi bi-trash3" aria-hidden="true"></i>
              ลบ
            </button>
          </div>
        </div>
      </div>

      <!-- 🖥️ เดสก์ท็อป: ตาราง -->
      <div class="page-card hidden overflow-hidden lg:block">
        <div class="overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th>หมวดหมู่</th>
                <th>ช่วงที่คิดยอด</th>
                <th class="text-right">งบประมาณ (฿)</th>
                <th class="text-right">ใช้ไป (฿)</th>
                <th class="text-right">คงเหลือ (฿)</th>
                <th class="w-44">ความคืบหน้า</th>
                <th class="text-center">สถานะ</th>
                <th v-if="canManageFinance" class="text-right">จัดการ</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in items"
                :key="item.budget_id"
                :class="item.is_over ? 'border-s-4 border-s-red-500' : ''"
              >
                <td>
                  <p class="font-bold text-stone-900">{{ item.category_name }}</p>
                  <p v-if="item.note" class="mt-0.5 max-w-xs truncate text-xs text-stone-400">
                    {{ item.note }}
                  </p>
                </td>
                <td class="num whitespace-nowrap text-stone-500">
                  {{ formatThaiDate(item.period_start) }} – {{ formatThaiDate(item.period_end) }}
                </td>
                <td class="num whitespace-nowrap text-right font-bold text-stone-900">
                  {{ formatMoney(item.amount) }}
                </td>
                <td class="num whitespace-nowrap text-right font-bold text-brand-700">
                  {{ formatMoney(item.used) }}
                </td>
                <td
                  class="num whitespace-nowrap text-right font-bold"
                  :class="item.remaining < 0 ? 'text-red-600' : 'text-stone-700'"
                >
                  {{ formatMoney(item.remaining) }}
                </td>
                <td>
                  <div class="h-2 w-full overflow-hidden rounded-full bg-stone-100">
                    <div
                      class="h-full rounded-full transition-[width]"
                      :class="barClass(item)"
                      :style="{ width: barWidth(item) }"
                    ></div>
                  </div>
                  <p class="num mt-1 text-[11px] font-bold text-stone-400">{{ pctLabel(item) }}</p>
                </td>
                <td class="text-center">
                  <span class="chip" :class="STATUS_CHIP[statusOf(item)].cls">
                    <i class="bi" :class="STATUS_CHIP[statusOf(item)].icon" aria-hidden="true"></i>
                    {{ STATUS_CHIP[statusOf(item)].label }}
                  </span>
                </td>
                <td v-if="canManageFinance">
                  <div class="flex justify-end gap-1.5">
                    <button
                      type="button"
                      class="btn-ghost-ui px-3 py-2 text-xs"
                      :title="`แก้ไขงบของ ${item.category_name}`"
                      @click="openEdit(item)"
                    >
                      <i class="bi bi-pencil" aria-hidden="true"></i>
                      แก้ไข
                    </button>
                    <button
                      type="button"
                      class="btn-ghost-ui px-3 py-2 text-xs text-red-600"
                      :title="`ลบงบของ ${item.category_name}`"
                      @click="confirmDelete(item)"
                    >
                      <i class="bi bi-trash3" aria-hidden="true"></i>
                      ลบ
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- แถบสรุปรวม — บนเดสก์ท็อปยอดรวมอยู่ใน KPI แล้ว จึงแสดงเฉพาะที่ตารางเพื่อเทียบรายแถว -->
      <div class="page-card hidden items-center justify-between gap-4 p-4 lg:flex">
        <p class="text-sm font-bold text-stone-500">
          รวม {{ items.length }} รายการ · เกินงบ {{ overview?.over_count ?? 0 }} · ใกล้เต็ม
          {{ overview?.warning_count ?? 0 }}
        </p>
        <p
          class="num font-display text-lg font-bold"
          :class="isTotalOver ? 'text-red-600' : 'text-stone-900'"
        >
          ใช้ไป {{ formatMoney(overview?.total_used ?? 0) }} /
          {{ formatMoney(overview?.total_budget ?? 0) }}
        </p>
      </div>
    </template>

    <!-- ตั้ง/แก้ไขงบ: bottom sheet บนมือถือ / modal กลางจอบนเดสก์ท็อป (pattern เดียวกับ DebtorList) -->
    <div
      v-if="isModalOpen && canManageFinance"
      class="fixed inset-0 z-50 flex items-end justify-center bg-stone-900/40 md:items-center md:p-4"
    >
      <div
        class="flex max-h-[90vh] w-full max-w-lg flex-col rounded-t-3xl border border-stone-200 bg-white md:max-h-[85vh] md:rounded-2xl"
      >
        <div
          class="flex shrink-0 items-center justify-between gap-3 border-b border-stone-200 px-4 py-4 sm:px-6"
        >
          <div class="min-w-0">
            <h2 class="font-display truncate text-lg font-bold text-stone-900">
              {{ isEditing ? 'แก้ไขงบประมาณ' : 'ตั้งงบประมาณ' }}
            </h2>
            <p class="mt-0.5 truncate text-xs text-stone-400">
              วงเงินต่อหมวดในช่วงวันที่ที่กำหนด — ระบบคิดเดือน/ปีให้เองจากช่วงนี้
            </p>
          </div>
          <button
            type="button"
            class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-900 active:scale-[0.97]"
            aria-label="ปิดหน้าต่าง"
            @click="closeModal"
          >
            <i class="bi bi-x-lg text-lg" aria-hidden="true"></i>
          </button>
        </div>

        <div class="flex-1 overflow-y-auto overscroll-contain bg-stone-50/50 p-4 sm:p-6">
          <div class="space-y-4">
            <div>
              <label class="field-label" for="budgetCategory">หมวดหมู่</label>
              <!-- หมวดย้ายไม่ได้หลังสร้างแล้ว — backend ไม่รับ category_id ใน PATCH -->
              <select
                id="budgetCategory"
                v-model="formCategoryId"
                class="field"
                :disabled="isEditing"
              >
                <option value="" disabled>— เลือกหมวดหมู่ —</option>
                <option v-for="c in categoryOptions" :key="c.id" :value="String(c.id)">
                  {{ c.label }}{{ c.alreadyBudgeted ? ' · มีงบอยู่แล้ว' : '' }}
                </option>
              </select>
              <p v-if="isEditing" class="mt-1 text-xs text-stone-400">
                เปลี่ยนหมวดไม่ได้ — ถ้าต้องการย้าย ให้ลบงบนี้แล้วสร้างใหม่
              </p>
              <p v-else-if="!categoryOptions.length" class="mt-1 text-xs text-amber-700">
                ยังไม่มีหมวดหมู่ในห้องนี้ — เพิ่มได้ที่หน้าตั้งค่าการเงิน
              </p>
            </div>

            <div>
              <label class="field-label" for="budgetAmount">วงเงิน (บาท)</label>
              <div class="relative">
                <span
                  class="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-3 text-sm font-bold text-stone-400"
                  aria-hidden="true"
                >
                  ฿
                </span>
                <input
                  id="budgetAmount"
                  v-model="formAmount"
                  type="number"
                  min="0"
                  step="0.01"
                  inputmode="decimal"
                  class="field num ps-7 text-right"
                  placeholder="0.00"
                />
              </div>
            </div>

            <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label class="field-label" for="budgetStart">วันเริ่มต้น</label>
                <input id="budgetStart" v-model="formStart" type="date" class="field num" />
              </div>
              <div>
                <label class="field-label" for="budgetEnd">วันสิ้นสุด</label>
                <input id="budgetEnd" v-model="formEnd" type="date" class="field num" />
              </div>
            </div>
            <p class="text-xs text-stone-400">
              ใส่ให้ครอบทั้งเดือน (1 ถึงวันสุดท้ายของเดือน) ระบบจะติดป้ายเป็นงบ "รายเดือน" ให้เอง —
              ช่วงอื่นที่ไม่ตรงเดือน/ปี จะถูกติดป้ายเป็น "กำหนดเอง"
            </p>

            <div>
              <label class="field-label" for="budgetNote">หมายเหตุ (ถ้ามี)</label>
              <input
                id="budgetNote"
                v-model="formNote"
                type="text"
                maxlength="255"
                class="field"
                placeholder="เช่น งบอาหารกลางวันภาคเรียนที่ 1"
              />
            </div>

            <!-- สองระดับ: แดง = บันทึกไม่ได้ (ดักไว้ก่อน), เหลือง = บันทึกได้แต่ backend อาจตีกลับ -->
            <p v-if="formError" class="chip w-full justify-start bg-red-50 text-red-700">
              <i class="bi bi-exclamation-circle" aria-hidden="true"></i>
              {{ formError }}
            </p>
            <p v-else-if="formWarning" class="chip w-full justify-start bg-amber-50 text-amber-700">
              <i class="bi bi-info-circle" aria-hidden="true"></i>
              {{ formWarning }}
            </p>
          </div>
        </div>

        <div
          class="flex shrink-0 flex-col gap-3 border-t border-stone-200 bg-white p-4 pb-[calc(env(safe-area-inset-bottom)+1rem)] sm:flex-row sm:items-center sm:justify-end sm:px-6 sm:pt-4 sm:pb-[calc(env(safe-area-inset-bottom)+1.5rem)]"
        >
          <button type="button" class="btn-ghost-ui w-full sm:w-auto" @click="closeModal">
            ยกเลิก
          </button>
          <button
            type="button"
            class="btn-primary w-full sm:w-auto"
            :disabled="!canSubmit"
            @click="submit"
          >
            <i
              class="bi"
              :class="isSaving ? 'bi-hourglass-split' : 'bi-check-circle-fill'"
              aria-hidden="true"
            ></i>
            {{ isSaving ? 'กำลังบันทึก...' : isEditing ? 'บันทึกการแก้ไข' : 'ตั้งงบประมาณ' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ซ่อนปุ่มลูกศรในช่อง Input Number ให้ดูคลีนๆ แบบแอปธนาคาร (เหมือน DebtorList.vue) */
input[type='number']::-webkit-inner-spin-button,
input[type='number']::-webkit-outer-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
input[type='number'] {
  -moz-appearance: textfield;
}
</style>
