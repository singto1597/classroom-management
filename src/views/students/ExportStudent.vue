<script setup lang="ts">
import { ref, computed } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { StudentService } from '@/services/student';
import Swal from 'sweetalert2';
import draggable from 'vuedraggable'; // 📦 vuedraggable สำหรับ Vue 3

const router = useRouter();
const authStore = useAuthStore();
const roomId = computed(() => authStore.currentRoomId!);
const userName = computed(() => authStore.currentUserName || 'Admin');

// --- 💡 1. TypeScript Interfaces ช่วยป้องกันบัคตอน Build ---
interface Field {
  id: string;
  label: string;
}

interface Category {
  id: string;
  name: string;
  icon: string;
  color: string;
  bg: string;
  border: string;
  fields: Field[];
}

interface SelectedColumn {
  id: string;
  label: string;
  catColor: string;
}

// --- 📂 2. Schema ข้อมูล ---
const exportSchema: Category[] = [
  {
    id: 'core', name: 'ข้อมูลส่วนตัวพื้นฐาน', icon: 'bi-person-badge-fill', color: 'text-blue-600', bg: 'bg-blue-50', border: 'border-blue-200',
    fields: [
      { id: 'student_no', label: 'เลขที่' },
      { id: 'student_id', label: 'รหัสนักเรียน' },
      { id: 'prefix', label: 'คำนำหน้า' },
      { id: 'first_name', label: 'ชื่อจริง' },
      { id: 'last_name', label: 'นามสกุล' },
      { id: 'nickname', label: 'ชื่อเล่น' },
      { id: 'birthday', label: 'วันเกิด' }
    ]
  },
  {
    id: 'academic', name: 'วิชาการและหน้าที่', icon: 'bi-journal-bookmark-fill', color: 'text-amber-600', bg: 'bg-amber-50', border: 'border-amber-200',
    fields: [
      { id: 'class_role', label: 'บทบาทในห้อง' },
      { id: 'cleaning_duty', label: 'เวรทำความสะอาด' },
      { id: 'olympic_camp', label: 'สอวน. / ค่าย' },
      { id: 'target_faculty', label: 'คณะเป้าหมาย' },
      { id: 'portfolio', label: 'ผลงาน' }
    ]
  },
  {
    id: 'health', name: 'ข้อมูลสุขภาพ', icon: 'bi-heart-pulse-fill', color: 'text-rose-600', bg: 'bg-rose-50', border: 'border-rose-200',
    fields: [
      { id: 'blood_group', label: 'กรุ๊ปเลือด' },
      { id: 'shirt_size', label: 'ไซส์เสื้อ' },
      { id: 'food_allergy', label: 'แพ้อาหาร' },
      { id: 'congenital_disease', label: 'โรคประจำตัว' }
    ]
  },
  {
    id: 'contact', name: 'การติดต่อ', icon: 'bi-telephone-fill', color: 'text-indigo-600', bg: 'bg-indigo-50', border: 'border-indigo-200',
    fields: [
      { id: 'phone_number', label: 'เบอร์โทรศัพท์' },
      { id: 'phone_number_parent', label: 'เบอร์ผู้ปกครอง' },
      { id: 'phone_number_parent_relation', label: 'ความสัมพันธ์' },
      { id: 'line_id', label: 'LINE ID' },
      { id: 'ig_username', label: 'IG Username' },
      { id: 'email', label: 'อีเมล' }
    ]
  },
  {
    id: 'address', name: 'ที่อยู่', icon: 'bi-house-door-fill', color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200',
    fields: [
      { id: 'address_house_no', label: 'บ้านเลขที่/หมู่/ซอย' },
      { id: 'address_road', label: 'ถนน' },
      { id: 'address_sub_district', label: 'ตำบล/แขวง' },
      { id: 'address_district', label: 'อำเภอ/เขต' },
      { id: 'address_province', label: 'จังหวัด' },
      { id: 'address_post_code', label: 'รหัสไปรษณีย์' }
    ]
  }
];

// --- 🗂️ 3. State ควบคุมลอจิก ---
const selectedColumns = ref<SelectedColumn[]>([]);

const isFieldSelected = (fieldId: string) => !!selectedColumns.value.find(c => c.id === fieldId);

