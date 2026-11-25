<script setup lang="ts">
/**
 * PersonPicker — ตัวเลือก "ผู้เกี่ยวข้องทางการเงิน" จากทะเบียนของห้อง (FIN-V2 / P1.2)
 *
 * 🔑 ทำไมไม่ใช้ช่องข้อความอิสระ: เอกสารต้องใช้ **person ตัวจริง** เพื่อตอบได้ว่า
 *    "ใครรับเงินไปเท่าไร" และเพื่อคัดชื่อไปเป็น snapshot บนใบเสร็จ (P2.1/P2.2)
 *
 * - โหลดรายชื่อ active ผ่าน `FinanceService.getPeople` (กรอง `type` ที่ backend)
 * - ค้นหา debounce 250ms ผ่าน `q` (ไม่กรองฝั่ง client อย่างเดียว — ห้องใหญ่จะช้า)
 * - `roles` เป็นตัวกรองเพิ่มฝั่ง client: "ผู้รับเงิน" ต้องมีบทบาท `receive`
 *
 * @example
 * <PersonPicker v-model="receiverId" type="teacher" :roles="['receive']" />
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useAuthStore } from '@/stores/auth';
import { FinanceService } from '@/services/finance';
import type { FinancePerson, PersonRole, PersonType } from '@/types/finance';

const props = withDefaults(
  defineProps<{
    modelValue: number | null;
    type?: PersonType;
    roles?: PersonRole[];
    placeholder?: string;
    label?: string;
    disabled?: boolean;
    /**
     * ตัวนับจากหน้าลูก — เปลี่ยนค่าเมื่อทะเบียนถูกแก้ (เพิ่ม/ลบ/ซิงก์) เพื่อโหลด
     * รายชื่อใหม่ ไม่งั้นตัวเลือกค้างชุดเก่าที่เปิดฟอร์มครั้งแรก
     */
    refreshKey?: number;
  }>(),
  {
    type: undefined,
    roles: () => [],
    placeholder: 'เลือกผู้เกี่ยวข้อง…',
    label: '',
    disabled: false,
    refreshKey: 0,
  },
);

const emit = defineEmits<{
  'update:modelValue': [number | null];
  change: [FinancePerson | null];
}>();

const authStore = useAuthStore();
const roomId = authStore.currentRoomId!;

const ROLE_LABELS: Record<PersonRole, string> = {
  receive: 'ผู้รับเงิน',
  pay: 'ผู้จ่าย',
  approve: 'ผู้อนุมัติ',
};

const people = ref<FinancePerson[]>([]);
const isLoading = ref(false);
const isOpen = ref(false);
const query = ref('');

/** id ของคนที่เลือก — เก็บ object ไว้เพื่อแสดงชื่อทันทีโดยไม่ต้องรอ fetch */
const selected = computed<FinancePerson | null>(() => {
  if (props.modelValue === null) return null;
  return people.value.find((p) => p.person_id === props.modelValue) ?? null;
});

const selectedLabel = computed(() => {
  if (props.modelValue === null) return '';
  return selected.value?.display_name ?? `#${props.modelValue}`;
});

/** กรองบทบาทฝั่ง client — backend ยังไม่มี filter roles (จะเพิ่มเมื่อมีผู้ใช้ถาม) */
const visiblePeople = computed(() => {
  if (props.roles.length === 0) return people.value;
  return people.value.filter((p) => p.roles.some((r) => props.roles.includes(r)));
});

const fetchPeople = async () => {
  isLoading.value = true;
  try {
    people.value = await FinanceService.getPeople(roomId, {
      type: props.type,
      active: true,
      q: query.value.trim() || undefined,
    });
  } catch {
    // เงียบไว้: ตัวเลือกที่โหลดไม่สำเร็จต้องไม่ทำให้ฟอร์มทั้งใบพัง — ผู้ใช้ยังพิมพ์ค้นหาใหม่ได้
    people.value = [];
  } finally {
    isLoading.value = false;
  }
};

let debounceTimer: ReturnType<typeof setTimeout> | null = null;
const onSearchInput = () => {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    void fetchPeople();
  }, 250);
};

const selectPerson = (person: FinancePerson) => {
  emit('update:modelValue', person.person_id);
  emit('change', person);
  isOpen.value = false;
  query.value = '';
};

const clearSelection = () => {
  emit('update:modelValue', null);
  emit('change', null);
  query.value = '';
};

// เปลี่ยน type จากหน้าลูก → โหลดชุดใหม่
watch(
  () => props.type,
  () => {
    void fetchPeople();
  },
);

// หน้าลูกแก้ทะเบียน (เพิ่ม/ลบ/ซิงก์) → โหลดรายชื่อใหม่
watch(
  () => props.refreshKey,
  () => {
    void fetchPeople();
  },
);

onMounted(() => {
  void fetchPeople();
});

onBeforeUnmount(() => {
  if (debounceTimer) clearTimeout(debounceTimer);
});
</script>

<template>
  <div class="relative">
    <label v-if="label" class="field-label">{{ label }}</label>

    <div v-if="!isOpen" class="flex items-center gap-2">
      <button
        type="button"
        class="field flex min-w-0 flex-1 items-center justify-between gap-2 text-left"
        :disabled="disabled"
        @click="isOpen = true"
      >
        <span class="truncate" :class="selected ? 'text-ink-1' : 'text-ink-3'">
          {{ selectedLabel || placeholder }}
        </span>
        <i class="bi bi-chevron-down shrink-0 text-ink-3" aria-hidden="true"></i>
      </button>
      <button
        v-if="selected && !disabled"
        type="button"
        class="flex h-11 w-11 shrink-0 items-center justify-center rounded-control text-ink-3 transition-colors hover:bg-canvas hover:text-danger-600"
        aria-label="ล้างผู้ที่เลือก"
        @click="clearSelection"
      >
        <i class="bi bi-x-lg" aria-hidden="true"></i>
      </button>
    </div>

    <div v-else class="rounded-control border border-line bg-surface shadow-sm">
      <div class="border-b border-line p-2">
        <input
          v-model="query"
          type="search"
          class="field"
          :placeholder="placeholder"
          autofocus
          @input="onSearchInput"
          @keydown.esc="isOpen = false"
        />
      </div>

      <div class="max-h-64 overflow-y-auto p-1">
        <p v-if="isLoading" class="px-3 py-2 text-sm text-ink-3">กำลังโหลด…</p>
        <p v-else-if="visiblePeople.length === 0" class="px-3 py-2 text-sm text-ink-3">
          ไม่พบผู้เกี่ยวข้อง — เพิ่มได้ที่หน้า “ตั้งค่าการเงิน”
        </p>
        <button
          v-for="person in visiblePeople"
          :key="person.person_id"
          type="button"
          class="flex w-full items-center justify-between gap-2 rounded-control px-3 py-2 text-left transition-colors hover:bg-canvas"
          @click="selectPerson(person)"
        >
          <span class="min-w-0">
            <span class="block truncate text-sm font-bold text-ink-1">
              {{ person.display_name }}
            </span>
            <span v-if="person.phone" class="num block text-xs text-ink-3">
              {{ person.phone }}
            </span>
          </span>
          <span class="flex shrink-0 flex-wrap justify-end gap-1">
            <span
              v-for="role in person.roles"
              :key="role"
              class="chip bg-canvas text-ink-2"
            >
              {{ ROLE_LABELS[role] }}
            </span>
          </span>
        </button>
      </div>

      <div class="border-t border-line p-2 text-right">
        <button type="button" class="btn-ghost-ui" @click="isOpen = false">
          ปิด
        </button>
      </div>
    </div>
  </div>
</template>
