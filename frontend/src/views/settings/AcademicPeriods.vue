<script setup lang="ts">
/**
 * 🗓️ ตั้งค่าปีการศึกษาและเทอม — **ตัวกรองเวลาของสถิติ** (P5)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * สิ่งที่หน้านี้ทำ และไม่ทำ (อ่านก่อนแก้)
 * ═══════════════════════════════════════════════════════════════════════════
 *  · ทำ: เก็บปฏิทินของห้อง (ปี พ.ศ. + เทอม) และเลือกว่า "ปีไหน/เทอมไหนคือปัจจุบัน"
 *    ปีปัจจุบันคือค่าที่ `/me/stats` ใช้ **เมื่อผู้ใช้ไม่ได้เลือกเอง**
 *  · ไม่ทำ: ย้ายนักเรียนไปปีใหม่ — ไม่มี `academic_year_id` บน `students`
 *    ⇒ สมาชิกทุกคนอยู่ในทุกปี ตัวเลขของปี/เทอมนับจาก *วันที่ของเหตุการณ์*
 *    (ใบเสร็จ / วันที่จัดกิจกรรม) เท่านั้น
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * กฎที่ฝังไว้
 * ═══════════════════════════════════════════════════════════════════════════
 *  1. **สมาชิกอ่านได้ทุกคน** (ตัวกรองสถิติต้องใช้ร่วมกัน) แต่ฟอร์มเขียนซ่อนไว้เมื่อ
 *     ไม่มี `MANAGE_CLASSROOM_SETTINGS` — backend บังคับจริงอีกชั้น
 *  2. **ไม่มีปีปัจจุบันเป็นสภาวะปกติ** ไม่ใช่ error — ห้องที่ยังไม่ตั้งปีจะได้สถิติ
 *     ทั้งก้อน (`term: null`) หน้าจอจึงต้องบอกให้ชัด ไม่ใช่ปล่อยว่าง
 *  3. **วันที่เป็นแบบรวมวันสุดท้าย** (DATE) — แสดงตามที่กรอก ไม่บวก/ลบหนึ่งวันเอง
 *  4. ปฏิเสธที่หน้าจอก่อนเมื่อทำได้โดยไม่ต้องถามเซิร์ฟเวอร์ (วันกลับด้าน, ปีเป็น ค.ศ.)
 *     แต่ **การทับซ้อนของเทอม/ช่วงที่หลุดออกจากปีให้ backend ตัดสิน** — มันมีกติกา
 *     เดียวกันทั้ง API และหน้าจอ จึงไม่เขียนกฎซ้ำสองที่ให้เพี้ยนกันได้
 *  5. ลบ = soft delete (ผู้ใช้ยังกู้ไม่ได้ผ่าน UI เพราะยังไม่มี endpoint กู้คืน)
 *     ⇒ ต้องยืนยันด้วย `dialog.confirm` และบอกว่าจะเกิดอะไรกับเทอมในปีนั้น
 */
import { computed, onMounted, reactive, ref } from 'vue';
import PageIntro from '@/components/ui/PageIntro.vue';
import AppButton from '@/components/ui/AppButton.vue';
import AppEmptyState from '@/components/ui/AppEmptyState.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import { AcademicService } from '@/services/academic';
import { useAuthStore } from '@/stores/auth';
import { useDialog } from '@/composables/useDialog';
import { formatThaiDate } from '@/utils/datetime';
import type { AcademicPeriods, AcademicTerm, AcademicYear } from '@/types/academic';

const MIN_YEAR_BE = 2500;
const MAX_YEAR_BE = 2699;

const dialog = useDialog();
const authStore = useAuthStore();
const roomId = authStore.currentRoomId ?? 0;

// นิพจน์เดียวกับ backend (`require_permission` + `is_admin` bypass) — อย่าเขียนใหม่เอง
const canManage = computed(() => authStore.hasPermission('MANAGE_CLASSROOM_SETTINGS'));

