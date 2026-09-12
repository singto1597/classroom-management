<script setup lang="ts">
import { ref, onMounted, watch, computed } from 'vue';
import { useAuthStore } from '@/stores/auth';
import { FinanceService } from '@/services/finance';
import type { Transaction, TransactionQueryParams } from '@/types/finance';
import Swal from 'sweetalert2';

import PageHeader from '@/components/ui/PageHeader.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';

const authStore = useAuthStore();
const currentServerId = authStore.currentRoomId!;
const currentUserName = authStore.currentUserName!;

// ดึง isAdmin ออกมาเป็น computed เพื่อให้ reactivity ทำงานถูกต้องและเรียกใช้สั้นลง
const isAdmin = computed(() => authStore.isAdmin);

const transactions = ref<Transaction[]>([]);
const totalCount = ref(0);
const isLoading = ref(true);

// สถานะผิดพลาดสำหรับ StateBlock (แสดงผลเท่านั้น ไม่กระทบการเรียก API)
const hasError = ref(false);

const filters = ref({
  type: '',
  start_date: '',
  end_date: '',
  limit: 50,
  offset: 0
});

const currentPage = ref(1);

const fetchTransactions = async () => {
  isLoading.value = true;
  hasError.value = false;
  try {
    // สร้าง query params แบบมี type ชัดเจน (ตัดคีย์ค่าว่างออกก่อนส่งไป API)
    const apiFilters: TransactionQueryParams = {
      limit: filters.value.limit,
      offset: (currentPage.value - 1) * filters.value.limit
    };
    if (filters.value.type === 'income' || filters.value.type === 'expense') {
      apiFilters.type = filters.value.type;
      apiFilters.transaction_type = filters.value.type;
    }
    if (filters.value.start_date) apiFilters.start_date = filters.value.start_date;
    if (filters.value.end_date) apiFilters.end_date = filters.value.end_date;

    const res = await FinanceService.getTransactions(currentServerId, apiFilters);
    transactions.value = res.items;
    totalCount.value = res.total_count;
  } catch (error: unknown) {
    hasError.value = true;
    Swal.fire('เกิดข้อผิดพลาด', error instanceof Error ? error.message : 'โหลดข้อมูลไม่สำเร็จ', 'error');
  } finally {
    isLoading.value = false;
  }
};

const handleRevert = async (transaction: Transaction) => {
  // เพิ่ม Guard ป้องกันเผื่อมีคนเรียกฟังก์ชันนี้ข้าม UI
  if (!isAdmin.value) {
    Swal.fire('ไม่มีสิทธิ์เข้าถึง', 'เฉพาะผู้ดูแลระบบเท่านั้นที่สามารถยกเลิกรายการได้', 'error');
    return;
  }

  const result = await Swal.fire({
    title: 'ต้องการยกเลิก?',
    // ใช้ inline style เพราะ SweetAlert2 ไม่ผ่าน Tailwind JIT
    html: `คุณกำลังจะยกเลิกรายการ:<br><b style="display:block;margin-top:8px;font-size:16px;color:#1c1917">"${transaction.description}"</b><span style="display:block;margin-top:8px;padding:8px 12px;border-radius:10px;border:1px solid #fecaca;background:#fef2f2;color:#b91c1c;font-size:13px;font-weight:600">ยอดเงินจะถูกคืนกลับกระเป๋าเดิม<br>หากเป็นรายการรับเงินจากเพื่อน สถานะบิลจะถูกตีกลับเป็น "ค้างจ่าย" ทันที</span>`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#dc2626',
    cancelButtonColor: '#78716c',
    confirmButtonText: 'ยืนยันการยกเลิก',
    cancelButtonText: 'ปิด'
  });

  if (result.isConfirmed) {
    try {
      await FinanceService.revertTransaction(currentServerId, transaction.id, currentUserName);
      Swal.fire({ icon: 'success', title: 'ยกเลิกรายการสำเร็จ!', timer: 1500, showConfirmButton: false });
      fetchTransactions();
    } catch (error: unknown) {
      Swal.fire('ยกเลิกไม่ได้', error instanceof Error ? error.message : 'ยกเลิกรายการไม่สำเร็จ', 'error');
    }
  }
};

// 🕐 แสดงเวลาเป็นภาษาไทยและ Timezone Asia/Bangkok (กฎของโปรเจกต์)
const formatDate = (dateStr: string) => {
  const date = new Date(dateStr);
  const datePart = date.toLocaleDateString('th-TH', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'Asia/Bangkok'
  });
  const timePart = date.toLocaleTimeString('th-TH', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Asia/Bangkok'
  });
  return { datePart, timePart };
};

