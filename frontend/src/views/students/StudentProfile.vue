<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import StudentService from '@/services/student'
// import type { Student } from '@/types/student' // ไม่ได้ใช้ใน template ตอนนี้คอมเม้นไว้ก่อน
import { displayName } from '@/utils/name'
import Swal from 'sweetalert2'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const studentNo = route.params.id as string
const student = ref<any | null>(null)
const loading = ref(true)

const currentRoomId = authStore.currentRoomId!

// 🏷️ แปลง class_role → ภาษาไทย (ให้ตรงกับ StudentList)
const ROLE_LABELS: Record<string, string> = {
  student: 'นักเรียน',
  president: 'หัวหน้าห้อง',
  vice_president: 'รองหัวหน้าห้อง',
  secretary: 'เลขานุการ (เรขา)',
  vice_academic: 'รองวิชาการ',
  vice_activity: 'รองกิจกรรม',
  vice_discipline: 'รองระเบียบวินัย',
  vice_reception: 'รองปฏิคม',
  vice_pr: 'รองประชาสัมพันธ์',
  vice_sanitation: 'รองสุขาภิบาล',
  staff_academic: 'กรรมการวิชาการ',
  staff_activity: 'กรรมการกิจกรรม',
  staff_discipline: 'กรรมการระเบียบวินัย',
  staff_reception: 'กรรมการปฏิคม',
  staff_pr: 'กรรมการประชาสัมพันธ์',
  staff_sanitation: 'กรรมการสุขาภิบาล',
  treasurer: 'เหรัญญิก'
};

const roleLabel = (role: string) => ROLE_LABELS[role] || role || 'นักเรียน';

// 🎯 เงื่อนไขสำหรับแสดงปุ่ม "แก้ไขข้อมูล"
const canEdit = computed(() => {
  return authStore.isAdmin || 
         authStore.currentPermissions.includes('MANAGE_STUDENTS') || 
         String(student.value?.user_id) === String(authStore.userId);
})

const fetchStudent = async () => {
  try {
    loading.value = true
    if (!currentRoomId) throw new Error('ไม่พบข้อมูลเซิร์ฟเวอร์ กรุณาเลือกห้องเรียนก่อน')
    
    student.value = await StudentService.getStudentByNo(currentRoomId, studentNo)
  } catch (error: any) {
    console.error('Error fetching student:', error)
    Swal.fire({
      icon: 'error',
      title: 'เกิดข้อผิดพลาด',
      text: error.response?.data?.detail || 'ไม่สามารถโหลดข้อมูลนักเรียนได้'
    })
    router.push('/students')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchStudent()
})
</script>

