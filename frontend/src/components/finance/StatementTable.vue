<script setup lang="ts">
/**
 * StatementTable — ตารางงบการเงิน (ใช้ร่วมกันทั้ง 3 งบใน F1 และงบประมาณใน F2)
 *
 * รับ `columns` + `rows` แบบ data-driven เพื่อให้ใบเดียวรองรับทั้ง
 *   - งบทดลอง   → code | name | debit | credit | amount (5 คอลัมน์)
 *   - งบกำไรขาดทุน / งบดุล → name | amount
 *
 * ใช้ `.data-table` บน `lg:` และ **การ์ดแนวตั้งบนมือถือ** ตาม DESIGN.md §5 (กฎเหล็ก)
 * แถวหัวกลุ่มและแถวรวมยอดเป็น "แถว" ในชนิดเดียวกัน ไม่ต้องแยก component
 */
import { computed } from 'vue';
import type { StatementColumn, StatementColumnKey, StatementRow } from '@/types/finance';

const props = withDefaults(
  defineProps<{
    rows: StatementRow[];
    columns: StatementColumn[];
    /** ข้อความเมื่อไม่มีแถวข้อมูลเลย */
    emptyText?: string;
  }>(),
  { emptyText: 'ยังไม่มีข้อมูลในช่วงเวลานี้' },
);

const hasRows = computed(() => props.rows.length > 0);

const money = (value: number): string =>
  `฿${Math.abs(value).toLocaleString('th-TH', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const cellText = (row: StatementRow, key: StatementColumnKey): string => {
  const raw = row[key];
  if (raw === null || raw === undefined || raw === '') return '—';
  if (key === 'code' || key === 'name') return String(raw);
  return money(Number(raw));
};

const isNegative = (row: StatementRow, key: StatementColumnKey): boolean => {
  if (key !== 'amount' && key !== 'debit' && key !== 'credit') return false;
  const raw = row[key];
  return typeof raw === 'number' && raw < 0;
};
</script>

<template>
  <div v-if="!hasRows" class="px-4 py-9 text-center text-sm text-stone-500 sm:px-6">
    {{ emptyText }}
  </div>

  <template v-else>
    <!-- 🖥️ Desktop: ตารางเต็ม -->
    <div class="hidden overflow-x-auto lg:block">
      <table class="data-table">
        <thead>
          <tr>
            <th
              v-for="col in columns"
              :key="col.key"
              :class="col.numeric ? 'text-right' : 'text-left'"
            >
              {{ col.label }}
            </th>
          </tr>
        </thead>
        <tbody>
          <template v-for="(row, index) in rows" :key="`${row.group ?? row.code ?? row.name}-${index}`">
            <!-- แถวหัวกลุ่ม (เช่น "สินทรัพย์") -->
            <tr v-if="row.group" class="bg-stone-50">
              <td
                :colspan="columns.length"
                class="font-display text-sm font-bold text-stone-700"
              >
                {{ row.group }}
              </td>
            </tr>
            <tr v-else :class="row.isTotal ? 'border-t-2 border-stone-300' : ''">
              <td
                v-for="col in columns"
                :key="col.key"
                :class="[
                  col.numeric ? 'num text-right whitespace-nowrap' : '',
                  col.key === 'code' ? 'num w-24 text-stone-400' : '',
                  row.isTotal ? 'font-bold text-stone-900' : '',
                  !row.isTotal && col.key === 'name' ? 'text-stone-700' : '',
                ]"
              >
                <span
                  :class="
                    isNegative(row, col.key) ? 'font-bold text-red-600' : row.isTotal ? 'text-stone-900' : ''
                  "
                >
                  {{ isNegative(row, col.key) ? '−' : '' }}{{ cellText(row, col.key) }}
                </span>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <!-- 📱 มือถือ: การ์ดเรียงแนวตั้ง (ตารางกว้างเกินจอมือถือเสมอ) -->
    <div class="space-y-2.5 p-4 pt-0 lg:hidden">
      <template v-for="(row, index) in rows" :key="`m-${row.group ?? row.code ?? row.name}-${index}`">
        <p
          v-if="row.group"
          class="font-display pt-2 text-sm font-bold text-stone-500"
        >
          {{ row.group }}
        </p>
        <div
          v-else
          class="page-card p-3.5"
          :class="row.isTotal ? 'border-s-4 border-s-brand-700' : ''"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <p
                class="truncate font-bold"
                :class="row.isTotal ? 'text-stone-900' : 'text-stone-700'"
              >
                {{ row.name || '—' }}
              </p>
              <p v-if="row.code" class="num mt-0.5 text-xs text-stone-400">รหัส {{ row.code }}</p>
            </div>

            <div class="shrink-0 text-right">
              <p
                v-for="col in columns.filter((c) => c.numeric)"
                :key="col.key"
                class="num text-sm font-bold whitespace-nowrap"
                :class="isNegative(row, col.key) ? 'text-red-600' : 'text-stone-900'"
              >
                <span v-if="columns.filter((c) => c.numeric).length > 1" class="me-1 text-[11px] font-medium text-stone-400">
                  {{ col.label }}
                </span>
                {{ isNegative(row, col.key) ? '−' : '' }}{{ cellText(row, col.key) }}
              </p>
            </div>
          </div>
        </div>
      </template>
    </div>
  </template>
</template>
