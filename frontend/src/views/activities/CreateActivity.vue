<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { StudentService } from '@/services/student'
import { ActivityService } from '@/services/activity'
import type { Student } from '@/types/student'
import type { ActivityParticipantInput } from '@/types/activity'
import Swal from 'sweetalert2'

const router = useRouter()
const authStore = useAuthStore()

const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName!

const isLoading = ref(true)
const isSaving = ref(false)

// --- ฟอร์มหลัก ---
const form = ref({
  title: '',
  description: '',
  activity_date: new Date().toISOString().slice(0, 10),
  base_hours: 0,
  status: 'upcoming' as string,
})

// --- 🌟 Metadata กิจกรรม (key-value) เก็บพิกัด/ลิ้งก์/แท็ก ---
interface MetaEntry {
  key: string
  value: string
}
const activityMeta = ref<MetaEntry[]>([{ key: '', value: '' }])

// ฟิลด์ช่วย (preset) สำหรับ metadata
const metaPresets = [
  { key: 'tags', placeholder: 'เช่น กีฬา, ค่าย, ทัศนศึกษา (คั่นด้วย ,)' },
  { key: 'location_url', placeholder: 'https://maps.google.com/...' },
  { key: 'agenda', placeholder: '08:00 เปิดงาน | 10:00 แข่ง | 12:00 พัก' },
  { key: 'location_name', placeholder: 'สนามกีฬาโรงเรียน' },
]

// --- รายชื่อนักเรียน + การเลือก ---
const students = ref<Student[]>([])
const selectedNos = ref<Set<number>>(new Set())
const roleDetails = ref<Record<number, string>>({})
const participantMeta = ref<Record<number, Record<string, string>>>({})

// ⚙️ Modal metadata ผู้เข้าร่วม (Advanced Meta)
const showMetaModal = ref(false)
const metaModalStudent = ref<Student | null>(null)
const metaModalEntries = ref<MetaEntry[]>([{ key: '', value: '' }])

const canManage = computed(
  () => authStore.isAdmin || authStore.currentPermissions.includes('MANAGE_ACTIVITIES'),
)

const Toast = Swal.mixin({
  toast: true,
  position: 'top-end',
  showConfirmButton: false,
  timer: 3000,
  timerProgressBar: true,
})

onMounted(async () => {
  isLoading.value = true
  try {
    const list = await StudentService.getStudents(currentRoomId)
    students.value = (list as any[]).filter((s) => s.status === 'active')
  } catch (error: any) {
    Swal.fire('ข้อผิดพลาด', error?.message || 'โหลดรายชื่อนักเรียนไม่สำเร็จ', 'error')
  } finally {
    isLoading.value = false
  }
})

const selectedCount = computed(() => selectedNos.value.size)

const toggleSelect = (student: Student) => {
  const no = Number(student.student_no)
  if (selectedNos.value.has(no)) {
    selectedNos.value.delete(no)
    delete roleDetails.value[no]
    delete participantMeta.value[no]
  } else {
    selectedNos.value.add(no)
  }
  // trigger reactivity
  selectedNos.value = new Set(selectedNos.value)
}

const selectAll = () => {
  students.value.forEach((s) => selectedNos.value.add(Number(s.student_no)))
  selectedNos.value = new Set(selectedNos.value)
}

const clearAll = () => {
  selectedNos.value = new Set()
  roleDetails.value = {}
  participantMeta.value = {}
}

// --- Metadata helper ---
const buildMetadata = (entries: MetaEntry[]): Record<string, unknown> => {
  const result: Record<string, unknown> = {}
  for (const e of entries) {
    const key = e.key.trim()
    const value = e.value.trim()
    if (!key) continue
    // แปลงค่าแบบง่าย: ถ้าเป็น array (คั่น ,) ให้แยกเป็น list
    if (key === 'tags' && value.includes(',')) {
      result[key] = value.split(',').map((t) => t.trim()).filter(Boolean)
    } else if (key === 'agenda' && value.includes('|')) {
      result[key] = value.split('|').map((t) => t.trim()).filter(Boolean)
    } else {
      result[key] = value
    }
  }
  return result
}