const messageOf = (err: unknown): string =>
  err instanceof Error && err.message ? err.message : 'เกิดข้อผิดพลาดจากระบบ';

/** วันเริ่มหลังวันจบ — backend ตอบ 400 ให้อยู่แล้ว แต่ดักที่ฟอร์มได้ถูกกว่า */
const rangeError = (start: string, end: string): string | null => {
  if (!start || !end) return 'ต้องระบุวันเริ่มต้นและวันสิ้นสุด';
  return end < start ? 'วันสิ้นสุดต้องไม่ก่อนวันเริ่มต้น' : null;
};

// ── โหลดรายการ ─────────────────────────────────────────────────────────────
const data = ref<AcademicPeriods | null>(null);
const isLoading = ref(true);
const loadError = ref<string | null>(null);

const load = async () => {
  isLoading.value = true;
  loadError.value = null;
  try {
    data.value = await AcademicService.periods(roomId);
  } catch (err) {
    loadError.value = messageOf(err);
  } finally {
    isLoading.value = false;
  }
};

onMounted(() => {
  if (!roomId) {
    isLoading.value = false;
    loadError.value = 'ยังไม่ได้เลือกห้องเรียน';
    return;
  }
  void load();
});

const showError = (title: string, err: unknown) => {
  void dialog.alert(title, messageOf(err), 'error');
};

// ── สร้างปี ────────────────────────────────────────────────────────────────
const newYear = reactive({ year_be: '', name: '', start_date: '', end_date: '' });
const yearFormError = ref<string | null>(null);
const isCreatingYear = ref(false);

const submitYear = async () => {
  if (!canManage.value || isCreatingYear.value) return;
  yearFormError.value = null;

  const yearBe = Number(newYear.year_be);
  if (!Number.isInteger(yearBe)) {
    yearFormError.value = 'กรอกปี พ.ศ. เป็นตัวเลข เช่น 2569';
    return;
  }
  if (yearBe < MIN_YEAR_BE || yearBe > MAX_YEAR_BE) {
    yearFormError.value =
      `ปี พ.ศ. ต้องอยู่ระหว่าง ${MIN_YEAR_BE}–${MAX_YEAR_BE}` +
      ' — ถ้ากรอกเป็น ค.ศ. (เช่น 2026) ให้บวก 543';
    return;
  }
  const invalidRange = rangeError(newYear.start_date, newYear.end_date);
  if (invalidRange) {
    yearFormError.value = invalidRange;
    return;
  }

  isCreatingYear.value = true;
  try {
    await AcademicService.createYear(roomId, {
      year_be: yearBe,
      name: newYear.name.trim() || null,
      start_date: newYear.start_date,
      end_date: newYear.end_date,
    });
    newYear.year_be = '';
    newYear.name = '';
    newYear.start_date = '';
    newYear.end_date = '';
    await load();
  } catch (err) {
    yearFormError.value = messageOf(err);
  } finally {
    isCreatingYear.value = false;
  }
};

// ── แก้ไขปี/เทอม (Inline) ──────────────────────────────────────────────────
type EditTarget = { kind: 'year'; id: number } | { kind: 'term'; id: number };

const editing = ref<EditTarget | null>(null);
const editForm = reactive({ name: '', start_date: '', end_date: '' });
const editError = ref<string | null>(null);
const isSavingEdit = ref(false);

const isEditingYear = (year: AcademicYear): boolean =>
  editing.value?.kind === 'year' && editing.value.id === year.id;

const isEditingTerm = (term: AcademicTerm): boolean =>
  editing.value?.kind === 'term' && editing.value.id === term.id;

const startEditYear = (year: AcademicYear) => {
  editing.value = { kind: 'year', id: year.id };
  editError.value = null;
  editForm.name = year.name ?? '';
  editForm.start_date = year.start_date;
  editForm.end_date = year.end_date;
};

