<script setup lang="ts">
/**
 * 📊 PushStatsCard — สถิติการส่งแจ้งเตือนบนมือถือ (P6.5)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * กฎที่ฝังไว้ — อ่านก่อนแก้
 * ═══════════════════════════════════════════════════════════════════════════
 *  1. **"จะลองใหม่" ≠ "ยอมแพ้"** — `retry` ยังมีโอกาสสำเร็จ ส่วน `dropped`/`stale`
 *     คือหมดหวังแล้ว (ครบจำนวนครั้ง/อุปกรณ์ถูกลบ) ⇒ ห้ามรวมเป็นตัวเลขเดียว
 *     ไม่งั้นการ์ดจะดูปกติทั้งที่อุปกรณ์ของนักเรียนตายไปครึ่งห้อง
 *  2. **`null` ≠ `0`** — `last_round = null` แปลว่า "ไม่รู้" (worker ยังไม่เคยรายงาน
 *     หรือ Redis ต่อไม่ได้) ส่วน 0 แปลว่า "รอบล่าสุดไม่มีงาน" ⇒ ข้อความต้องต่างกัน
 *  3. **`last_round` เป็นของทั้งระบบ** — worker ตัวเดียวส่งให้ทุกห้อง ⇒ ต้องเขียนกำกับ
 *     ไม่ให้ผู้ดูแลอ่านว่าเป็นตัวเลขของห้องตัวเอง
 *  4. **สิทธิ์**: การ์ดนี้แสดงเฉพาะผู้มี `MANAGE_CLASSROOM_SETTINGS` — ผู้ปกครองฝั่งหน้า
 *     ใช้ `computed` เดียวกับ backend (AND เดียวกัน) ไม่ใช่ CSS ซ่อน
 *
 * ⚠️ ตัวเลขทั้งหมดอ่านจาก API ตรง ๆ — ไม่มีสูตรคำนวณฝั่งหน้า (กฎ "การ์ด = ลิสต์")
 */
import { computed, onMounted, ref } from 'vue';
import AppButton from '@/components/ui/AppButton.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import { NotificationService } from '@/services/notification';
import { useAuthStore } from '@/stores/auth';
import { formatThaiDateTime } from '@/utils/datetime';
import type { PushDeliveryStats } from '@/types/notification';

const authStore = useAuthStore();
const roomId = authStore.currentRoomId ?? 0;

const stats = ref<PushDeliveryStats | null>(null);
const isLoading = ref(true);
const loadError = ref<string | null>(null);

const load = async () => {
  isLoading.value = true;
  loadError.value = null;
  try {
    stats.value = await NotificationService.getPushStats(roomId);
  } catch (error) {
    loadError.value =
      error instanceof Error && error.message ? error.message : 'โหลดสถิติการส่งไม่สำเร็จ';
  } finally {
    isLoading.value = false;
  }
};

onMounted(load);

/** ต่ออายุ heartbeat ของ worker คือ 600 วิ (core/heartbeat.py) — เกินนั้นคือ "เงียบ" */
const HEARTBEAT_SILENT_SECONDS = 600;

const formatAge = (seconds: number): string => {
  if (seconds < 60) return `${seconds} วินาที`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} นาที`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} ชั่วโมง`;
  return `${Math.floor(seconds / 86400)} วัน`;
};

/** รวมสองสถานะ "ยอมแพ้" เพื่อแสดงบรรทัดเดียว แต่แยกตัวเลขไว้ใน tooltip/รายละเอียด */
const gaveUp = computed(() =>
  stats.value ? stats.value.queue.dropped + stats.value.queue.stale : 0,
);

type WorkerState = 'live' | 'silent' | 'disabled' | 'unknown';

const workerState = computed<WorkerState>(() => {
  const value = stats.value;
  if (!value) return 'unknown';
  if (value.last_round && !value.last_round.enabled) return 'disabled';
  if (value.worker_heartbeat_age_seconds === null) return 'unknown';
  if (value.worker_heartbeat_age_seconds > HEARTBEAT_SILENT_SECONDS) return 'silent';
  return 'live';
});

