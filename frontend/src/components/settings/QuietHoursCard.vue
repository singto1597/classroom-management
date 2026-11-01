<script setup lang="ts">
/**
 * 🌙 QuietHoursCard — ช่วงงดรบกวนของห้อง (เวลาไทย)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * กฎที่ฝังไว้
 * ═══════════════════════════════════════════════════════════════════════════
 *  1. **สมาชิกทุกคนอ่านได้** — เพื่อเข้าใจว่าทำไมมือถือเงียบตอนกลางคืน
 *     แต่ **แก้ได้เฉพาะผู้มี `MANAGE_CLASSROOM_SETTINGS`** (backend บังคับอยู่แล้ว
 *     ที่นี่เพียงซ่อนฟอร์ม — ไม่ใช่การป้องกัน)
 *  2. `start === end` = ปิด (ข้อตกลงกับ backend) ⇒ อ่านค่าที่ได้มาแล้วแสดง "ปิดอยู่"
 *     ไม่พยายามเดาความหมายอื่น
 *  3. ช่วงข้ามเที่ยงคืน (22:00 → 07:00) เป็นค่าปกติ — ห้ามสลับ start/end ให้เอง
 *     เพราะนั่นคือการเปลี่ยนความหมายที่ผู้ใช้ตั้งไว้
 *  4. ถ้าบันทึกไม่สำเร็จ ฟอร์มต้อง **ไม่คงค่าที่ดูเหมือนบันทึกแล้ว** — ดึงค่าจริงกลับมา
 *
 * ⚠️ ประกาศ "ด่วน" ทะลุช่วงนี้ได้เสมอ — ต้องบอกผู้ใช้บนการ์ด ไม่ใช่ซ่อนในเอกสาร
 */
import { computed, onMounted, reactive, ref } from 'vue';
import Swal from 'sweetalert2';
import AppButton from '@/components/ui/AppButton.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import { NotificationService } from '@/services/notification';
import { useAuthStore } from '@/stores/auth';
import { UI_COLOR } from '@/constants/theme';
import type { QuietHours } from '@/types/notification';

const authStore = useAuthStore();
const roomId = authStore.currentRoomId ?? 0;

const canEdit = computed(
  () => authStore.isAdmin || authStore.currentPermissions.includes('MANAGE_CLASSROOM_SETTINGS'),
);

const isLoading = ref(true);
const loadError = ref<string | null>(null);
const isSaving = ref(false);

const form = reactive<QuietHours>({ enabled: false, start: '22:00', end: '07:00' });

const apply = (value: QuietHours) => {
  // start === end = ปิด — พยายามเก็บเวลาที่มีความหมายไว้ในฟอร์มถ้าทำได้
  form.enabled = value.enabled && value.start !== value.end;
  form.start = value.start;
  form.end = value.end;
};

const load = async () => {
  isLoading.value = true;
  loadError.value = null;
  try {
    apply(await NotificationService.getQuietHours(roomId));
  } catch (error) {
    loadError.value =
      error instanceof Error && error.message ? error.message : 'โหลดช่วงงดรบกวนไม่สำเร็จ';
  } finally {
    isLoading.value = false;
  }
};

onMounted(load);

const save = async () => {
  if (!canEdit.value || isSaving.value) return;

  // เวลาเริ่ม = เวลาสิ้นสุด แปลว่า "ปิด" ตามข้อตกลงฝั่ง backend
  // ⇒ ถ้าผู้ใช้เปิดสวิตช์แต่ตั้งสองช่องเท่ากัน ต้องเตือน ไม่ปล่อยผ่านเงียบ ๆ
  if (form.enabled && form.start === form.end) {
    await Swal.fire({
      icon: 'warning',
      title: 'เวลาเริ่มกับเวลาสิ้นสุดต้องไม่เท่ากัน',
      text: 'ถ้าไม่อยากให้งดรบกวน กรุณาปิดสวิตช์แทน',
      confirmButtonColor: UI_COLOR.brand,
    });
    return;
  }

  isSaving.value = true;
  try {
    const payload: QuietHours = form.enabled
      ? { enabled: true, start: form.start, end: form.end }
      : { enabled: false, start: form.start, end: form.start };
    apply(await NotificationService.setQuietHours(roomId, payload));
    await Swal.fire({
      icon: 'success',
      title: form.enabled ? 'บันทึกช่วงงดรบกวนแล้ว' : 'ปิดช่วงงดรบกวนแล้ว',
      text: form.enabled
        ? `แจ้งเตือนบนมือถือจะเงียบตั้งแต่ ${form.start} ถึง ${form.end} น.`
        : 'สมาชิกจะได้รับแจ้งเตือนบนมือถือทุกเวลา',
      timer: 2200,
      showConfirmButton: false,
    });
  } catch (error) {
    // ค่าที่ผู้ใช้เห็นต้องกลับไปตรงกับของจริงในฐานข้อมูล
    await load();
    await Swal.fire({
      icon: 'error',
      title: 'บันทึกไม่สำเร็จ',
      text: error instanceof Error ? error.message : 'เกิดข้อผิดพลาดจากระบบ โปรดลองใหม่',
      confirmButtonColor: UI_COLOR.brand,
    });
  } finally {
    isSaving.value = false;
  }
};
</script>