const startEditTerm = (term: AcademicTerm) => {
  editing.value = { kind: 'term', id: term.id };
  editError.value = null;
  editForm.name = term.name;
  editForm.start_date = term.start_date;
  editForm.end_date = term.end_date;
};

const cancelEdit = () => {
  editing.value = null;
  editError.value = null;
};

const saveEdit = async () => {
  const target = editing.value;
  if (!target || isSavingEdit.value) return;
  editError.value = null;

  const invalidRange = rangeError(editForm.start_date, editForm.end_date);
  if (invalidRange) {
    editError.value = invalidRange;
    return;
  }
  const name = editForm.name.trim();
  if (target.kind === 'term' && !name) {
    editError.value = 'ต้องระบุชื่อเทอม';
    return;
  }

  isSavingEdit.value = true;
  try {
    if (target.kind === 'year') {
      await AcademicService.updateYear(roomId, target.id, {
        name: name || null,
        start_date: editForm.start_date,
        end_date: editForm.end_date,
      });
    } else {
      await AcademicService.updateTerm(roomId, target.id, {
        name,
        start_date: editForm.start_date,
        end_date: editForm.end_date,
      });
    }
    editing.value = null;
    await load();
  } catch (err) {
    // ข้อความจาก backend เช่น "ช่วงของเทอมทับกับเทอมอื่นในปีเดียวกัน"
    editError.value = messageOf(err);
  } finally {
    isSavingEdit.value = false;
  }
};

// ── สร้างเทอม ──────────────────────────────────────────────────────────────
const termFormYearId = ref<number | null>(null);
const newTerm = reactive({ name: '', start_date: '', end_date: '' });
const termFormError = ref<string | null>(null);
const isCreatingTerm = ref(false);

const openTermForm = (year: AcademicYear) => {
  termFormYearId.value = year.id;
  termFormError.value = null;
  newTerm.name = '';
  newTerm.start_date = year.start_date;
  newTerm.end_date = year.end_date;
};

const cancelTermForm = () => {
  termFormYearId.value = null;
  termFormError.value = null;
};

const submitTerm = async (year: AcademicYear) => {
  if (isCreatingTerm.value) return;
  termFormError.value = null;

  if (!newTerm.name.trim()) {
    termFormError.value = 'ต้องระบุชื่อเทอม เช่น “เทอม 1”';
    return;
  }
  const invalidRange = rangeError(newTerm.start_date, newTerm.end_date);
  if (invalidRange) {
    termFormError.value = invalidRange;
    return;
  }

  isCreatingTerm.value = true;
  try {
    await AcademicService.createTerm(roomId, year.id, {
      name: newTerm.name.trim(),
      start_date: newTerm.start_date,
      end_date: newTerm.end_date,
    });
    termFormYearId.value = null;
    await load();
  } catch (err) {
    termFormError.value = messageOf(err);
  } finally {
    isCreatingTerm.value = false;
  }
};

// ── ตั้ง/ปลด "ปัจจุบัน" ────────────────────────────────────────────────────
const isSettingCurrent = ref(false);

const setCurrent = async (yearId: number | null, termId: number | null = null) => {
  if (!canManage.value || isSettingCurrent.value) return;
  isSettingCurrent.value = true;
  try {
    await AcademicService.setCurrent(roomId, { year_id: yearId, term_id: termId });
    await load();
  } catch (err) {
    await showError('ตั้งช่วงเวลาปัจจุบันไม่สำเร็จ', err);
  } finally {
    isSettingCurrent.value = false;
  }
};

const clearCurrent = async () => {
  const { isConfirmed } = await dialog.confirm(
    'ปลดปีปัจจุบัน?',
    'สถิติของทุกคนจะกลับไปนับทั้งหมด (ไม่กรองตามปี/เทอม) จนกว่าจะตั้งใหม่',
    { icon: 'question', confirmButtonText: 'ปลด', cancelButtonText: 'ยกเลิก' },
  );
  if (isConfirmed) await setCurrent(null);
};

