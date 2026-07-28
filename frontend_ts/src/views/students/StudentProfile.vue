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
const student = ref<any | null>(null) // ใส่ any เพราะมี is_admin
const loading = ref(true)

const currentRoomId = authStore.currentRoomId!

// 🎯 สร้างเงื่อนไขสำหรับแสดงปุ่ม "แก้ไขข้อมูล" ให้แม่นยำ
// คนที่เห็นปุ่มได้ = แอดมิน หรือ คนที่มีสิทธิ์ MANAGE_STUDENTS หรือ เจ้าของโปรไฟล์เอง
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
  <div class="min-h-screen bg-slate-50/80 p-4 sm:p-6 md:p-8 pb-20">
    <div v-if="loading" class="flex flex-col justify-center items-center h-[60vh] gap-4">
      <div class="relative w-16 h-16">
        <div class="absolute inset-0 border-4 border-slate-100 rounded-full"></div>
        <div class="absolute inset-0 border-4 border-blue-600 rounded-full border-t-transparent animate-spin"></div>
      </div>
      <p class="text-slate-500 font-bold animate-pulse mt-2">กำลังโหลดโปรไฟล์...</p>
    </div>

    <div v-else-if="student" class="max-w-5xl mx-auto space-y-4 md:space-y-6">
      
      <div class="flex justify-between items-center px-1 mb-2">
        <button 
          @click="router.push('/students')" 
          class="w-10 h-10 md:w-auto md:px-5 flex items-center justify-center gap-2 bg-white text-slate-600 rounded-full md:rounded-2xl shadow-sm border border-slate-200 hover:bg-slate-50 active:scale-95 transition-all font-bold group"
        >
          <i class="bi bi-arrow-left text-lg group-hover:-translate-x-1 transition-transform"></i>
          <span class="hidden md:inline">กลับหน้ารายชื่อ</span>
        </button>
        
        <!-- 🎯 โชว์ปุ่มให้เฉพาะคนที่มีสิทธิ์ -->
        <RouterLink 
          v-if="canEdit"
          :to="`/students/${student.student_no}/edit`" 
          class="w-10 h-10 md:w-auto md:px-6 flex items-center justify-center gap-2 bg-slate-900 hover:bg-slate-800 text-white rounded-full md:rounded-2xl shadow-lg shadow-slate-900/20 active:scale-95 transition-all font-bold group"
        >
          <i class="bi bi-pencil-square text-lg"></i>
          <span class="hidden md:inline">แก้ไขข้อมูล</span>
        </RouterLink>
      </div>

      <div class="bg-white rounded-[2rem] md:rounded-[2.5rem] shadow-[0_8px_30px_rgb(0,0,0,0.04)] overflow-hidden border border-slate-100">
        
        <div class="relative bg-gradient-to-br from-slate-900 via-blue-950 to-indigo-950 p-6 sm:p-8 md:p-14 text-white overflow-hidden">
          <div class="absolute top-0 right-0 w-64 h-64 bg-blue-500/10 rounded-full blur-3xl -translate-y-1/2 translate-x-1/2 pointer-events-none"></div>
          <div class="absolute bottom-0 left-0 w-48 h-48 bg-indigo-500/10 rounded-full blur-3xl translate-y-1/2 -translate-x-1/2 pointer-events-none"></div>
          
          <div class="relative flex flex-col md:flex-row justify-between items-start md:items-center gap-6">
            
            <div class="space-y-4 md:space-y-5 w-full md:w-auto">
              <div class="flex md:hidden justify-between items-center w-full mb-2">
                <div class="bg-white/10 backdrop-blur-md border border-white/20 px-4 py-1.5 rounded-full text-[11px] font-black tracking-widest text-white shadow-inner flex items-center gap-2">
                  เลขที่ <span class="text-lg text-blue-300">{{ student.student_no }}</span>
                </div>
              </div>

              <!-- 🎯 โซน Badge สถานะและสิทธิ์ -->
              <div class="flex flex-wrap items-center gap-2.5">
                <span class="bg-white/10 backdrop-blur-md border border-white/20 px-3 py-1.5 rounded-lg text-[10px] md:text-xs font-black uppercase tracking-widest text-blue-100 shadow-sm">
                  {{ student.class_role }}
                </span>
                <span :class="[
                  'px-3 py-1.5 rounded-lg text-[10px] md:text-xs font-black uppercase tracking-widest backdrop-blur-md border shadow-sm',
                  student.status === 'active' ? 'bg-emerald-500/20 border-emerald-500/30 text-emerald-300' : 'bg-rose-500/20 border-rose-500/30 text-rose-300'
                ]">
                  {{ student.status === 'active' ? 'กำลังศึกษา' : 'พ้นสภาพ' }}
                </span>

                <!-- 🌟 โชว์มงกุฎสำหรับคนที่เป็น Admin ในหน้าโปรไฟล์ -->
                <span v-if="student.is_admin" class="bg-gradient-to-r from-amber-500 to-orange-400 px-3 py-1.5 rounded-lg text-[10px] md:text-xs font-black uppercase tracking-widest text-white shadow-lg shadow-orange-500/30 flex items-center gap-1.5 border border-orange-300/50">
                  <i class="bi bi-shield-lock-fill"></i> SYSTEM ADMIN
                </span>
                <!-- หรือถ้ามีสิทธิ์ย่อย ก็โชว์ STAFF ให้เท่ๆ -->
                <span v-else-if="student.permissions && student.permissions.length > 0" class="bg-purple-500/20 border-purple-500/30 px-3 py-1.5 rounded-lg text-[10px] md:text-xs font-black uppercase tracking-widest text-purple-200 backdrop-blur-md border shadow-sm flex items-center gap-1.5">
                  <i class="bi bi-key-fill"></i> STAFF
                </span>
              </div>

              <div>
                <h1 class="text-2xl sm:text-3xl md:text-4xl lg:text-5xl font-black tracking-tight mb-2 md:mb-3 leading-tight">
                  {{ student.prefix }}{{ student.first_name }} {{ student.last_name }}
                </h1>
                <div class="flex flex-wrap items-center gap-2 md:gap-3 text-blue-200/80 text-sm md:text-lg font-medium">
                  <span class="flex items-center gap-1.5 bg-black/20 px-3 py-1 rounded-md">
                    <i class="bi bi-person-vcard text-blue-300"></i> {{ student.student_id || 'ไม่ระบุรหัส' }}
                  </span>
                  <span class="hidden sm:inline opacity-30">|</span>
                  <span class="flex items-center gap-1.5 bg-black/20 px-3 py-1 rounded-md text-white">
                    ชื่อเล่น: {{ student.nickname || '-' }}
                  </span>
                </div>
              </div>
            </div>
            
            <div class="hidden md:flex bg-white/10 backdrop-blur-md border border-white/20 px-8 py-6 rounded-3xl text-center min-w-[140px] shadow-2xl flex-col items-center justify-center transform hover:scale-105 transition-transform">
              <p class="text-xs font-bold text-blue-200/70 uppercase tracking-widest mb-1">เลขที่</p>
              <p class="text-5xl font-black text-white">{{ student.student_no }}</p>
            </div>
            
          </div>
        </div>

        <div class="p-5 sm:p-8 md:p-10 lg:p-14">
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-8 lg:gap-12">
            
            <!-- LEFT COLUMN -->
            <div class="space-y-8 md:space-y-10">
              
              <!-- Contact Section -->
              <section>
                <h3 class="text-[11px] md:text-xs font-bold text-slate-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                  <i class="bi bi-person-lines-fill text-indigo-500 text-sm"></i> ข้อมูลการติดต่อ
                </h3>
                <div class="space-y-3">
                  <div class="flex items-center gap-4 bg-white border border-slate-100 shadow-sm rounded-2xl p-4 hover:border-blue-100 transition-colors">
                    <div class="w-12 h-12 bg-slate-50 rounded-xl flex items-center justify-center text-slate-700">
                      <i class="bi bi-telephone-fill text-lg"></i>
                    </div>
                    <div>
                      <p class="text-[11px] text-slate-400 font-bold uppercase tracking-wider mb-0.5">เบอร์โทรศัพท์</p>
                      <template v-if="student.phone_number === '🔒 ไม่มีสิทธิ์เข้าถึง'">
                        <span class="inline-flex items-center gap-1.5 px-2.5 py-1 mt-0.5 rounded-md bg-slate-100 text-slate-400 text-xs font-bold border border-slate-200">
                          <i class="bi bi-lock-fill text-slate-300"></i> ปิดบังข้อมูล
                        </span>
                      </template>
                      <template v-else>
                        <p class="text-slate-800 font-extrabold text-base md:text-lg">{{ student.phone_number || '-' }}</p>
                      </template>
                    </div>
                  </div>
                  
                  <div class="flex items-center gap-4 bg-white border border-slate-100 shadow-sm rounded-2xl p-4 hover:border-[#00B900]/20 transition-colors">
                    <div class="w-12 h-12 bg-[#00B900]/10 rounded-xl flex items-center justify-center text-[#00B900]">
                      <i class="bi bi-line text-lg"></i>
                    </div>
                    <div>
                      <p class="text-[11px] text-slate-400 font-bold uppercase tracking-wider mb-0.5">Line ID</p>
                      <p class="text-slate-800 font-extrabold text-base md:text-lg">{{ student.line_id || '-' }}</p>
                    </div>
                  </div>

                  <div class="flex items-center gap-4 bg-white border border-slate-100 shadow-sm rounded-2xl p-4 hover:border-[#E1306C]/20 transition-colors">
                    <div class="w-12 h-12 bg-gradient-to-tr from-[#FFDC80] via-[#F56040] to-[#833AB4] rounded-xl flex items-center justify-center text-white shadow-inner">
                      <i class="bi bi-instagram text-lg"></i>
                    </div>
                    <div>
                      <p class="text-[11px] text-slate-400 font-bold uppercase tracking-wider mb-0.5">Instagram</p>
                      <p class="text-slate-800 font-extrabold text-base md:text-lg">{{ student.ig_username || '-' }}</p>
                    </div>
                  </div>
                </div>
              </section>

              <!-- Address Section -->
              <section>
                <h3 class="text-[11px] md:text-xs font-bold text-slate-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                  <i class="bi bi-geo-alt-fill text-emerald-500 text-sm"></i> ที่อยู่ตามทะเบียนบ้าน
                </h3>
                <div class="bg-emerald-50/50 rounded-2xl md:rounded-3xl p-5 md:p-6 border border-emerald-100/60 flex gap-4 items-start">
                  <div class="mt-1 w-8 h-8 rounded-full bg-emerald-100 flex items-center justify-center text-emerald-600 shrink-0">
                    <i class="bi bi-house-door-fill text-sm"></i>
                  </div>
                  <div class="text-slate-700 leading-relaxed font-bold text-sm md:text-base w-full">
                    <template v-if="student.address_house_no === '🔒 ไม่มีสิทธิ์เข้าถึง'">
                      <div class="flex items-center gap-2 text-emerald-600/60 bg-emerald-100/50 px-3 py-2 rounded-xl border border-emerald-200/50 w-fit">
                        <i class="bi bi-shield-lock-fill text-lg"></i>
                        <span>ข้อมูลส่วนตัว (สงวนสิทธิ์การเข้าถึง)</span>
                      </div>
                    </template>
                    <template v-else>
                      <p>
                        {{ student.address_house_no ? `${student.address_house_no} ถ.${student.address_road || '-'} ต.${student.address_sub_district || '-'} อ.${student.address_district || '-'} จ.${student.address_province || '-'} ${student.address_post_code || ''}` : 'ไม่มีข้อมูลที่อยู่' }}
                      </p>
                    </template>
                  </div>
                </div>
              </section>

            </div>

            <!-- RIGHT COLUMN -->
            <div class="space-y-8 md:space-y-10">
              
              <!-- Emergency Section -->
              <section>
                <div class="bg-rose-50/50 rounded-2xl md:rounded-3xl p-6 md:p-8 border border-rose-100/80 relative overflow-hidden group">
                  <i class="bi bi-heart-pulse-fill absolute -right-4 -bottom-4 text-7xl text-rose-500/5 group-hover:scale-110 transition-transform"></i>
                  <div class="flex items-start justify-between relative z-10">
                    <div>
                      <h4 class="text-[11px] font-black text-rose-500 uppercase tracking-widest mb-1.5 flex items-center gap-1.5">
                        <span class="w-2 h-2 rounded-full bg-rose-500 animate-pulse"></span> ติดต่อฉุกเฉิน
                      </h4>
                      <template v-if="student.phone_number_parent_relation === '🔒 ไม่มีสิทธิ์เข้าถึง'">
                        <p class="text-rose-400 font-bold text-sm flex items-center gap-1"><i class="bi bi-lock-fill"></i> ปกปิดข้อมูล</p>
                      </template>
                      <template v-else>
                        <p class="text-rose-950 font-bold text-base md:text-lg">{{ student.phone_number_parent_relation || 'ผู้ปกครอง' }}</p>
                      </template>
                    </div>
                    <div class="w-12 h-12 bg-white rounded-xl shadow-sm flex items-center justify-center text-rose-500 border border-rose-100">
                      <i class="bi bi-shield-fill-exclamation text-xl"></i>
                    </div>
                  </div>
                  <div class="mt-5 pt-5 border-t border-rose-200/50 relative z-10">
                    <template v-if="student.phone_number_parent === '🔒 ไม่มีสิทธิ์เข้าถึง'">
                      <div class="text-xl md:text-2xl font-black text-rose-300 tracking-tight flex items-center gap-2">
                        <i class="bi bi-lock-fill"></i> ไม่มีสิทธิ์เข้าถึง
                      </div>
                    </template>
                    <template v-else>
                      <a :href="'tel:' + student.phone_number_parent" class="text-2xl md:text-3xl font-black text-rose-600 tracking-tight hover:text-rose-700 transition-colors">
                        {{ student.phone_number_parent || '-' }}
                      </a>
                    </template>
                  </div>
                </div>
              </section>

              <!-- Basic Info Grid -->
              <section>
                <h3 class="text-[11px] md:text-xs font-bold text-slate-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                  <i class="bi bi-grid-fill text-blue-500 text-sm"></i> ข้อมูลส่วนตัวพื้นฐาน
                </h3>
                <div class="grid grid-cols-2 gap-3 md:gap-4">
                  <div class="bg-slate-50 rounded-2xl p-4 md:p-5 border border-slate-100">
                    <p class="text-[10px] text-slate-400 font-bold uppercase tracking-wider mb-1">กรุ๊ปเลือด</p>
                    <template v-if="student.blood_group === '🔒 ไม่มีสิทธิ์เข้าถึง'">
                      <i class="bi bi-lock-fill text-slate-300 text-xl md:text-2xl mt-1 block"></i>
                    </template>
                    <template v-else>
                      <p class="text-xl md:text-2xl font-black text-rose-600">{{ student.blood_group || '-' }}</p>
                    </template>
                  </div>
                  
                  <div class="bg-slate-50 rounded-2xl p-4 md:p-5 border border-slate-100">
                    <p class="text-[10px] text-slate-400 font-bold uppercase tracking-wider mb-1">ไซส์เสื้อ</p>
                    <template v-if="student.shirt_size === '🔒 ไม่มีสิทธิ์เข้าถึง'">
                      <i class="bi bi-lock-fill text-slate-300 text-xl md:text-2xl mt-1 block"></i>
                    </template>
                    <template v-else>
                      <p class="text-xl md:text-2xl font-black text-blue-600">{{ student.shirt_size || '-' }}</p>
                    </template>
                  </div>
                  
                  <div class="bg-slate-50 rounded-2xl p-4 md:p-5 border border-slate-100 col-span-2">
                    <p class="text-[10px] text-slate-400 font-bold uppercase tracking-wider mb-1.5">แพ้อาหาร / โรคประจำตัว</p>
                    <template v-if="student.food_allergy === '🔒 ไม่มีสิทธิ์เข้าถึง'">
                      <div class="inline-flex items-center gap-1.5 px-2.5 py-1 mt-0.5 rounded-md bg-slate-200/50 text-slate-400 text-xs font-bold">
                        <i class="bi bi-lock-fill"></i> ปกปิดข้อมูล
                      </div>
                    </template>
                    <template v-else>
                      <p class="font-bold text-slate-700 text-sm md:text-base">{{ student.food_allergy || 'ไม่มีประวัติการแพ้' }}</p>
                    </template>
                  </div>
                  
                  <div class="bg-slate-50 rounded-2xl p-4 md:p-5 border border-slate-100 col-span-2">
                    <p class="text-[10px] text-slate-400 font-bold uppercase tracking-wider mb-1.5">คณะที่ใฝ่ฝัน</p>
                    <template v-if="student.target_faculty === '🔒 ไม่มีสิทธิ์เข้าถึง'">
                      <div class="inline-flex items-center gap-1.5 px-2.5 py-1 mt-0.5 rounded-md bg-slate-200/50 text-slate-400 text-xs font-bold">
                        <i class="bi bi-lock-fill"></i> ปกปิดข้อมูล
                      </div>
                    </template>
                    <template v-else>
                      <p class="font-bold text-slate-700 text-sm md:text-base">{{ student.target_faculty || 'ยังไม่ได้ระบุ' }}</p>
                    </template>
                  </div>
                </div>
              </section>

            </div>
          </div>

          <div class="mt-8 md:mt-12 space-y-6 md:space-y-8 border-t border-slate-100 pt-8 md:pt-10">
            
            <section>
              <h3 class="text-[11px] md:text-xs font-bold text-slate-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                <i class="bi bi-stars text-amber-500 text-sm"></i> สอวน. และค่ายวิชาการ
              </h3>
              <div class="bg-gradient-to-br from-amber-50/50 to-orange-50/50 rounded-2xl md:rounded-3xl p-5 md:p-8 border border-amber-100 shadow-sm text-slate-700 font-bold text-sm md:text-base whitespace-pre-line leading-relaxed">
                {{ student.olympic_camp || 'ยังไม่มีประวัติการเข้าค่ายวิชาการ' }}
              </div>
            </section>

            <section>
              <h3 class="text-[11px] md:text-xs font-bold text-slate-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                <i class="bi bi-trophy-fill text-orange-500 text-sm"></i> ผลงานและรางวัล (Portfolio)
              </h3>
              <div class="bg-gradient-to-br from-orange-50/50 to-rose-50/30 rounded-2xl md:rounded-3xl p-5 md:p-8 border border-orange-100 shadow-sm text-slate-700 font-bold text-sm md:text-base whitespace-pre-line leading-relaxed min-h-[120px] md:min-h-[150px]">
                {{ student.portfolio || 'ยังไม่มีข้อมูลผลงานหรือรางวัลที่บันทึกไว้' }}
              </div>
            </section>
            
          </div>

        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
* {
  -webkit-tap-highlight-color: transparent;
}
</style>