// ⚠️ ใน template refs ถูก auto-unwrap → ฟังก์ชันรับ array ตรง ๆ (ไม่ใช่ Ref)
const addMetaRow = (entries: MetaEntry[]) => {
  entries.push({ key: '', value: '' })
}
const removeMetaRow = (entries: MetaEntry[], index: number) => {
  entries.splice(index, 1)
}

// ⚙️ Modal: เติม metadata ของผู้เข้าร่วมคนนั้น
const openMetaModal = (student: Student) => {
  metaModalStudent.value = student
  const existing = participantMeta.value[Number(student.student_no)] || {}
  metaModalEntries.value = Object.entries(existing).map(([key, value]) => ({ key, value: String(value) }))
  if (metaModalEntries.value.length === 0) metaModalEntries.value = [{ key: '', value: '' }]
  showMetaModal.value = true
}

const saveMetaModal = () => {
  if (!metaModalStudent.value) return
  const no = Number(metaModalStudent.value.student_no)
  participantMeta.value[no] = buildMetadata(metaModalEntries.value) as Record<string, string>
  showMetaModal.value = false
  Toast.fire({ icon: 'success', title: `บันทึก metadata ของ ${metaModalStudent.value.first_name} แล้ว` })
}

// --- Submit ---
const validateForm = (): string | null => {
  if (!form.value.title.trim()) return 'กรุณากรอกชื่อกิจกรรม'
  if (!form.value.activity_date) return 'กรุณาเลือกวันที่'
  if (selectedNos.value.size === 0) return 'กรุณาเลือกผู้เข้าร่วมอย่างน้อย 1 คน'
  return null
}

const submit = async () => {
  if (!canManage.value) {
    return Swal.fire('ไม่มีสิทธิ์', 'เฉพาะผู้ดูแลกิจกรรมเท่านั้น', 'error')
  }
  const error = validateForm()
  if (error) return Swal.fire('กรอกข้อมูลไม่ครบ', error, 'warning')

  const participants: ActivityParticipantInput[] = []
  for (const no of selectedNos.value) {
    const student = students.value.find((s) => Number(s.student_no) === no)
    if (!student) continue
    participants.push({
      student_no: no,
      role_type: 'participant',
      role_detail: roleDetails.value[no]?.trim() || null,
      earned_hours: form.value.base_hours > 0 ? form.value.base_hours : 0,
      metadata: participantMeta.value[no] || {},
    })
  }

  isSaving.value = true
  try {
    await ActivityService.createActivity(currentRoomId, {
      title: form.value.title.trim(),
      description: form.value.description.trim() || null,
      activity_date: form.value.activity_date,
      base_hours: Number(form.value.base_hours) || 0,
      status: form.value.status,
      metadata: buildMetadata(activityMeta.value),
      participants,
      user_name: currentUserName,
    })
    await Swal.fire({
      icon: 'success',
      title: 'สร้างกิจกรรมสำเร็จ! 🎪',
      text: `"${form.value.title}" พร้อมผู้เข้าร่วม ${participants.length} คน ถูกบันทึกแล้ว`,
      confirmButtonColor: '#8b5cf6',
      customClass: { popup: 'rounded-[2rem] shadow-2xl' },
    })
    router.push('/activities')
  } catch (error: any) {
    Swal.fire('ข้อผิดพลาด', error?.message || 'สร้างกิจกรรมไม่สำเร็จ', 'error')
  } finally {
    isSaving.value = false
  }
}
</script>

