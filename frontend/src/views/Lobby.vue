<script setup lang="ts">
defineOptions({ name: 'LobbyView' });

import { ref, onMounted, computed } from 'vue';
import { useRouter } from 'vue-router';
import { useAuthStore } from '@/stores/auth';
import { ClassroomService } from '@/services/classroom';
import { StudentService } from '@/services/student';
import PageHeader from '@/components/ui/PageHeader.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import type { UserRoom } from '@/types/classroom';
import type { Invite } from '@/types/student';
import Swal from 'sweetalert2';

const authStore = useAuthStore();
const router = useRouter();

const isLoadingRooms = ref(true);
const rooms = ref<UserRoom[]>([]);
const searchQuery = ref('');

// สถานะผิดพลาดของการโหลดห้อง (เดิมกลืน error เงียบ ๆ ทำให้เห็นเป็น "ยังไม่มีห้องเรียน")
const hasErrorRooms = ref(false);

// 🛡️ คำเชิญเข้าร่วมห้อง (Consent Model) — แอดมินแอดชื่อให้ ต้องกดรับเองก่อนถึงเป็นสมาชิก
const invites = ref<Invite[]>([]);

const fetchInvites = async () => {
  try {
    invites.value = await StudentService.getInvites();
  } catch (error: unknown) {
    console.error("Failed to load invites:", error);
  }
};

const acceptInvite = async (invite: Invite) => {
  try {
    await StudentService.acceptInvite(invite.invite_id);
    invites.value = invites.value.filter(i => i.invite_id !== invite.invite_id);
    await fetchRooms();
    return Swal.fire({
      icon: 'success',
      title: 'รับคำเชิญแล้ว!',
      text: `เข้าร่วมห้อง "${invite.room_name}" แล้ว`,
      confirmButtonText: 'รับทราบ',
      confirmButtonColor: '#1d4ed8'
    });
  } catch (error: unknown) {
    Swal.fire('ข้อผิดพลาด', error instanceof Error ? error.message : 'ไม่สามารถรับคำเชิญได้', 'error');
  }
};

// --- Modal States ---
const showCreateModal = ref(false);
const showJoinModal = ref(false);

const createForm = ref({ room_name: '' });
const joinForm = ref({ room_code: '', student_no: null as number | null, first_name: '', last_name: '', first_name_en: '', last_name_en: '' });

onMounted(async () => {
  if (!authStore.userId) {
    isLoadingRooms.value = false;
    return;
  }

  if (!authStore.firstName) {
    await authStore.fetchProfile();
  }

  await fetchRooms();
  await fetchInvites();
});

const fetchRooms = async () => {
  isLoadingRooms.value = true;
  hasErrorRooms.value = false;
  try {
    rooms.value = await ClassroomService.getUserRooms(authStore.userId!);
  } catch (error: unknown) {
    console.error("Failed to load rooms:", error);
    hasErrorRooms.value = true;
  } finally {
    isLoadingRooms.value = false;
  }
};

const filteredRooms = computed(() => {
  if (!searchQuery.value) return rooms.value;
  const q = searchQuery.value.toLowerCase();
  return rooms.value.filter(r =>
    (r.room_name && r.room_name.toLowerCase().includes(q)) ||
    (r.room_code && r.room_code.toLowerCase().includes(q))
  );
});

const selectRoom = (room: UserRoom) => {
  // 🎯 ยัดสิทธิ์ (is_admin, permissions) เข้า Store ตอนเลือกห้อง!
  authStore.setRoom(
    room.room_id,
    room.room_name,
    room.room_code,
    room.role,
    authStore.currentUserName,
    room.is_admin || false,
    room.permissions || []
  );
  router.push('/dashboard');
};

const openJoinModal = () => {
  joinForm.value = {
    room_code: '',
    student_no: null,
    first_name: authStore.firstName !== 'ไม่ระบุชื่อ' ? (authStore.firstName || '') : '',
    last_name: authStore.lastName || '',
    first_name_en: authStore.firstNameEn || '',
    last_name_en: authStore.lastNameEn || ''
  };
  showJoinModal.value = true;
};

