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

const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!

// --- 💡 1. สร้างตัวแปรตรวจสอบสิทธิ์ (Permissions) ---
const isAdmin = computed(() => authStore.isAdmin)

// สมมติว่านักเรียนคนนี้คือเจ้าของโปรไฟล์ (ดึงข้อมูลนักเรียนของตัวเองในห้องนี้มาเทียบ)
const currentUserProfile = ref<any>(null);
const isOwner = computed(() => {
  if (isAdmin.value) return true; // ถ้าเป็น Admin ก็ถือว่าผ่าน
  if (!currentUserProfile.value) return false;
  // เทียบเลขที่จาก URL กับเลขที่ของ User ที่ล็อกอินอยู่ในห้องนี้
  return String(currentUserProfile.value.student_no) === studentNo;
})

// รวมสิทธิ์: เป็น Admin หรือเป็นเจ้าของโปรไฟล์ถึงจะแก้ได้
const canEdit = computed(() => isAdmin.value || isOwner.value)

const form = ref<Partial<Student>>({
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
  address_post_code: ''
})

const fetchStudent = async () => {
  try {
    loading.value = true
    
    // โหลดข้อมูลโปรไฟล์ของคนที่คลิกเข้ามาดู (ตาม URL)
    const data = await StudentService.getStudentByNo(currentRoomId, studentNo)
    Object.keys(form.value).forEach(key => {
      if (key in data) {
        (form.value as any)[key] = (data as any)[key] || ''
      }
    })

    // โหลดข้อมูลตัวเอง เพื่อเอามาเช็คสิทธิ์ (ถ้าไม่ใช่ Admin)
    if (!isAdmin.value) {
        try {
            currentUserProfile.value = await StudentService.getMyProfile(currentRoomId);
        } catch (e) {
            console.log("Not a student in this room or error fetching my profile", e)
        }
    }

  } catch (error: any) {
    console.error("🔴 สอดแนม Error:", error)
    Swal.fire({
      icon: 'error',
      title: 'เกิดข้อผิดพลาด',
      text: 'ไม่สามารถโหลดข้อมูลได้'
    })
    router.push('/students')
  } finally {
    loading.value = false
  }
}

const handleSubmit = async () => {
  // 💡 2. เปลี่ยนเงื่อนไขการเช็คสิทธิ์ก่อนบันทึก
  if (!canEdit.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'คุณสามารถแก้ไขได้เฉพาะข้อมูลของตัวเองเท่านั้น', 'error')
  }

  try {
    saving.value = true
    const payload: any = { ...form.value }
    
    // 💡 3. Data Sanitization: ล้างข้อมูลก่อนส่งไป Backend เพื่อป้องกัน Error 422
    Object.keys(payload).forEach(key => {
      // 3.1 ลบช่องว่างหัวท้าย ถ้าเป็น String
      if (typeof payload[key] === 'string') {
        payload[key] = payload[key].trim();
        // 3.2 แปลง String ว่างๆ เป็น null (Pydantic Backend ชอบแบบนี้)
        if (payload[key] === "") {
          payload[key] = null;
        }
      }
    })

    // 3.3 บังคับให้ user_name มีค่าเสมอ
    payload.user_name = currentUserName || 'System';

    await StudentService.updateStudent(currentRoomId, studentNo, payload)
    
    await Swal.fire({
      icon: 'success',
      title: 'สำเร็จ',
      text: 'อัปเดตข้อมูลเรียบร้อยแล้ว',
      timer: 1500,
      showConfirmButton: false
    })
    
    router.push(`/students/${studentNo}`)
  } catch (error: any) {
    console.error("Save Error:", error)
    // แกะ Error Message จาก FastAPI 422 ออกมาโชว์ให้คนอ่านรู้เรื่อง
    let errorMsg = 'เกิดข้อผิดพลาดในการบันทึกข้อมูล';
    if (error.response?.status === 422) {
      errorMsg = 'ข้อมูลบางช่องไม่ถูกต้อง กรุณาตรวจสอบอีกครั้ง';
      // ถ้า Backend ส่ง Validation Error กลับมา พยายามแกะมาโชว์
      if (error.response?.data?.detail && Array.isArray(error.response.data.detail)) {
        const errors = error.response.data.detail.map((e: any) => e.loc.join('.') + ': ' + e.msg);
        errorMsg += '\n' + errors.join('\n');
      }
    } else if (error.response?.data?.detail) {
      errorMsg = error.response.data.detail;
    } else if (error.message) {
      errorMsg = error.message;
    }

    Swal.fire({
      icon: 'error',
      title: 'บันทึกไม่สำเร็จ',
      text: errorMsg
    })
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  fetchStudent()
})
</script>

