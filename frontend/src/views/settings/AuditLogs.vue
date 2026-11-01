<script setup lang="ts">
/**
 * 🔍 บันทึกกิจกรรมของห้อง — หน้าดูสำหรับผู้บริหารห้อง (P6.2)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * หน้านี้ถืออะไรไว้
 * ═══════════════════════════════════════════════════════════════════════════
 *  · รายการ "ใครทำอะไร เมื่อไร จากที่ไหน" จากตาราง `audit_logs`
 *  · ตัวกรอง: ช่วงวันที่ (เวลาไทย, รวมวันสุดท้าย) · บริการ · การกระทำ · สถานะ · คำค้น
 *  · เลื่อนหน้าแบบ **keyset** — ใช้ `next_cursor` จาก backend ตรง ๆ ห้ามคำนวณ offset
 *    (ตารางนี้มีแถวใหม่แทรกหัวตลอดเวลา ⇒ offset จะทำให้เห็นซ้ำ/ข้าม)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * กฎที่ฝังไว้
 * ═══════════════════════════════════════════════════════════════════════════
 *  1. **สิทธิ์ฝั่งหน้า = นิพจน์เดียวกับ backend** (`hasPermission` มี isAdmin bypass)
 *     แต่ไม่ใช่ด่านความปลอดภัย — backend ตอบ 403 เองถ้าไม่มีสิทธิ์
 *  2. **เปลี่ยนตัวกรอง = เริ่มจากหน้าแรก** (ทิ้ง cursor เสมอ) ไม่งั้นจะได้หน้า 2
 *     ของชุดใหม่ที่ไม่มีหัวต่อ ⇒ ใช้ `resetAndLoad()` ทุกครั้งที่ตัวกรองเปลี่ยน
 *  3. **ข้อความว่างสองแบบ**: ยังไม่มีบันทึกเลย กับ "กรองแล้วไม่เจอ" — ทางออกคนละทาง
 *     (ล้างตัวกรอง vs กลับไปทำรายการ)
 *  4. ค่าที่ละเอียด (IP / User-Agent / old–new values) ซ่อนใต้ `<details>` —
 *     เป็นข้อมูลสำหรับสืบเหตุ ไม่ใช่อ่านประจำวัน
 */
import { computed, onMounted, reactive, ref } from 'vue';
import PageHeader from '@/components/ui/PageHeader.vue';
import AppButton from '@/components/ui/AppButton.vue';
import AppEmptyState from '@/components/ui/AppEmptyState.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import { AuditService } from '@/services/audit';
import { useAuthStore } from '@/stores/auth';
import { formatThaiDateTime } from '@/utils/datetime';
import type { AuditLogItem, AuditLogOptions, AuditLogPage } from '@/types/audit';

const authStore = useAuthStore();
const roomId = authStore.currentRoomId ?? 0;

// 🔒 นิพจน์เดียวกับ backend — `is_admin` ผ่านทุกด่าน ไม่ต้องถือสิทธิ์รายตัว
const canView = computed(() => authStore.hasPermission('VIEW_AUDIT_LOGS'));

const messageOf = (err: unknown): string =>
  err instanceof Error && err.message ? err.message : 'เกิดข้อผิดพลาดจากระบบ';

// ── ตัวกรอง ────────────────────────────────────────────────────────────────
// `date_from`/`date_to` เป็น `YYYY-MM-DD` ตาม `<input type="date">` — backend รับ
// เป็น DATE และตีความเป็นวันตามเวลาไทยที่ฝั่งนั้น (ไม่ต้องแปลง TZ ที่หน้า)
const filters = reactive({
  date_from: '',
  date_to: '',
  service_name: '',
  action: '',
  status: '',
  q: '',
});

const hasActiveFilters = computed(() =>
  Object.values(filters).some((value) => value !== ''),
);

// ── รายการ + การเลื่อนหน้า ────────────────────────────────────────────────
const page = ref<AuditLogPage | null>(null);
const items = ref<AuditLogItem[]>([]);
const isLoading = ref(true);
const isLoadingMore = ref(false);
const loadError = ref<string | null>(null);
const loadMoreError = ref<string | null>(null);
const options = ref<AuditLogOptions>({ service_names: [], actions: [], statuses: [] });

