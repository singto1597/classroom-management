<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useAuthStore } from '@/stores/auth';
import { FinanceService } from '@/services/finance';
import type { Collection, BasicStudent } from '@/types/finance';
import Swal from 'sweetalert2';

const authStore = useAuthStore();
const currentServerId = authStore.currentRoomId!;
const currentUserName = authStore.currentUserName!;

const collections = ref<Collection[]>([]);
const isLoading = ref(true);

// --- 🌟 State สำหรับการสร้างโปรเจกต์ (Modal แบบเขียนเอง) ---
const isCreateModalOpen = ref(false);
const isSubmitting = ref(false);
const formTitle = ref('');
const formAmount = ref<number | ''>('');
const formDueDate = ref('');

// โหมดเลือกว่าจะเก็บเงินใครบ้าง
const selectionMode = ref<'all' | 'custom'>('all');
const studentsList = ref<BasicStudent[]>([]);
const selectedStudentIds = ref<number[]>([]);

const fetchCollections = async () => {
  isLoading.value = true;
  try {
    const res = await FinanceService.getCollections(currentServerId);
    collections.value = res;
  } catch (error: any) {
    Swal.fire('เกิดข้อผิดพลาด', 'โหลดโปรเจกต์เก็บเงินไม่สำเร็จ', 'error');
  } finally {
    isLoading.value = false;
  }
};

// เมื่อกดปุ่ม "สร้างโปรเจกต์ใหม่"
const openCreateModal = async () => {
  // รีเซ็ตฟอร์ม
  formTitle.value = '';
  formAmount.value = '';
  formDueDate.value = '';
  selectionMode.value = 'all';
  selectedStudentIds.value = [];
  
  // โหลดรายชื่อนักเรียนรอไว้เลย
  try {
    studentsList.value = await FinanceService.getActiveStudents(currentServerId);
    // ค่าเริ่มต้นของ Custom mode คือให้เลือกทุกคนไว้ก่อน
    selectedStudentIds.value = studentsList.value.map(s => s.id);
  } catch (err) {
    console.error(err);
  }

  isCreateModalOpen.value = true;
};

// เมื่อเปลี่ยนโหมดเป็น Custom
const handleModeChange = (mode: 'all' | 'custom') => {
  selectionMode.value = mode;
  // ถ้าเปลี่ยนกลับมา Custom ใหม่ ก็เช็คให้เลือกทุกคนเหมือนเดิม
  if (mode === 'custom' && selectedStudentIds.value.length === 0) {
    selectedStudentIds.value = studentsList.value.map(s => s.id);
  }
};

// Submit ฟอร์มสร้าง
const submitCreateCollection = async () => {
  if (!formTitle.value || !formAmount.value || !formDueDate.value) {
    return Swal.fire('ข้อมูลไม่ครบ', 'กรุณากรอกชื่อ, ยอดเรียกเก็บ และวันครบกำหนดให้ครบถ้วน', 'warning');
  }
  
  if (selectionMode.value === 'custom' && selectedStudentIds.value.length === 0) {
    return Swal.fire('ยังไม่ได้เลือกเพื่อน', 'กรุณาเลือกรายชื่ออย่างน้อย 1 คน หรือเปลี่ยนกลับไปใช้โหมดเก็บทุกคน', 'warning');
  }

  isSubmitting.value = true;
  try {
    const payload = {
      title: formTitle.value,
      amount: Number(formAmount.value),
      due_date: formDueDate.value,
      user_name: currentUserName,
      // ถ้า mode custom ให้ส่ง array id ไป, ถ้า all ให้ส่ง undefined (ระบบหลักจะดึงทุกคนเอง)
      student_ids: selectionMode.value === 'custom' ? selectedStudentIds.value : undefined
    };

    await FinanceService.createCollection(currentServerId, payload);
    Swal.fire({ icon: 'success', title: 'สร้างสำเร็จ!', timer: 1500, showConfirmButton: false, customClass: { popup: 'rounded-3xl' } });
    isCreateModalOpen.value = false;
    fetchCollections();
  } catch (error: any) {
    Swal.fire('เกิดข้อผิดพลาด', error.message, 'error');
  } finally {
    isSubmitting.value = false;
  }
};

