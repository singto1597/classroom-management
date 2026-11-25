<script setup lang="ts">
/**
 * 🔎 [FIN-V2 / P5.2] ตัวกรองของทะเบียนเอกสารรวม — 7 มิติ
 *
 * ชนิด · ช่วงวันที่ · นักเรียน · ผู้รับเงิน · ช่องทาง · สถานะ · คำค้น
 *
 * 🔴 เป็น **presentational** — ไม่เรียก API เองนอกจากโหลดตัวเลือก (นักเรียน/ช่องทาง/ผู้รับ)
 *    การยิงรายการเอกสารเป็นของ `DocumentRegistry.vue` (จุดเดียวที่รู้ offset/selection)
 *
 * ⚠️ ช่องทาง/ผู้รับเป็น **optional ที่ซ่อนได้**: ถ้า endpoint ยังไม่พร้อม (เช่นสาขาที่ยังไม่มี
 *    P2.4) การโหลดล้มเหลวต้องไม่ทำให้ทั้งหน้าพัง — ตรวจ `try/catch` แล้วซ่อนช่องนั้น
 *    (หน้าใช้งานได้ด้วยตัวกรองพื้นฐาน)
 *
 * 🗓️ วันที่ส่งเป็น `YYYY-MM-DD` (ISO) — backend ตีความเป็น **วันไทย** เอง (half-open)
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';

import PersonPicker from '@/components/finance/PersonPicker.vue';

import { FinanceService } from '@/services/finance';
import { useAuthStore } from '@/stores/auth';
import { displayName } from '@/utils/name';
import { DOC_TYPES, typeLabel } from '@/utils/documentFilters';
import type {
  BasicStudent,
  DocumentListQuery,
  DocumentType,
  PaymentChannel,
} from '@/types/finance';

const props = defineProps<{ modelValue: DocumentListQuery }>();

const emit = defineEmits<{
  'update:modelValue': [DocumentListQuery];
  /** กด "ค้นหา"/Enter — ให้หน้าลูกโหลดใหม่แม้ค่าไม่ได้เปลี่ยน (เช่นกดซ้ำหลัง error) */
  submit: [];
}>();

const authStore = useAuthStore();
const roomId = authStore.currentRoomId!;

/** อัปเดตบางส่วนของตัวกรอง — ค่าที่ไม่ส่งมาคงเดิม */
const patch = (part: Partial<DocumentListQuery>) => {
  emit('update:modelValue', { ...props.modelValue, ...part });
};

// ── ชนิดเอกสาร (multi-checkbox) ────────────────────────────────────────────
const selectedTypes = computed<readonly DocumentType[]>(
  () => props.modelValue.doc_types ?? [],
);

const isTypeSelected = (docType: DocumentType): boolean =>
  selectedTypes.value.includes(docType);

const toggleType = (docType: DocumentType) => {
  const current = selectedTypes.value;
  const next = current.includes(docType)
    ? current.filter((t) => t !== docType)
    : [...current, docType];
  // ว่าง = ไม่กรอง ⇒ ส่ง undefined ไม่ใช่ []
  patch({ doc_types: next.length ? [...next] : undefined });
};

// ── ช่วงวันที่ (ISO date input คู่ — ว่าง = ไม่จำกัดขอบ) ─────────────────────
const onDateChange = (key: 'from' | 'to', event: Event) => {
  const value = (event.target as HTMLInputElement).value;
  patch({ [key]: value || undefined });
};

// ── สถานะ ────────────────────────────────────────────────────────────────
const statusValue = computed(() => props.modelValue.status ?? 'active');

const onStatusChange = (event: Event) => {
  const value = (event.target as HTMLSelectElement).value;
  if (value === 'active' || value === 'voided' || value === 'all') {
    patch({ status: value });
  }
};

// ── นักเรียน (ค้นหาในรายการที่โหลดไว้ — ห้องละไม่กี่สิบคน) ────────────────
const students = ref<BasicStudent[]>([]);
const studentsReady = ref(false);
const studentQuery = ref('');
const isStudentOpen = ref(false);

const studentLabel = (s: BasicStudent): string =>
  `${s.student_no ? `#${s.student_no} ` : ''}${displayName(s)}`.trim();

const selectedStudent = computed<BasicStudent | null>(() => {
  const id = props.modelValue.student_id;
  if (id === null || id === undefined) return null;
  return students.value.find((s) => s.id === id) ?? null;
});

/** ซิงก์ช่องค้นหานักเรียนเมื่อค่าถูกเปลี่ยนจากภายนอก (ปุ่มล้างตัวกรอง/route) */
watch(
  () => props.modelValue.student_id,
  () => {
    studentQuery.value = selectedStudent.value ? studentLabel(selectedStudent.value) : '';
  },
);