const WORKER_MESSAGE: Record<WorkerState, { icon: string; title: string; hint: string; box: string }> = {
  live: {
    icon: 'bi-broadcast',
    title: 'ตัวส่งแจ้งเตือนทำงานอยู่',
    hint: 'รายงานล่าสุด {age}ที่แล้ว — คิวถูกส่งตามปกติ',
    box: 'border-ok-200 bg-ok-50',
  },
  silent: {
    icon: 'bi-exclamation-triangle-fill',
    title: 'ตัวส่งแจ้งเตือนเงียบไปแล้ว',
    hint: 'ติดต่อครั้งล่าสุด {age}ที่แล้ว — แจ้งเตือนจะค้างในคิวจนกว่าจะกลับมา',
    box: 'border-danger-200 bg-danger-50',
  },
  disabled: {
    icon: 'bi-pause-fill',
    title: 'ยังไม่ได้เปิดระบบส่งแจ้งเตือน',
    hint: 'ยังไม่ได้ตั้งคีย์ VAPID — แจ้งเตือนในแอปยังทำงาน แต่ push ไม่ออก',
    box: 'border-warn-200 bg-warn-50',
  },
  unknown: {
    icon: 'bi-question-circle-fill',
    title: 'ยังไม่ทราบสถานะตัวส่ง',
    hint: 'ยังไม่ได้รับรายงานจากตัวส่ง — ถ้าแจ้งเตือนบนมือถือไม่เข้า ให้แจ้งผู้ดูแลระบบ',
    box: 'border-stone-200 bg-stone-50',
  },
};

const workerMessage = computed(() => WORKER_MESSAGE[workerState.value]);

const workerHint = computed(() => {
  const age = stats.value?.worker_heartbeat_age_seconds;
  if (age === null || age === undefined) return workerMessage.value.hint;
  return workerMessage.value.hint.replace('{age}', formatAge(age));
});
</script>