const toggleField = (field: Field, category: Category | { color: string }) => {
  const index = selectedColumns.value.findIndex(c => c.id === field.id);
  if (index > -1) {
    selectedColumns.value.splice(index, 1);
  } else {
    selectedColumns.value.push({ id: field.id, label: field.label, catColor: category.color });
  }
};

const isCategoryAllSelected = (category: Category) => category.fields.every(f => isFieldSelected(f.id));
const isCategoryPartialSelected = (category: Category) => category.fields.some(f => isFieldSelected(f.id)) && !isCategoryAllSelected(category);

const toggleCategory = (category: Category) => {
  if (isCategoryAllSelected(category)) {
    selectedColumns.value = selectedColumns.value.filter(c => !category.fields.find(f => f.id === c.id));
  } else {
    category.fields.forEach(field => {
      if (!isFieldSelected(field.id)) {
        selectedColumns.value.push({ id: field.id, label: field.label, catColor: category.color });
      }
    });
  }
};

const clearAll = () => { selectedColumns.value = []; };

// --- 🚀 4. ฟังก์ชันส่งออก ---
const handleExport = async () => {
  if (selectedColumns.value.length === 0) {
    return Swal.fire({ 
      icon: 'warning', 
      title: 'แจ้งเตือน', 
      text: 'กรุณาเลือกข้อมูลอย่างน้อย 1 คอลัมน์ครับ!',
      confirmButtonColor: '#3b82f6'
    });
  }

  const finalFieldsOrder = selectedColumns.value.map(col => col.id);

  try {
    Swal.fire({ 
      title: 'กำลังคราฟต์ไฟล์ Excel...', 
      text: 'ระบบกำลังจัดเรียงคอลัมน์ให้คุณ', 
      allowOutsideClick: false, 
      didOpen: () => Swal.showLoading() 
    });
    
    // ดึงก้อน Blob ออกมาจาก API
    const blob = await StudentService.exportStudentsExcel(roomId.value, finalFieldsOrder, userName.value);
    
    // เปลี่ยน Blob ให้เป็นลิงก์ดาวน์โหลด
    const url = window.URL.createObjectURL(blob); 
    const link = document.createElement('a');
    link.href = url;
    
    // ตั้งชื่อไฟล์สวยๆ
    const dateStr = new Date().toISOString().split('T')[0];
    link.setAttribute('download', `Custom_Export_${roomId.value}_${dateStr}.xlsx`);
    
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);

    Swal.fire({ 
      icon: 'success', 
      title: 'สำเร็จ!', 
      text: 'ดาวน์โหลดไฟล์ Excel เรียบร้อยแล้ว', 
      timer: 1500, 
      showConfirmButton: false 
    });
  } catch (error) {
    console.error(error);
    Swal.fire({ 
      icon: 'error', 
      title: 'เกิดข้อผิดพลาด', 
      text: 'ไม่สามารถส่งออกข้อมูลได้ กรุณาลองใหม่อีกครั้ง' 
    });
  }
};
</script>