const studentMatches = computed<BasicStudent[]>(() => {
  const term = studentQuery.value.trim().toLowerCase();
  if (!term) return students.value.slice(0, 8);
  return students.value
    .filter(
      (s) =>
        String(s.student_no).includes(term) ||
        studentLabel(s).toLowerCase().includes(term) ||
        (s.nickname ?? '').toLowerCase().includes(term) ||
        (s.nickname_en ?? '').toLowerCase().includes(term),
    )
    .slice(0, 8);
});

const onStudentInput = () => {
  isStudentOpen.value = true;
  // พิมพ์ทับชื่อที่เลือกไว้ = กำลังหาคนใหม่ ⇒ ต้องปลดตัวกรองเดิม ไม่ให้ผลลัพธ์ขัดกับข้อความ
  if (props.modelValue.student_id !== null && props.modelValue.student_id !== undefined) {
    patch({ student_id: null });
  }
};

const selectStudent = (s: BasicStudent) => {
  studentQuery.value = studentLabel(s);
  isStudentOpen.value = false;
  patch({ student_id: s.id });
};

const clearStudent = () => {
  studentQuery.value = '';
  isStudentOpen.value = false;
  patch({ student_id: null });
};

// ── ผู้รับเงิน / ช่องทาง (optional — ซ่อนเมื่อโหลดไม่ได้) ───────────────────
const channels = ref<PaymentChannel[]>([]);

const onReceiverChange = (value: number | null) => {
  patch({ receiver_id: value });
};

const onChannelChange = (event: Event) => {
  const raw = (event.target as HTMLSelectElement).value;
  patch({ channel_id: raw ? Number(raw) : null });
};

// ── คำค้น (debounce 300ms — pattern เดียวกับ PaymentHistory/FineList) ──────
const searchInput = ref(props.modelValue.q ?? '');
let searchTimer: ReturnType<typeof setTimeout> | null = null;

watch(
  () => props.modelValue.q,
  (value) => {
    const next = value ?? '';
    if (searchInput.value !== next) searchInput.value = next;
  },
);

const onSearchInput = () => {
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    searchTimer = null;
    const term = searchInput.value.trim();
    if ((props.modelValue.q ?? '') !== term) patch({ q: term || undefined });
  }, 300);
};

// ── ล้างตัวกรอง ──────────────────────────────────────────────────────────
const clearFilters = () => {
  studentQuery.value = '';
  searchInput.value = '';
  isStudentOpen.value = false;
  // ค่าเปลี่ยน ⇒ watcher ของหน้าลูกโหลดใหม่เอง (ไม่ต้อง emit submit ซ้ำแล้วยิงสองคำขอ)
  emit('update:modelValue', { status: 'active' });
};

onMounted(async () => {
  try {
    students.value = await FinanceService.getActiveStudents(roomId);
    studentsReady.value = true;
    // ตัวเลือกมาช้ากว่าค่าเริ่มต้น ⇒ เติมชื่อที่เลือกไว้ให้ตรง
    if (selectedStudent.value) studentQuery.value = studentLabel(selectedStudent.value);
  } catch {
    studentsReady.value = false;
  }
  try {
    channels.value = await FinanceService.getPaymentChannels(roomId);
  } catch {
    // ⚠️ endpoint ยังไม่พร้อม = ซ่อนช่อง ไม่ให้ทั้งหน้าพัง
    channels.value = [];
  }
});

onBeforeUnmount(() => {
  if (searchTimer) clearTimeout(searchTimer);
});
</script>