<template>
  <div class="min-h-screen bg-slate-50/50 p-4 sm:p-6 md:p-8">
    <div class="max-w-6xl mx-auto">

      <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-3">
        <div>
          <h3 class="text-lg sm:text-xl md:text-2xl font-extrabold text-slate-800 flex items-center gap-2.5">
            <div class="p-2 sm:p-2.5 bg-violet-100 rounded-xl text-violet-600 shadow-sm flex-shrink-0">
              <i class="bi bi-calendar-plus-fill"></i>
            </div>
            สร้างกิจกรรมใหม่
          </h3>
          <p class="text-slate-500 mt-1.5 ml-1 text-sm md:text-base">กรอกข้อมูลหัวกิจกรรม + เลือกผู้เข้าร่วมและหน้าที่</p>
        </div>
        <router-link to="/activities" class="inline-flex items-center gap-2 text-sm font-bold text-slate-500 hover:text-slate-800 hover:bg-slate-100 px-4 py-2 rounded-xl transition-all">
          <i class="bi bi-arrow-left"></i> กลับรายการ
        </router-link>
      </div>

      <div v-if="isLoading" class="flex flex-col justify-center items-center py-20 gap-4">
        <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-violet-600"></div>
        <p class="text-slate-400 font-medium animate-pulse">กำลังโหลดรายชื่อนักเรียน...</p>
      </div>

      <div v-else class="grid grid-cols-1 lg:grid-cols-5 gap-5 md:gap-6">
        <!-- ========== ส่วนหัวกิจกรรม ========== -->
        <div class="lg:col-span-2 space-y-5">
          <div class="bg-white rounded-3xl p-5 md:p-6 shadow-sm border border-slate-100">
            <h4 class="text-base font-bold text-slate-700 mb-4 flex items-center gap-2">
              <i class="bi bi-card-heading text-violet-500"></i> ข้อมูลกิจกรรม
            </h4>
            <div class="space-y-4">
              <div>
                <label class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5 block">ชื่อกิจกรรม *</label>
                <input
                  v-model="form.title"
                  type="text"
                  placeholder="เช่น กีฬาสีประจำปี 2026"
                  class="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
                />
              </div>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5 block">วันที่ *</label>
                  <input
                    v-model="form.activity_date"
                    type="date"
                    class="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
                  />
                </div>
                <div>
                  <label class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5 block">ชั่วโมงจิตอาสา</label>
                  <input
                    v-model.number="form.base_hours"
                    type="number"
                    min="0"
                    step="0.5"
                    placeholder="0"
                    class="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
                  />
                </div>
              </div>
              <div>
                <label class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5 block">สถานะ</label>
                <select
                  v-model="form.status"
                  class="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400"
                >
                  <option value="upcoming">กำลังจะมา</option>
                  <option value="ongoing">กำลังดำเนินการ</option>
                  <option value="completed">เสร็จสิ้น</option>
                  <option value="cancelled">ยกเลิก</option>
                </select>
              </div>
              <div>
                <label class="text-xs font-bold text-slate-500 uppercase tracking-wider mb-1.5 block">รายละเอียด</label>
                <textarea
                  v-model="form.description"
                  rows="3"
                  placeholder="รายละเอียดกิจกรรม กำหนดการคร่าว ๆ..."
                  class="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 focus:border-violet-400 resize-none"
                ></textarea>
              </div>
            </div>
          </div>

          <!-- 🌟 Metadata กิจกรรม -->
          <div class="bg-white rounded-3xl p-5 md:p-6 shadow-sm border border-slate-100">
            <div class="flex items-center justify-between mb-4">
              <h4 class="text-base font-bold text-slate-700 flex items-center gap-2">
                <i class="bi bi-asterisk text-violet-500"></i> Metadata เพิ่มเติม
              </h4>
              <button
                @click="addMetaRow(activityMeta)"
                class="text-xs font-bold text-violet-600 bg-violet-50 hover:bg-violet-100 px-3 py-1.5 rounded-lg transition-colors inline-flex items-center gap-1"
              >
                <i class="bi bi-plus-lg"></i> Add Metadata
              </button>
            </div>
            <div class="space-y-3">
              <div
                v-for="(meta, index) in activityMeta"
                :key="index"
                class="flex gap-2 items-center"
              >
                <input
                  v-model="meta.key"
                  list="meta-preset-keys"
                  placeholder="คีย์ (เช่น location_url, tags)"
                  class="flex-1 min-w-0 px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30"
                />
                <datalist id="meta-preset-keys">
                  <option v-for="p in metaPresets" :key="p.key" :value="p.key">{{ p.placeholder }}</option>
                </datalist>
                <input
                  v-model="meta.value"
                  :placeholder="metaPresets.find((p) => p.key === meta.key)?.placeholder || 'ค่า'"
                  class="flex-1 min-w-0 px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30"
                />
                <button
                  v-if="activityMeta.length > 1"
                  @click="removeMetaRow(activityMeta, index)"
                  class="w-8 h-8 flex-shrink-0 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 transition-colors flex items-center justify-center"
                  title="ลบคีย์"
                >
                  <i class="bi bi-x-lg"></i>
                </button>
              </div>
              <p class="text-[11px] text-slate-400 mt-2 leading-relaxed">
                💡 ใช้ <code class="bg-slate-100 px-1 rounded">tags</code> คั่นด้วย , เพื่อทำ Badge หมวดหมู่ · <code class="bg-slate-100 px-1 rounded">location_url</code> สำหรับลิ้งก์ Google Maps
              </p>
            </div>
          </div>
        </div>

        <!-- ========== รายชื่อผู้เข้าร่วม ========== -->
        <div class="lg:col-span-3">
          <div class="bg-white rounded-3xl p-5 md:p-6 shadow-sm border border-slate-100">
            <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-4 gap-3">
              <div>
                <h4 class="text-base font-bold text-slate-700 flex items-center gap-2">
                  <i class="bi bi-people-fill text-violet-500"></i> เลือกผู้เข้าร่วม
                </h4>
                <p class="text-xs text-slate-400 mt-0.5">ติ๊กชื่อ → พิมพ์หน้าที่ · กด ⚙️ เพื่อกรอก metadata ต่อคน</p>
              </div>
              <div class="flex gap-2">
                <button @click="selectAll" class="text-xs font-bold text-slate-500 hover:text-violet-600 bg-slate-50 hover:bg-violet-50 px-3 py-1.5 rounded-lg transition-colors inline-flex items-center gap-1">
                  <i class="bi bi-check-all"></i> เลือกทั้งหมด
                </button>
                <button @click="clearAll" class="text-xs font-bold text-slate-500 hover:text-rose-600 bg-slate-50 hover:bg-rose-50 px-3 py-1.5 rounded-lg transition-colors inline-flex items-center gap-1">
                  <i class="bi bi-x-lg"></i> ล้าง
                </button>
              </div>
            </div>

            <div class="flex items-center gap-2 text-xs font-bold text-violet-600 bg-violet-50 border border-violet-100 rounded-xl px-3 py-2 mb-4">
              <i class="bi bi-person-check-fill"></i> เลือกแล้ว {{ selectedCount }} คน
            </div>

            <!-- ตารางรายชื่อ (mobile card + desktop table) -->
            <div class="max-h-[480px] overflow-y-auto overflow-x-hidden rounded-xl border border-slate-100">
              <div v-if="students.length === 0" class="text-center py-10 text-slate-400 text-sm">
                ยังไม่มีนักเรียนในห้องนี้
              </div>
              <div v-for="student in students" :key="student.student_no" class="border-b border-slate-50 last:border-0">
                <div class="flex items-center gap-3 px-3 py-3 hover:bg-slate-50/70 transition-colors">
                  <input
                    type="checkbox"
                    :checked="selectedNos.has(Number(student.student_no))"
                    @change="toggleSelect(student)"
                    class="w-5 h-5 rounded accent-violet-600 flex-shrink-0"
                  />
                  <div class="flex-shrink-0 w-8 h-8 rounded-full bg-slate-100 text-slate-500 flex items-center justify-center text-xs font-bold">
                    {{ student.student_no }}
                  </div>
                  <div class="min-w-0 flex-1">
                    <p class="text-sm font-bold text-slate-800 truncate">
                      {{ student.prefix || '' }}{{ student.first_name }} {{ student.last_name }}
                    </p>
                    <p class="text-[11px] text-slate-400">{{ student.nickname || '—' }}</p>
                  </div>

                  <!-- หน้าที่ (role_detail) — โผล่เมื่อติ๊ก -->
                  <input
                    v-if="selectedNos.has(Number(student.student_no))"
                    v-model="roleDetails[Number(student.student_no)]"
                    type="text"
                    placeholder="หน้าที่ เช่น ถือป้าย / สวัสดิการ"
                    class="flex-1 min-w-0 px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-violet-500/30 max-w-[180px]"
                  />

                  <!-- ⚙️ Advanced Meta ต่อคน -->
                  <button
                    v-if="selectedNos.has(Number(student.student_no))"
                    @click="openMetaModal(student)"
                    class="w-9 h-9 flex-shrink-0 rounded-lg text-slate-400 hover:text-violet-600 hover:bg-violet-50 transition-colors flex items-center justify-center"
                    title="กรอก Metadata เพิ่มเติม (เบอร์รถบัส ฯลฯ)"
                  >
                    <i class="bi bi-gear-fill"></i>
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- ปุ่มบันทึก -->
          <div class="mt-5 flex flex-col sm:flex-row justify-end gap-3">
            <router-link to="/activities" class="w-full sm:w-auto px-6 py-3 text-slate-500 hover:text-slate-800 hover:bg-slate-100 font-bold rounded-xl transition-all text-center">
              ยกเลิก
            </router-link>
            <button
              @click="submit"
              :disabled="isSaving"
              class="w-full sm:w-auto px-8 py-3 bg-violet-600 hover:bg-violet-700 disabled:opacity-60 text-white font-bold rounded-xl shadow-lg shadow-violet-600/20 transition-all inline-flex items-center justify-center gap-2"
            >
              <i v-if="isSaving" class="bi bi-arrow-repeat animate-spin"></i>
              <i v-else class="bi bi-check-lg"></i>
              {{ isSaving ? 'กำลังบันทึก...' : 'สร้างกิจกรรม' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- ⚙️ Modal: Metadata ผู้เข้าร่วม -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="showMetaModal" class="fixed inset-0 z-[70] bg-slate-900/40 backdrop-blur-sm flex items-end md:items-center justify-center p-0 md:p-4" @click.self="showMetaModal = false">
          <div class="w-full md:max-w-md bg-white rounded-t-3xl md:rounded-3xl shadow-2xl p-5 md:p-6 max-h-[90dvh] overflow-y-auto overflow-x-hidden">
            <div class="flex items-center justify-between mb-4">
              <h4 class="text-base font-bold text-slate-800 flex items-center gap-2">
                <i class="bi bi-gear-fill text-violet-500"></i>
                Metadata: {{ metaModalStudent?.prefix || '' }}{{ metaModalStudent?.first_name }}
              </h4>
              <button @click="showMetaModal = false" class="w-9 h-9 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700 flex items-center justify-center">
                <i class="bi bi-x-lg"></i>
              </button>
            </div>
            <p class="text-xs text-slate-400 mb-4">
              เก็บข้อมูลเฉพาะคน เช่น เบอร์รถบัส (bus_number), ห้องพัก (room_number), ไซส์เสื้อ (shirt_size)
            </p>
            <div class="space-y-3 mb-4">
              <div v-for="(meta, index) in metaModalEntries" :key="index" class="flex gap-2">
                <input
                  v-model="meta.key"
                  placeholder="คีย์ เช่น bus_number"
                  class="flex-1 min-w-0 px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-violet-500/30"
                />
                <input
                  v-model="meta.value"
                  placeholder="ค่า เช่น A1"
                  class="flex-1 min-w-0 px-3 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold focus:outline-none focus:ring-2 focus:ring-violet-500/30"
                />
                <button
                  v-if="metaModalEntries.length > 1"
                  @click="removeMetaRow(metaModalEntries, index)"
                  class="w-8 h-8 flex-shrink-0 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 flex items-center justify-center"
                >
                  <i class="bi bi-x-lg"></i>
                </button>
              </div>
            </div>
            <div class="flex justify-between items-center gap-3">
              <button
                @click="addMetaRow(metaModalEntries)"
                class="text-xs font-bold text-violet-600 bg-violet-50 hover:bg-violet-100 px-3 py-2 rounded-lg transition-colors inline-flex items-center gap-1"
              >
                <i class="bi bi-plus-lg"></i> เพิ่มคีย์
              </button>
              <button
                @click="saveMetaModal"
                class="px-6 py-2.5 bg-violet-600 hover:bg-violet-700 text-white font-bold rounded-xl shadow-lg shadow-violet-600/20 transition-all text-sm"
              >
                บันทึก metadata
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.25s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