<template>
  <div class="min-h-screen bg-slate-100/50 py-10">
    <div class="container mx-auto px-4 sm:px-6 lg:px-8">
      
      <div v-if="loading" class="flex flex-col justify-center items-center h-[60vh] gap-4">
        <span class="loading loading-spinner loading-lg text-primary"></span>
        <p class="text-slate-500 font-medium animate-pulse">กำลังโหลดข้อมูลโปรไฟล์...</p>
      </div>

      <form v-else @submit.prevent="handleSubmit" class="max-w-5xl mx-auto space-y-8">
        
        <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-6 bg-white p-6 rounded-2xl shadow-sm border border-slate-200">
          <div>
            <div class="flex items-center gap-3 mb-1">
              <div class="p-2 bg-blue-100 rounded-lg text-blue-600">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" /></svg>
              </div>
              <h2 class="text-2xl font-bold text-slate-800">แก้ไขข้อมูลโปรไฟล์</h2>
            </div>
            <p class="text-slate-500 text-sm ml-11">รหัสนักเรียน: <span class="font-semibold text-slate-700">#{{ studentNo }}</span> • อัปเดตข้อมูลให้เป็นปัจจุบัน</p>
          </div>
          
          <div class="flex gap-3 w-full md:w-auto ml-11 md:ml-0">
            <button 
              type="button" 
              @click="router.back()" 
              class="btn bg-slate-100 hover:bg-slate-200 text-slate-700 border-none flex-1 md:flex-none font-medium"
              :disabled="saving"
            >
              ยกเลิก
            </button>
            <!-- 💡 4. เปลี่ยนปุ่ม Save เป็นเช็ค canEdit -->
            <template v-if="canEdit">
              <button 
                type="submit" 
                class="btn bg-blue-600 hover:bg-blue-700 text-white border-none px-8 shadow-lg shadow-blue-600/30 transition-all flex-1 md:flex-none font-medium flex items-center gap-2"
                :disabled="saving"
              >
                <span v-if="saving" class="loading loading-spinner loading-sm"></span>
                <span v-else>💾</span>
                บันทึกการเปลี่ยนแปลง
              </button>
            </template>
            <div v-else class="flex items-center px-4 bg-slate-100 text-slate-500 rounded-lg text-sm font-medium border border-slate-200">
              🔒 สิทธิ์การแก้ไขจำกัด
            </div>
          </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
          
          <div class="card bg-white shadow-sm border border-slate-200 rounded-2xl overflow-hidden">
            <div class="border-b border-slate-200 bg-blue-50/50 px-6 py-4 flex items-center gap-3">
              <span class="text-xl">🔵</span>
              <h3 class="font-bold text-blue-800 text-lg">ข้อมูลส่วนตัวหลัก</h3>
            </div>
            <div class="p-6 space-y-5 bg-slate-50/30">
              <div class="form-control">
                <!-- 💡 5. เปลี่ยน :disabled ให้ยึดตาม canEdit ทุกช่อง -->
                <label class="label pb-1"><span class="label-text font-medium text-slate-700">รหัสนักเรียน</span></label>
                <input :disabled="!canEdit" v-model="form.student_id" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-primary focus:ring-2 focus:ring-primary/20 text-slate-800 h-11 disabled:bg-slate-100" />
              </div>
              <div class="grid grid-cols-2 gap-5">
                <div class="form-control">
                  <label class="label pb-1"><span class="label-text font-medium text-slate-700">คำนำหน้า</span></label>
                  <input :disabled="!canEdit" v-model="form.prefix" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-primary focus:ring-2 focus:ring-primary/20 text-slate-800 h-11 disabled:bg-slate-100" />
                </div>
                <div class="form-control">
                  <label class="label pb-1"><span class="label-text font-medium text-slate-700">ชื่อเล่น</span></label>
                  <input :disabled="!canEdit" v-model="form.nickname" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-primary focus:ring-2 focus:ring-primary/20 text-slate-800 h-11 disabled:bg-slate-100" />
                </div>
              </div>
              <div class="grid grid-cols-2 gap-5">
                <div class="form-control">
                  <label class="label pb-1"><span class="label-text font-medium text-slate-700">ชื่อ <span class="text-red-500">*</span></span></label>
                  <input :disabled="!canEdit" v-model="form.first_name" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-primary focus:ring-2 focus:ring-primary/20 text-slate-800 h-11 disabled:bg-slate-100" required />
                </div>
                <div class="form-control">
                  <label class="label pb-1"><span class="label-text font-medium text-slate-700">นามสกุล <span class="text-red-500">*</span></span></label>
                  <input :disabled="!canEdit" v-model="form.last_name" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-primary focus:ring-2 focus:ring-primary/20 text-slate-800 h-11 disabled:bg-slate-100" required />
                </div>
              </div>
            </div>
          </div>

          <div class="card bg-white shadow-sm border border-slate-200 rounded-2xl overflow-hidden">
            <div class="border-b border-slate-200 bg-red-50/50 px-6 py-4 flex items-center gap-3">
              <span class="text-xl">🔴</span>
              <h3 class="font-bold text-red-800 text-lg">ข้อมูลสุขภาพ</h3>
            </div>
            <div class="p-6 space-y-5 bg-slate-50/30">
              <div class="grid grid-cols-2 gap-5">
                <div class="form-control">
                  <label class="label pb-1"><span class="label-text font-medium text-slate-700">กรุ๊ปเลือด</span></label>
                  <input :disabled="!canEdit" v-model="form.blood_group" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-red-400 focus:ring-2 focus:ring-red-400/20 text-slate-800 h-11 disabled:bg-slate-100" placeholder="A, B, O, AB" />
                </div>
                <div class="form-control">
                  <label class="label pb-1"><span class="label-text font-medium text-slate-700">ไซส์เสื้อ</span></label>
                  <input :disabled="!canEdit" v-model="form.shirt_size" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-red-400 focus:ring-2 focus:ring-red-400/20 text-slate-800 h-11 disabled:bg-slate-100" placeholder="S, M, L, XL" />
                </div>
              </div>
              <div class="form-control">
                <label class="label pb-1"><span class="label-text font-medium text-slate-700">โรคประจำตัว / แพ้อาหาร</span></label>
                <input :disabled="!canEdit" v-model="form.food_allergy" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-red-400 focus:ring-2 focus:ring-red-400/20 text-slate-800 h-11 disabled:bg-slate-100" placeholder="ถ้าไม่มีให้ระบุ 'ไม่มี'" />
              </div>
            </div>
          </div>

          <div class="card bg-white shadow-sm border border-slate-200 rounded-2xl overflow-hidden">
            <div class="border-b border-slate-200 bg-purple-50/50 px-6 py-4 flex items-center gap-3">
              <span class="text-xl">🟣</span>
              <h3 class="font-bold text-purple-800 text-lg">ข้อมูลการติดต่อ</h3>
            </div>
            <div class="p-6 space-y-5 bg-slate-50/30">
              <div class="form-control">
                <label class="label pb-1"><span class="label-text font-medium text-slate-700">เบอร์โทรศัพท์</span></label>
                <input :disabled="!canEdit" v-model="form.phone_number" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 text-slate-800 h-11 disabled:bg-slate-100" />
              </div>
              <div class="grid grid-cols-2 gap-5">
                <div class="form-control">
                  <label class="label pb-1"><span class="label-text font-medium text-slate-700">เบอร์ผู้ปกครอง</span></label>
                  <input :disabled="!canEdit" v-model="form.phone_number_parent" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 text-slate-800 h-11 disabled:bg-slate-100" />
                </div>
                <div class="form-control">
                  <label class="label pb-1"><span class="label-text font-medium text-slate-700">เกี่ยวข้องเป็น</span></label>
                  <input :disabled="!canEdit" v-model="form.phone_number_parent_relation" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 text-slate-800 h-11 disabled:bg-slate-100" placeholder="เช่น บิดา, มารดา" />
                </div>
              </div>
              <div class="grid grid-cols-2 gap-5">
                <div class="form-control">
                  <label class="label pb-1"><span class="label-text font-medium text-slate-700">Line ID</span></label>
                  <input :disabled="!canEdit" v-model="form.line_id" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 text-slate-800 h-11 disabled:bg-slate-100" />
                </div>
                <div class="form-control">
                  <label class="label pb-1"><span class="label-text font-medium text-slate-700">IG Username</span></label>
                  <input :disabled="!canEdit" v-model="form.ig_username" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-purple-400 focus:ring-2 focus:ring-purple-400/20 text-slate-800 h-11 disabled:bg-slate-100" />
                </div>
              </div>
            </div>
          </div>

          <div class="card bg-white shadow-sm border border-slate-200 rounded-2xl overflow-hidden">
            <div class="border-b border-slate-200 bg-amber-50/50 px-6 py-4 flex items-center gap-3">
              <span class="text-xl">📚</span>
              <h3 class="font-bold text-amber-800 text-lg">วิชาการและหน้าที่</h3>
            </div>
            <div class="p-6 space-y-5 bg-slate-50/30 flex flex-col h-full">
              <div class="grid grid-cols-2 gap-5">
                <div class="form-control">
                  <label class="label pb-1"><span class="label-text font-medium text-slate-700">คณะที่ใฝ่ฝัน</span></label>
                  <input :disabled="!canEdit" v-model="form.target_faculty" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-amber-400 focus:ring-2 focus:ring-amber-400/20 text-slate-800 h-11 disabled:bg-slate-100" />
                </div>
                <div class="form-control">
                  <label class="label pb-1"><span class="label-text font-medium text-slate-700">เวรทำความสะอาด</span></label>
                  <input :disabled="!canEdit" v-model="form.cleaning_duty" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-amber-400 focus:ring-2 focus:ring-amber-400/20 text-slate-800 h-11 disabled:bg-slate-100" placeholder="เช่น วันจันทร์" />
                </div>
              </div>
              <div class="form-control flex-grow">
                <label class="label pb-1"><span class="label-text font-medium text-slate-700">สอวน. / ค่ายวิชาการ</span></label>
                <textarea :disabled="!canEdit" v-model="form.olympic_camp" class="textarea textarea-bordered w-full h-32 bg-white border-slate-300 shadow-sm focus:border-amber-400 focus:ring-2 focus:ring-amber-400/20 text-slate-800 text-base py-3 leading-relaxed disabled:bg-slate-100" placeholder="ระบุค่ายวิชาการที่เคยเข้าร่วม (เว้นบรรทัดได้)"></textarea>
              </div>
            </div>
          </div>

          <div class="lg:col-span-2">
            <div class="card bg-white shadow-sm border border-slate-200 rounded-2xl overflow-hidden">
              <div class="border-b border-slate-200 bg-orange-50/50 px-6 py-4 flex items-center gap-3">
                <span class="text-xl">🏆</span>
                <h3 class="font-bold text-orange-800 text-lg">ผลงาน / รางวัลที่เคยได้รับ</h3>
              </div>
              <div class="p-6 bg-slate-50/30">
                <textarea :disabled="!canEdit" v-model="form.portfolio" class="textarea textarea-bordered w-full h-48 bg-white border-slate-300 shadow-sm focus:border-orange-400 focus:ring-2 focus:ring-orange-400/20 text-slate-800 text-base p-4 leading-relaxed disabled:bg-slate-100" placeholder="เล่าผลงานเด่นๆ หรือรางวัลที่ประทับใจของคุณที่นี่... (สามารถเว้นบรรทัดและพิมพ์ยาวๆ ได้เลย)"></textarea>
              </div>
            </div>
          </div>

          <div class="lg:col-span-2">
            <div class="card bg-white shadow-sm border border-slate-200 rounded-2xl overflow-hidden mb-8">
              <div class="border-b border-slate-200 bg-gray-100 px-6 py-4 flex items-center gap-3">
                <span class="text-xl">🏠</span>
                <h3 class="font-bold text-gray-800 text-lg">ข้อมูลที่อยู่ตามทะเบียนบ้าน</h3>
              </div>
              <div class="p-6 bg-slate-50/30">
                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
                  <div class="form-control">
                    <label class="label pb-1"><span class="label-text font-medium text-slate-700">บ้านเลขที่/หมู่/ซอย</span></label>
                    <input :disabled="!canEdit" v-model="form.address_house_no" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-gray-400 focus:ring-2 focus:ring-gray-400/20 text-slate-800 h-11 disabled:bg-slate-100" />
                  </div>
                  <div class="form-control">
                    <label class="label pb-1"><span class="label-text font-medium text-slate-700">ถนน</span></label>
                    <input :disabled="!canEdit" v-model="form.address_road" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-gray-400 focus:ring-2 focus:ring-gray-400/20 text-slate-800 h-11 disabled:bg-slate-100" />
                  </div>
                  <div class="form-control">
                    <label class="label pb-1"><span class="label-text font-medium text-slate-700">ตำบล / แขวง</span></label>
                    <input :disabled="!canEdit" v-model="form.address_sub_district" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-gray-400 focus:ring-2 focus:ring-gray-400/20 text-slate-800 h-11 disabled:bg-slate-100" />
                  </div>
                  <div class="form-control">
                    <label class="label pb-1"><span class="label-text font-medium text-slate-700">อำเภอ / เขต</span></label>
                    <input :disabled="!canEdit" v-model="form.address_district" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-gray-400 focus:ring-2 focus:ring-gray-400/20 text-slate-800 h-11 disabled:bg-slate-100" />
                  </div>
                  <div class="form-control md:col-span-1 lg:col-span-2">
                    <label class="label pb-1"><span class="label-text font-medium text-slate-700">จังหวัด</span></label>
                    <input :disabled="!canEdit" v-model="form.address_province" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-gray-400 focus:ring-2 focus:ring-gray-400/20 text-slate-800 h-11 disabled:bg-slate-100" />
                  </div>
                  <div class="form-control md:col-span-1 lg:col-span-2">
                    <label class="label pb-1"><span class="label-text font-medium text-slate-700">รหัสไปรษณีย์</span></label>
                    <input :disabled="!canEdit" v-model="form.address_post_code" type="text" class="input input-bordered w-full bg-white border-slate-300 shadow-sm focus:border-gray-400 focus:ring-2 focus:ring-gray-400/20 text-slate-800 h-11 disabled:bg-slate-100" />
                  </div>
                </div>
              </div>
            </div>
          </div>

        </div>
      </form>
    </div>
  </div>
</template>