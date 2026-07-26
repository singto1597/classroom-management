<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import StudentService from '@/services/student'
import type { Student } from '@/types/student'
import Swal from 'sweetalert2'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const studentNo = route.params.id as string
const loading = ref(true)
const saving = ref(false)

// 🎯 สถานะควบคุมการเปิด-ปิดฟอร์ม
const isEditMode = ref(false) 

const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!

// เช็คว่าคนที่ Login เป็น God Admin ไหม
const isAdmin = computed(() => authStore.isAdmin)

// รายการสิทธิ์ย่อยทั้งหมดที่มีในระบบ
const AVAILABLE_PERMISSIONS = [
  { id: 'VIEW_ALL_STUDENTS', label: 'ดูข้อมูลนักเรียนทุกคนแบบเชิงลึก' },
  { id: 'MANAGE_STUDENTS', label: 'จัดการนักเรียน (รับเข้า, ลบ, แก้ไขข้อมูล)' },
  { id: 'EXPORT_STUDENTS', label: 'ดาวน์โหลดข้อมูลออกเป็นไฟล์ Excel' },
  { id: 'MANAGE_FINANCE', label: 'จัดการระบบการเงินของห้อง' },
  { id: 'MANAGE_CLASSROOM_SETTINGS', label: 'ตั้งค่าห้องเรียนขั้นสูง' },
  { id: 'MANAGE_CLASSROOM_TASKS', label: 'จัดการงานและตารางเรียน' }
]

// สมมติว่านักเรียนคนนี้คือเจ้าของโปรไฟล์ (ดึงข้อมูลนักเรียนของตัวเองในห้องนี้มาเทียบ)
const currentUserProfile = ref<any>(null);
const isOwner = computed(() => {
  if (isAdmin.value) return true; 
  if (!currentUserProfile.value) return false;
  return String(currentUserProfile.value.student_no) === studentNo;
})

// รวมสิทธิ์: เป็น Admin หรือเป็นเจ้าของโปรไฟล์ถึงจะกด "เปิดโหมดแก้ไข" ได้
const canEdit = computed(() => isAdmin.value || isOwner.value)

// 🎯 เพิ่มฟิลด์สำหรับระบบ RBAC และ Moving Target
const form = ref<Partial<Student> & { new_student_no?: number | null, is_admin?: boolean, permissions?: string[] }>({
  new_student_no: null,
  is_admin: false,
  permissions: [],
  student_id: null,
  prefix: '',
  first_name: '',
  last_name: '',
  nickname: '',
  blood_group: '',
  shirt_size: '',
  food_allergy: '',
  phone_number: '',
  phone_number_parent: '',
  phone_number_parent_relation: '',
  line_id: '',
  ig_username: '',
  target_faculty: '',
  cleaning_duty: '',
  olympic_camp: '',
  portfolio: '',
  address_house_no: '',
  address_road: '',
  address_sub_district: '',
  address_district: '',
  address_province: '',
  address_post_code: '',
  class_role: 'student'
})

const fetchStudent = async () => {
  try {
    loading.value = true
    
    // โหลดข้อมูลโปรไฟล์ของคนที่คลิกเข้ามาดู
    const data = await StudentService.getStudentByNo(currentRoomId, studentNo)
    Object.keys(form.value).forEach(key => {
      if (key in data) {
        (form.value as any)[key] = (data as any)[key] || ''
      }
    })

    // 🎯 โหลดค่าพิเศษ
    form.value.new_student_no = data.student_no
    form.value.is_admin = (data as any).is_admin || false
    form.value.permissions = (data as any).permissions || []

    // โหลดข้อมูลตัวเอง เพื่อเอามาเช็คสิทธิ์การเป็นเจ้าของ (ถ้าไม่ใช่ Admin)
    if (!isAdmin.value) {
        try {
            currentUserProfile.value = await StudentService.getMyProfile(currentRoomId);
        } catch (e) {
            console.log("Not a student in this room", e)
        }
    }

  } catch (error: any) {
    Swal.fire({ icon: 'error', title: 'เกิดข้อผิดพลาด', text: 'ไม่สามารถโหลดข้อมูลได้' })
    router.push('/students')
  } finally {
    loading.value = false
  }
}