<template>
  <div class="min-h-screen bg-slate-50/50 p-4 md:p-6 pb-20">
    <!-- Loading State -->
    <div v-if="loading" class="flex flex-col justify-center items-center h-[70vh] gap-3">
      <div class="relative w-12 h-12">
        <div class="absolute inset-0 border-4 border-slate-100 rounded-full"></div>
        <div class="absolute inset-0 border-4 border-blue-600 rounded-full border-t-transparent animate-spin"></div>
      </div>
      <p class="text-slate-400 font-medium text-sm animate-pulse mt-2">กำลังโหลดโปรไฟล์...</p>
    </div>

    <!-- Main Content -->
    <div v-else-if="student" class="max-w-6xl mx-auto animate-fade-in-up">
      
      <!-- Top Action Bar -->
      <div class="flex justify-between items-center mb-5">
        <button
          @click="router.push('/students')"
          class="flex items-center gap-2 text-slate-500 hover:text-slate-800 transition-colors font-semibold text-sm group px-2 py-1.5 rounded-lg hover:bg-slate-100"
        >
          <i class="bi bi-arrow-left group-hover:-translate-x-1 transition-transform"></i>
          <span>กลับหน้ารายชื่อ</span>
        </button>

        <RouterLink
          v-if="canEdit"
          :to="`/students/${student.student_no}/edit`"
          class="flex items-center gap-2 bg-slate-900 hover:bg-slate-800 text-white px-4 py-2.5 rounded-xl shadow-sm active:scale-95 transition-all text-sm font-bold"
        >
          <i class="bi bi-pencil-square"></i>
          <span>แก้ไขข้อมูล</span>
        </RouterLink>
      </div>

      <!-- Layout Grid (Sidebar + Main) -->
      <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        
        <!-- ========================================== -->
        <!-- LEFT COLUMN: Profile Hero & Contact (4/12) -->
        <!-- ========================================== -->
        <div class="lg:col-span-4 space-y-6">
          
          <!-- Profile Hero Card -->
          <div class="bg-white rounded-3xl shadow-[0_4px_20px_rgb(0,0,0,0.03)] border border-slate-100 overflow-hidden relative group hover:shadow-[0_8px_30px_rgb(0,0,0,0.06)] transition-all duration-300">
            <!-- Header BG -->
            <div class="h-24 sm:h-28 bg-gradient-to-r from-slate-900 via-blue-900 to-indigo-900 relative overflow-hidden">
              <div class="absolute inset-0 bg-[url('https://www.transparenttextures.com/patterns/cubes.png')] opacity-10"></div>
              <div class="absolute right-3 top-3 sm:right-4 sm:top-4 bg-white/20 backdrop-blur-md border border-white/20 px-3 py-1 rounded-lg text-white font-black text-base sm:text-lg shadow-sm">
                #{{ student.student_no }}
              </div>
            </div>

            <!-- Content -->
            <div class="p-5 sm:p-6 pt-0 relative">
              <!-- Avatar Placeholder (Optional) -->
              <div class="w-16 h-16 sm:w-20 sm:h-20 bg-white rounded-2xl shadow-md border border-slate-50 -mt-8 sm:-mt-10 flex items-center justify-center text-2xl sm:text-3xl mb-4 text-blue-600 bg-gradient-to-br from-blue-50 to-indigo-50">
                <i class="bi bi-person-fill"></i>
              </div>

              <!-- Badges -->
              <div class="flex flex-wrap gap-2 mb-3">
                <span :class="[
                  'px-2.5 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider',
                  student.status === 'active' ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'
                ]">
                  {{ student.status === 'active' ? 'กำลังศึกษา' : 'พ้นสภาพ' }}
                </span>
                <span class="bg-slate-100 text-slate-600 px-2.5 py-1 rounded-md text-[10px] font-bold uppercase tracking-wider">
                  {{ roleLabel(student.class_role) }}
                </span>
                <span v-if="student.is_admin" class="bg-gradient-to-r from-amber-500 to-orange-400 px-2.5 py-1 rounded-md text-[10px] font-bold uppercase text-white flex items-center gap-1 shadow-sm">
                  <i class="bi bi-shield-lock-fill"></i> ADMIN
                </span>
              </div>

              <h1 class="text-xl sm:text-2xl font-black text-slate-800 leading-tight mb-1">
                {{ student.prefix }}{{ displayName(student) }}
              </h1>
              <p class="text-slate-500 font-medium text-sm flex items-center gap-2 mb-4 flex-wrap">
                <i class="bi bi-person-vcard text-blue-400"></i> {{ student.student_id || 'ไม่ระบุรหัส' }}
                <span v-if="student.nickname || student.nickname_en"> • ชื่อเล่น: {{ student.nickname || student.nickname_en }}</span>
              </p>
            </div>
          </div>

          <!-- Contact Card -->
          <div class="bg-white rounded-3xl shadow-[0_4px_20px_rgb(0,0,0,0.03)] border border-slate-100 p-6">
            <h3 class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4 flex items-center gap-2">
              <i class="bi bi-link-45deg text-lg text-indigo-500"></i> ช่องทางการติดต่อ
            </h3>
            <div class="space-y-4">
              <!-- Phone -->
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-xl bg-slate-50 flex items-center justify-center text-slate-500 shrink-0">
                  <i class="bi bi-telephone-fill"></i>
                </div>
                <div>
                  <p class="text-[10px] font-bold text-slate-400 uppercase">เบอร์โทรศัพท์</p>
                  <p v-if="student.phone_number === '🔒 ไม่มีสิทธิ์เข้าถึง'" class="text-xs font-bold text-slate-400 flex items-center gap-1"><i class="bi bi-lock-fill"></i> ปิดบังข้อมูล</p>
                  <p v-else class="font-bold text-slate-700 text-sm">{{ student.phone_number || '-' }}</p>
                </div>
              </div>
              <!-- Line -->
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-xl bg-[#00B900]/10 flex items-center justify-center text-[#00B900] shrink-0">
                  <i class="bi bi-line text-lg"></i>
                </div>
                <div>
                  <p class="text-[10px] font-bold text-slate-400 uppercase">Line ID</p>
                  <p class="font-bold text-slate-700 text-sm">{{ student.line_id || '-' }}</p>
                </div>
              </div>
              <!-- IG -->
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-xl bg-gradient-to-tr from-[#FFDC80] via-[#F56040] to-[#833AB4] flex items-center justify-center text-white shrink-0">
                  <i class="bi bi-instagram"></i>
                </div>
                <div class="truncate">
                  <p class="text-[10px] font-bold text-slate-400 uppercase">Instagram</p>
                  <p class="font-bold text-slate-700 text-sm truncate">{{ student.ig_username || '-' }}</p>
                </div>
              </div>
            </div>
          </div>

        </div>

        <!-- ========================================== -->
        <!-- RIGHT COLUMN: Details & Info (8/12)      -->
        <!-- ========================================== -->
        <div class="lg:col-span-8 space-y-6">
          
          <!-- Top Grid (Basic Info & Emergency) -->
          <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            
            <!-- Basic Info Card -->
            <div class="bg-white rounded-3xl shadow-[0_4px_20px_rgb(0,0,0,0.03)] border border-slate-100 p-6 flex flex-col justify-center">
              <h3 class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                <i class="bi bi-info-circle-fill text-blue-500"></i> ข้อมูลพื้นฐาน
              </h3>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <p class="text-[10px] font-bold text-slate-400 uppercase mb-1">กรุ๊ปเลือด</p>
                  <i v-if="student.blood_group === '🔒 ไม่มีสิทธิ์เข้าถึง'" class="bi bi-lock-fill text-slate-300"></i>
                  <p v-else class="font-black text-rose-500 text-lg">{{ student.blood_group || '-' }}</p>
                </div>
                <div>
                  <p class="text-[10px] font-bold text-slate-400 uppercase mb-1">ไซส์เสื้อ</p>
                  <i v-if="student.shirt_size === '🔒 ไม่มีสิทธิ์เข้าถึง'" class="bi bi-lock-fill text-slate-300"></i>
                  <p v-else class="font-black text-blue-600 text-lg">{{ student.shirt_size || '-' }}</p>
                </div>
                <div class="col-span-2 bg-slate-50 p-3 rounded-xl border border-slate-100">
                  <p class="text-[10px] font-bold text-slate-400 uppercase mb-1">แพ้อาหาร / โรคประจำตัว</p>
                  <p v-if="student.food_allergy === '🔒 ไม่มีสิทธิ์เข้าถึง'" class="text-xs font-bold text-slate-400"><i class="bi bi-lock-fill"></i> ปกปิดข้อมูล</p>
                  <p v-else class="font-bold text-slate-700 text-sm">{{ student.food_allergy || 'ไม่มีประวัติ' }}</p>
                </div>
              </div>
            </div>

            <!-- Emergency Card -->
            <div class="bg-rose-50/50 rounded-3xl shadow-sm border border-rose-100 p-6 relative overflow-hidden group">
              <i class="bi bi-shield-plus absolute -right-6 -bottom-6 text-7xl text-rose-500/10 group-hover:scale-110 transition-transform duration-500"></i>
              <h3 class="text-xs font-black text-rose-500 uppercase tracking-widest mb-4 flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-rose-500 animate-pulse"></span> ฉุกเฉิน
              </h3>
              
              <div class="space-y-4 relative z-10">
                <div>
                  <p class="text-[10px] font-bold text-rose-400/80 uppercase">ผู้ติดต่อฉุกเฉิน</p>
                  <p v-if="student.phone_number_parent_relation === '🔒 ไม่มีสิทธิ์เข้าถึง'" class="text-sm font-bold text-rose-400"><i class="bi bi-lock-fill"></i> ปกปิด</p>
                  <p v-else class="font-bold text-rose-900">{{ student.phone_number_parent_relation || 'ผู้ปกครอง' }}</p>
                </div>
                
                <div class="bg-white/60 p-3 rounded-xl border border-rose-100/50 backdrop-blur-sm">
                  <p class="text-[10px] font-bold text-rose-400/80 uppercase mb-0.5">เบอร์โทรศัพท์</p>
                  <div v-if="student.phone_number_parent === '🔒 ไม่มีสิทธิ์เข้าถึง'" class="text-rose-400 font-bold flex items-center gap-1">
                    <i class="bi bi-lock-fill"></i> ไม่มีสิทธิ์
                  </div>
                  <a v-else :href="'tel:' + student.phone_number_parent" class="font-black text-rose-600 text-xl hover:text-rose-700 transition-colors block">
                    {{ student.phone_number_parent || '-' }}
                  </a>
                </div>
              </div>
            </div>
            
          </div>

          <!-- Address Card -->
          <div class="bg-white rounded-3xl shadow-[0_4px_20px_rgb(0,0,0,0.03)] border border-slate-100 p-6">
            <h3 class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3 flex items-center gap-2">
              <i class="bi bi-geo-alt-fill text-emerald-500"></i> ที่อยู่ตามทะเบียนบ้าน
            </h3>
            <div class="flex gap-3 items-start bg-slate-50/50 p-4 rounded-2xl border border-slate-100">
              <div class="w-8 h-8 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-600 shrink-0 mt-0.5">
                <i class="bi bi-house-door-fill text-sm"></i>
              </div>
              <div class="text-slate-700 font-medium text-sm leading-relaxed">
                <template v-if="student.address_house_no === '🔒 ไม่มีสิทธิ์เข้าถึง'">
                  <span class="text-slate-400 font-bold flex items-center gap-1 mt-1"><i class="bi bi-shield-lock-fill"></i> สงวนสิทธิ์การเข้าถึงข้อมูล</span>
                </template>
                <template v-else>
                  {{ student.address_house_no ? `${student.address_house_no} ถ.${student.address_road || '-'} ต.${student.address_sub_district || '-'} อ.${student.address_district || '-'} จ.${student.address_province || '-'} ${student.address_post_code || ''}` : 'ยังไม่มีข้อมูลที่อยู่' }}
                </template>
              </div>
            </div>
          </div>

          <!-- Academic & Portfolio -->
          <div class="bg-white rounded-3xl shadow-[0_4px_20px_rgb(0,0,0,0.03)] border border-slate-100 p-6 space-y-6">
            
            <!-- Target -->
            <div>
              <h3 class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-2 flex items-center gap-2">
                <i class="bi bi-mortarboard-fill text-purple-500"></i> คณะที่ใฝ่ฝัน
              </h3>
              <p v-if="student.target_faculty === '🔒 ไม่มีสิทธิ์เข้าถึง'" class="text-sm font-bold text-slate-400"><i class="bi bi-lock-fill"></i> ปกปิดข้อมูล</p>
              <p v-else class="text-slate-800 font-bold text-sm bg-purple-50 p-3 rounded-xl border border-purple-100/50">
                {{ student.target_faculty || 'ยังไม่ได้ระบุ' }}
              </p>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-6 pt-4 border-t border-slate-100">
              <!-- Camps -->
              <div>
                <h3 class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3 flex items-center gap-2">
                  <i class="bi bi-stars text-amber-500"></i> สอวน. / ค่ายวิชาการ
                </h3>
                <div class="text-sm font-medium text-slate-600 bg-amber-50/50 p-4 rounded-2xl border border-amber-100/50 min-h-[100px] whitespace-pre-line leading-relaxed">
                  {{ student.olympic_camp || '-' }}
                </div>
              </div>
              
              <!-- Portfolio -->
              <div>
                <h3 class="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3 flex items-center gap-2">
                  <i class="bi bi-trophy-fill text-orange-500"></i> ผลงาน / รางวัล
                </h3>
                <div class="text-sm font-medium text-slate-600 bg-orange-50/30 p-4 rounded-2xl border border-orange-100/50 min-h-[100px] whitespace-pre-line leading-relaxed">
                  {{ student.portfolio || '-' }}
                </div>
              </div>
            </div>

          </div>

        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* เพิ่ม Animation สมูทๆ เวลาโหลดข้อมูลเสร็จ */
@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(15px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.animate-fade-in-up {
  animation: fadeInUp 0.4s ease-out forwards;
}

/* ลบ Highlight สีฟ้าตอนกดปุ่มบนมือถือ */
* {
  -webkit-tap-highlight-color: transparent;
}
</style>