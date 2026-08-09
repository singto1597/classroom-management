<script setup lang="ts">
import { ref, onMounted, computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth'; 
import { FinanceService } from '@/services/finance';
import type { CollectionStatus, Account, StudentPaymentDetail } from '@/types/finance';
import Swal from 'sweetalert2';

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore(); 

const currentServerId = authStore.currentRoomId!;
const currentUserName = authStore.currentUserName!;
const isAdmin = computed(() => authStore.isAdmin);

const collectionId = Number(route.params.id);
const data = ref<CollectionStatus | null>(null);
const accounts = ref<Account[]>([]);
const isLoading = ref(true);

// ✨ State สำหรับโหมดแก้ไข
const isEditMode = ref(false);

const fetchDetail = async () => {
  isLoading.value = true;
  try {
    const [detailRes, accountsRes] = await Promise.all([
      FinanceService.getCollectionStatus(currentServerId, collectionId),
      FinanceService.getAccounts(currentServerId)
    ]);
    data.value = detailRes;
    accounts.value = accountsRes;
  } catch (error: any) {
    Swal.fire('เกิดข้อผิดพลาด', 'ไม่สามารถโหลดรายละเอียดแคมเปญได้', 'error');
  } finally {
    isLoading.value = false;
  }
};

const progress = computed(() => {
  if (!data.value) return 0;
  const { total, paid } = data.value.summary;
  return total > 0 ? Math.round((paid / total) * 100) : 0;
});

const handlePay = async (student: StudentPaymentDetail) => {
  if (!isAdmin.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะแอดมินเท่านั้นที่สามารถรับเงินได้', 'error');
  }

  const remaining = student.total_amount - student.paid_amount;
  
  const { value: formValues } = await Swal.fire({
    title: `รับเงิน: ${student.first_name}`,
    html:
      '<div class="mb-3 text-left">' +
      '<label class="block text-xs font-bold text-gray-400 mb-1 uppercase">รับเงินเข้าบัญชีห้อง</label>' +
      `<select id="swal-acc" class="swal2-input w-full">
        ${accounts.value.map(acc => `<option value="${acc.id}">${acc.account_name}</option>`).join('')}
      </select>` +
      '</div>' +
      '<div class="mb-3 text-left">' +
      '<label class="block text-xs font-bold text-gray-400 mb-1 uppercase">จำนวนเงินที่จ่าย (฿)</label>' +
      `<input id="swal-amt" type="number" class="swal2-input w-full" value="${remaining}" step="0.01">` +
      '</div>' +
      '<div class="text-left">' +
      '<label class="block text-xs font-bold text-gray-400 mb-1 uppercase">URL รูปสลิป (ถ้ามี)</label>' +
      '<input id="swal-slip" type="url" class="swal2-input w-full" placeholder="https://...">' +
      '</div>',
    focusConfirm: false,
    showCancelButton: true,
    confirmButtonText: '✅ ยืนยันการรับเงิน',
    cancelButtonText: 'ยกเลิก',
    preConfirm: () => {
      const accId = (document.getElementById('swal-acc') as HTMLSelectElement).value;
      const amount = (document.getElementById('swal-amt') as HTMLInputElement).value;
      const slip = (document.getElementById('swal-slip') as HTMLInputElement).value;
      if (!accId || !amount) {
        Swal.showValidationMessage('กรุณากรอกข้อมูลให้ครบถ้วน');
        return false;
      }
      return { paid_to_account_id: Number(accId), paid_amount: parseFloat(amount), slip_image_url: slip };
    }
  });

  if (formValues) {
    try {
      await FinanceService.confirmPayment(currentServerId, student.payment_id, { ...formValues, user_name: currentUserName });
      Swal.fire({ icon: 'success', title: 'รับเงินสำเร็จ!', timer: 1500, showConfirmButton: false });
      fetchDetail();
    } catch (error: any) {
      Swal.fire('เกิดข้อผิดพลาด', error.message, 'error');
    }
  }
};

// ✨ ฟังก์ชันใหม่: ลบรายชื่อคนออกจากแคมเปญ
const handleRemoveStudent = async (student: StudentPaymentDetail) => {
  if (student.paid_amount > 0) {
    return Swal.fire('ลบไม่ได้', 'มีการชำระเงินเข้ามาแล้ว ถ้ายกเลิกต้องไป Revert รายการแทน', 'warning');
  }

  const result = await Swal.fire({
    title: 'ยืนยันการลบ?',
    html: `คุณต้องการลบรายชื่อ <b>${student.first_name}</b> ออกจากการเก็บเงินนี้ใช่หรือไม่?`,
    icon: 'warning',
    showCancelButton: true,
    confirmButtonColor: '#ef4444',
    confirmButtonText: 'ลบรายชื่อออก',
    cancelButtonText: 'ยกเลิก'
  });

  if (result.isConfirmed) {
    try {
      await FinanceService.removeStudentFromCollection(currentServerId, collectionId, student.student_id, currentUserName);
      Swal.fire({ icon: 'success', title: 'ลบเรียบร้อย', timer: 1500, showConfirmButton: false });
      fetchDetail();
    } catch (error: any) {
      Swal.fire('เกิดข้อผิดพลาด', error.message, 'error');
    }
  }
};

const formatNumber = (num: number) => {
  return new Intl.NumberFormat('th-TH', { minimumFractionDigits: 2 }).format(num);
};

const formatDate = (dateStr: string | null) => {
  if (!dateStr) return '-';
  const date = new Date(dateStr);
  return date.toLocaleString('th-TH', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Asia/Bangkok'
  }) + ' น.';
};