const queryFor = (cursor: string | null) => ({
  date_from: filters.date_from || undefined,
  date_to: filters.date_to || undefined,
  service_name: filters.service_name || undefined,
  action: filters.action || undefined,
  status: filters.status || undefined,
  q: filters.q.trim() || undefined,
  cursor: cursor ?? undefined,
});

/** โหลดหน้าแรก (ทิ้งรายการเดิม) — เรียกทุกครั้งที่ตัวกรองเปลี่ยน */
const resetAndLoad = async () => {
  isLoading.value = true;
  loadError.value = null;
  loadMoreError.value = null;
  try {
    const result = await AuditService.list(roomId, queryFor(null));
    items.value = result.items;
    page.value = result;
  } catch (err) {
    loadError.value = messageOf(err);
    items.value = [];
    page.value = null;
  } finally {
    isLoading.value = false;
  }
};

/** ต่อท้ายรายการด้วย `next_cursor` ของ backend — ห้ามคำนวณ offset เอง */
const loadMore = async () => {
  const cursor = page.value?.next_cursor;
  if (!cursor || isLoadingMore.value) return;

  isLoadingMore.value = true;
  loadMoreError.value = null;
  try {
    const result = await AuditService.list(roomId, queryFor(cursor));
    items.value = [...items.value, ...result.items];
    page.value = result;
  } catch (err) {
    loadMoreError.value = messageOf(err);
  } finally {
    isLoadingMore.value = false;
  }
};

const clearFilters = () => {
  filters.date_from = '';
  filters.date_to = '';
  filters.service_name = '';
  filters.action = '';
  filters.status = '';
  filters.q = '';
  void resetAndLoad();
};

onMounted(async () => {
  if (!roomId) {
    isLoading.value = false;
    loadError.value = 'ยังไม่ได้เลือกห้องเรียน';
    return;
  }
  if (!canView.value) {
    isLoading.value = false;
    return;
  }
  // ตัวเลือกของ dropdown มาจากข้อมูลจริง — ล้มเหลวแล้วไม่ควรทำให้ทั้งหน้าล้มตาม
  void AuditService.options(roomId)
    .then((result) => {
      options.value = result;
    })
    .catch(() => {
      // ปล่อยว่าง — ผู้ใช้ยังกรองด้วยคำค้น/วันที่ได้
    });
  await resetAndLoad();
});

// ── การแสดงผลรายแถว ────────────────────────────────────────────────────────
/** ป้ายชื่อผู้ทำ: ใช้ชื่อจริงถ้ามี ไม่งั้นแสดงตัวระบุดิบที่บันทึกไว้ */
const actorLabel = (item: AuditLogItem): string => item.actor_name || item.actor_identifier;

const actorDetail = (item: AuditLogItem): string | null =>
  item.actor_name ? item.actor_identifier : null;

const isFailure = (item: AuditLogItem): boolean => item.status === 'failed';