const handleEditCollection = async (col: Collection) => {
  const { value: formValues } = await Swal.fire({
    title: 'ตั้งค่าโปรเจกต์',
    html: `
      <div class="flex flex-col gap-3 mt-4 text-left">
        <div>
          <label class="text-xs font-bold text-slate-400 ms-2 uppercase tracking-wider">ชื่อรายการ</label>
          <input id="swal-title" class="swal2-input custom-swal-input mt-1" placeholder="ชื่อรายการ" value="${col.title}">
        </div>
        <div>
          <label class="text-xs font-bold text-slate-400 ms-2 uppercase tracking-wider">ยอดเรียกเก็บ (฿)</label>
          <input id="swal-amount" type="number" class="swal2-input custom-swal-input mt-1" placeholder="ยอดเรียกเก็บ" value="${col.amount}">
        </div>
        <div>
          <label class="text-xs font-bold text-slate-400 ms-2 uppercase tracking-wider">ครบกำหนดชำระ</label>
          <input id="swal-date" type="date" class="swal2-input custom-swal-input mt-1" value="${col.due_date}">
        </div>
        <div>
          <label class="text-xs font-bold text-slate-400 ms-2 uppercase tracking-wider">สถานะแคมเปญ</label>
          <select id="swal-status" class="swal2-select custom-swal-input mt-1">
            <option value="active" ${col.status === 'active' ? 'selected' : ''}>🟢 เปิดรับเงิน</option>
            <option value="closed" ${col.status === 'closed' ? 'selected' : ''}>🔴 ปิดแคมเปญ</option>
          </select>
        </div>
      </div>
    `,
    focusConfirm: false,
    showCancelButton: true,
    confirmButtonColor: '#2563eb',
    cancelButtonColor: '#94a3b8',
    confirmButtonText: 'บันทึกการตั้งค่า',
    cancelButtonText: 'ยกเลิก',
    customClass: {
      popup: 'rounded-3xl',
      confirmButton: 'rounded-xl font-bold px-6 py-2.5',
      cancelButton: 'rounded-xl font-bold px-6 py-2.5',
    },
    preConfirm: () => {
      const title = (document.getElementById('swal-title') as HTMLInputElement).value;
      const amount = (document.getElementById('swal-amount') as HTMLInputElement).value;
      const dueDate = (document.getElementById('swal-date') as HTMLInputElement).value;
      const status = (document.getElementById('swal-status') as HTMLSelectElement).value;
      return { title, amount: parseFloat(amount), due_date: dueDate, status };
    }
  });

  if (formValues) {
    try {
      await FinanceService.updateCollection(currentServerId, col.id, { ...formValues, user_name: currentUserName });
      Swal.fire({ icon: 'success', title: 'อัปเดตสำเร็จ!', timer: 1500, showConfirmButton: false, customClass: { popup: 'rounded-3xl' } });
      fetchCollections();
    } catch (error: any) {
      Swal.fire('เกิดข้อผิดพลาด', error.message, 'error');
    }
  }
};

const formatDate = (dateStr: string | null) => {
  if (!dateStr) return '-';
  const date = new Date(dateStr + 'T00:00:00');
  return date.toLocaleDateString('th-TH', {
    day: 'numeric',
    month: 'short',
    year: 'numeric'
  });
};

const formatNumber = (num: number) => {
  return new Intl.NumberFormat('th-TH', { minimumFractionDigits: 2 }).format(num);
};

onMounted(() => {
  fetchCollections();
});
</script>

