<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import api from '@/services/api';
import Swal from 'sweetalert2';

// @ts-ignore
import * as ThaiAddressDB from 'thai-address-database';

interface AddressOption {
  subDistrict: string;
  district: string;
  province: string;
  zipcode: string;
}

const router = useRouter();
const authStore = useAuthStore();

const form = ref({
  prefix: '',
  first_name: '',
  last_name: '',
  nickname: '',
  birthday: '',
  phone_number: '',
  line_id: '',
  address_house_no: '',
  address_road: '',
  address_sub_district: '',
  address_district: '',
  address_province: '',
  address_post_code: ''
});

const isSubmitting = ref(false);

// ---------- Thai address autocomplete ----------
let searchTimeout: ReturnType<typeof setTimeout> | null = null;
const addressSuggestions = ref<AddressOption[]>([]);
const isAddressDropdownOpen = ref(false);
const activeAddressField = ref<'address_sub_district' | 'address_district' | 'address_province' | 'address_post_code' | null>(null);

const onAddressInput = (field: 'address_sub_district' | 'address_district' | 'address_province' | 'address_post_code') => {
  activeAddressField.value = field;
  const query = String(form.value[field] ?? '').trim();
  
  if (!query) {
    addressSuggestions.value = [];
    isAddressDropdownOpen.value = false;
    activeAddressField.value = null;
    if (searchTimeout) {
      clearTimeout(searchTimeout);
      searchTimeout = null;
    }
    return;
  }

  if (searchTimeout) {
    clearTimeout(searchTimeout);
    searchTimeout = null;
  }

  searchTimeout = setTimeout(() => {
    // 🛡️ ดึงฟังก์ชันค้นหาจาก thai-address-database ให้ตรงกับช่องที่กำลังพิมพ์
    const db: any = ThaiAddressDB.default || ThaiAddressDB;
    let searchFn: Function | null = null;

    if (field === 'address_sub_district') {
      searchFn = db.searchAddressByDistrict;
    } else if (field === 'address_district') {
      searchFn = db.searchAddressByAmphoe;
    } else if (field === 'address_province') {
      searchFn = db.searchAddressByProvince;
    } else if (field === 'address_post_code') {
      searchFn = db.searchAddressByZipcode;
    }
    
    if (!searchFn || typeof searchFn !== 'function') {
      console.warn('[thai-address-database] Specific search function not found for field:', field, db);
      return;
    }

    try {
      const results = searchFn(query);
      
      // Map ข้อมูลให้ตรงกับโครงสร้างของ thai-address-database (district = ตำบล, amphoe = อำเภอ)
      addressSuggestions.value = (results || []).map((item: any) => ({
        subDistrict: item.district || item.subdistrict || item.tambon || '',
        district: item.amphoe || item.district || '',
        province: item.province || item.changwat || '',
        zipcode: String(item.zipcode || item.postcode || '')
      })).filter((item: AddressOption) => item.subDistrict || item.district || item.province || item.zipcode);

      isAddressDropdownOpen.value = addressSuggestions.value.length > 0;
    } catch (err) {
      console.error('[thai-address-database] Error executing search:', err);
    } finally {
      searchTimeout = null;
    }
  }, 300);
};

const closeAddressDropdown = () => {
  if (searchTimeout) {
    clearTimeout(searchTimeout);
    searchTimeout = null;
  }
  setTimeout(() => {
    isAddressDropdownOpen.value = false;
    activeAddressField.value = null;
  }, 200);
};

const selectAddress = (option: AddressOption) => {
  if (searchTimeout) {
    clearTimeout(searchTimeout);
    searchTimeout = null;
  }
  form.value.address_sub_district = option.subDistrict;
  form.value.address_district = option.district;
  form.value.address_province = option.province;
  form.value.address_post_code = option.zipcode;
  isAddressDropdownOpen.value = false;
  activeAddressField.value = null;
};

// ----------------------------------------------

onMounted(() => {
  // 📥 Pre-fill ข้อมูลทั้งหมดที่มีจาก authStore เพื่อลดการพิมพ์ซ้ำ
  form.value.prefix = authStore.prefix ?? '';
  form.value.first_name = authStore.firstName ?? '';
  form.value.last_name = authStore.lastName ?? '';
  form.value.nickname = authStore.nickname ?? '';
  form.value.phone_number = authStore.phoneNumber ?? '';
});