const formatNumber = (num: number) => {
  return new Intl.NumberFormat('th-TH', { minimumFractionDigits: 2 }).format(num);
};

const totalPages = computed(() => Math.ceil(totalCount.value / filters.value.limit));

onMounted(() => {
  fetchTransactions();
});

watch([currentPage, () => filters.value.limit], () => {
  fetchTransactions();
});

const applyFilters = () => {
  currentPage.value = 1;
  fetchTransactions();
};

const resetFilters = () => {
  filters.value = {
    type: '',
    start_date: '',
    end_date: '',
    limit: 50,
    offset: 0
  };
  currentPage.value = 1;
  fetchTransactions();
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader
      eyebrow="Transaction Ledger"
      title="ประวัติการทำรายการ"
      description="รายการรับ จ่าย และโอนเงินทั้งหมดของห้อง"
    >
      <template #actions>
        <RouterLink to="/finance" class="btn-ghost-ui" title="กลับหน้าภาพรวม">
          <i class="bi bi-arrow-left" aria-hidden="true"></i>
          กลับหน้าภาพรวม
        </RouterLink>
        <RouterLink v-if="isAdmin" to="/finance/transactions/add" class="btn-primary">
          <i class="bi bi-plus-lg" aria-hidden="true"></i>
          บันทึกรายการใหม่
        </RouterLink>
      </template>
    </PageHeader>

    <!-- ตัวกรอง -->
    <div class="page-card p-4 sm:p-5">
      <div class="grid grid-cols-1 items-end gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <label class="field-label" for="filterType">ประเภทรายการ</label>
          <select id="filterType" v-model="filters.type" class="field">
            <option value="">ทั้งหมด</option>
            <option value="income">รายรับ</option>
            <option value="expense">รายจ่าย</option>
          </select>
        </div>
        <div>
          <label class="field-label" for="filterStart">จากวันที่</label>
          <input id="filterStart" v-model="filters.start_date" class="field" type="date" />
        </div>
        <div>
          <label class="field-label" for="filterEnd">ถึงวันที่</label>
          <input id="filterEnd" v-model="filters.end_date" class="field" type="date" />
        </div>
        <div class="flex gap-2">
          <button class="btn-primary flex-1" @click="applyFilters">ค้นหา</button>
          <button class="btn-ghost-ui flex-1" @click="resetFilters">ล้างค่า</button>
        </div>
      </div>
    </div>

    <!-- จำนวนผลลัพธ์ + จำนวนแถวต่อหน้า -->
    <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <p class="flex items-center gap-1.5 text-sm font-bold text-stone-500">
        พบข้อมูลทั้งหมด
        <span class="chip num bg-brand-50 text-brand-700">{{ totalCount }}</span>
        รายการ
      </p>
      <div class="flex shrink-0 items-center gap-2">
        <span class="text-xs font-bold uppercase tracking-wider text-stone-400">แสดง</span>
        <select v-model="filters.limit" class="field w-auto py-1.5" aria-label="จำนวนแถวต่อหน้า">
          <option :value="10">10 แถว</option>
          <option :value="50">50 แถว</option>
          <option :value="100">100 แถว</option>
        </select>
      </div>
    </div>

    <!-- สถานะโหลด / ผิดพลาด / ว่างเปล่า -->
    <SkeletonRows v-if="isLoading" :rows="6" height="h-16" />
    <StateBlock v-else-if="hasError" variant="error" @retry="fetchTransactions" />
    <StateBlock
      v-else-if="!transactions.length"
      variant="empty"
      icon="bi-receipt"
      title="ไม่พบข้อมูลการทำรายการ"
      hint="ลองปรับช่วงวันที่หรือประเภทรายการ แล้วกดค้นหาอีกครั้ง"
    />

    <template v-else>
      <!-- 📱 มือถือ: การ์ด -->
      <div class="space-y-2.5 lg:hidden">
        <div
          v-for="t in transactions"
          :key="t.id"
          class="page-card border-s-4 p-4"
          :class="t.transaction_type === 'income' ? 'border-s-emerald-500' : 'border-s-red-500'"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <p class="break-words font-bold text-stone-900">{{ t.description }}</p>
              <p class="num mt-1 flex items-center gap-1.5 text-[11px] font-medium text-stone-400">
                <i class="bi bi-clock" aria-hidden="true"></i>
                {{ formatDate(t.created_at).datePart }} • {{ formatDate(t.created_at).timePart }} น.
              </p>
            </div>
            <p
              class="num font-display shrink-0 text-base font-bold"
              :class="t.transaction_type === 'income' ? 'text-emerald-600' : 'text-red-600'"
            >
              {{ t.transaction_type === 'income' ? '+' : '-' }}฿{{ formatNumber(t.amount) }}
            </p>
          </div>

          <div class="mt-3 flex items-center justify-between gap-3 border-t border-stone-100 pt-3">
            <div class="flex min-w-0 flex-wrap items-center gap-1.5">
              <span class="chip bg-brand-50 text-brand-700">
                <i class="bi bi-wallet2" aria-hidden="true"></i>
                {{ t.account_name || 'ไม่ระบุ' }}
              </span>
              <span v-if="t.category_name" class="chip bg-stone-100 text-stone-600">
                {{ t.category_name }}
              </span>
            </div>

            <div class="shrink-0">
              <span
                v-if="t.transfer_group_id && t.transaction_type === 'income'"
                class="chip bg-sky-50 text-sky-700"
                title="ยกเลิกได้ที่รายการขาออก"
              >
                <i class="bi bi-link-45deg" aria-hidden="true"></i> โอนเข้า
              </span>
              <button
                v-else-if="isAdmin"
                class="btn-danger px-3 py-2 text-xs"
                aria-label="ยกเลิกรายการ"
                @click="handleRevert(t)"
              >
                <i class="bi bi-arrow-counterclockwise" aria-hidden="true"></i> ยกเลิก
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 🖥️ Desktop: ตาราง -->
      <div class="page-card hidden overflow-hidden lg:block">
        <div class="overflow-x-auto">
          <table class="data-table min-w-[760px]">
            <thead>
              <tr>
                <th class="w-40">วันที่-เวลา</th>
                <th>รายละเอียดรายการ</th>
                <th>กระเป๋าเงิน</th>
                <th class="text-right">จำนวนเงิน</th>
                <th class="w-24 text-center">จัดการ</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in transactions" :key="t.id">
                <td>
                  <div class="num font-bold text-stone-700">{{ formatDate(t.created_at).datePart }}</div>
                  <div class="num mt-0.5 text-xs text-stone-400">
                    {{ formatDate(t.created_at).timePart }} น.
                  </div>
                </td>
                <td>
                  <div class="min-w-0 max-w-[380px] truncate font-bold text-stone-900" :title="t.description">
                    {{ t.description }}
                  </div>
                  <div class="mt-1.5 flex flex-wrap items-center gap-2">
                    <span v-if="t.category_name" class="chip bg-stone-100 text-stone-600">
                      {{ t.category_name }}
                    </span>
                    <span class="flex items-center gap-1 text-[11px] font-medium text-stone-400">
                      <i class="bi bi-person-circle" aria-hidden="true"></i> {{ t.recorded_by }}
                    </span>
                  </div>
                </td>
                <td>
                  <span class="chip bg-brand-50 text-brand-700">
                    <i class="bi bi-wallet2" aria-hidden="true"></i>
                    {{ t.account_name || 'ไม่ระบุ' }}
                  </span>
                </td>
                <td class="text-right">
                  <span
                    class="num font-display font-bold"
                    :class="t.transaction_type === 'income' ? 'text-emerald-600' : 'text-red-600'"
                  >
                    {{ t.transaction_type === 'income' ? '+' : '-' }} ฿{{ formatNumber(t.amount) }}
                  </span>
                </td>
                <td class="text-center">
                  <span
                    v-if="t.transfer_group_id && t.transaction_type === 'income'"
                    class="chip bg-sky-50 text-sky-700"
                    title="ยกเลิกได้ที่รายการขาออก"
                  >
                    <i class="bi bi-link-45deg" aria-hidden="true"></i> โอนเงิน
                  </span>
                  <button
                    v-else-if="isAdmin"
                    class="btn-danger mx-auto h-9 w-9 px-0 py-0"
                    title="ยกเลิกรายการ"
                    aria-label="ยกเลิกรายการ"
                    @click="handleRevert(t)"
                  >
                    <i class="bi bi-arrow-counterclockwise" aria-hidden="true"></i>
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- แบ่งหน้า -->
      <div v-if="totalPages > 1" class="flex justify-center">
        <div class="page-card flex flex-wrap justify-center gap-1 p-1.5">
          <button
            v-for="page in totalPages"
            :key="page"
            class="num h-11 min-w-[44px] rounded-lg px-2 text-sm font-bold transition-colors active:scale-[0.97]"
            :class="currentPage === page ? 'bg-brand-700 text-white' : 'text-stone-500 hover:bg-stone-100'"
            @click="currentPage = page"
          >
            {{ page }}
          </button>
        </div>
      </div>
    </template>
  </div>
</template>