<template>
  <div class="min-h-screen bg-slate-50/50 p-4 sm:p-6 md:p-8">
    <div class="max-w-7xl mx-auto">
      
      <div class="flex flex-col md:flex-row justify-between items-start md:items-center mb-5 md:mb-7 gap-3 md:gap-5">
        <div class="flex flex-row items-center gap-3 w-full md:w-auto min-w-0">
          <RouterLink
            to="/finance"
            class="bg-white hover:bg-slate-100 text-slate-600 p-2.5 rounded-xl transition-all shadow-sm border border-slate-200 group flex-shrink-0"
            title="กลับหน้าภาพรวม"
          >
            <i class="bi bi-arrow-left text-lg group-hover:-translate-x-1 transition-transform"></i>
          </RouterLink>
          <div class="flex-1 min-w-0">
            <h1 class="text-xl md:text-2xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-blue-600 to-indigo-600 truncate">
              โปรเจกต์เก็บเงิน
            </h1>
            <p class="text-slate-500 mt-0.5 text-sm md:text-base font-medium truncate">จัดการแคมเปญระดมทุนและการเก็บเงินเพื่อนในห้อง</p>
          </div>
        </div>

        <button
          v-if="authStore.isAdmin"
          @click="openCreateModal"
          class="w-full md:w-auto bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-700 hover:to-indigo-700 text-white font-bold py-2.5 px-5 rounded-xl shadow-lg shadow-blue-600/25 transition-all flex items-center justify-center gap-2 transform hover:scale-[1.02]"
        >
          <i class="bi bi-plus-circle text-lg"></i> สร้างโปรเจกต์ใหม่
        </button>
      </div>

      <div v-if="isLoading" class="flex flex-col items-center justify-center py-24 bg-white rounded-3xl border border-slate-100 shadow-sm">
        <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mb-4"></div>
        <span class="text-slate-400 font-medium">กำลังโหลดข้อมูลโปรเจกต์...</span>
      </div>

      <div v-else-if="collections.length === 0" class="flex flex-col items-center justify-center py-24 bg-white rounded-3xl border border-dashed border-slate-300 shadow-sm px-4 text-center">
        <div class="w-20 h-20 bg-slate-50 rounded-full flex items-center justify-center mb-5 shadow-inner">
          <i class="bi bi-folder2-open text-4xl text-slate-300"></i>
        </div>
        <h3 class="text-xl font-extrabold text-slate-700 mb-1">ยังไม่มีโปรเจกต์เก็บเงินในขณะนี้</h3>
        <p class="text-slate-500 text-sm">กดปุ่ม "สร้างโปรเจกต์ใหม่" เพื่อเริ่มต้นเรียกเก็บเงินจากเพื่อนๆ ได้เลย</p>
      </div>

      <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5 md:gap-6">
        <div 
          v-for="col in collections" 
          :key="col.id"
          :class="[
            'bg-white rounded-3xl shadow-[0_8px_30px_rgb(0,0,0,0.04)] p-6 md:p-7 flex flex-col justify-between transition-all duration-300 group hover:-translate-y-1 hover:shadow-xl relative overflow-hidden',
            col.status === 'closed' ? 'opacity-85 grayscale-[0.2] border border-slate-200' : 'border border-slate-100'
          ]"
        >
          <div class="absolute top-0 left-0 w-full h-1.5" :class="col.status === 'active' ? 'bg-gradient-to-r from-blue-500 to-indigo-500' : 'bg-slate-300'"></div>

          <div>
            <div class="flex justify-between items-start mb-5">
              <div class="flex items-center gap-2">
                <span 
                  :class="[
                    'px-3.5 py-1.5 rounded-full text-[10px] font-extrabold uppercase tracking-widest border',
                    col.status === 'active' ? 'bg-emerald-50 text-emerald-600 border-emerald-100' : 'bg-slate-50 text-slate-500 border-slate-200'
                  ]"
                >
                  {{ col.status === 'active' ? 'เปิดรับเงิน' : 'ปิดแล้ว' }}
                </span>
              </div>
              <button 
                v-if="authStore.isAdmin"
                @click="handleEditCollection(col)"
                class="w-9 h-9 flex items-center justify-center text-slate-400 bg-slate-50 hover:bg-slate-100 hover:text-slate-700 rounded-xl transition-colors"
                title="ตั้งค่า"
              >
                <i class="bi bi-gear-fill"></i>
              </button>
            </div>

            <h3 class="text-xl md:text-2xl font-extrabold text-slate-800 mb-2 leading-tight" :title="col.title">{{ col.title }}</h3>
            
            <div class="flex items-center gap-2 mb-6 text-xs font-bold text-slate-400 bg-slate-50 w-fit px-3 py-1.5 rounded-lg border border-slate-100">
              <i class="bi bi-calendar-event text-blue-500"></i> ครบกำหนด: <span class="text-slate-600">{{ formatDate(col.due_date) }}</span>
            </div>

            <div class="flex items-baseline gap-1 mb-8">
              <span :class="['text-3xl font-black tracking-tight', col.status === 'active' ? 'text-blue-600' : 'text-slate-600']">
                ฿{{ formatNumber(col.amount) }}
              </span>
              <span class="text-slate-400 text-sm font-bold">/ คน</span>
            </div>
          </div>

          <RouterLink 
            :to="`/finance/collections/${col.id}`"
            class="w-full bg-slate-800 hover:bg-slate-900 text-white text-center font-bold py-3.5 rounded-2xl shadow-md transition-all flex items-center justify-center gap-2 group-hover:shadow-slate-800/20"
          >
            ดูรายละเอียด <i class="bi bi-arrow-right transition-transform group-hover:translate-x-1"></i>
          </RouterLink>
        </div>
      </div>
    </div>

    <div v-if="isCreateModalOpen" class="fixed inset-0 z-[70] flex items-end md:items-center justify-center p-0 md:p-4 bg-slate-900/40 backdrop-blur-sm transition-opacity">
      <div class="bg-white w-full max-w-lg rounded-t-3xl md:rounded-[2rem] shadow-2xl flex flex-col max-h-[90dvh] animate-in md:zoom-in-95 duration-200">
        
        <div class="px-6 py-5 border-b border-slate-100 flex justify-between items-center bg-white rounded-t-[2rem]">
          <div>
            <h3 class="text-xl font-extrabold text-slate-800">สร้างโปรเจกต์เก็บเงิน</h3>
            <p class="text-xs font-bold text-slate-400 mt-0.5">ตั้งค่าบิลเรียกเก็บเงินเข้ากองกลาง</p>
          </div>
          <button @click="isCreateModalOpen = false" class="w-10 h-10 bg-slate-50 hover:bg-slate-100 rounded-full flex items-center justify-center text-slate-500 transition-colors">
            <i class="bi bi-x-lg"></i>
          </button>
        </div>

        <div class="p-6 overflow-y-auto flex-1 space-y-4 bg-slate-50/30">
          
          <div class="space-y-4">
            <div>
              <label class="block text-xs font-bold text-slate-500 mb-1.5 uppercase tracking-wider ms-1">ชื่อรายการ</label>
              <input v-model="formTitle" placeholder="เช่น ค่าชีทฟิสิกส์, ค่าปรับเวร" class="w-full bg-white border border-slate-200 rounded-xl py-3 px-4 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all font-medium text-slate-700 shadow-sm">
            </div>

            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label class="block text-xs font-bold text-slate-500 mb-1.5 uppercase tracking-wider ms-1">ยอดเรียกเก็บ (฿)</label>
                <div class="relative">
                  <div class="absolute inset-y-0 left-0 flex items-center pl-4 pointer-events-none">
                    <span class="text-slate-400 font-bold">฿</span>
                  </div>
                  <input v-model="formAmount" type="number" placeholder="0.00" class="w-full bg-white border border-slate-200 rounded-xl py-3 pl-9 pr-4 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all font-bold text-slate-700 shadow-sm text-right">
                </div>
              </div>
              <div>
                <label class="block text-xs font-bold text-slate-500 mb-1.5 uppercase tracking-wider ms-1">ครบกำหนด</label>
                <input v-model="formDueDate" type="date" class="w-full bg-white border border-slate-200 rounded-xl py-3 px-4 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 transition-all font-medium text-slate-700 shadow-sm">
              </div>
            </div>
          </div>

          <hr class="border-slate-100 my-2">

          <div>
            <label class="block text-xs font-bold text-slate-500 mb-2 uppercase tracking-wider ms-1">ต้องการเรียกเก็บใครบ้าง?</label>
            <div class="grid grid-cols-2 gap-3 mb-4">
              <button 
                @click="handleModeChange('all')"
                :class="[
                  'py-2.5 px-3 rounded-xl border font-bold text-sm transition-all flex flex-col items-center justify-center gap-1',
                  selectionMode === 'all' ? 'bg-blue-50 border-blue-500 text-blue-700 shadow-sm' : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300'
                ]"
              >
                <i class="bi bi-people-fill text-lg"></i> เก็บทุกคน (Active)
              </button>
              <button 
                @click="handleModeChange('custom')"
                :class="[
                  'py-2.5 px-3 rounded-xl border font-bold text-sm transition-all flex flex-col items-center justify-center gap-1',
                  selectionMode === 'custom' ? 'bg-purple-50 border-purple-500 text-purple-700 shadow-sm' : 'bg-white border-slate-200 text-slate-500 hover:border-slate-300'
                ]"
              >
                <i class="bi bi-person-check-fill text-lg"></i> ระบุตัวบุคคล
              </button>
            </div>

            <div v-if="selectionMode === 'custom'" class="animate-in fade-in slide-in-from-top-2 duration-300">
              <div class="flex justify-between items-center mb-2 px-1">
                <span class="text-xs font-bold text-slate-500">เลือกแล้ว {{ selectedStudentIds.length }} คน</span>
                <div class="flex gap-2">
                  <button @click="selectedStudentIds = studentsList.map(s => s.id)" class="text-xs font-bold text-blue-600 hover:underline">เลือกทั้งหมด</button>
                  <span class="text-slate-300">|</span>
                  <button @click="selectedStudentIds = []" class="text-xs font-bold text-slate-500 hover:underline">ล้างทั้งหมด</button>
                </div>
              </div>

              <div class="bg-white border border-slate-200 rounded-2xl max-h-48 overflow-y-auto divide-y divide-slate-100 shadow-inner">
                <label 
                  v-for="s in studentsList" 
                  :key="s.id"
                  class="flex items-center justify-between p-3 cursor-pointer hover:bg-slate-50 transition-colors"
                >
                  <div class="flex items-center gap-3">
                    <div class="text-slate-400 font-black text-xs w-6 text-right">#{{ s.student_no }}</div>
                    <div class="font-bold text-slate-700 text-sm">
                      {{ s.first_name }} {{ s.last_name }} <span v-if="s.nickname" class="text-slate-400 font-normal">({{ s.nickname }})</span>
                    </div>
                  </div>
                  
                  <div :class="[
                    'w-5 h-5 rounded border flex items-center justify-center transition-colors',
                    selectedStudentIds.includes(s.id) ? 'bg-blue-500 border-blue-500' : 'bg-white border-slate-300'
                  ]">
                    <i v-if="selectedStudentIds.includes(s.id)" class="bi bi-check-lg text-white text-xs font-black"></i>
                  </div>
                  <input type="checkbox" :value="s.id" v-model="selectedStudentIds" class="hidden">
                </label>
              </div>
            </div>
            
            <div v-if="selectionMode === 'all'" class="text-[11px] text-blue-600 bg-blue-50 p-3 rounded-xl border border-blue-100 font-bold flex items-center gap-2">
              <i class="bi bi-info-circle-fill"></i> ระบบจะสร้างบิลเรียกเก็บเงินไปยังนักเรียนที่มีสถานะ Active ทุกคน ({{ studentsList.length }} คน) อัตโนมัติ
            </div>

          </div>

        </div>

        <div class="p-4 md:p-6 bg-white border-t border-slate-100 rounded-b-[2rem] flex justify-end gap-3 shrink-0">
          <button 
            @click="isCreateModalOpen = false" 
            class="px-5 py-2.5 rounded-xl text-slate-500 font-bold text-sm bg-slate-100 hover:bg-slate-200 transition-colors"
            :disabled="isSubmitting"
          >
            ยกเลิก
          </button>
          <button 
            @click="submitCreateCollection"
            class="px-6 py-2.5 rounded-xl text-white font-bold text-sm bg-blue-600 hover:bg-blue-700 shadow-md shadow-blue-500/20 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            :disabled="isSubmitting"
          >
            <i v-if="isSubmitting" class="bi bi-arrow-repeat animate-spin"></i>
            {{ isSubmitting ? 'กำลังสร้าง...' : 'สร้างแคมเปญ' }}
          </button>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
/* ซ่อนปุ่มในช่อง Number */
input[type=number]::-webkit-inner-spin-button, 
input[type=number]::-webkit-outer-spin-button { 
  -webkit-appearance: none; 
  margin: 0; 
}
input[type=number] {
  -moz-appearance: textfield;
}

/* Custom Scrollbar สำหรับกล่องเลือกเพื่อน */
.overflow-y-auto::-webkit-scrollbar {
  width: 6px;
}
.overflow-y-auto::-webkit-scrollbar-track {
  background: #f8fafc; 
  border-radius: 4px;
}
.overflow-y-auto::-webkit-scrollbar-thumb {
  background: #cbd5e1; 
  border-radius: 4px;
}
.overflow-y-auto::-webkit-scrollbar-thumb:hover {
  background: #94a3b8; 
}
</style>