// ── ลบ (soft) ──────────────────────────────────────────────────────────────
const deleteYear = async (year: AcademicYear) => {
  const termCount = year.terms.length;
  const { isConfirmed } = await dialog.confirm(
    `ลบปีการศึกษา ${year.year_be}?`,
    termCount > 0
      ? `เทอมทั้งหมด ${termCount} เทอมในปีนี้จะถูกลบไปด้วย (ข้อมูลการเงิน/กิจกรรมไม่ถูกลบ)`
      : 'ข้อมูลการเงินและกิจกรรมของปีนี้จะไม่ถูกลบ — แต่จะมองไม่เห็นปฏิทินปีนี้อีก',
    { icon: 'warning', danger: true, confirmButtonText: 'ลบ', cancelButtonText: 'ยกเลิก' },
  );
  if (!isConfirmed) return;
  try {
    await AcademicService.deleteYear(roomId, year.id);
    await load();
  } catch (err) {
    await showError('ลบปีการศึกษาไม่สำเร็จ', err);
  }
};

const deleteTerm = async (term: AcademicTerm) => {
  const { isConfirmed } = await dialog.confirm(
    `ลบ ${term.name}?`,
    'ช่วงเวลานี้จะใช้กรองสถิติไม่ได้อีก แต่ตัวเลขการเงิน/กิจกรรมยังอยู่ครบ',
    { icon: 'warning', danger: true, confirmButtonText: 'ลบ', cancelButtonText: 'ยกเลิก' },
  );
  if (!isConfirmed) return;
  try {
    await AcademicService.deleteTerm(roomId, term.id);
    await load();
  } catch (err) {
    await showError('ลบเทอมไม่สำเร็จ', err);
  }
};

// ── ข้อความสรุป ────────────────────────────────────────────────────────────
const currentLabel = computed(() => {
  const current = data.value;
  if (!current) return '';
  const year = current.years.find((row) => row.id === current.current_year_id);
  if (!year) return 'ยังไม่ได้ตั้งปีปัจจุบัน — สถิติจะนับทั้งหมด';
  const term = year.terms.find((row) => row.id === current.current_term_id);
  return term ? `ปีการศึกษา ${year.year_be} · ${term.name}` : `ปีการศึกษา ${year.year_be} (ทั้งปี)`;
});

