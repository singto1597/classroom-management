<script setup lang="ts">
defineOptions({ name: 'OnboardingView' });

import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { updateMyProfile } from '@/services/auth';
import Swal from 'sweetalert2';
import PageHeader from '@/components/ui/PageHeader.vue';

import * as ThaiAddressDB from 'thai-address-database';
import type {
  ThaiAddressModule,
  ThaiAddressRecord,
  ThaiAddressSearchFn,
} from 'thai-address-database';

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
  first_name_en: '',
  last_name_en: '',
  nickname: '',
  nickname_en: '',
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
    const db: ThaiAddressModule = ThaiAddressDB.default || ThaiAddressDB;
    let searchFn: ThaiAddressSearchFn | null = null;

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
      addressSuggestions.value = (results || []).map((item: ThaiAddressRecord) => ({
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

onMounted(async () => {
  // 📥 ดึงโปรไฟล์ล่าสุดจาก Backend ก่อน Pre-fill เพื่อข้อมูลสดใหม่เสมอ
  if (authStore.isAuthenticated) {
    await authStore.fetchProfile();
  }

  // 📥 Pre-fill ข้อมูลทั้งหมดที่มีจาก authStore เพื่อลดการพิมพ์ซ้ำ
  form.value.prefix = authStore.prefix ?? '';
  form.value.first_name = authStore.firstName ?? '';
  form.value.last_name = authStore.lastName ?? '';
  form.value.first_name_en = authStore.firstNameEn ?? '';
  form.value.last_name_en = authStore.lastNameEn ?? '';
  form.value.nickname = authStore.nickname ?? '';
  form.value.nickname_en = authStore.nicknameEn ?? '';
  form.value.phone_number = authStore.phoneNumber ?? '';
});

const submitProfile = async () => {
  // ใช้ array เก็บ key ทั้งหมดของ form ยกเว้นฟิลด์ optional:
  // address_road (ถนน/ซอย) + *_en (ชื่อ/ชื่อเล่นอังกฤษ — identity แต่ไม่บังคับ)
  const OPTIONAL_FIELDS = new Set(['address_road', 'first_name_en', 'last_name_en', 'nickname_en']);
  const requiredFields = (Object.keys(form.value) as Array<keyof typeof form.value>).filter(
    (field) => !OPTIONAL_FIELDS.has(field as string)
  );

  const isAllFilled = requiredFields.every((field) => {
    const value = form.value[field];
    return value && String(value).trim() !== '';
  });

  if (!isAllFilled) {
    Swal.fire({
      icon: 'warning',
      title: 'ข้อมูลไม่ครบ',
      text: 'กรุณากรอกข้อมูลให้ครบถ้วน',
      confirmButtonColor: '#1d4ed8',
    });
    return;
  }

  isSubmitting.value = true;
  try {
    // 🚀 ยิง API อัปเดตข้อมูลตัวเอง โดยส่ง form ทั้งตัวไปเลย
    await updateMyProfile(form.value);

    // 🔄 สั่งให้ Store ดึงข้อมูลใหม่ เพื่อรับรองว่า Onboard แล้ว
    await authStore.fetchProfile();

    // 🚪 ปล่อยผ่านเข้าล็อบบี้ได้เลย!
    router.push('/lobby');

  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : '';
    Swal.fire({
      icon: 'error',
      title: 'ข้อผิดพลาด',
      text: message || 'ไม่สามารถบันทึกข้อมูลได้',
      confirmButtonColor: '#1d4ed8',
    });
  } finally {
    isSubmitting.value = false;
  }
};
</script>

<template>
  <!-- ⚠️ หน้านี้อยู่นอก MainLayout จึงต้องจัดระยะขอบเอง -->
  <div class="min-h-screen min-h-dvh bg-paper font-sans text-ink">
    <div class="mx-auto w-full max-w-3xl px-4 py-8 sm:px-6 sm:py-12">
      <PageHeader
        eyebrow="Profile Setup"
        title="ตั้งค่าโปรไฟล์ครั้งแรก"
        description="ข้อมูลนี้จะถูกใช้เพื่อยืนยันตัวตนและผูกเข้ากับรายชื่อในห้องเรียน กรุณากรอกให้ตรงตามความจริง"
      />

      <!-- ลำดับหัวข้อ (แสดงผลอย่างเดียว) — คั่นด้วยเส้นบาง ไม่ใช่แถบสีทึบ -->
      <div
        class="mb-5 flex flex-wrap items-center gap-x-3 gap-y-2 border-y border-stone-200 py-3 sm:mb-6"
        aria-hidden="true"
      >
        <div class="flex items-center gap-2">
          <span
            class="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-[11px] font-bold text-brand-700"
          >
            1
          </span>
          <span class="text-xs font-bold text-stone-600">ข้อมูลส่วนตัว</span>
        </div>
        <div class="hidden h-px w-6 shrink-0 bg-stone-200 sm:block"></div>
        <div class="flex items-center gap-2">
          <span
            class="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-[11px] font-bold text-brand-700"
          >
            2
          </span>
          <span class="text-xs font-bold text-stone-600">ข้อมูลการติดต่อ</span>
        </div>
        <div class="hidden h-px w-6 shrink-0 bg-stone-200 sm:block"></div>
        <div class="flex items-center gap-2">
          <span
            class="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-[11px] font-bold text-brand-700"
          >
            3
          </span>
          <span class="text-xs font-bold text-stone-600">ที่อยู่ปัจจุบัน</span>
        </div>
      </div>

      <form class="space-y-4" @submit.prevent="submitProfile">
        <!-- ── ส่วนที่ 1: ข้อมูลส่วนตัว ── -->
        <section class="page-card p-5 sm:p-6">
          <h2 class="section-title border-b border-stone-100 pb-2.5">ข้อมูลส่วนตัว</h2>

          <div class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div class="sm:col-span-2">
              <label class="field-label" for="prefix">
                คำนำหน้า <span class="text-red-500">*</span>
              </label>
              <div class="relative">
                <select
                  id="prefix"
                  v-model="form.prefix"
                  required
                  class="field cursor-pointer appearance-none pe-10"
                >
                  <option value="" disabled selected>เลือกคำนำหน้า</option>
                  <option value="นาย">นาย</option>
                  <option value="นางสาว">นางสาว</option>
                  <option value="เด็กชาย">เด็กชาย (ด.ช.)</option>
                  <option value="เด็กหญิง">เด็กหญิง (ด.ญ.)</option>
                </select>
                <i
                  class="bi bi-chevron-down pointer-events-none absolute inset-y-0 end-3.5 flex items-center text-sm text-stone-400"
                  aria-hidden="true"
                ></i>
              </div>
            </div>

            <div>
              <label class="field-label" for="first_name">
                ชื่อจริง <span class="text-red-500">*</span>
              </label>
              <input
                id="first_name"
                v-model="form.first_name"
                type="text"
                required
                placeholder="สมชาย"
                class="field"
              />
            </div>
            <div>
              <label class="field-label" for="last_name">
                นามสกุล <span class="text-red-500">*</span>
              </label>
              <input
                id="last_name"
                v-model="form.last_name"
                type="text"
                required
                placeholder="ใจดี"
                class="field"
              />
            </div>

            <div>
              <label class="field-label" for="first_name_en">
                ชื่อจริง (อังกฤษ)
                <span class="font-normal text-stone-400">ไม่บังคับ</span>
              </label>
              <input
                id="first_name_en"
                v-model="form.first_name_en"
                type="text"
                placeholder="Somchai"
                class="field"
              />
            </div>
            <div>
              <label class="field-label" for="last_name_en">
                นามสกุล (อังกฤษ)
                <span class="font-normal text-stone-400">ไม่บังคับ</span>
              </label>
              <input
                id="last_name_en"
                v-model="form.last_name_en"
                type="text"
                placeholder="Jaidee"
                class="field"
              />
            </div>

            <div>
              <label class="field-label" for="nickname">
                ชื่อเล่น <span class="text-red-500">*</span>
              </label>
              <input
                id="nickname"
                v-model="form.nickname"
                type="text"
                required
                placeholder="เช่น โอม"
                class="field"
              />
            </div>
            <div>
              <label class="field-label" for="nickname_en">
                ชื่อเล่น (อังกฤษ)
                <span class="font-normal text-stone-400">ไม่บังคับ</span>
              </label>
              <input
                id="nickname_en"
                v-model="form.nickname_en"
                type="text"
                placeholder="เช่น Om"
                class="field"
              />
            </div>

            <div>
              <label class="field-label" for="birthday">
                วันเกิด <span class="text-red-500">*</span>
              </label>
              <input id="birthday" v-model="form.birthday" type="date" required class="field" />
            </div>
          </div>
        </section>

        <!-- ── ส่วนที่ 2: ข้อมูลการติดต่อ ── -->
        <section class="page-card p-5 sm:p-6">
          <h2 class="section-title border-b border-stone-100 pb-2.5">ข้อมูลการติดต่อ</h2>

          <div class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label class="field-label" for="phone_number">
                เบอร์โทรศัพท์ <span class="text-red-500">*</span>
              </label>
              <input
                id="phone_number"
                v-model="form.phone_number"
                type="tel"
                required
                placeholder="081-234-5678"
                class="field"
              />
            </div>
            <div>
              <label class="field-label" for="line_id">
                Line ID <span class="text-red-500">*</span>
              </label>
              <input
                id="line_id"
                v-model="form.line_id"
                type="text"
                required
                placeholder="เช่น om_2005"
                class="field"
              />
            </div>
          </div>
        </section>

        <!-- ── ส่วนที่ 3: ที่อยู่ปัจจุบัน ── -->
        <section class="page-card p-5 sm:p-6">
          <h2 class="section-title border-b border-stone-100 pb-2.5">ที่อยู่ปัจจุบัน</h2>

          <div class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label class="field-label" for="address_house_no">
                บ้านเลขที่/หมู่ <span class="text-red-500">*</span>
              </label>
              <input
                id="address_house_no"
                v-model="form.address_house_no"
                type="text"
                required
                placeholder="123/45 หมู่ 2"
                class="field"
              />
            </div>
            <div>
              <label class="field-label" for="address_road">ถนน/ซอย</label>
              <input
                id="address_road"
                v-model="form.address_road"
                type="text"
                placeholder="ซอยสุขุมวิท 50"
                class="field"
              />
            </div>

            <div>
              <label class="field-label" for="address_sub_district">
                ตำบล/แขวง <span class="text-red-500">*</span>
              </label>
              <div class="relative">
                <input
                  id="address_sub_district"
                  v-model="form.address_sub_district"
                  type="text"
                  required
                  placeholder="พระโขนง"
                  class="field"
                  @input="onAddressInput('address_sub_district')"
                  @focus="onAddressInput('address_sub_district')"
                  @blur="closeAddressDropdown"
                />
                <ul
                  v-if="isAddressDropdownOpen && activeAddressField === 'address_sub_district'"
                  class="page-card absolute z-30 mt-2 max-h-60 w-full overflow-y-auto overscroll-contain border-stone-300"
                >
                  <li
                    v-for="(option, idx) in addressSuggestions"
                    :key="idx"
                    class="cursor-pointer border-b border-stone-100 px-4 py-3 text-sm transition-colors last:border-b-0 hover:bg-stone-50"
                    @mousedown.prevent="selectAddress(option)"
                  >
                    <span class="font-bold text-stone-900">{{ option.subDistrict }} ต.</span>
                    <span class="text-stone-500">
                      อ. {{ option.district }} จ. {{ option.province }} {{ option.zipcode }}</span
                    >
                  </li>
                </ul>
              </div>
            </div>

            <div>
              <label class="field-label" for="address_district">
                อำเภอ/เขต <span class="text-red-500">*</span>
              </label>
              <div class="relative">
                <input
                  id="address_district"
                  v-model="form.address_district"
                  type="text"
                  required
                  placeholder="คลองเตย"
                  class="field"
                  @input="onAddressInput('address_district')"
                  @focus="onAddressInput('address_district')"
                  @blur="closeAddressDropdown"
                />
                <ul
                  v-if="isAddressDropdownOpen && activeAddressField === 'address_district'"
                  class="page-card absolute z-30 mt-2 max-h-60 w-full overflow-y-auto overscroll-contain border-stone-300"
                >
                  <li
                    v-for="(option, idx) in addressSuggestions"
                    :key="idx"
                    class="cursor-pointer border-b border-stone-100 px-4 py-3 text-sm transition-colors last:border-b-0 hover:bg-stone-50"
                    @mousedown.prevent="selectAddress(option)"
                  >
                    <span class="font-bold text-stone-900">{{ option.subDistrict }} ต.</span>
                    <span class="text-stone-500">
                      อ. {{ option.district }} จ. {{ option.province }} {{ option.zipcode }}</span
                    >
                  </li>
                </ul>
              </div>
            </div>

            <div>
              <label class="field-label" for="address_province">
                จังหวัด <span class="text-red-500">*</span>
              </label>
              <div class="relative">
                <input
                  id="address_province"
                  v-model="form.address_province"
                  type="text"
                  required
                  placeholder="กรุงเทพมหานคร"
                  class="field"
                  @input="onAddressInput('address_province')"
                  @focus="onAddressInput('address_province')"
                  @blur="closeAddressDropdown"
                />
                <ul
                  v-if="isAddressDropdownOpen && activeAddressField === 'address_province'"
                  class="page-card absolute z-30 mt-2 max-h-60 w-full overflow-y-auto overscroll-contain border-stone-300"
                >
                  <li
                    v-for="(option, idx) in addressSuggestions"
                    :key="idx"
                    class="cursor-pointer border-b border-stone-100 px-4 py-3 text-sm transition-colors last:border-b-0 hover:bg-stone-50"
                    @mousedown.prevent="selectAddress(option)"
                  >
                    <span class="font-bold text-stone-900">{{ option.subDistrict }} ต.</span>
                    <span class="text-stone-500">
                      อ. {{ option.district }} จ. {{ option.province }} {{ option.zipcode }}</span
                    >
                  </li>
                </ul>
              </div>
            </div>

            <div>
              <label class="field-label" for="address_post_code">
                รหัสไปรษณีย์ <span class="text-red-500">*</span>
              </label>
              <div class="relative">
                <input
                  id="address_post_code"
                  v-model="form.address_post_code"
                  type="text"
                  required
                  placeholder="10110"
                  class="field"
                  @input="onAddressInput('address_post_code')"
                  @focus="onAddressInput('address_post_code')"
                  @blur="closeAddressDropdown"
                />
                <ul
                  v-if="isAddressDropdownOpen && activeAddressField === 'address_post_code'"
                  class="page-card absolute z-30 mt-2 max-h-60 w-full overflow-y-auto overscroll-contain border-stone-300"
                >
                  <li
                    v-for="(option, idx) in addressSuggestions"
                    :key="idx"
                    class="cursor-pointer border-b border-stone-100 px-4 py-3 text-sm transition-colors last:border-b-0 hover:bg-stone-50"
                    @mousedown.prevent="selectAddress(option)"
                  >
                    <span class="font-bold text-stone-900">{{ option.subDistrict }} ต.</span>
                    <span class="text-stone-500">
                      อ. {{ option.district }} จ. {{ option.province }} {{ option.zipcode }}</span
                    >
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </section>

        <!-- ── ปุ่มยืนยัน: มือถือเต็มความกว้าง ── -->
        <div class="flex flex-col-reverse gap-2 border-t border-stone-100 pt-4 sm:flex-row sm:justify-end">
          <button type="submit" class="btn-primary w-full sm:w-auto" :disabled="isSubmitting">
            <span
              v-if="isSubmitting"
              class="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
              aria-hidden="true"
            ></span>
            <span v-else>บันทึกและเข้าสู่ระบบ <i class="bi bi-arrow-right" aria-hidden="true"></i></span>
          </button>
        </div>
      </form>
    </div>
  </div>
</template>