const submitJoinRoom = async () => {
  // ✅ ตรวจสอบข้อมูลก่อนส่ง (รหัส, เลขที่, ชื่อ-นามสกุล)
  const code = joinForm.value.room_code.trim().toUpperCase();
  const no = Number(joinForm.value.student_no);

  if (!code) {
    return Swal.fire('ข้อมูลไม่ครบ', 'กรุณากรอกรหัสเข้าห้อง', 'warning');
  }
  if (!no || no <= 0) {
    return Swal.fire('ข้อมูลไม่ถูกต้อง', 'กรุณากรอกเลขที่ที่ถูกต้อง', 'warning');
  }
  if (!joinForm.value.first_name.trim() || !joinForm.value.last_name.trim()) {
    return Swal.fire('ข้อมูลไม่ครบ', 'กรุณากรอกชื่อและนามสกุลให้ครบถ้วน', 'warning');
  }

  try {
    Swal.fire({ title: 'กำลังตรวจสอบข้อมูล...', allowOutsideClick: false, didOpen: () => Swal.showLoading() });

    const payload = {
      room_code: code,
      student_no: no,
      first_name: joinForm.value.first_name.trim(),
      last_name: joinForm.value.last_name.trim(),
      first_name_en: joinForm.value.first_name_en.trim(),
      last_name_en: joinForm.value.last_name_en.trim()
    };

    const result = await ClassroomService.joinRoom(payload);

    // ✅ ตรวจสอบว่าเป็น "รอการอนุมัติ" (สมาชิกใหม่) หรือ "ยืนยันตัวตนสำเร็จ" (บัญชีผีถูกอ้างสิทธิ์ = active)
    const isPending = (result.message || '').includes('รอการอนุมัติ');

    if (isPending) {
      // 🚧 ยังไม่ active → อยู่หน้าเลือกห้อง รอหัวหน้าห้องอนุมัติ
      showJoinModal.value = false;
      await fetchRooms();
      return Swal.fire({
        icon: 'success',
        title: 'ส่งคำขอแล้ว!',
        text: 'รอหัวหน้าห้อง / ผู้ดูแลอนุมัติคำขอของคุณ',
        confirmButtonText: 'รับทราบ',
        confirmButtonColor: '#1d4ed8'
      });
    }

    // ✅ เข้าห้องได้เลย (ยืนยันตัวตนสำเร็จ)
    Swal.fire({
      icon: 'success',
      title: 'สำเร็จ!',
      text: result.message || 'เข้าสู่ห้องเรียนสำเร็จ',
      confirmButtonText: 'เข้าสู่แดชบอร์ด',
      confirmButtonColor: '#1d4ed8'
    }).then(() => {
      showJoinModal.value = false;
      // 🎯 เข้าห้องใหม่ สิทธิ์ตั้งต้นจะเป็น False และ []
      authStore.setRoom(result.room_id, result.room_name, payload.room_code, 'student', authStore.currentUserName, false, []);
      router.push('/dashboard');
    });

  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : '';
    Swal.fire({
      icon: 'error',
      title: 'ไม่สามารถเข้าร่วมได้',
      text: message || 'รหัสห้องผิด หรือเลขที่นี้มีผู้ใช้งานแล้ว',
      confirmButtonColor: '#1d4ed8',
      confirmButtonText: 'รับทราบ'
    });
  }
};