const submitProfile = async () => {
  // ใช้ array เก็บ key ทั้งหมดของ form ยกเว้น address_road (ฟิลด์ optional)
  const requiredFields = (Object.keys(form.value) as Array<keyof typeof form.value>).filter(
    (field) => field !== 'address_road'
  );

  const isAllFilled = requiredFields.every((field) => {
    const value = form.value[field];
    return value && String(value).trim() !== '';
  });

  if (!isAllFilled) {
    Swal.fire('ข้อมูลไม่ครบ', 'กรุณากรอกข้อมูลให้ครบถ้วน', 'warning');
    return;
  }

  isSubmitting.value = true;
  try {
    // 🚀 ยิง API อัปเดตข้อมูลตัวเอง โดยส่ง form ทั้งตัวไปเลย
    await api.patch('/api/auth/me', form.value);

    // 🔄 สั่งให้ Store ดึงข้อมูลใหม่ เพื่อรับรองว่า Onboard แล้ว
    await authStore.fetchProfile();
    
    // 🚪 ปล่อยผ่านเข้าล็อบบี้ได้เลย!
    router.push('/lobby');
    
  } catch (error: any) {
    Swal.fire('ข้อผิดพลาด', error.message || 'ไม่สามารถบันทึกข้อมูลได้', 'error');
  } finally {
    isSubmitting.value = false;
  }
};
</script>

