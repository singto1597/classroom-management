<script setup lang="ts">
import { computed } from 'vue';
import { useAuthStore } from '@/stores/auth';
import Swal from 'sweetalert2';
import PageHeader from '@/components/ui/PageHeader.vue';

const authStore = useAuthStore();

const currentRoomCode = computed(() => {
  return authStore.currentRoomCode || 'N/A';
});

// ถ้าไม่ได้ตั้งค่า env ไว้ เดิมจะ fallback เป็น '#' ทำให้ปุ่มหลักกดแล้วเหมือนไม่มีอะไรเกิดขึ้น
// (เบราว์เซอร์เลื่อนกลับขึ้นบนสุด) — แยกเป็นค่าว่างแล้วปิดปุ่มพร้อมบอกสาเหตุแทน
const botInviteUrl = computed(() => {
  return import.meta.env.VITE_DISCORD_BOT_INVITE_URL || '';
});

const hasBotInviteUrl = computed(() => botInviteUrl.value.length > 0);

const copyRoomCode = async () => {
  try {
    await navigator.clipboard.writeText(currentRoomCode.value);
    Swal.fire({
      icon: 'success',
      title: 'คัดลอกแล้ว!',
      text: `รหัสห้อง "${currentRoomCode.value}" ถูกคัดลอกไปยังคลิปบอร์ดแล้ว`,
      timer: 2000,
      showConfirmButton: false,
    });
  } catch {
    Swal.fire({
      icon: 'error',
      title: 'ไม่สามารถคัดลอกได้',
      text: 'กรุณาคัดลอกด้วยตนเอง',
      confirmButtonColor: '#1d4ed8',
    });
  }
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader
      eyebrow="Discord Integration"
      title="เชื่อมต่อ Discord"
      description="รับการแจ้งเตือนและเช็คข้อมูลส่วนตัวผ่านบอท"
    />

    <div class="page-card overflow-hidden">
      <div class="flex items-center gap-3 border-b border-stone-200 bg-stone-50/70 px-4 py-3.5 sm:px-5">
        <div
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-700 text-white"
        >
          <i class="bi bi-discord text-base" aria-hidden="true"></i>
        </div>
        <div class="min-w-0">
          <p class="section-title truncate">ขั้นตอนการเชื่อมต่อ</p>
          <p class="truncate text-xs text-stone-500">ทำตามลำดับสองขั้นตอนด้านล่าง</p>
        </div>
      </div>

      <!-- ลำดับขั้นด้วยเลข font-display คั่นด้วยเส้น hairline ไม่ใช่การ์ดซ้อนการ์ด -->
      <ol class="divide-y divide-stone-100">
        <li class="flex gap-3 p-4 sm:gap-4 sm:p-5">
          <span
            class="num flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-50 font-display text-sm font-bold text-brand-700"
            aria-hidden="true"
          >
            1
          </span>
          <div class="min-w-0 flex-1">
            <h2 class="section-title">เชิญบอทเข้าเซิร์ฟเวอร์ของคุณ</h2>
            <p class="mt-1 text-sm leading-relaxed text-stone-500">
              คลิกปุ่มด้านล่างเพื่อเพิ่มบอทลงในเซิร์ฟเวอร์ Discord
              ที่คุณต้องการรับการแจ้งเตือน
            </p>
            <a
              v-if="hasBotInviteUrl"
              :href="botInviteUrl"
              target="_blank"
              rel="noopener noreferrer"
              class="btn-primary mt-3"
            >
              <i class="bi bi-discord" aria-hidden="true"></i>
              เพิ่มบอทลง Discord
            </a>
            <template v-else>
              <button type="button" class="btn-primary mt-3" disabled>
                <i class="bi bi-discord" aria-hidden="true"></i>
                เพิ่มบอทลง Discord
              </button>
              <p class="mt-2 text-xs leading-relaxed text-amber-700">
                <i class="bi bi-exclamation-triangle-fill me-1" aria-hidden="true"></i>
                ยังไม่ได้ตั้งค่าลิงก์เชิญบอทในระบบ กรุณาแจ้งผู้ดูแลระบบ
              </p>
            </template>
          </div>
        </li>

        <li class="flex gap-3 p-4 sm:gap-4 sm:p-5">
          <span
            class="num flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-50 font-display text-sm font-bold text-brand-700"
            aria-hidden="true"
          >
            2
          </span>
          <div class="min-w-0 flex-1">
            <h2 class="section-title">พิมพ์คำสั่งใน Discord</h2>
            <p class="mt-1 text-sm leading-relaxed text-stone-500">
              หลังจากเพิ่มบอทแล้ว ให้พิมพ์คำสั่งด้านล่างในช่องแชท
              (หรือ DM หาบอท) เพื่อเชื่อมต่อบัญชีของคุณกับห้องเรียน
            </p>

            <div class="mt-3 space-y-2.5 rounded-xl bg-stone-50 p-3.5">
              <div
                class="overflow-x-auto whitespace-nowrap rounded-xl bg-stone-900 px-3.5 py-3 font-mono text-sm text-emerald-300"
              >
                <span class="text-stone-500">/</span>sync_room
                <span class="text-amber-300">{{ currentRoomCode }}&nbsp;</span><span
                  class="text-brand-300"
                  >5</span
                >
              </div>
              <p class="text-xs leading-relaxed text-stone-500">
                เปลี่ยนเลข
                <span class="font-bold text-brand-700">5</span>
                เป็นเลขที่ของคุณ (เช่น
                <span class="font-bold text-brand-700">1</span>,
                <span class="font-bold text-brand-700">12</span>,
                <span class="font-bold text-brand-700">30</span>)
              </p>
            </div>

            <div class="mt-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
              <span class="text-sm font-semibold text-stone-500">รหัสห้อง:</span>
              <code
                class="min-w-0 max-w-full self-start truncate rounded-lg bg-stone-100 px-3 py-1.5 font-mono text-sm font-bold text-stone-800"
              >
                {{ currentRoomCode }}
              </code>
              <button type="button" class="btn-ghost-ui shrink-0 sm:ms-auto" @click="copyRoomCode">
                <i class="bi bi-clipboard" aria-hidden="true"></i>
                คัดลอก
              </button>
            </div>
          </div>
        </li>
      </ol>
    </div>

    <RouterLink to="/dashboard" class="btn-ghost-ui w-full sm:w-auto">
      <i class="bi bi-arrow-left" aria-hidden="true"></i>
      กลับสู่หน้าหลัก
    </RouterLink>
  </div>
</template>