onMounted(() => {
  fetchDetail();
});
</script>

<template>
  <div class="p-4 md:p-8">
    <div v-if="data" class="bg-white rounded-3xl border border-gray-100 shadow-sm p-4 sm:p-5 mb-5">
      <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
        <div class="flex items-center gap-3 min-w-0">
          <RouterLink
            to="/finance/collections"
            class="w-10 h-10 bg-gray-100 hover:bg-gray-200 text-gray-600 rounded-xl transition shadow-sm group flex items-center justify-center shrink-0"
            title="กลับหน้าโครงการ"
          >
            <i class="bi bi-arrow-left text-lg"></i>
          </RouterLink>
          <h1 class="text-lg md:text-xl font-extrabold text-gray-800 truncate">
            รายละเอียดโปรเจกต์ #{{ data.collection_id }}
          </h1>
        </div>

        <button
          v-if="isAdmin"
          @click="isEditMode = !isEditMode"
          :class="[
            'px-4 py-2 rounded-xl font-bold text-sm shadow-sm transition-all flex items-center gap-2 shrink-0',
            isEditMode ? 'bg-amber-100 text-amber-700 border border-amber-300' : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
          ]"
        >
          <i class="bi bi-pencil-square"></i>
          {{ isEditMode ? 'ปิดโหมดแก้ไข' : 'โหมดจัดการรายชื่อ' }}
        </button>
      </div>

      <div class="space-y-2">
        <div class="flex justify-between text-sm font-bold">
          <span class="text-gray-400">ความคืบหน้า (จ่ายแล้ว {{ data.summary.paid }} จาก {{ data.summary.total }} คน)</span>
          <span class="text-emerald-600">{{ progress }}%</span>
        </div>
        <div class="w-full bg-gray-100 rounded-full h-3.5 overflow-hidden border border-gray-50">
          <div
            class="bg-emerald-500 h-full transition-all duration-1000 shadow-sm"
            :style="{ width: `${progress}%` }"
          ></div>
        </div>
      </div>
    </div>

    <div v-if="isLoading" class="flex flex-col items-center justify-center py-20">
      <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
    </div>

    <div v-else-if="data" class="bg-white rounded-3xl border border-gray-100 shadow-sm overflow-hidden relative">
      <div v-if="isEditMode" class="absolute top-0 left-0 w-full h-1 bg-amber-400 z-10"></div>

      <!-- Empty state -->
      <div v-if="data.students.length === 0" class="px-6 py-10 text-center text-gray-400 font-bold">
        ไม่มีรายชื่อนักเรียนในแคมเปญนี้
      </div>

      <template v-else>
        <!-- ============ MOBILE CARDS ============ -->
        <div class="md:hidden divide-y divide-gray-50">
          <div v-for="s in data.students" :key="s.payment_id" class="p-4">
            <div class="flex items-start justify-between gap-3 mb-2.5">
              <div class="flex items-center gap-3 min-w-0">
                <div class="w-9 h-9 rounded-xl bg-gray-50 text-gray-500 border border-gray-100 flex items-center justify-center font-black text-xs shrink-0">#{{ s.student_no }}</div>
                <div class="min-w-0">
                  <p class="font-bold text-gray-800 text-sm truncate">{{ s.first_name }} {{ s.last_name }}</p>
                  <p v-if="s.nickname" class="text-xs text-gray-400 italic truncate">({{ s.nickname }})</p>
                </div>
              </div>

              <!-- สถานะ -->
              <div v-if="s.status === 'paid'" class="flex flex-col items-end shrink-0">
                <span class="inline-flex items-center gap-1 bg-emerald-50 text-emerald-600 px-2.5 py-1 rounded-full text-[10px] font-bold border border-emerald-100">
                  <i class="bi bi-check-circle-fill"></i> จ่ายครบแล้ว
                </span>
                <small v-if="s.paid_at" class="text-[9px] text-gray-400 mt-1 font-bold"><i class="bi bi-clock"></i> {{ formatDate(s.paid_at) }}</small>
              </div>
              <div v-else-if="s.paid_amount > 0" class="flex flex-col items-end shrink-0">
                <span class="inline-flex items-center gap-1 bg-amber-50 text-amber-600 px-2.5 py-1 rounded-full text-[10px] font-bold border border-amber-100">
                  <i class="bi bi-hourglass-split"></i> ฿{{ formatNumber(s.paid_amount) }}
                </span>
                <small class="text-rose-500 font-bold text-[9px] mt-1">ค้างอีก ฿{{ formatNumber(s.total_amount - s.paid_amount) }}</small>
              </div>
              <span v-else class="inline-flex items-center gap-1 bg-rose-50 text-rose-600 px-2.5 py-1 rounded-full text-[10px] font-bold border border-rose-100 shrink-0">
                <i class="bi bi-clock-fill"></i> ค้าง ฿{{ formatNumber(s.total_amount) }}
              </span>
            </div>

            <!-- Actions -->
            <div class="flex justify-end">
              <template v-if="!isEditMode">
                <button
                  v-if="s.status === 'pending' && isAdmin"
                  @click="handlePay(s)"
                  class="bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-5 rounded-xl shadow-sm transition text-sm flex items-center gap-1.5"
                >
                  <i class="bi bi-wallet2"></i> รับเงิน
                </button>
                <span v-else-if="s.status === 'pending' && !isAdmin" class="text-[11px] text-gray-400 italic bg-gray-50 px-3 py-1.5 rounded-lg border border-gray-100 inline-block">
                  รอแอดมินรับยอด
                </span>
              </template>
              <template v-else>
                <button
                  v-if="s.paid_amount === 0"
                  @click="handleRemoveStudent(s)"
                  class="bg-white border border-rose-200 text-rose-500 hover:bg-rose-50 font-bold py-2 px-4 rounded-xl transition text-sm flex items-center gap-1.5"
                  title="ลบออกจากแคมเปญ"
                >
                  <i class="bi bi-trash3-fill"></i> ลบออก
                </button>
                <span v-else class="text-[10px] text-gray-300 italic bg-gray-50 px-2.5 py-1.5 rounded-lg border border-gray-100 inline-flex items-center gap-1" title="ลบไม่ได้ เพราะมีการจ่ายเงินแล้ว">
                  <i class="bi bi-lock-fill"></i> ลบไม่ได้
                </span>
              </template>
            </div>
          </div>
        </div>

        <!-- ============ DESKTOP TABLE ============ -->
        <div class="hidden md:block overflow-x-auto">
          <table class="w-full text-left border-collapse">
            <thead>
              <tr class="bg-gray-50 text-gray-400 text-xs uppercase font-bold border-b border-gray-100">
                <th class="px-6 py-4 w-24">เลขที่</th>
                <th class="px-6 py-4">ชื่อ-สกุล</th>
                <th class="px-6 py-4">สถานะ</th>
                <th class="px-6 py-4 text-right">จัดการ</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-50">
              <tr v-for="s in data.students" :key="s.payment_id" class="hover:bg-gray-50/50 transition-colors group">
                <td class="px-6 py-4 font-bold text-gray-400">#{{ s.student_no }}</td>
                <td class="px-6 py-4">
                  <div class="font-bold text-gray-800">{{ s.first_name }} {{ s.last_name }}</div>
                  <div v-if="s.nickname" class="text-xs text-gray-400 italic">({{ s.nickname }})</div>
                </td>
                <td class="px-6 py-4">
                  <div v-if="s.status === 'paid'" class="flex flex-col">
                    <span class="inline-flex items-center gap-1.5 bg-emerald-50 text-emerald-600 px-3 py-1 rounded-full text-[10px] font-bold w-fit border border-emerald-100">
                      <i class="bi bi-check-circle-fill"></i> จ่ายครบแล้ว
                    </span>
                    <small v-if="s.paid_at" class="text-[9px] text-gray-400 mt-1 font-bold">
                      <i class="bi bi-clock"></i> {{ formatDate(s.paid_at) }}
                    </small>
                  </div>
                  <div v-else-if="s.paid_amount > 0" class="flex flex-col">
                    <span class="inline-flex items-center gap-1.5 bg-amber-50 text-amber-600 px-3 py-1 rounded-full text-[10px] font-bold w-fit border border-amber-100">
                      <i class="bi bi-hourglass-split"></i> ทยอยจ่ายแล้ว ฿{{ formatNumber(s.paid_amount) }}
                    </span>
                    <small class="text-rose-500 font-bold text-[9px] mt-1">(ค้างอีก ฿{{ formatNumber(s.total_amount - s.paid_amount) }})</small>
                  </div>
                  <span v-else class="inline-flex items-center gap-1.5 bg-rose-50 text-rose-600 px-3 py-1 rounded-full text-[10px] font-bold w-fit border border-rose-100">
                    <i class="bi bi-clock-fill"></i> ค้างจ่าย (฿{{ formatNumber(s.total_amount) }})
                  </span>
                </td>
                <td class="px-6 py-4 text-right">
                  <div class="flex justify-end gap-2">
                    <template v-if="!isEditMode">
                      <button
                        v-if="s.status === 'pending' && isAdmin"
                        @click="handlePay(s)"
                        class="bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded-xl shadow-sm transition text-xs flex items-center gap-1"
                      >
                        <i class="bi bi-wallet2"></i> รับเงิน
                      </button>
                      <span v-else-if="s.status === 'pending' && !isAdmin" class="text-[10px] text-gray-400 italic bg-gray-50 px-3 py-1.5 rounded-lg border border-gray-100 inline-block">
                        รอแอดมินรับยอด
                      </span>
                    </template>
                    <template v-else>
                      <button
                        v-if="s.paid_amount === 0"
                        @click="handleRemoveStudent(s)"
                        class="bg-white border border-rose-200 text-rose-500 hover:bg-rose-50 hover:text-rose-600 font-bold w-9 h-9 rounded-lg shadow-sm transition text-xs flex justify-center items-center"
                        title="ลบออกจากแคมเปญ"
                      >
                        <i class="bi bi-trash3-fill"></i>
                      </button>
                      <span v-else class="text-[10px] text-gray-300 italic bg-gray-50 px-2 py-1.5 rounded-lg border border-gray-100 flex items-center" title="ลบไม่ได้ เพราะมีการจ่ายเงินแล้ว">
                        <i class="bi bi-lock-fill"></i> ลบไม่ได้
                      </span>
                    </template>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.swal2-input {
  border-radius: 1rem !important;
  font-family: 'Sarabun', sans-serif !important;
}
</style>