<template>
  <section class="page-card p-4 sm:p-6">
    <div class="flex items-start gap-3 border-b border-stone-100 pb-3 sm:pb-4">
      <div
        class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700"
      >
        <i class="bi bi-bar-chart-line-fill text-base" aria-hidden="true"></i>
      </div>
      <div class="min-w-0 flex-1">
        <h2 class="section-title">สถานะการส่งแจ้งเตือน</h2>
        <p class="mt-0.5 text-xs leading-relaxed text-stone-500">
          คิวของห้องนี้ และรอบล่าสุดของตัวส่ง (ใช้ร่วมทุกห้อง) — สำหรับผู้ดูแลเท่านั้น
        </p>
      </div>
      <AppButton v-if="!isLoading" variant="quiet" :disabled="isLoading" @click="load">
        <i class="bi bi-arrow-clockwise" aria-hidden="true"></i>
        <span class="sr-only">โหลดใหม่</span>
      </AppButton>
    </div>

    <SkeletonRows v-if="isLoading" :rows="3" height="h-16" />

    <StateBlock
      v-else-if="loadError"
      variant="error"
      title="โหลดสถิติการส่งไม่สำเร็จ"
      :hint="loadError"
      @retry="load"
    />

    <div v-else-if="stats" class="mt-3 space-y-4 sm:mt-4">
      <!-- สถานะของตัวส่ง — ต้องมาก่อนตัวเลข เพื่อไม่ให้อ่านตัวเลขผิดความหมาย -->
      <div class="flex items-start gap-3 rounded-xl border px-3.5 py-3" :class="workerMessage.box">
        <i :class="['bi', workerMessage.icon, 'mt-0.5 text-base']" aria-hidden="true"></i>
        <div class="min-w-0">
          <p class="text-sm font-bold text-stone-800">{{ workerMessage.title }}</p>
          <p class="mt-0.5 text-xs leading-relaxed text-stone-600">{{ workerHint }}</p>
        </div>
      </div>

      <!-- ตัวเลขคิวของห้องนี้ -->
      <div class="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        <div class="rounded-xl border border-stone-200 bg-stone-50 px-3 py-2.5">
          <p class="text-[11px] font-bold text-stone-500">ส่งสำเร็จ (24 ชม.)</p>
          <p class="num mt-0.5 text-xl font-bold text-ok-700">{{ stats.queue.sent_24h }}</p>
        </div>
        <div class="rounded-xl border border-stone-200 bg-stone-50 px-3 py-2.5">
          <p class="text-[11px] font-bold text-stone-500">รอส่ง</p>
          <p class="num mt-0.5 text-xl font-bold text-stone-800">{{ stats.queue.pending }}</p>
        </div>
        <div class="rounded-xl border border-warn-200 bg-warn-50 px-3 py-2.5">
          <p class="text-[11px] font-bold text-warn-700">จะลองใหม่</p>
          <p class="num mt-0.5 text-xl font-bold text-warn-700">{{ stats.queue.retry }}</p>
        </div>
        <div class="rounded-xl border border-danger-200 bg-danger-50 px-3 py-2.5">
          <p class="text-[11px] font-bold text-danger-700">ยอมแพ้แล้ว</p>
          <p class="num mt-0.5 text-xl font-bold text-danger-700">{{ gaveUp }}</p>
        </div>
      </div>

      <!-- รายละเอียดเฉพาะเมื่อมีของค้าง/ของที่ถูกทิ้ง — ไม่กวนตอนทุกอย่างปกติ -->
      <p v-if="stats.queue.due_now > 0" class="text-xs leading-relaxed text-warn-700">
        <i class="bi bi-clock-history me-1" aria-hidden="true"></i>
        มี <span class="num font-bold">{{ stats.queue.due_now }}</span> รายการถึงกำหนดแล้วแต่ยังไม่ได้ส่ง —
        รอนานที่สุด <span class="num font-bold">{{ formatAge(stats.queue.oldest_due_seconds) }}</span>
      </p>

      <p v-if="gaveUp > 0" class="text-xs leading-relaxed text-stone-600">
        <i class="bi bi-info-circle me-1" aria-hidden="true"></i>
        "ยอมแพ้" คือเลิกส่งแล้วจริง ๆ — แยกเป็นครบจำนวนครั้ง
        <span class="num font-bold">{{ stats.queue.dropped }}</span> รายการ
        และอุปกรณ์ถูกลบ/ใช้ไม่ได้
        <span class="num font-bold">{{ stats.queue.stale }}</span> รายการ
        ⇒ นักเรียนกลุ่มนี้อาจไม่ได้รับแจ้งเตือนบนมือถืออีกจนกว่าจะเปิดใหม่
      </p>

      <!-- รอบล่าสุดของ worker — ทั้งระบบ -->
      <div class="rounded-xl border border-stone-200 px-3.5 py-3">
        <p class="text-xs font-bold text-stone-700">
          รอบล่าสุดของตัวส่ง
          <span class="font-normal text-stone-500">— ใช้ร่วมทุกห้อง ไม่ใช่เฉพาะห้องนี้</span>
        </p>

        <p v-if="!stats.last_round" class="mt-1.5 text-xs leading-relaxed text-stone-500">
          <i class="bi bi-dash-circle me-1" aria-hidden="true"></i>
          ยังไม่ได้รับรายงานรอบล่าสุด — ไม่ได้หมายความว่าไม่มีอะไรถูกส่ง
        </p>

        <template v-else>
          <p class="mt-1 text-[11px] font-bold text-stone-500">
            {{ formatThaiDateTime(stats.last_round.at) }} น.
          </p>
          <dl class="mt-2 grid grid-cols-3 gap-y-2 text-xs sm:grid-cols-5">
            <div>
              <dt class="text-stone-500">หยิบมา</dt>
              <dd class="num font-bold text-stone-800">{{ stats.last_round.claimed }}</dd>
            </div>
            <div>
              <dt class="text-stone-500">สำเร็จ</dt>
              <dd class="num font-bold text-ok-700">{{ stats.last_round.sent }}</dd>
            </div>
            <div>
              <dt class="text-stone-500">ลองใหม่</dt>
              <dd class="num font-bold text-warn-700">{{ stats.last_round.retry }}</dd>
            </div>
            <div>
              <dt class="text-stone-500">งดรบกวน</dt>
              <dd class="num font-bold text-stone-800">{{ stats.last_round.deferred }}</dd>
            </div>
            <div>
              <dt class="text-stone-500">ทิ้ง/หมดอายุ</dt>
              <dd class="num font-bold text-danger-700">
                {{ stats.last_round.dropped + stats.last_round.stale }}
              </dd>
            </div>
          </dl>
          <p class="mt-2 text-[11px] leading-relaxed text-stone-500">
            "งดรบกวน" = เลื่อนการส่งออกไปโดยยังไม่นับเป็นการลองที่ล้มเหลว —
            เกิดจากช่วงงดรบกวนของห้อง ไม่ใช่ความผิดพลาด
          </p>
        </template>
      </div>
    </div>
  </section>
</template>