// 🎯 ฟังก์ชันสลับโหมดแก้ไข
const toggleEditMode = () => {
  if (canEdit.value) {
    isEditMode.value = !isEditMode.value
  } else {
    Swal.fire('ปฏิเสธการเข้าถึง', 'คุณสามารถแก้ไขได้เฉพาะข้อมูลของตัวเองเท่านั้น', 'error')
  }
}

// 🎯 ฟังก์ชันเลือกสิทธิ์ย่อย
const togglePermission = (permId: string) => {
  if (!form.value.permissions) form.value.permissions = [];
  const idx = form.value.permissions.indexOf(permId);
  if (idx > -1) form.value.permissions.splice(idx, 1);
  else form.value.permissions.push(permId);
}

const handleSubmit = async () => {
  if (!canEdit.value) return Swal.fire('ไม่มีสิทธิ์', 'คุณแก้ได้เฉพาะข้อมูลตัวเอง', 'error')

  try {
    saving.value = true
    const payload: any = { ...form.value }
    
    // ล้างข้อมูลก่อนส่งไป Backend
    Object.keys(payload).forEach(key => {
      if (typeof payload[key] === 'string') {
        payload[key] = payload[key].trim();
        if (payload[key] === "") payload[key] = null;
      }
    })

    payload.user_name = currentUserName || 'System';

    await StudentService.updateStudent(currentRoomId, studentNo, payload)
    
    await Swal.fire({
      icon: 'success',
      title: 'สำเร็จ',
      text: 'อัปเดตข้อมูลเรียบร้อยแล้ว',
      timer: 1500,
      showConfirmButton: false
    })
    
    // 🎯 The Moving Target: Redirect ไปเลขที่ใหม่ทันทีถ้ามีการเปลี่ยนเลขที่
    const finalStudentNo = payload.new_student_no ? payload.new_student_no : studentNo;
    router.push(`/students/${finalStudentNo}`)

  } catch (error: any) {
    let errorMsg = error.response?.data?.detail || error.message || 'เกิดข้อผิดพลาดในการบันทึกข้อมูล';
    if (error.response?.status === 422) errorMsg = 'ข้อมูลบางช่องไม่ถูกต้อง กรุณาตรวจสอบอีกครั้ง';
    Swal.fire({ icon: 'error', title: 'บันทึกไม่สำเร็จ', text: errorMsg })
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  fetchStudent()
})
</script>