<template>
  <div class="page-card space-y-4 p-3 sm:p-4">
    <!-- ชนิดเอกสาร -->
    <div>
      <p class="field-label mb-1.5">ชนิดเอกสาร</p>
      <div
        class="grid grid-cols-2 gap-1.5 sm:grid-cols-4"
        role="group"
        aria-label="กรองชนิดเอกสาร"
      >
        <label
          v-for="docType in DOC_TYPES"
          :key="docType"
          class="flex min-h-11 cursor-pointer items-center gap-2 rounded-control border px-2.5 py-2 text-sm font-bold transition-colors"
          :class="
            isTypeSelected(docType)
              ? 'border-brand-700 bg-brand-tint text-brand'
              : 'border-line text-ink-3 hover:bg-canvas hover:text-ink'
          "
        >
          <input
            type="checkbox"
            class="peer sr-only"
            :checked="isTypeSelected(docType)"
            @change="toggleType(docType)"
          />
          <span
            class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
            :class="
              isTypeSelected(docType)
                ? 'border-brand-700 bg-brand-700'
                : 'border-line bg-surface'
            "
          >
            <i
              v-if="isTypeSelected(docType)"
              class="bi bi-check-lg text-xs font-bold text-white"
              aria-hidden="true"
            ></i>
          </span>
          <span class="min-w-0 truncate">{{ typeLabel(docType) }}</span>
        </label>
      </div>
      <p class="mt-1 text-caption text-ink-3">
        ไม่ติ๊ก = แสดงทุกชนิด
      </p>
    </div>

    <!-- วันที่ + นักเรียน + ผู้รับ + ช่องทาง + สถานะ -->
    <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <label class="block">
        <span class="field-label">จากวันที่</span>
        <input
          type="date"
          class="field mt-1 w-full"
          :value="modelValue.from ?? ''"
          @change="onDateChange('from', $event)"
        />
      </label>
      <label class="block">
        <span class="field-label">ถึงวันที่</span>
        <input
          type="date"
          class="field mt-1 w-full"
          :value="modelValue.to ?? ''"
          @change="onDateChange('to', $event)"
        />
      </label>
      <label class="block">
        <span class="field-label">สถานะ</span>
        <select
          class="field mt-1 w-full"
          :value="statusValue"
          @change="onStatusChange"
        >
          <option value="active">ใช้งาน</option>
          <option value="voided">ยกเลิก</option>
          <option value="all">ทั้งหมด</option>
        </select>
      </label>

      <!-- นักเรียน: ช่องค้นหา + dropdown (ค้นในรายการที่โหลดไว้ ไม่ยิง API ต่อคีย์) -->
      <div v-if="studentsReady" class="relative block">
        <label class="field-label" for="doc-filter-student">นักเรียน</label>
        <div class="mt-1 flex items-center gap-1.5">
          <input
            id="doc-filter-student"
            v-model="studentQuery"
            type="text"
            class="field w-full"
            placeholder="พิมพ์ชื่อหรือเลขที่นักเรียน"
            autocomplete="off"
            @input="onStudentInput"
            @focus="isStudentOpen = true"
            @focusout="isStudentOpen = false"
          />
          <button
            v-if="modelValue.student_id !== null && modelValue.student_id !== undefined"
            type="button"
            class="btn-ghost-ui shrink-0"
            aria-label="ล้างนักเรียนที่เลือก"
            @click="clearStudent"
          >
            <i class="bi bi-x-lg" aria-hidden="true"></i>
          </button>
        </div>
        <ul
          v-if="isStudentOpen && studentMatches.length"
          class="absolute z-20 mt-1 max-h-64 w-full overflow-y-auto rounded-card border border-line bg-surface py-1 shadow-lg"
          role="listbox"
        >
          <li v-for="s in studentMatches" :key="s.id">
            <button
              type="button"
              class="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-canvas"
              :class="
                modelValue.student_id === s.id ? 'font-bold text-brand' : 'text-ink'
              "
              role="option"
              :aria-selected="modelValue.student_id === s.id"
              @mousedown.prevent="selectStudent(s)"
            >
              <span class="min-w-0 truncate">{{ displayName(s) }}</span>
              <span class="num shrink-0 text-xs text-ink-3">#{{ s.student_no }}</span>
            </button>
          </li>
        </ul>
      </div>

      <!-- ผู้รับเงิน: PersonPicker (ซ่อนเองถ้าทะเบียนผู้เกี่ยวข้องว่าง) -->
      <div class="block">
        <span class="field-label">ผู้รับเงิน</span>
        <div class="mt-1">
          <PersonPicker
            :model-value="modelValue.receiver_id ?? null"
            type="teacher"
            :roles="['receive']"
            placeholder="ทุกคน"
            @update:model-value="onReceiverChange"
          />
        </div>
      </div>

      <label v-if="channels.length" class="block">
        <span class="field-label">ช่องทาง</span>
        <select
          class="field mt-1 w-full"
          :value="modelValue.channel_id ?? ''"
          @change="onChannelChange"
        >
          <option value="">ทุกช่องทาง</option>
          <option v-for="c in channels" :key="c.id" :value="c.id">
            {{ c.label }}
          </option>
        </select>
      </label>
    </div>

    <!-- คำค้น + ปุ่ม -->
    <div class="flex flex-col gap-2 sm:flex-row sm:items-end">
      <label class="block min-w-0 flex-1">
        <span class="field-label">ค้นหา</span>
        <input
          v-model="searchInput"
          type="search"
          class="field mt-1 w-full"
          placeholder="เลขที่เอกสาร · ชื่อนักเรียน · ชื่อผู้รับ"
          @input="onSearchInput"
          @keydown.enter.prevent="emit('submit')"
        />
      </label>
      <div class="flex shrink-0 items-center gap-2">
        <button type="button" class="btn-ghost-ui" @click="clearFilters">
          <i class="bi bi-arrow-counterclockwise" aria-hidden="true"></i>
          ล้างตัวกรอง
        </button>
        <button type="button" class="btn-primary" @click="emit('submit')">
          <i class="bi bi-search" aria-hidden="true"></i>
          ค้นหา
        </button>
      </div>
    </div>
  </div>
</template>