<template>
  <section class="page-card p-4 sm:p-6">
    <div class="flex items-start gap-3 border-b border-stone-100 pb-3 sm:pb-4">
      <div
        class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700"
      >
        <i class="bi bi-moon-stars-fill text-base" aria-hidden="true"></i>
      </div>
      <div class="min-w-0">
        <h2 class="section-title">ช่วงงดรบกวน</h2>
        <p class="mt-0.5 text-xs leading-relaxed text-stone-500">
          ช่วงเวลาที่ห้องนี้ไม่ส่งการแจ้งเตือนบนมือถือ — ตั้งเป็นเวลาของห้อง ไม่ใช่รายคน
        </p>
      </div>
    </div>

    <SkeletonRows v-if="isLoading" :rows="2" height="h-14" />

    <StateBlock
      v-else-if="loadError"
      variant="error"
      title="โหลดช่วงงดรบกวนไม่สำเร็จ"
      :hint="loadError"
      @retry="load"
    />

    <div v-else class="mt-3 space-y-3 sm:mt-4">
      <!-- สรุปสถานะปัจจุบัน (ทุกคนเห็น) -->
      <div
        class="flex items-start gap-3 rounded-xl border px-3.5 py-3"
        :class="form.enabled ? 'border-brand-200 bg-brand-50' : 'border-stone-200 bg-stone-50'"
      >
        <i
          :class="['bi', form.enabled ? 'bi-moon-fill text-brand-700' : 'bi-sun-fill text-stone-500', 'mt-0.5 text-base']"
          aria-hidden="true"
        ></i>
        <div class="min-w-0">
          <p class="text-sm font-bold text-stone-800">
            {{ form.enabled ? 'งดรบกวนอยู่' : 'ไม่เปิดช่วงงดรบกวน' }}
          </p>
          <p class="mt-0.5 text-xs leading-relaxed text-stone-600">
            <template v-if="form.enabled">
              ไม่ส่งแจ้งเตือนบนมือถือระหว่าง
              <span class="num font-bold">{{ form.start }}</span> ถึง
              <span class="num font-bold">{{ form.end }}</span> น.
            </template>
            <template v-else>แจ้งเตือนบนมือถือส่งได้ตลอดเวลา</template>
          </p>
        </div>
      </div>

      <p class="text-xs leading-relaxed text-stone-500">
        <i class="bi bi-info-circle me-1" aria-hidden="true"></i>
        ประกาศ "ด่วน" ทะลุช่วงงดรบกวนได้เสมอ — ใช้เฉพาะเรื่องที่ต้องรู้ทันที
      </p>

      <!-- ฟอร์ม (เฉพาะผู้มีสิทธิ์) -->
      <template v-if="canEdit">
        <label class="flex min-h-11 cursor-pointer items-center gap-2.5 rounded-xl border border-stone-200 px-3">
          <input v-model="form.enabled" type="checkbox" class="h-4 w-4 accent-brand-700" />
          <span class="text-sm font-bold text-stone-700">เปิดช่วงงดรบกวน</span>
        </label>

        <div v-if="form.enabled" class="grid grid-cols-2 gap-3">
          <div>
            <label class="field-label" for="quietStart">เริ่ม</label>
            <input id="quietStart" v-model="form.start" type="time" class="field" />
          </div>
          <div>
            <label class="field-label" for="quietEnd">สิ้นสุด</label>
            <input id="quietEnd" v-model="form.end" type="time" class="field" />
          </div>
        </div>

        <p v-if="form.enabled" class="text-xs leading-relaxed text-stone-500">
          ถ้าเวลาสิ้นสุดน้อยกว่าเวลาเริ่ม ระบบจะถือว่าข้ามเที่ยงคืน (เช่น 22:00 ถึง 07:00)
        </p>

        <AppButton variant="primary" :loading="isSaving" @click="save">
          <i class="bi bi-check2" aria-hidden="true"></i>
          บันทึกช่วงงดรบกวน
        </AppButton>
      </template>

      <p v-else class="flex items-center gap-2 text-xs font-bold text-stone-500">
        <i class="bi bi-lock-fill" aria-hidden="true"></i>
        เฉพาะผู้ดูแล / ผู้มีสิทธิ์จัดการตั้งค่าห้องเท่านั้นที่แก้ไขได้
      </p>
    </div>
  </section>
</template>