<template>
  <div class="min-h-screen bg-slate-50 flex items-center justify-center p-4 relative overflow-hidden">
    <div class="absolute top-0 right-0 w-[500px] h-[500px] bg-blue-500/10 rounded-full blur-[100px] pointer-events-none -translate-y-1/2 translate-x-1/3"></div>
    <div class="absolute bottom-0 left-0 w-[400px] h-[400px] bg-indigo-500/10 rounded-full blur-[80px] pointer-events-none translate-y-1/2 -translate-x-1/3"></div>

    <div class="max-w-lg w-full bg-white/80 backdrop-blur-xl rounded-[2.5rem] shadow-2xl shadow-slate-200/50 border border-white p-8 md:p-12 relative z-10">
      
      <div class="w-20 h-20 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-[1.5rem] flex items-center justify-center shadow-lg shadow-blue-500/30 mb-8 mx-auto">
        <i class="bi bi-person-vcard text-white text-4xl"></i>
      </div>
      
      <div class="text-center mb-10">
        <h1 class="text-3xl font-black text-slate-800 tracking-tight mb-2">ตั้งค่าโปรไฟล์ครั้งแรก</h1>
        <p class="text-slate-500 font-medium text-sm">ข้อมูลนี้จะถูกใช้เพื่อยืนยันตัวตนและผูกเข้ากับรายชื่อในห้องเรียน กรุณากรอกให้ตรงตามความจริง</p>
      </div>

      <form @submit.prevent="submitProfile" class="space-y-8">
        <!-- Section 1: ข้อมูลส่วนตัว -->
        <div>
          <h3 class="text-sm font-black text-slate-800 border-b border-slate-100 pb-2 mb-4">ข้อมูลส่วนตัว</h3>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div class="sm:col-span-2">
              <label class="block text-xs font-black text-slate-400 uppercase tracking-widest mb-2">คำนำหน้า <span class="text-rose-500">*</span></label>
              <div class="relative">
                <select v-model="form.prefix" required class="w-full bg-white border border-slate-200 text-slate-800 text-base font-bold rounded-2xl px-5 py-4 focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all shadow-sm appearance-none cursor-pointer">
                  <option value="" disabled selected>เลือกคำนำหน้า</option>
                  <option value="นาย">นาย</option>
                  <option value="นางสาว">นางสาว</option>
                  <option value="เด็กชาย">เด็กชาย (ด.ช.)</option>
                  <option value="เด็กหญิง">เด็กหญิง (ด.ญ.)</option>
                </select>
                <div class="pointer-events-none absolute inset-y-0 right-0 flex items-center px-5 text-slate-400">
                  <i class="bi bi-chevron-down"></i>
                </div>
              </div>
            </div>

            <div>
              <label class="block text-xs font-black text-slate-400 uppercase tracking-widest mb-2">ชื่อจริง <span class="text-rose-500">*</span></label>
              <input v-model="form.first_name" type="text" required placeholder="สมชาย" class="w-full bg-white border border-slate-200 text-slate-800 text-base font-bold rounded-2xl px-5 py-4 focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all shadow-sm">
            </div>
            <div>
              <label class="block text-xs font-black text-slate-400 uppercase tracking-widest mb-2">นามสกุล <span class="text-rose-500">*</span></label>
              <input v-model="form.last_name" type="text" required placeholder="ใจดี" class="w-full bg-white border border-slate-200 text-slate-800 text-base font-bold rounded-2xl px-5 py-4 focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all shadow-sm">
            </div>
            <div>
              <label class="block text-xs font-black text-slate-400 uppercase tracking-widest mb-2">ชื่อเล่น <span class="text-rose-500">*</span></label>
              <input v-model="form.nickname" type="text" required placeholder="เช่น โอม" class="w-full bg-white border border-slate-200 text-slate-800 text-base font-bold rounded-2xl px-5 py-4 focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all shadow-sm">
            </div>
            <div>
              <label class="block text-xs font-black text-slate-400 uppercase tracking-widest mb-2">วันเกิด <span class="text-rose-500">*</span></label>
              <input v-model="form.birthday" type="date" required class="w-full bg-white border border-slate-200 text-slate-800 text-base font-bold rounded-2xl px-5 py-4 focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all shadow-sm">
            </div>
          </div>
        </div>

        <!-- Section 2: ข้อมูลการติดต่อ -->
        <div>
          <h3 class="text-sm font-black text-slate-800 border-b border-slate-100 pb-2 mb-4">ข้อมูลการติดต่อ</h3>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div>
              <label class="block text-xs font-black text-slate-400 uppercase tracking-widest mb-2">เบอร์โทรศัพท์ <span class="text-rose-500">*</span></label>
              <input v-model="form.phone_number" type="tel" required placeholder="081-234-5678" class="w-full bg-white border border-slate-200 text-slate-800 text-base font-bold rounded-2xl px-5 py-4 focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all shadow-sm">
            </div>
            <div>
              <label class="block text-xs font-black text-slate-400 uppercase tracking-widest mb-2">Line ID <span class="text-rose-500">*</span></label>
              <input v-model="form.line_id" type="text" required placeholder="เช่น om_2005" class="w-full bg-white border border-slate-200 text-slate-800 text-base font-bold rounded-2xl px-5 py-4 focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all shadow-sm">
            </div>
          </div>
        </div>

        <!-- Section 3: ที่อยู่ปัจจุบัน -->
        <div>
          <h3 class="text-sm font-black text-slate-800 border-b border-slate-100 pb-2 mb-4">ที่อยู่ปัจจุบัน</h3>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-5">
            <div>
              <label class="block text-xs font-black text-slate-400 uppercase tracking-widest mb-2">บ้านเลขที่/หมู่ <span class="text-rose-500">*</span></label>
              <input v-model="form.address_house_no" type="text" required placeholder="123/45 หมู่ 2" class="w-full bg-white border border-slate-200 text-slate-800 text-base font-bold rounded-2xl px-5 py-4 focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all shadow-sm">
            </div>
            <div>
              <label class="block text-xs font-black text-slate-400 uppercase tracking-widest mb-2">ถนน/ซอย</label>
              <input v-model="form.address_road" type="text" placeholder="ซอยสุขุมวิท 50" class="w-full bg-white border border-slate-200 text-slate-800 text-base font-bold rounded-2xl px-5 py-4 focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all shadow-sm">
            </div>
            <div>
              <label class="block text-xs font-black text-slate-400 uppercase tracking-widest mb-2">ตำบล/แขวง <span class="text-rose-500">*</span></label>
              <div class="relative">
                <input v-model="form.address_sub_district" type="text" required placeholder="พระโขนง" class="w-full bg-white border border-slate-200 text-slate-800 text-base font-bold rounded-2xl px-5 py-4 focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all shadow-sm" @input="onAddressInput('address_sub_district')" @focus="onAddressInput('address_sub_district')" @blur="closeAddressDropdown">
                <ul v-if="isAddressDropdownOpen && activeAddressField === 'address_sub_district'" class="absolute z-30 mt-2 w-full bg-white border border-slate-200 shadow-2xl rounded-xl max-h-60 overflow-y-auto">
                  <li v-for="(option, idx) in addressSuggestions" :key="idx" @mousedown.prevent="selectAddress(option)" class="px-4 py-3 text-sm text-slate-700 hover:bg-slate-50 cursor-pointer border-b border-slate-100 last:border-b-0">
                    <span class="font-bold">{{ option.subDistrict }} ต.</span>
                    <span class="text-slate-500"> อ. {{ option.district }} จ. {{ option.province }} {{ option.zipcode }}</span>
                  </li>
                </ul>
              </div>
            </div>
            <div>
              <label class="block text-xs font-black text-slate-400 uppercase tracking-widest mb-2">อำเภอ/เขต <span class="text-rose-500">*</span></label>
              <div class="relative">
                <input v-model="form.address_district" type="text" required placeholder="คลองเตย" class="w-full bg-white border border-slate-200 text-slate-800 text-base font-bold rounded-2xl px-5 py-4 focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all shadow-sm" @input="onAddressInput('address_district')" @focus="onAddressInput('address_district')" @blur="closeAddressDropdown">
                <ul v-if="isAddressDropdownOpen && activeAddressField === 'address_district'" class="absolute z-30 mt-2 w-full bg-white border border-slate-200 shadow-2xl rounded-xl max-h-60 overflow-y-auto">
                  <li v-for="(option, idx) in addressSuggestions" :key="idx" @mousedown.prevent="selectAddress(option)" class="px-4 py-3 text-sm text-slate-700 hover:bg-slate-50 cursor-pointer border-b border-slate-100 last:border-b-0">
                    <span class="font-bold">{{ option.subDistrict }} ต.</span>
                    <span class="text-slate-500"> อ. {{ option.district }} จ. {{ option.province }} {{ option.zipcode }}</span>
                  </li>
                </ul>
              </div>
            </div>
            <div>
              <label class="block text-xs font-black text-slate-400 uppercase tracking-widest mb-2">จังหวัด <span class="text-rose-500">*</span></label>
              <div class="relative">
                <input v-model="form.address_province" type="text" required placeholder="กรุงเทพมหานคร" class="w-full bg-white border border-slate-200 text-slate-800 text-base font-bold rounded-2xl px-5 py-4 focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all shadow-sm" @input="onAddressInput('address_province')" @focus="onAddressInput('address_province')" @blur="closeAddressDropdown">
                <ul v-if="isAddressDropdownOpen && activeAddressField === 'address_province'" class="absolute z-30 mt-2 w-full bg-white border border-slate-200 shadow-2xl rounded-xl max-h-60 overflow-y-auto">
                  <li v-for="(option, idx) in addressSuggestions" :key="idx" @mousedown.prevent="selectAddress(option)" class="px-4 py-3 text-sm text-slate-700 hover:bg-slate-50 cursor-pointer border-b border-slate-100 last:border-b-0">
                    <span class="font-bold">{{ option.subDistrict }} ต.</span>
                    <span class="text-slate-500"> อ. {{ option.district }} จ. {{ option.province }} {{ option.zipcode }}</span>
                  </li>
                </ul>
              </div>
            </div>
            <div>
              <label class="block text-xs font-black text-slate-400 uppercase tracking-widest mb-2">รหัสไปรษณีย์ <span class="text-rose-500">*</span></label>
              <div class="relative">
                <input v-model="form.address_post_code" type="text" required placeholder="10110" class="w-full bg-white border border-slate-200 text-slate-800 text-base font-bold rounded-2xl px-5 py-4 focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all shadow-sm" @input="onAddressInput('address_post_code')" @focus="onAddressInput('address_post_code')" @blur="closeAddressDropdown">
                <ul v-if="isAddressDropdownOpen && activeAddressField === 'address_post_code'" class="absolute z-30 mt-2 w-full bg-white border border-slate-200 shadow-2xl rounded-xl max-h-60 overflow-y-auto">
                  <li v-for="(option, idx) in addressSuggestions" :key="idx" @mousedown.prevent="selectAddress(option)" class="px-4 py-3 text-sm text-slate-700 hover:bg-slate-50 cursor-pointer border-b border-slate-100 last:border-b-0">
                    <span class="font-bold">{{ option.subDistrict }} ต.</span>
                    <span class="text-slate-500"> อ. {{ option.district }} จ. {{ option.province }} {{ option.zipcode }}</span>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </div>

        <div class="pt-6">
          <button type="submit" :disabled="isSubmitting" class="w-full bg-slate-900 hover:bg-slate-800 text-white font-black text-lg py-4 rounded-2xl transition-all shadow-lg shadow-slate-900/20 active:scale-95 disabled:opacity-50 disabled:active:scale-100 flex items-center justify-center gap-2">
            <span v-if="isSubmitting" class="animate-spin inline-block w-5 h-5 border-2 border-white/30 border-t-white rounded-full"></span>
            <span v-else>บันทึกและเข้าสู่ระบบ <i class="bi bi-arrow-right"></i></span>
          </button>
        </div>

      </form>
    </div>
  </div>
</template>