const describeRange = (start: string, end: string): string =>
  `${formatThaiDate(start)} – ${formatThaiDate(end)}`;
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro
      description="กำหนดปฏิทินของห้องเพื่อกรองสถิติตามปี/เทอม — ไม่ได้ย้ายนักเรียนไปปีใหม่"
    />

    <!-- ภาพรวมปัจจุบัน: ค่าที่สถิติใช้เมื่อไม่ได้เลือกเอง -->
    <section class="rounded-card border border-line bg-surface p-4" aria-label="ช่วงเวลาปัจจุบัน">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="min-w-0">
          <p class="text-xs font-bold text-ink-3">ปี/เทอมปัจจุบัน</p>
          <p class="mt-0.5 break-words text-sm font-bold text-ink">{{ currentLabel }}</p>
        </div>
        <AppButton
          v-if="canManage && data?.current_year_id"
          variant="secondary"
          :loading="isSettingCurrent"
          @click="clearCurrent"
        >
          ปลดปีปัจจุบัน
        </AppButton>
      </div>
      <p class="mt-2 text-xs leading-relaxed text-ink-3">
        สถิติของฉันจะใช้ช่วงนี้โดยอัตโนมัติ · สมาชิกยังเลือกดูปีอื่นเองได้ในหน้าของฉัน
      </p>
    </section>

    <SkeletonRows v-if="isLoading" :rows="2" height="h-28" />

    <StateBlock
      v-else-if="loadError"
      variant="error"
      title="โหลดปีการศึกษาไม่สำเร็จ"
      :hint="loadError"
      @retry="load"
    />

    <template v-else>
      <!-- ยังไม่มีปีเลย -->
      <AppEmptyState
        v-if="(data?.years.length ?? 0) === 0 && !canManage"
        icon="bi-calendar3"
        title="ห้องนี้ยังไม่ได้ตั้งปีการศึกษา"
        hint="ผู้ดูแลห้องสามารถเพิ่มปีการศึกษาและเทอมเพื่อใช้กรองสถิติได้"
      />

      <!-- รายการปี + เทอม -->
      <ul v-if="(data?.years.length ?? 0) > 0" class="space-y-3">
        <li v-for="year in data?.years ?? []" :key="year.id" class="page-card p-4 sm:p-5">
          <div class="flex flex-wrap items-start justify-between gap-2">
            <div class="min-w-0">
              <p class="flex flex-wrap items-center gap-1.5 text-sm font-bold text-ink">
                ปีการศึกษา {{ year.year_be }}
                <span
                  v-if="year.is_current"
                  class="rounded-full bg-ok-50 px-2 py-0.5 text-xs font-bold text-ok-700"
                >
                  ปัจจุบัน
                </span>
              </p>
              <p class="mt-0.5 break-words text-xs text-ink-3">
                {{ year.name || 'ไม่มีชื่อกำกับ' }} · {{ describeRange(year.start_date, year.end_date) }}
              </p>
            </div>

            <div v-if="canManage" class="flex flex-wrap items-center gap-1.5">
              <AppButton
                v-if="!year.is_current"
                variant="quiet"
                :disabled="isSettingCurrent"
                @click="setCurrent(year.id)"
              >
                ตั้งเป็นปัจจุบัน
              </AppButton>
              <AppButton variant="quiet" @click="startEditYear(year)">แก้ไข</AppButton>
              <AppButton variant="danger" @click="deleteYear(year)">ลบ</AppButton>
            </div>
          </div>

          <!-- ฟอร์มแก้ไขปี -->
          <form
            v-if="isEditingYear(year)"
            class="mt-3 space-y-2 rounded-control border border-line bg-canvas p-3"
            @submit.prevent="saveEdit"
          >
            <div class="grid gap-2 sm:grid-cols-3">
              <label class="block">
                <span class="text-xs font-bold text-ink-2">ชื่อกำกับ (ไม่บังคับ)</span>
                <input
                  v-model="editForm.name"
                  type="text"
                  maxlength="60"
                  class="mt-1 min-h-11 w-full rounded-control border border-line bg-surface px-3 text-sm"
                />
              </label>
              <label class="block">
                <span class="text-xs font-bold text-ink-2">วันเริ่มต้น</span>
                <input
                  v-model="editForm.start_date"
                  type="date"
                  required
                  class="mt-1 min-h-11 w-full rounded-control border border-line bg-surface px-3 text-sm"
                />
              </label>
              <label class="block">
                <span class="text-xs font-bold text-ink-2">วันสิ้นสุด (รวมวันนี้)</span>
                <input
                  v-model="editForm.end_date"
                  type="date"
                  required
                  class="mt-1 min-h-11 w-full rounded-control border border-line bg-surface px-3 text-sm"
                />
              </label>
            </div>
            <p v-if="editError" class="text-xs font-bold text-danger-700" role="alert">
              {{ editError }}
            </p>
            <div class="flex flex-wrap gap-2">
              <AppButton type="submit" :loading="isSavingEdit">บันทึก</AppButton>
              <AppButton variant="secondary" @click="cancelEdit">ยกเลิก</AppButton>
            </div>
          </form>

          <!-- เทอมในปีนี้ -->
          <div class="mt-3 border-t border-line pt-3">
            <p class="text-xs font-bold text-ink-3">เทอม</p>

            <p v-if="year.terms.length === 0" class="mt-1 text-xs text-ink-3">
              ยังไม่มีเทอม — สถิติของปีนี้จึงนับทั้งปี
            </p>

            <ul v-else class="mt-1 space-y-1.5">
              <li v-for="term in year.terms" :key="term.id" class="rounded-control bg-canvas p-2.5">
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <div class="min-w-0">
                    <p class="flex flex-wrap items-center gap-1.5 text-sm font-bold text-ink">
                      {{ term.name }}
                      <span
                        v-if="term.is_current"
                        class="rounded-full bg-ok-50 px-2 py-0.5 text-xs font-bold text-ok-700"
                      >
                        เทอมปัจจุบัน
                      </span>
                    </p>
                    <p class="text-xs text-ink-3">
                      {{ describeRange(term.start_date, term.end_date) }}
                    </p>
                  </div>
                  <div v-if="canManage" class="flex flex-wrap items-center gap-1">
                    <AppButton
                      v-if="!term.is_current"
                      variant="quiet"
                      :disabled="isSettingCurrent"
                      @click="setCurrent(year.id, term.id)"
                    >
                      ใช้เทอมนี้
                    </AppButton>
                    <AppButton variant="quiet" @click="startEditTerm(term)">แก้ไข</AppButton>
                    <AppButton variant="danger" @click="deleteTerm(term)">ลบ</AppButton>
                  </div>
                </div>

                <form
                  v-if="isEditingTerm(term)"
                  class="mt-2 space-y-2 rounded-control border border-line bg-surface p-2.5"
                  @submit.prevent="saveEdit"
                >
                  <div class="grid gap-2 sm:grid-cols-3">
                    <label class="block">
                      <span class="text-xs font-bold text-ink-2">ชื่อเทอม</span>
                      <input
                        v-model="editForm.name"
                        type="text"
                        maxlength="60"
                        required
                        class="mt-1 min-h-11 w-full rounded-control border border-line px-3 text-sm"
                      />
                    </label>
                    <label class="block">
                      <span class="text-xs font-bold text-ink-2">วันเริ่มต้น</span>
                      <input
                        v-model="editForm.start_date"
                        type="date"
                        required
                        class="mt-1 min-h-11 w-full rounded-control border border-line px-3 text-sm"
                      />
                    </label>
                    <label class="block">
                      <span class="text-xs font-bold text-ink-2">วันสิ้นสุด (รวมวันนี้)</span>
                      <input
                        v-model="editForm.end_date"
                        type="date"
                        required
                        class="mt-1 min-h-11 w-full rounded-control border border-line px-3 text-sm"
                      />
                    </label>
                  </div>
                  <p v-if="editError" class="text-xs font-bold text-danger-700" role="alert">
                    {{ editError }}
                  </p>
                  <div class="flex flex-wrap gap-2">
                    <AppButton type="submit" :loading="isSavingEdit">บันทึก</AppButton>
                    <AppButton variant="secondary" @click="cancelEdit">ยกเลิก</AppButton>
                  </div>
                </form>
              </li>
            </ul>

            <!-- เพิ่มเทอม -->
            <div v-if="canManage" class="mt-2">
              <AppButton
                v-if="termFormYearId !== year.id"
                variant="quiet"
                @click="openTermForm(year)"
              >
                <i class="bi bi-plus-lg" aria-hidden="true"></i>
                เพิ่มเทอม
              </AppButton>

              <form
                v-else
                class="space-y-2 rounded-control border border-brand-200 bg-brand-tint p-3"
                @submit.prevent="submitTerm(year)"
              >
                <div class="grid gap-2 sm:grid-cols-3">
                  <label class="block">
                    <span class="text-xs font-bold text-ink-2">ชื่อเทอม</span>
                    <input
                      v-model="newTerm.name"
                      type="text"
                      maxlength="60"
                      placeholder="เช่น เทอม 1"
                      required
                      class="mt-1 min-h-11 w-full rounded-control border border-line bg-surface px-3 text-sm"
                    />
                  </label>
                  <label class="block">
                    <span class="text-xs font-bold text-ink-2">วันเริ่มต้น</span>
                    <input
                      v-model="newTerm.start_date"
                      type="date"
                      required
                      class="mt-1 min-h-11 w-full rounded-control border border-line bg-surface px-3 text-sm"
                    />
                  </label>
                  <label class="block">
                    <span class="text-xs font-bold text-ink-2">วันสิ้นสุด (รวมวันนี้)</span>
                    <input
                      v-model="newTerm.end_date"
                      type="date"
                      required
                      class="mt-1 min-h-11 w-full rounded-control border border-line bg-surface px-3 text-sm"
                    />
                  </label>
                </div>
                <p class="text-xs text-ink-3">
                  เทอมต้องอยู่ในช่วงของปีนี้และต้องไม่ทับกับเทอมอื่น
                </p>
                <p v-if="termFormError" class="text-xs font-bold text-danger-700" role="alert">
                  {{ termFormError }}
                </p>
                <div class="flex flex-wrap gap-2">
                  <AppButton type="submit" :loading="isCreatingTerm">เพิ่มเทอม</AppButton>
                  <AppButton variant="secondary" @click="cancelTermForm">ยกเลิก</AppButton>
                </div>
              </form>
            </div>
          </div>
        </li>
      </ul>

      <!-- ฟอร์มสร้างปี -->
      <section v-if="canManage" class="page-card p-4 sm:p-6">
        <h2 class="section-title">เพิ่มปีการศึกษา</h2>
        <p class="mt-0.5 text-xs leading-relaxed text-ink-3">
          ใส่ปี พ.ศ. (เช่น 2569) — ระบบไม่ย้ายนักเรียน จึงเพิ่มปีล่วงหน้าได้โดยไม่กระทบข้อมูลเดิม
        </p>

        <form class="mt-3 space-y-3" @submit.prevent="submitYear">
          <div class="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <label class="block">
              <span class="text-xs font-bold text-ink-2">ปี พ.ศ.</span>
              <input
                v-model="newYear.year_be"
                type="number"
                :min="MIN_YEAR_BE"
                :max="MAX_YEAR_BE"
                inputmode="numeric"
                placeholder="2569"
                required
                class="mt-1 min-h-11 w-full rounded-control border border-line bg-surface px-3 text-sm"
              />
            </label>
            <label class="block">
              <span class="text-xs font-bold text-ink-2">ชื่อกำกับ (ไม่บังคับ)</span>
              <input
                v-model="newYear.name"
                type="text"
                maxlength="60"
                placeholder="ปีการศึกษา 2569"
                class="mt-1 min-h-11 w-full rounded-control border border-line bg-surface px-3 text-sm"
              />
            </label>
            <label class="block">
              <span class="text-xs font-bold text-ink-2">วันเริ่มต้น</span>
              <input
                v-model="newYear.start_date"
                type="date"
                required
                class="mt-1 min-h-11 w-full rounded-control border border-line bg-surface px-3 text-sm"
              />
            </label>
            <label class="block">
              <span class="text-xs font-bold text-ink-2">วันสิ้นสุด (รวมวันนี้)</span>
              <input
                v-model="newYear.end_date"
                type="date"
                required
                class="mt-1 min-h-11 w-full rounded-control border border-line bg-surface px-3 text-sm"
              />
            </label>
          </div>

          <p v-if="yearFormError" class="text-xs font-bold text-danger-700" role="alert">
            {{ yearFormError }}
          </p>

          <AppButton type="submit" :loading="isCreatingYear">เพิ่มปีการศึกษา</AppButton>
        </form>
      </section>

      <p v-else class="text-xs leading-relaxed text-ink-3">
        สมาชิกทุกคนดูปฏิทินของห้องได้ — การเพิ่ม/แก้ไขต้องมีสิทธิ์ตั้งค่าห้องเรียน
      </p>
    </template>
  </div>
</template>