<template>
  <div class="relative overflow-hidden min-h-screen bg-slate-50/50 pb-12">
    <div class="max-w-7xl mx-auto space-y-6 md:space-y-8 relative z-10 p-4 sm:p-6 md:p-8">
      
      <!-- Top Navigation -->
      <div class="flex items-center gap-4 mb-2">
        <button 
          @click="router.back()" 
          class="w-10 h-10 md:w-auto md:px-5 flex items-center justify-center gap-2 bg-white text-slate-600 rounded-full md:rounded-2xl shadow-sm border border-slate-200 hover:bg-slate-50 active:scale-95 transition-all font-bold group"
        >
          <i class="bi bi-arrow-left text-lg group-hover:-translate-x-1 transition-transform"></i>
          <span class="hidden md:inline">กลับหน้ารายชื่อ</span>
        </button>
      </div>

      <!-- Header Section -->
      <div class="flex flex-col lg:flex-row justify-between items-start lg:items-end gap-6 bg-white p-6 md:p-8 rounded-[2rem] border border-slate-200 shadow-[0_8px_30px_rgb(0,0,0,0.04)]">
        <div>
          <h2 class="text-3xl md:text-4xl font-black text-slate-800 tracking-tight flex items-center gap-3">
            <span class="w-12 h-12 bg-emerald-100 text-emerald-600 rounded-2xl flex items-center justify-center text-2xl shadow-inner">🪄</span>
            Custom Export Builder
          </h2>
          <p class="text-slate-500 mt-3 font-medium md:text-lg">เลือกหมวดหมู่ที่ต้องการ และลากวางคอลัมน์ฝั่งขวาเพื่อจัดลำดับไฟล์ Excel ได้อย่างอิสระ</p>
        </div>
        <button 
          @click="handleExport" 
          class="w-full lg:w-auto bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white font-bold px-8 py-4 rounded-2xl shadow-lg shadow-emerald-600/20 active:scale-95 transition-all flex items-center justify-center gap-2 group"
        >
          <i class="bi bi-file-earmark-excel-fill text-xl group-hover:scale-110 transition-transform"></i> 
          สร้างไฟล์ Excel
        </button>
      </div>

      <div class="grid grid-cols-1 xl:grid-cols-12 gap-6 lg:gap-8 items-start">
        
        <!-- ⬅️ ซ้าย: กล่องเลือกข้อมูล (Source) -->
        <div class="xl:col-span-7 space-y-5">
          <div 
            v-for="cat in exportSchema" 
            :key="cat.id" 
            class="bg-white rounded-[1.5rem] border border-slate-200 overflow-hidden shadow-sm transition-all hover:shadow-md hover:border-slate-300"
          >
            <!-- Category Header -->
            <div 
              @click="toggleCategory(cat)"
              class="p-5 cursor-pointer flex items-center justify-between transition-colors group select-none"
              :class="cat.bg"
            >
              <div class="flex items-center gap-4">
                <div class="w-10 h-10 rounded-xl bg-white flex items-center justify-center shadow-sm">
                  <i :class="[cat.icon, cat.color, 'text-xl']"></i>
                </div>
                <h3 class="font-bold text-slate-800 text-lg group-hover:text-black transition-colors">{{ cat.name }}</h3>
              </div>
              
              <!-- Checkbox -->
              <div 
                class="w-6 h-6 rounded-lg border-2 flex items-center justify-center transition-all shadow-sm"
                :class="[
                  isCategoryAllSelected(cat) ? `${cat.bg.replace('50', '500')} border-transparent text-white` : 
                  isCategoryPartialSelected(cat) ? `${cat.bg.replace('50', '300')} border-transparent text-slate-700` : 
                  'border-slate-300 bg-white'
                ]"
              >
                <i v-if="isCategoryAllSelected(cat)" class="bi bi-check-lg font-black text-sm"></i>
                <i v-else-if="isCategoryPartialSelected(cat)" class="bi bi-dash-lg font-black text-sm"></i>
              </div>
            </div>

            <!-- Fields Grid -->
            <div class="p-5 bg-white border-t border-slate-100">
              <div class="flex flex-wrap gap-3">
                <button 
                  v-for="field in cat.fields" 
                  :key="field.id"
                  @click="toggleField(field, cat)"
                  class="px-4 py-2 rounded-xl text-sm font-bold border transition-all active:scale-95 select-none flex items-center"
                  :class="isFieldSelected(field.id) ? `${cat.color} ${cat.bg} border-transparent shadow-sm ring-1 ring-inset ring-${cat.color.replace('text-', '')}/30` : 'border-slate-200 text-slate-500 hover:border-slate-300 hover:bg-slate-50'"
                >
                  <i v-if="isFieldSelected(field.id)" class="bi bi-check2 me-1.5 text-lg leading-none"></i>
                  <i v-else class="bi bi-plus me-1.5 text-lg leading-none opacity-50"></i>
                  {{ field.label }}
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- ➡️ ขวา: จัดลำดับการส่งออก (Sortable Result) -->
        <div class="xl:col-span-5 relative overflow-hidden bg-gradient-to-b from-slate-900 to-slate-800 rounded-[2rem] p-6 lg:p-8 shadow-[0_10px_40px_-10px_rgba(0,0,0,0.5)] xl:sticky xl:top-8 border border-slate-700">
          <!-- Background Texture -->
          <div class="absolute inset-0 bg-[url('https://www.transparenttextures.com/patterns/cubes.png')] opacity-5 mix-blend-overlay pointer-events-none"></div>

          <div class="relative z-10">
            <div class="flex justify-between items-center mb-6 border-b border-slate-700/50 pb-5">
              <div>
                <h3 class="font-black text-xl flex items-center gap-2 text-white"><i class="bi bi-list-ol text-emerald-400"></i> ลำดับคอลัมน์ Excel</h3>
                <p class="text-slate-400 text-sm mt-1">จำนวนที่เลือก: <span class="text-emerald-400 font-bold">{{ selectedColumns.length }}</span> รายการ</p>
              </div>
              <button 
                v-if="selectedColumns.length > 0" 
                @click="clearAll" 
                class="text-xs font-bold text-rose-400 hover:text-white bg-rose-500/10 hover:bg-rose-500 border border-rose-500/20 hover:border-rose-500 px-3 py-2 rounded-xl transition-all active:scale-95"
              >
                ล้างทั้งหมด
              </button>
            </div>

            <!-- กล่องว่างเปล่า -->
            <div v-if="selectedColumns.length === 0" class="border-2 border-dashed border-slate-700 bg-slate-800/50 rounded-[1.5rem] p-12 flex flex-col items-center justify-center text-slate-500 gap-4 mt-8">
              <div class="w-16 h-16 bg-slate-800 rounded-full flex items-center justify-center border border-slate-700">
                <i class="bi bi-cursor text-2xl text-slate-400"></i>
              </div>
              <p class="font-medium text-sm text-center leading-relaxed">คลิกเลือกข้อมูลจากฝั่งซ้าย<br>เพื่อนำมาจัดลำดับที่นี่</p>
            </div>

            <!-- 🚀 กล่อง DRAG & DROP (บังคับให้จับเฉพาะที่ Handle) -->
            <draggable 
              v-else
              v-model="selectedColumns" 
              item-key="id"
              handle=".drag-handle" 
              :animation="250"
              class="space-y-3 max-h-[55vh] overflow-y-auto pr-2 custom-scrollbar"
              ghost-class="opacity-50 ring-2 ring-emerald-500 ring-offset-2 ring-offset-slate-900 rounded-2xl"
              drag-class="cursor-grabbing shadow-2xl scale-[1.02]"
            >
              <template #item="{ element, index }">
                <!-- Item Card -->
                <div class="group flex items-center justify-between bg-slate-800/80 backdrop-blur-sm border border-slate-700/80 hover:border-slate-500 p-3.5 rounded-2xl transition-colors">
                  
                  <div class="flex items-center gap-3 overflow-hidden w-full">
                    <!-- จุดจับลาก (Drag Handle) -->
                    <div class="drag-handle p-1.5 -ml-1.5 text-slate-500 hover:text-emerald-400 transition-colors">
                      <i class="bi bi-grip-vertical text-lg"></i>
                    </div>
                    
                    <!-- เนื้อหา -->
                    <div class="flex items-center gap-3 truncate">
                      <span class="text-[10px] font-black bg-slate-950 text-slate-400 w-7 h-7 flex items-center justify-center rounded-full shrink-0 shadow-inner border border-slate-800">
                        {{ index + 1 }}
                      </span>
                      <span :class="[element.catColor, 'font-bold text-sm truncate tracking-wide']">{{ element.label }}</span>
                    </div>
                  </div>

                  <!-- ปุ่มลบ -->
                  <button 
                    @click.stop="toggleField(element, { color: element.catColor })" 
                    class="w-8 h-8 rounded-full flex items-center justify-center text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 transition-all shrink-0 active:scale-90"
                    title="ลบออก"
                  >
                    <i class="bi bi-x-lg text-[10px] font-black"></i>
                  </button>

                </div>
              </template>
            </draggable>
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>
/* Scrollbar ฝั่งขวาสีมืด */
.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.02);
  border-radius: 10px;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.15);
  border-radius: 10px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.3);
}

/* บังคับเคอร์เซอร์ตอนชี้ที่จุดจับลาก */
.drag-handle {
  cursor: grab;
}
.drag-handle:active {
  cursor: grabbing;
}
</style>