/** แสดง JSON แบบอ่านได้ แต่ตัดความยาวไม่ให้ท่วมการ์ด */
const prettyJson = (value: unknown): string => {
  if (value === null || value === undefined) return '—';
  try {
    const text = JSON.stringify(value, null, 2);
    return text.length > 2000 ? `${text.slice(0, 2000)}\n… (ตัดเพื่อแสดงผล)` : text;
  } catch {
    return String(value);
  }
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader
      title="บันทึกกิจกรรม"
      description="ตรวจย้อนว่าใครทำอะไรกับข้อมูลห้อง เมื่อไร และจากอุปกรณ์/IP ใด"
    />

    <!-- ไม่มีสิทธิ์: บอกตรง ๆ ไม่ใช่ปล่อยหน้าว่าง (backend ตอบ 403 อยู่แล้ว) -->
    <StateBlock
      v-if="!canView"
      variant="error"
      icon="bi-shield-lock"
      title="คุณไม่มีสิทธิ์ดูบันทึกกิจกรรม"
      hint="การดูบันทึกนี้กำหนดให้ประธาน รองประธาน และเลขานุการของห้อง — ติดต่อผู้ดูแลห้องหากจำเป็น"
    />

    <template v-else>
      <!-- ── ตัวกรอง ──────────────────────────────────────────────────── -->
      <section class="rounded-2xl border border-stone-200 bg-white p-4" aria-label="ตัวกรอง">
        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <label class="block text-xs font-bold text-stone-600">
            ตั้งแต่
            <input
              v-model="filters.date_from"
              type="date"
              class="mt-1 w-full rounded-lg border border-stone-300 px-3 py-2 text-sm font-normal text-stone-900"
              @change="resetAndLoad"
            />
          </label>
          <label class="block text-xs font-bold text-stone-600">
            ถึง
            <input
              v-model="filters.date_to"
              type="date"
              class="mt-1 w-full rounded-lg border border-stone-300 px-3 py-2 text-sm font-normal text-stone-900"
              @change="resetAndLoad"
            />
          </label>
          <label class="block text-xs font-bold text-stone-600">
            คำค้น
            <input
              v-model="filters.q"
              type="search"
              placeholder="ชื่อผู้ทำ / endpoint / รหัส entity"
              class="mt-1 w-full rounded-lg border border-stone-300 px-3 py-2 text-sm font-normal text-stone-900"
              @change="resetAndLoad"
            />
          </label>
          <label class="block text-xs font-bold text-stone-600">
            บริการ
            <select
              v-model="filters.service_name"
              class="mt-1 w-full rounded-lg border border-stone-300 px-3 py-2 text-sm font-normal text-stone-900"
              @change="resetAndLoad"
            >
              <option value="">ทั้งหมด</option>
              <option v-for="name in options.service_names" :key="name" :value="name">
                {{ name }}
              </option>
            </select>
          </label>
          <label class="block text-xs font-bold text-stone-600">
            การกระทำ
            <select
              v-model="filters.action"
              class="mt-1 w-full rounded-lg border border-stone-300 px-3 py-2 text-sm font-normal text-stone-900"
              @change="resetAndLoad"
            >
              <option value="">ทั้งหมด</option>
              <option v-for="name in options.actions" :key="name" :value="name">
                {{ name }}
              </option>
            </select>
          </label>
          <label class="block text-xs font-bold text-stone-600">
            สถานะ
            <select
              v-model="filters.status"
              class="mt-1 w-full rounded-lg border border-stone-300 px-3 py-2 text-sm font-normal text-stone-900"
              @change="resetAndLoad"
            >
              <option value="">ทั้งหมด</option>
              <option v-for="name in options.statuses" :key="name" :value="name">
                {{ name }}
              </option>
            </select>
          </label>
        </div>
        <div v-if="hasActiveFilters" class="mt-3">
          <AppButton variant="quiet" @click="clearFilters">ล้างตัวกรอง</AppButton>
        </div>
      </section>

      <SkeletonRows v-if="isLoading" :rows="4" height="h-24" />

      <StateBlock
        v-else-if="loadError"
        variant="error"
        title="โหลดบันทึกกิจกรรมไม่สำเร็จ"
        :hint="loadError"
        @retry="resetAndLoad"
      />

      <!-- ยังไม่มีบันทึกเลย กับ "กรองแล้วไม่เจอ" เป็นคนละเรื่อง -->
      <AppEmptyState
        v-else-if="items.length === 0 && hasActiveFilters"
        icon="bi-funnel"
        title="ไม่พบบันทึกที่ตรงกับตัวกรอง"
        hint="ลองขยายช่วงวันที่หรือล้างตัวกรอง"
      />

      <AppEmptyState
        v-else-if="items.length === 0"
        icon="bi-journal-text"
        title="ยังไม่มีบันทึกกิจกรรมในห้องนี้"
        hint="บันทึกจะเริ่มมีเมื่อสมาชิกสร้าง/แก้ไขข้อมูลผ่านระบบ"
      />

      <template v-else>
        <ul class="space-y-2.5">
          <li v-for="item in items" :key="item.id" class="page-card p-4 sm:p-5">
            <div class="flex flex-wrap items-start justify-between gap-2">
              <div class="min-w-0">
                <p class="flex flex-wrap items-center gap-1.5 text-sm font-bold text-stone-900">
                  <span>{{ actorLabel(item) }}</span>
                  <span class="rounded-full bg-stone-100 px-2 py-0.5 text-[11px] font-bold text-stone-600">
                    {{ item.action }}
                  </span>
                  <span
                    v-if="isFailure(item)"
                    class="rounded-full bg-danger-50 px-2 py-0.5 text-[11px] font-bold text-danger-700"
                  >
                    ล้มเหลว
                  </span>
                </p>
                <p class="mt-0.5 break-words text-xs text-stone-500">
                  {{ item.service_name }}<template v-if="item.entity_type">
                    · {{ item.entity_type }}<template v-if="item.entity_id"> #{{ item.entity_id }}</template>
                  </template>
                  <template v-if="item.endpoint_or_command">
                    · {{ item.endpoint_or_command }}
                  </template>
                </p>
              </div>
              <time class="shrink-0 text-xs text-stone-500" :datetime="item.created_at">
                {{ formatThaiDateTime(item.created_at) }}
              </time>
            </div>

            <p v-if="actorDetail(item)" class="mt-1 text-[11px] text-stone-400">
              {{ actorDetail(item) }} · {{ item.client_source }}
            </p>

            <p
              v-if="item.error_detail"
              class="mt-2 rounded-lg bg-danger-50 px-3 py-2 text-xs text-danger-700"
            >
              {{ item.error_detail }}
            </p>

            <!-- รายละเอียดเชิงสืบเหตุ — ซ่อนไว้เป็นค่าเริ่มต้น -->
            <details class="mt-2">
              <summary class="cursor-pointer text-xs font-bold text-brand-700">รายละเอียด</summary>
              <dl class="mt-2 space-y-1 text-xs text-stone-600">
                <div v-if="item.ip_address" class="flex gap-2">
                  <dt class="w-24 shrink-0 text-stone-500">IP</dt>
                  <dd class="break-all">{{ item.ip_address }}</dd>
                </div>
                <div v-if="item.user_agent" class="flex gap-2">
                  <dt class="w-24 shrink-0 text-stone-500">อุปกรณ์</dt>
                  <dd class="break-all">{{ item.user_agent }}</dd>
                </div>
                <div v-if="item.execution_time_ms !== null" class="flex gap-2">
                  <dt class="w-24 shrink-0 text-stone-500">เวลาทำงาน</dt>
                  <dd>{{ item.execution_time_ms }} ms</dd>
                </div>
              </dl>
              <div
                v-if="item.old_values !== null || item.new_values !== null"
                class="mt-2 grid gap-2 sm:grid-cols-2"
              >
                <div v-if="item.old_values !== null">
                  <p class="text-[11px] font-bold text-stone-500">ก่อนแก้</p>
                  <pre
                    class="mt-1 max-h-56 overflow-auto rounded-lg bg-stone-50 p-2 text-[11px] leading-relaxed"
                    v-text="prettyJson(item.old_values)"
                  ></pre>
                </div>
                <div v-if="item.new_values !== null">
                  <p class="text-[11px] font-bold text-stone-500">หลังแก้</p>
                  <pre
                    class="mt-1 max-h-56 overflow-auto rounded-lg bg-stone-50 p-2 text-[11px] leading-relaxed"
                    v-text="prettyJson(item.new_values)"
                  ></pre>
                </div>
              </div>
            </details>
          </li>
        </ul>

        <StateBlock
          v-if="loadMoreError"
          variant="error"
          title="โหลดหน้าถัดไปไม่สำเร็จ"
          :hint="loadMoreError"
          @retry="loadMore"
        />

        <div v-if="page?.has_more" class="flex justify-center">
          <AppButton variant="secondary" :loading="isLoadingMore" @click="loadMore">
            โหลดเพิ่ม
          </AppButton>
        </div>
        <p v-else class="text-center text-xs text-stone-400">แสดงครบทั้งหมดแล้ว</p>
      </template>
    </template>
  </div>
</template>