<template>
  <div class="min-h-screen bg-slate-50 py-8 md:py-12">
    <div class="container mx-auto px-4 sm:px-6 lg:px-8 max-w-6xl">
      
      <div v-if="loading" class="flex flex-col justify-center items-center h-[60vh] gap-4">
        <span class="loading loading-spinner loading-lg text-blue-600"></span>
        <p class="text-slate-500 font-bold animate-pulse tracking-wide">กำลังเตรียมข้อมูล...</p>
      </div>

      <form v-else @submit.prevent="handleSubmit" class="space-y-6 md:space-y-8">
        
        <!-- ✨ Header & Control Bar -->
        <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-6 bg-white p-6 rounded-[2rem] shadow-sm border border-slate-200 sticky top-4 z-50">
          <div>
            <div class="flex items-center gap-3 mb-1">
              <div class="p-2.5 bg-blue-50 rounded-xl text-blue-600 border border-blue-100 shadow-inner">
                <i class="bi bi-person-lines-fill text-xl"></i>
              </div>
              <h2 class="text-2xl font-black text-slate-800 tracking-tight">จัดการข้อมูลโปรไฟล์</h2>
            </div>
            <p class="text-slate-500 text-sm ml-[3.25rem]">รหัสนักเรียน: <span class="font-bold text-slate-700">#{{ studentNo }}</span></p>
          </div>
          
          <div class="flex flex-wrap gap-3 w-full md:w-auto ml-[3.25rem] md:ml-0">
            <button type="button" @click="router.back()" class="btn bg-slate-100 hover:bg-slate-200 text-slate-600 border-none flex-1 md:flex-none font-bold rounded-xl" :disabled="saving">
              <i class="bi bi-arrow-left"></i> กลับ
            </button>
            
            <template v-if="canEdit">
              <!-- 🎯 ปุ่มเปิด-ปิดโหมด -->
              <button 
                type="button" 
                @click="toggleEditMode" 
                class="btn border-none flex-1 md:flex-none transition-all rounded-xl shadow-sm"
                :class="isEditMode ? 'bg-amber-100 text-amber-700 hover:bg-amber-200' : 'bg-blue-100 text-blue-700 hover:bg-blue-200'"
                :disabled="saving"
              >
                <i :class="isEditMode ? 'bi bi-x-lg' : 'bi bi-pencil-square'"></i>
                {{ isEditMode ? 'ยกเลิกการแก้ไข' : 'เปิดโหมดแก้ไข' }}
              </button>

              <!-- 🎯 ปุ่ม Save (ซ่อนไว้จนกว่าจะกดเปิดโหมด) -->
              <button 
                v-if="isEditMode"
                type="submit" 
                class="btn bg-blue-600 hover:bg-blue-700 text-white border-none px-8 shadow-lg shadow-blue-600/30 rounded-xl flex-1 md:flex-none font-bold flex items-center gap-2"
                :disabled="saving"
              >
                <span v-if="saving" class="loading loading-spinner loading-sm"></span>
                <span v-else><i class="bi bi-floppy2-fill"></i></span>
                บันทึกการเปลี่ยนแปลง
              </button>
            </template>
            <div v-else class="flex items-center px-4 py-3 bg-slate-50 text-slate-400 rounded-xl text-sm font-bold border border-slate-200">
              <i class="bi bi-lock-fill me-2"></i> สิทธิ์จำกัด
            </div>
          </div>
        </div>

        <!-- 🚀 ADMIN CONTROL PANEL (เห็นเฉพาะ Admin ตัวจริง เมื่อเปิดโหมด Edit) -->
        <div v-if="isAdmin && isEditMode" class="bg-slate-900 rounded-[2rem] shadow-2xl border border-slate-700 overflow-hidden relative transform transition-all animate-fade-in-up">
          <div class="absolute inset-0 bg-gradient-to-br from-blue-500/10 via-transparent to-purple-500/10 pointer-events-none"></div>
          
          <div class="px-6 md:px-8 py-5 flex items-center justify-between border-b border-slate-700/50 bg-black/20">
            <h3 class="font-black text-white text-lg flex items-center gap-3 tracking-wide">
              <span class="w-8 h-8 rounded-lg bg-emerald-500/20 text-emerald-400 flex items-center justify-center border border-emerald-500/30">
                <i class="bi bi-shield-lock-fill"></i>
              </span>
              ผู้ดูแลระบบ (Admin Zone)
            </h3>
            <span class="text-[10px] bg-rose-500/20 text-rose-300 px-3 py-1 rounded-full font-bold border border-rose-500/30 uppercase tracking-widest animate-pulse">Danger Zone</span>
          </div>
          
          <div class="p-6 md:p-8 relative z-10 space-y-8">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div class="space-y-2">
                <label class="text-xs font-black text-slate-400 uppercase tracking-widest">เปลี่ยนเลขที่นักเรียน</label>
                <input v-model="form.new_student_no" type="number" class="w-full bg-slate-950 border border-slate-700 text-white focus:border-emerald-400 focus:ring-1 focus:ring-emerald-400 rounded-xl px-4 py-3 outline-none transition-colors" />
                <p class="text-[11px] text-slate-500 mt-1"><i class="bi bi-info-circle"></i> เปลี่ยนแล้วระบบจะทำการย้ายข้อมูลทั้งหมดไปที่เลขที่ใหม่</p>
              </div>
              <div class="space-y-2">
                <label class="text-xs font-black text-slate-400 uppercase tracking-widest">ป้ายตำแหน่ง (Cosmetic)</label>
                <select v-model="form.class_role" class="w-full bg-slate-950 border border-slate-700 text-white focus:border-emerald-400 focus:ring-1 focus:ring-emerald-400 rounded-xl px-4 py-3 outline-none transition-colors appearance-none">
                  <option value="student">🧑‍🎓 นักเรียนทั่วไป (Student)</option>
                  <option value="president">👑 หัวหน้าห้อง (President)</option>
                  <option value="vice_academic">📖 รองฯ วิชาการ</option>
                  <option value="vice_activity">🎭 รองฯ กิจกรรม</option>
                  <option value="vice_discipline">⚖️ รองฯ ระเบียบวินัย</option>
                  <option value="vice_reception">🤝 รองฯ ปฏิคม</option>
                  <option value="staff_academic">📝 กรรมการวิชาการ</option>
                  <option value="staff_activity">🎪 กรรมการกิจกรรม</option>
                  <option value="staff_discipline">🛡️ กรรมการระเบียบวินัย</option>
                  <option value="staff_reception">🎀 กรรมการปฏิคม</option>
                  <option value="treasurer">💰 เหรัญญิก</option>
                </select>
                <p class="text-[11px] text-slate-500 mt-1"><i class="bi bi-info-circle"></i> แสดงผลบนหน้าเว็บเท่านั้น ไม่มีผลกับสิทธิ์</p>
              </div>
            </div>

            <div class="bg-slate-800/50 rounded-2xl p-6 border border-slate-700">
              <label class="flex items-center gap-4 cursor-pointer mb-6 pb-6 border-b border-slate-700/50 group">
                <input type="checkbox" v-model="form.is_admin" class="toggle toggle-success toggle-lg group-hover:scale-105 transition-transform" />
                <div>
                  <span class="font-black text-emerald-400 text-lg block tracking-wide">GOD MODE (มอบสิทธิ์ผู้ดูแลระบบสูงสุด)</span>
                  <span class="text-xs text-slate-400 font-medium">หากเปิดโหมดนี้ นักเรียนคนนี้จะสามารถทำได้ทุกอย่างในห้องโดยไม่ต้องสนใจสิทธิ์ย่อยด้านล่าง</span>
                </div>
              </label>

              <div class="space-y-4" :class="{'opacity-30 pointer-events-none grayscale transition-all': form.is_admin}">
                <p class="text-sm font-bold text-slate-300 flex items-center gap-2">
                  <i class="bi bi-ui-checks-grid text-blue-400"></i> กำหนดสิทธิ์ย่อย (Custom Permissions):
                </p>
                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  <label v-for="perm in AVAILABLE_PERMISSIONS" :key="perm.id" class="flex items-start gap-3 bg-slate-900/80 p-4 rounded-xl border border-slate-700/80 cursor-pointer hover:border-blue-500/50 hover:bg-slate-800 transition-colors">
                    <input type="checkbox" class="checkbox checkbox-info checkbox-sm mt-0.5" 
                           :checked="form.permissions?.includes(perm.id)"
                           @change="togglePermission(perm.id)" />
                    <span class="text-xs font-bold text-slate-300 leading-relaxed">{{ perm.label }}</span>
                  </label>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 📝 FORM CONTENT (ปรับให้ดูจางๆ ลงเวลาไม่ได้อยู่ในโหมด Edit) -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 md:gap-8 transition-all duration-500" :class="{ 'opacity-80 grayscale-[0.1] pointer-events-none': !isEditMode }">
          
          <!-- Personal Info -->
          <div class="bg-white shadow-sm border border-slate-200 rounded-[2rem] overflow-hidden">
            <div class="border-b border-slate-100 bg-blue-50/30 px-6 py-5 flex items-center gap-3">
              <div class="w-8 h-8 rounded-lg bg-blue-100 text-blue-600 flex items-center justify-center"><i class="bi bi-person-fill"></i></div>
              <h3 class="font-black text-slate-800 text-lg tracking-tight">ข้อมูลส่วนตัว</h3>
            </div>
            <div class="p-6 md:p-8 space-y-6">
              <div class="space-y-2">
                <label class="text-xs font-black text-slate-400 uppercase tracking-widest">รหัสนักเรียน (ประจำตัว)</label>
                <input :disabled="!isEditMode" v-model="form.student_id" type="text" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" />
              </div>
              <div class="grid grid-cols-2 gap-5">
                <div class="space-y-2">
                  <label class="text-xs font-black text-slate-400 uppercase tracking-widest">คำนำหน้า</label>
                  <input :disabled="!isEditMode" v-model="form.prefix" type="text" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" />
                </div>
                <div class="space-y-2">
                  <label class="text-xs font-black text-slate-400 uppercase tracking-widest">ชื่อเล่น</label>
                  <input :disabled="!isEditMode" v-model="form.nickname" type="text" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" />
                </div>
              </div>
              <div class="grid grid-cols-2 gap-5">
                <div class="space-y-2">
                  <label class="text-xs font-black text-slate-400 uppercase tracking-widest flex justify-between">ชื่อจริง <span class="text-rose-500 text-[10px]">*</span></label>
                  <input :disabled="!isEditMode" v-model="form.first_name" type="text" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" required />
                </div>
                <div class="space-y-2">
                  <label class="text-xs font-black text-slate-400 uppercase tracking-widest flex justify-between">นามสกุล <span class="text-rose-500 text-[10px]">*</span></label>
                  <input :disabled="!isEditMode" v-model="form.last_name" type="text" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" required />
                </div>
              </div>
            </div>
          </div>

          <!-- Health Info -->
          <div class="bg-white shadow-sm border border-slate-200 rounded-[2rem] overflow-hidden">
            <div class="border-b border-slate-100 bg-rose-50/30 px-6 py-5 flex items-center gap-3">
              <div class="w-8 h-8 rounded-lg bg-rose-100 text-rose-600 flex items-center justify-center"><i class="bi bi-heart-pulse-fill"></i></div>
              <h3 class="font-black text-slate-800 text-lg tracking-tight">ข้อมูลสุขภาพ</h3>
            </div>
            <div class="p-6 md:p-8 space-y-6">
              <div class="grid grid-cols-2 gap-5">
                <div class="space-y-2">
                  <label class="text-xs font-black text-slate-400 uppercase tracking-widest">กรุ๊ปเลือด</label>
                  <input :disabled="!isEditMode" v-model="form.blood_group" type="text" placeholder="A, B, O, AB" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-rose-400 focus:ring-2 focus:ring-rose-400/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" />
                </div>
                <div class="space-y-2">
                  <label class="text-xs font-black text-slate-400 uppercase tracking-widest">ไซส์เสื้อ</label>
                  <input :disabled="!isEditMode" v-model="form.shirt_size" type="text" placeholder="S, M, L, XL" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-rose-400 focus:ring-2 focus:ring-rose-400/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" />
                </div>
              </div>
              <div class="space-y-2">
                <label class="text-xs font-black text-slate-400 uppercase tracking-widest">โรคประจำตัว / แพ้อาหาร</label>
                <input :disabled="!isEditMode" v-model="form.food_allergy" type="text" placeholder="ถ้าไม่มีให้ระบุ 'ไม่มี'" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-rose-400 focus:ring-2 focus:ring-rose-400/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" />
              </div>
            </div>
          </div>

          <!-- Contact Info -->
          <div class="bg-white shadow-sm border border-slate-200 rounded-[2rem] overflow-hidden">
            <div class="border-b border-slate-100 bg-purple-50/30 px-6 py-5 flex items-center gap-3">
              <div class="w-8 h-8 rounded-lg bg-purple-100 text-purple-600 flex items-center justify-center"><i class="bi bi-telephone-fill"></i></div>
              <h3 class="font-black text-slate-800 text-lg tracking-tight">ข้อมูลการติดต่อ</h3>
            </div>
            <div class="p-6 md:p-8 space-y-6">
              <div class="space-y-2">
                <label class="text-xs font-black text-slate-400 uppercase tracking-widest">เบอร์โทรศัพท์ (ตัวเอง)</label>
                <input :disabled="!isEditMode" v-model="form.phone_number" type="text" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" />
              </div>
              <div class="grid grid-cols-2 gap-5">
                <div class="space-y-2">
                  <label class="text-xs font-black text-slate-400 uppercase tracking-widest">เบอร์ผู้ปกครอง</label>
                  <input :disabled="!isEditMode" v-model="form.phone_number_parent" type="text" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" />
                </div>
                <div class="space-y-2">
                  <label class="text-xs font-black text-slate-400 uppercase tracking-widest">เกี่ยวข้องเป็น</label>
                  <input :disabled="!isEditMode" v-model="form.phone_number_parent_relation" type="text" placeholder="เช่น บิดา, มารดา" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" />
                </div>
              </div>
              <div class="grid grid-cols-2 gap-5">
                <div class="space-y-2">
                  <label class="text-xs font-black text-slate-400 uppercase tracking-widest">Line ID</label>
                  <input :disabled="!isEditMode" v-model="form.line_id" type="text" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" />
                </div>
                <div class="space-y-2">
                  <label class="text-xs font-black text-slate-400 uppercase tracking-widest">IG Username</label>
                  <input :disabled="!isEditMode" v-model="form.ig_username" type="text" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" />
                </div>
              </div>
            </div>
          </div>

          <!-- Academic Info -->
          <div class="bg-white shadow-sm border border-slate-200 rounded-[2rem] overflow-hidden">
            <div class="border-b border-slate-100 bg-amber-50/30 px-6 py-5 flex items-center gap-3">
              <div class="w-8 h-8 rounded-lg bg-amber-100 text-amber-600 flex items-center justify-center"><i class="bi bi-book-half"></i></div>
              <h3 class="font-black text-slate-800 text-lg tracking-tight">วิชาการและหน้าที่</h3>
            </div>
            <div class="p-6 md:p-8 space-y-6 flex flex-col h-[calc(100%-4.5rem)]">
              <div class="grid grid-cols-2 gap-5">
                <div class="space-y-2">
                  <label class="text-xs font-black text-slate-400 uppercase tracking-widest">คณะที่ใฝ่ฝัน</label>
                  <input :disabled="!isEditMode" v-model="form.target_faculty" type="text" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-amber-400 focus:ring-2 focus:ring-amber-400/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" />
                </div>
                <div class="space-y-2">
                  <label class="text-xs font-black text-slate-400 uppercase tracking-widest">เวรทำความสะอาด</label>
                  <input :disabled="!isEditMode" v-model="form.cleaning_duty" type="text" placeholder="เช่น วันจันทร์" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-amber-400 focus:ring-2 focus:ring-amber-400/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" />
                </div>
              </div>
              <div class="space-y-2 flex-grow">
                <label class="text-xs font-black text-slate-400 uppercase tracking-widest">สอวน. / ค่ายวิชาการ</label>
                <textarea :disabled="!isEditMode" v-model="form.olympic_camp" class="w-full h-full min-h-[120px] bg-slate-50 border border-slate-200 text-slate-800 rounded-2xl px-5 py-4 focus:bg-white focus:border-amber-400 focus:ring-2 focus:ring-amber-400/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100 leading-relaxed resize-none" placeholder="ระบุค่ายวิชาการที่เคยเข้าร่วม (เว้นบรรทัดได้)"></textarea>
              </div>
            </div>
          </div>

          <!-- Portfolio -->
          <div class="lg:col-span-2 bg-white shadow-sm border border-slate-200 rounded-[2rem] overflow-hidden">
            <div class="border-b border-slate-100 bg-orange-50/30 px-6 py-5 flex items-center gap-3">
              <div class="w-8 h-8 rounded-lg bg-orange-100 text-orange-600 flex items-center justify-center"><i class="bi bi-trophy-fill"></i></div>
              <h3 class="font-black text-slate-800 text-lg tracking-tight">ผลงาน / รางวัลที่ประทับใจ</h3>
            </div>
            <div class="p-6 md:p-8">
              <textarea :disabled="!isEditMode" v-model="form.portfolio" class="w-full min-h-[200px] bg-slate-50 border border-slate-200 text-slate-800 rounded-2xl px-6 py-5 focus:bg-white focus:border-orange-400 focus:ring-2 focus:ring-orange-400/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100 leading-relaxed resize-none" placeholder="เล่าผลงานเด่นๆ หรือรางวัลที่ประทับใจของคุณที่นี่..."></textarea>
            </div>
          </div>

          <!-- Address -->
          <div class="lg:col-span-2 bg-white shadow-sm border border-slate-200 rounded-[2rem] overflow-hidden mb-8">
            <div class="border-b border-slate-100 bg-emerald-50/30 px-6 py-5 flex items-center gap-3">
              <div class="w-8 h-8 rounded-lg bg-emerald-100 text-emerald-600 flex items-center justify-center"><i class="bi bi-house-door-fill"></i></div>
              <h3 class="font-black text-slate-800 text-lg tracking-tight">ที่อยู่ตามทะเบียนบ้าน</h3>
            </div>
            <div class="p-6 md:p-8">
              <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                <div class="space-y-2">
                  <label class="text-xs font-black text-slate-400 uppercase tracking-widest">บ้านเลขที่/หมู่/ซอย</label>
                  <input :disabled="!isEditMode" v-model="form.address_house_no" type="text" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-emerald-400 focus:ring-2 focus:ring-emerald-400/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" />
                </div>
                <div class="space-y-2">
                  <label class="text-xs font-black text-slate-400 uppercase tracking-widest">ถนน</label>
                  <input :disabled="!isEditMode" v-model="form.address_road" type="text" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-emerald-400 focus:ring-2 focus:ring-emerald-400/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" />
                </div>
                <div class="space-y-2">
                  <label class="text-xs font-black text-slate-400 uppercase tracking-widest">ตำบล / แขวง</label>
                  <input :disabled="!isEditMode" v-model="form.address_sub_district" type="text" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-emerald-400 focus:ring-2 focus:ring-emerald-400/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" />
                </div>
                <div class="space-y-2">
                  <label class="text-xs font-black text-slate-400 uppercase tracking-widest">อำเภอ / เขต</label>
                  <input :disabled="!isEditMode" v-model="form.address_district" type="text" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-emerald-400 focus:ring-2 focus:ring-emerald-400/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" />
                </div>
                <div class="space-y-2 md:col-span-1 lg:col-span-2">
                  <label class="text-xs font-black text-slate-400 uppercase tracking-widest">จังหวัด</label>
                  <input :disabled="!isEditMode" v-model="form.address_province" type="text" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-emerald-400 focus:ring-2 focus:ring-emerald-400/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" />
                </div>
                <div class="space-y-2 md:col-span-1 lg:col-span-2">
                  <label class="text-xs font-black text-slate-400 uppercase tracking-widest">รหัสไปรษณีย์</label>
                  <input :disabled="!isEditMode" v-model="form.address_post_code" type="text" class="w-full bg-slate-50 border border-slate-200 text-slate-800 rounded-xl px-4 py-3 focus:bg-white focus:border-emerald-400 focus:ring-2 focus:ring-emerald-400/20 outline-none transition-all disabled:bg-slate-100 disabled:text-slate-500 disabled:border-slate-100" />
                </div>
              </div>
            </div>
          </div>

        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
@keyframes fadeInUp {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
.animate-fade-in-up {
  animation: fadeInUp 0.4s ease-out forwards;
}
</style>