const submitCreateRoom = async () => {
  try {
    Swal.fire({ title: 'กำลังสร้างห้อง...', allowOutsideClick: false, didOpen: () => Swal.showLoading() });
    const result = await ClassroomService.createRoom({ room_name: createForm.value.room_name });

    Swal.fire({
      icon: 'success',
      title: 'สร้างห้องเรียนสำเร็จ!',
      text: `นำรหัสห้อง ${result.room_code} ไปแชร์ให้นักเรียนได้เลย`,
      confirmButtonText: 'ตกลง',
      confirmButtonColor: '#1d4ed8'
    }).then(() => {
      showCreateModal.value = false;
      fetchRooms();
    });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : '';
    Swal.fire('ข้อผิดพลาด', message || 'ไม่สามารถสร้างห้องได้', 'error');
  }
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <!-- ============================================ -->
    <!-- หัวหน้าแบบบรรณาธิการ                          -->
    <!-- ============================================ -->
    <PageHeader
      eyebrow="Choose a Classroom"
      :title="`ยินดีต้อนรับ, ${authStore.firstName || authStore.firstNameEn || 'ผู้ใช้งาน'}`"
      description="เลือกห้องเรียนของคุณเพื่อเริ่มต้นการจัดการ หรือเข้าร่วมห้องใหม่ด้วยรหัสห้อง"
    >
      <template #actions>
        <button type="button" class="btn-ghost-ui" @click="openJoinModal">
          <i class="bi bi-door-open" aria-hidden="true"></i> เข้าห้องเรียน
        </button>
        <button type="button" class="btn-primary" @click="showCreateModal = true">
          <i class="bi bi-plus-lg" aria-hidden="true"></i> สร้างห้อง
        </button>
      </template>
    </PageHeader>

    <!-- ค้นหาห้อง -->
    <div class="relative">
      <div class="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-3.5">
        <i class="bi bi-search text-stone-400" aria-hidden="true"></i>
      </div>
      <input
        v-model="searchQuery"
        type="text"
        placeholder="ค้นหาชื่อห้อง หรือ รหัส..."
        class="field ps-11"
      />
    </div>

    <!-- 🛡️ คำเชิญเข้าร่วมห้อง (Consent Model) — แอดมินแอดชื่อให้ ต้องกดรับเองก่อน -->
    <section v-if="invites.length > 0" class="space-y-3">
      <div class="flex flex-wrap items-center gap-2">
        <h2 class="section-title">คำเชิญเข้าร่วมห้อง</h2>
        <span class="chip bg-amber-50 text-amber-700">{{ invites.length }} ฉบับ</span>
      </div>

      <div class="space-y-2.5">
        <div v-for="invite in invites" :key="invite.invite_id" class="page-card p-4 sm:p-5">
          <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div class="flex min-w-0 items-start gap-3">
              <div
                class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-50 text-amber-600"
              >
                <i class="bi bi-building-add text-lg" aria-hidden="true"></i>
              </div>
              <div class="min-w-0">
                <p class="truncate font-bold text-stone-900">{{ invite.room_name }}</p>
                <p class="num mt-0.5 truncate text-xs text-stone-500">
                  เลขที่ {{ invite.student_no }} · เชิญโดย {{ invite.added_by_first || '' }}
                  {{ invite.added_by_last || '' }}
                </p>
                <p class="mt-1 text-[11px] font-medium text-amber-600">
                  รับคำเชิญแล้วระบบจะเปิดข้อมูลส่วนตัวของคุณให้ห้องนี้ดู
                </p>
              </div>
            </div>

            <button type="button" class="btn-primary shrink-0" @click="acceptInvite(invite)">
              <i class="bi bi-check-lg" aria-hidden="true"></i> รับคำเชิญ
            </button>
          </div>
        </div>
      </div>
    </section>

    <!-- ============================================ -->
    <!-- รายการห้อง — โหลด / ผิดพลาด / ว่าง / มีข้อมูล  -->
    <!-- ============================================ -->
    <SkeletonRows v-if="isLoadingRooms" :rows="3" height="h-32" />

    <StateBlock
      v-else-if="hasErrorRooms"
      variant="error"
      title="โหลดรายการห้องไม่สำเร็จ"
      hint="ตรวจสอบการเชื่อมต่อแล้วลองใหม่อีกครั้ง"
      @retry="fetchRooms"
    />

    <StateBlock
      v-else-if="filteredRooms.length === 0"
      variant="empty"
      title="ยังไม่มีห้องเรียน"
      hint="คุณสามารถสร้างห้องใหม่ หรือขอรหัสเพื่อเข้าร่วมห้องได้เลย"
    />

    <div v-else class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <div
        v-for="room in filteredRooms"
        :key="room.room_id"
        class="page-card card-hover cursor-pointer p-4 sm:p-5"
        @click="selectRoom(room)"
      >
        <div class="flex items-start justify-between gap-3">
          <div
            class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-stone-100 text-stone-500"
          >
            <i class="bi bi-buildings text-xl" aria-hidden="true"></i>
          </div>

          <!-- 🎯 โซนโชว์ป้าย (Role & Admin Badges) -->
          <div class="flex flex-wrap items-center justify-end gap-1.5">
            <span class="chip bg-stone-100 text-stone-600">{{ room.role }}</span>
            <span v-if="room.is_admin" class="chip bg-brand-50 text-brand-700">
              <i class="bi bi-shield-lock-fill" aria-hidden="true"></i> ADMIN
            </span>
            <span
              v-else-if="room.permissions && room.permissions.length > 0"
              class="chip bg-sky-50 text-sky-700"
            >
              <i class="bi bi-key-fill" aria-hidden="true"></i> STAFF
            </span>
          </div>
        </div>

        <h3 class="font-display mt-4 truncate text-base font-bold text-stone-900">
          {{ room.room_name }}
        </h3>
        <p class="font-display num mt-1 flex items-center gap-1.5 truncate text-sm font-bold tracking-widest text-stone-500">
          <i class="bi bi-key shrink-0 text-stone-300" aria-hidden="true"></i>
          {{ room.room_code || 'ไม่มีรหัส' }}
        </p>

        <div class="mt-4 flex items-center justify-between gap-3 border-t border-stone-100 pt-3">
          <span class="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-stone-500">
            <span class="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" aria-hidden="true"></span>
            {{ room.status }}
          </span>
          <i class="bi bi-arrow-right shrink-0 text-stone-300" aria-hidden="true"></i>
        </div>
      </div>
    </div>

    <!-- ============================================ -->
    <!-- Modals                                       -->
    <!-- ============================================ -->
    <Transition name="fade">
      <div
        v-if="showJoinModal"
        class="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/40 p-4"
      >
        <div class="page-card w-full max-w-md max-h-[90vh] overflow-y-auto overscroll-contain p-5 sm:p-6">
          <div
            class="flex h-12 w-12 items-center justify-center rounded-xl bg-brand-50 text-brand-700"
          >
            <i class="bi bi-door-open-fill text-xl" aria-hidden="true"></i>
          </div>
          <h2 class="font-display mt-4 text-xl font-bold text-stone-900">เข้าร่วมห้องเรียน</h2>
          <p class="mt-1 text-sm leading-relaxed text-stone-500">
            กรอกรหัส 6 หลัก และตรวจสอบชื่อของคุณให้ตรงกับระบบเพื่อยืนยันตัวตน
          </p>

          <form class="mt-5 space-y-4" @submit.prevent="submitJoinRoom">
            <div>
              <label class="field-label" for="joinRoomCode">
                รหัสเข้าห้อง <span class="text-red-500">*</span>
              </label>
              <input
                id="joinRoomCode"
                v-model="joinForm.room_code"
                type="text"
                required
                placeholder="เช่น AB12CD"
                class="field font-mono font-bold uppercase placeholder:font-sans placeholder:normal-case"
              />
            </div>

            <div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div class="sm:col-span-1">
                <label class="field-label" for="joinStudentNo">
                  เลขที่ <span class="text-red-500">*</span>
                </label>
                <input
                  id="joinStudentNo"
                  v-model="joinForm.student_no"
                  type="number"
                  required
                  class="field num text-center"
                />
              </div>
              <div class="sm:col-span-2">
                <label class="field-label" for="joinFirstName">
                  ชื่อจริง <span class="text-red-500">*</span>
                </label>
                <input id="joinFirstName" v-model="joinForm.first_name" type="text" required class="field" />
              </div>
            </div>

            <div>
              <label class="field-label" for="joinLastName">
                นามสกุล <span class="text-red-500">*</span>
              </label>
              <input id="joinLastName" v-model="joinForm.last_name" type="text" required class="field" />
            </div>

            <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label class="field-label" for="joinFirstNameEn">
                  ชื่อจริง (อังกฤษ)
                  <span class="font-normal normal-case text-stone-400">ไม่บังคับ</span>
                </label>
                <input id="joinFirstNameEn" v-model="joinForm.first_name_en" type="text" class="field" />
              </div>
              <div>
                <label class="field-label" for="joinLastNameEn">
                  นามสกุล (อังกฤษ)
                  <span class="font-normal normal-case text-stone-400">ไม่บังคับ</span>
                </label>
                <input id="joinLastNameEn" v-model="joinForm.last_name_en" type="text" class="field" />
              </div>
            </div>

            <div
              class="flex flex-col-reverse gap-2 border-t border-stone-100 pt-4 sm:flex-row sm:justify-end"
            >
              <button type="button" class="btn-ghost-ui" @click="showJoinModal = false">ยกเลิก</button>
              <button type="submit" class="btn-primary">ยืนยันเข้าร่วม</button>
            </div>
          </form>
        </div>
      </div>
    </Transition>

    <Transition name="fade">
      <div
        v-if="showCreateModal"
        class="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/40 p-4"
      >
        <div class="page-card w-full max-w-md p-5 sm:p-6">
          <div
            class="flex h-12 w-12 items-center justify-center rounded-xl bg-brand-50 text-brand-700"
          >
            <i class="bi bi-plus-circle-fill text-xl" aria-hidden="true"></i>
          </div>
          <h2 class="font-display mt-4 text-xl font-bold text-stone-900">สร้างห้องเรียนใหม่</h2>
          <p class="mt-1 text-sm leading-relaxed text-stone-500">
            ตั้งชื่อห้องเรียนของคุณ ระบบจะสร้างรหัสสำหรับแชร์ให้นักเรียนอัตโนมัติ
          </p>

          <form class="mt-5" @submit.prevent="submitCreateRoom">
            <div>
              <label class="field-label" for="createRoomName">
                ชื่อห้องเรียน <span class="text-red-500">*</span>
              </label>
              <input
                id="createRoomName"
                v-model="createForm.room_name"
                type="text"
                required
                placeholder="เช่น ม.4/1, สมเกียรติวิทยา"
                class="field"
              />
            </div>

            <div
              class="mt-5 flex flex-col-reverse gap-2 border-t border-stone-100 pt-4 sm:flex-row sm:justify-end"
            >
              <button type="button" class="btn-ghost-ui" @click="showCreateModal = false">ยกเลิก</button>
              <button type="submit" class="btn-primary">สร้างห้อง</button>
            </div>
          </form>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
