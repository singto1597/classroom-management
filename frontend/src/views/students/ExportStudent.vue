<script setup lang="ts">
import { ref, computed } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { StudentService } from '@/services/student';
import PageHeader from '@/components/ui/PageHeader.vue';
import Swal from 'sweetalert2';
import draggable from 'vuedraggable'; // 📦 vuedraggable สำหรับ Vue 3

const router = useRouter();
const authStore = useAuthStore();
const roomId = computed(() => authStore.currentRoomId!);
const userName = computed(() => authStore.currentUserName || 'ผู้ดูแลระบบ');

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
  ring: string; // ✨ คลาส ring แบบเต็ม (Tailwind ต้องเห็นข้อความเต็ม ถึงจะ compile)
  fields: Field[];
}

interface SelectedColumn {
  id: string;
  label: string;
  catColor: string;
}

// --- 📂 2. Schema ข้อมูล ---
// 🎨 ธีม Academic Ledger: สีเน้นเดียว (brand) — แยกหมวดด้วยไอคอน ไม่ใช่ด้วยสี
const exportSchema: Category[] = [
  {
    id: 'core', name: 'ข้อมูลส่วนตัวพื้นฐาน', icon: 'bi-person-badge-fill', color: 'text-brand-700', bg: 'bg-brand-50', border: 'border-brand-200', ring: 'ring-brand-500/30',
    fields: [
      { id: 'student_no', label: 'เลขที่' },
      { id: 'student_id', label: 'รหัสนักเรียน' },
      { id: 'prefix', label: 'คำนำหน้า' },
      { id: 'first_name', label: 'ชื่อจริง' },
      { id: 'last_name', label: 'นามสกุล' },
      { id: 'first_name_en', label: 'ชื่อจริง (EN)' },
      { id: 'last_name_en', label: 'นามสกุล (EN)' },
      { id: 'nickname', label: 'ชื่อเล่น' },
      { id: 'nickname_en', label: 'ชื่อเล่น (EN)' },
      { id: 'birthday', label: 'วันเกิด' }
    ]
  },
  {
    id: 'academic', name: 'วิชาการและหน้าที่', icon: 'bi-journal-bookmark-fill', color: 'text-brand-700', bg: 'bg-brand-50', border: 'border-brand-200', ring: 'ring-brand-500/30',
    fields: [
      { id: 'class_role', label: 'บทบาทในห้อง' },
      { id: 'cleaning_duty', label: 'เวรทำความสะอาด' },
      { id: 'olympic_camp', label: 'สอวน. / ค่าย' },
      { id: 'target_faculty', label: 'คณะเป้าหมาย' },
      { id: 'portfolio', label: 'ผลงาน' }
    ]
  },
  {
    id: 'health', name: 'ข้อมูลสุขภาพ', icon: 'bi-heart-pulse-fill', color: 'text-brand-700', bg: 'bg-brand-50', border: 'border-brand-200', ring: 'ring-brand-500/30',
    fields: [
      { id: 'blood_group', label: 'กรุ๊ปเลือด' },
      { id: 'shirt_size', label: 'ไซส์เสื้อ' },
      { id: 'food_allergy', label: 'แพ้อาหาร' },
      { id: 'congenital_disease', label: 'โรคประจำตัว' }
    ]
  },
  {
    id: 'contact', name: 'การติดต่อ', icon: 'bi-telephone-fill', color: 'text-brand-700', bg: 'bg-brand-50', border: 'border-brand-200', ring: 'ring-brand-500/30',
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
    id: 'address', name: 'ที่อยู่', icon: 'bi-house-door-fill', color: 'text-brand-700', bg: 'bg-brand-50', border: 'border-brand-200', ring: 'ring-brand-500/30',
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

// 🎨 Map สี checkbox แบบ literal (Tailwind JIT ต้องเห็นข้อความเต็ม ถึงจะ compile)
const CHECK_COLORS: Record<string, { checked: string; partial: string }> = {
  'text-brand-700': { checked: 'bg-brand-700 border-transparent', partial: 'bg-brand-300 border-transparent' },
};

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
      confirmButtonColor: '#1d4ed8'
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
      text: 'ไม่สามารถส่งออกข้อมูลได้ กรุณาลองใหม่อีกครั้ง',
      confirmButtonColor: '#1d4ed8'
    });
  }
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">

    <PageHeader
      eyebrow="Export Builder"
      title="เครื่องมือสร้างไฟล์ Export"
      description="เลือกหมวดหมู่ และลากวางคอลัมน์เพื่อจัดลำดับไฟล์ Excel"
    >
      <template #actions>
        <button type="button" class="btn-ghost-ui" @click="router.back()">
          <i class="bi bi-arrow-left" aria-hidden="true"></i> กลับ
        </button>
        <button type="button" class="btn-primary" @click="handleExport">
          <i class="bi bi-file-earmark-excel-fill" aria-hidden="true"></i>
          สร้างไฟล์ Excel
        </button>
      </template>
    </PageHeader>

    <div class="grid grid-cols-1 items-start gap-4 sm:gap-5 xl:grid-cols-12">

      <!-- ⬅️ ซ้าย: กล่องเลือกข้อมูล (Source) -->
      <div class="space-y-4 xl:col-span-7">
        <section v-for="cat in exportSchema" :key="cat.id" class="page-card overflow-hidden">

          <!-- Category Header (เป็นปุ่มจริงเพื่อให้กดด้วยคีย์บอร์ด/โปรแกรมอ่านจอได้) -->
          <button
            type="button"
            class="flex w-full cursor-pointer select-none items-center justify-between gap-3 border-b border-stone-200 bg-stone-50/70 px-4 py-3.5 text-left transition-colors hover:bg-stone-100 sm:px-5"
            :aria-pressed="isCategoryAllSelected(cat)"
            @click="toggleCategory(cat)"
          >
            <h3 class="flex min-w-0 items-center gap-2.5">
              <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white ring-1 ring-stone-200">
                <i :class="[cat.icon, cat.color, 'text-base']" aria-hidden="true"></i>
              </span>
              <span class="section-title truncate">{{ cat.name }}</span>
            </h3>

            <!-- Checkbox เลือกทั้งหมวด -->
            <div
              class="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border-2 transition-all"
              :class="isCategoryAllSelected(cat)
                ? CHECK_COLORS[cat.color]?.checked || 'bg-brand-700 border-transparent'
                : isCategoryPartialSelected(cat)
                  ? CHECK_COLORS[cat.color]?.partial || 'bg-brand-300 border-transparent'
                  : 'border-stone-300 bg-white'"
            >
              <i v-if="isCategoryAllSelected(cat)" class="bi bi-check-lg text-sm font-black text-white" aria-hidden="true"></i>
              <i v-else-if="isCategoryPartialSelected(cat)" class="bi bi-dash-lg text-sm font-black text-stone-600" aria-hidden="true"></i>
            </div>
          </button>

          <!-- Fields -->
          <div class="flex flex-wrap gap-2 p-4 sm:p-5">
            <button
              v-for="field in cat.fields"
              :key="field.id"
              type="button"
              class="flex select-none items-center gap-2 rounded-xl border px-3 py-2 text-sm font-bold transition-colors active:scale-[0.97]"
              :class="isFieldSelected(field.id)
                ? `${cat.color} ${cat.bg} border-transparent ring-1 ring-inset ${cat.ring}`
                : 'border-stone-200 text-stone-500 hover:border-stone-300 hover:bg-stone-50'"
              @click="toggleField(field, cat)"
            >
              <span
                class="flex h-4 w-4 shrink-0 items-center justify-center rounded border-2 transition-colors"
                :class="isFieldSelected(field.id) ? 'border-brand-700 bg-brand-700' : 'border-stone-300'"
                aria-hidden="true"
              >
                <i v-if="isFieldSelected(field.id)" class="bi bi-check text-[10px] font-black leading-none text-white"></i>
              </span>
              {{ field.label }}
            </button>
          </div>
        </section>
      </div>

      <!-- ➡️ ขวา: จัดลำดับการส่งออก (แสดงก่อนบนมือถือ เพราะเป็น action หลัก) -->
      <div class="page-card order-first overflow-hidden xl:order-none xl:col-span-5 xl:sticky xl:top-8">

        <div class="flex items-center justify-between gap-3 border-b border-stone-200 bg-stone-50/70 px-4 py-3.5 sm:px-5">
          <div class="min-w-0">
            <h3 class="section-title flex items-center gap-2">
              <i class="bi bi-list-ol text-brand-700" aria-hidden="true"></i> ลำดับคอลัมน์ Excel
            </h3>
            <p class="mt-0.5 text-xs text-stone-500">
              เลือกแล้ว <span class="num font-bold text-brand-700">{{ selectedColumns.length }}</span> รายการ
            </p>
          </div>

          <button
            v-if="selectedColumns.length > 0"
            type="button"
            class="btn-danger shrink-0 px-3 py-1.5 text-xs"
            @click="clearAll"
          >
            <i class="bi bi-trash" aria-hidden="true"></i> ล้างทั้งหมด
          </button>
        </div>

        <div class="p-4 sm:p-5">
          <!-- กล่องว่างเปล่า -->
          <div
            v-if="selectedColumns.length === 0"
            class="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-stone-300 px-5 py-8 text-center sm:px-6 sm:py-12"
          >
            <i class="bi bi-cursor text-3xl text-stone-300" aria-hidden="true"></i>
            <p class="text-sm leading-normal text-stone-500">
              <span class="sm:hidden">แตะเลือกข้อมูลจากด้านล่าง</span><span class="hidden sm:inline">คลิกเลือกข้อมูลจากฝั่งซ้าย</span><br />เพื่อนำมาจัดลำดับที่นี่
            </p>
          </div>

          <!-- 🚀 กล่อง DRAG & DROP (บังคับให้จับเฉพาะที่ Handle) -->
          <draggable
            v-else
            v-model="selectedColumns"
            item-key="id"
            handle=".drag-handle"
            :animation="250"
            class="max-h-[55vh] space-y-2 overflow-y-auto overscroll-contain pe-1"
            ghost-class="opacity-40"
            drag-class="cursor-grabbing"
          >
            <template #item="{ element, index }">
              <div class="flex items-center justify-between gap-2 rounded-xl border border-stone-200 bg-white p-3 transition-colors hover:border-stone-300">

                <div class="flex min-w-0 items-center gap-2.5">
                  <!-- จุดจับลาก (Drag Handle) — พื้นที่แตะ 44px ตามสัญญา DESIGN ข้อ 6 (-my-2 ไม่ให้แถวสูงขึ้น) -->
                  <div
                    class="drag-handle -my-2 -ms-1 flex h-11 w-11 shrink-0 cursor-grab items-center justify-center text-stone-400 transition-colors hover:text-brand-700"
                    role="button"
                    aria-label="ลากเพื่อจัดลำดับคอลัมน์"
                  >
                    <i class="bi bi-grip-vertical text-lg" aria-hidden="true"></i>
                  </div>

                  <span class="num flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-stone-100 text-[11px] font-bold text-stone-600">
                    {{ index + 1 }}
                  </span>

                  <span :class="[element.catColor, 'truncate text-sm font-bold tracking-wide']">{{ element.label }}</span>
                </div>

                <!-- ปุ่มลบ — พื้นที่แตะ 44px (-my-1.5 คุมความสูงแถวไม่ให้บวม) -->
                <button
                  type="button"
                  class="-my-1.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-stone-400 transition-colors hover:bg-red-50 hover:text-red-600 active:scale-[0.97]"
                  title="ลบออก"
                  aria-label="ลบออก"
                  @click.stop="toggleField(element, { color: element.catColor })"
                >
                  <i class="bi bi-x-lg text-[10px] font-black" aria-hidden="true"></i>
                </button>

              </div>
            </template>
          </draggable>
        </div>
      </div>

    </div>
  </div>
</template>
