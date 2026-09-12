<script setup lang="ts">
/**
 * 👥 ParticipantRosterList — รายชื่อผู้เข้าร่วม/นักเรียนแบบการ์ด (ตามแบบ StudentList.vue)
 * ใช้ร่วมทั้งหน้าแก้ไขกิจกรรม (ActivityForm) และหน้ารายละเอียด (ActivityDetail)
 * - การ์ด rounded-2xl: badge เลขที่ + ชื่อ/status dot/ชื่อเล่น + หน้าที่/ตำแหน่ง + หมายเหตุ
 * - Search ชื่อ/เลขที่/ชื่อเล่น
 * - Toolbar: ตั้งค่าแบบกลุ่ม (เมื่อมีการติ๊ก) / เลือกทั้งหมด / ล้าง
 *
 * 🌟 โหมด readOnly (ActivityDetail): แสดงเฉย ๆ ไม่ให้แก้ไข
 * - ไม่มี checkbox/เลือก / ไม่มี dropdown หน้าที่ / ไม่มี toolbar
 * - คลิกที่แถวของนักเรียน = เปิดข้อมูลเพิ่มเติม (แทนปุ่ม "i" ที่เอาออก)
 * - ปุ่มติ๊ก "มาแล้ว/ยังไม่มา" เป็นปุ่มเล็กกระชับอยู่ในแถว · "นำออก" ซ่อนในเมนูจุด 3 จุด
 *
 * 📱 Mobile-friendly (StudentList-inspired):
 * - ชื่อ block เป็น flex-1 min-w-0 เสมอ → ชื่อไม่ถูกเบียดหาย แม้จอแคบ
 * - "ข้อมูลเพิ่มเติม" ย่อเป็นไอคอนล้วนบนมือถือ (w-9 h-9) คลี่เป็น icon+text บน sm+
 * - ปุ่มเช็คอินเป็น action กลางแถวล่าง ความสูง ≥36px (touch target)
 * Presentational — parent เป็นคนเก็บ state และยิง API ผ่าน emits
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { splitDutyRole } from '@/constants/activityFields'
import { displayName } from '@/utils/name'
import StateBlock from '@/components/ui/StateBlock.vue'
import type { RosterItem } from '@/types/activity'

const props = defineProps<{
  items: RosterItem[]
  positions: string[]
  /** ชุด key ที่ถูกติ๊ก — ส่ง Set ใหม่ทุกครั้งเพื่อ trigger reactivity */
  selectedKeys?: Set<string | number>
  /** ActivityForm: ต้องติ๊กก่อนถึงจะแก้หน้าที่/ข้อมูลได้ */
  selectable?: boolean
  canManage?: boolean
  /** ActivityDetail: แสดงปุ่มเช็คอิน/ยกเลิก */
  showStatusToggle?: boolean
  /** ActivityDetail: แสดง "นำออก" (ในเมนูจุด 3 จุด เมื่อ readOnly) */
  showRemove?: boolean
  /** 🌟 โหมดแสดงผลอย่างเดียว (ActivityDetail) — ซ่อนทุกการแก้ไข คงเหลือแค่ดู + เช็คอิน */
  readOnly?: boolean
  /** 🧩 ซ่อนตัวแก้ไขหน้าที่/หมายเหตุ inline (ใช้หน้า ManageActivity — แก้ผ่าน modal ข้อมูลเพิ่มเติมแทน) */
  hideDutyEditor?: boolean
  emptyText?: string
}>()

const emit = defineEmits<{
  (e: 'toggleSelect', key: string | number): void
  (e: 'selectAll'): void
  (e: 'clearAll'): void
  (e: 'changeDuty', key: string | number, position: string, note: string): void
  (e: 'openInfo', key: string | number): void
  (e: 'toggleStatus', key: string | number): void
  (e: 'remove', key: string | number): void
  (e: 'batch'): void
}>()

const searchQuery = ref('')

const filteredItems = computed(() => {
  const query = searchQuery.value.toLowerCase().trim()
  if (!query) return props.items
  return props.items.filter((item) => {
    const fullName = `${item.first_name} ${item.last_name} ${item.first_name_en || ''} ${item.last_name_en || ''}`.toLowerCase()
    const no = String(item.student_no)
    const nickname = `${item.nickname || ''} ${item.nickname_en || ''}`.toLowerCase()
    return fullName.includes(query) || no.includes(query) || nickname.includes(query)
  })
})

const isSelected = (item: RosterItem) => props.selectedKeys?.has(item.key) ?? false
const isDisabled = (item: RosterItem) => {
  if (props.readOnly) return false
  return (props.selectable ?? false) && !isSelected(item)
}

/** ตำแหน่ง/หมายเหตุ ของ item นี้ (แยกจาก role_detail ด้วย ": ") */
function dutyOf(item: RosterItem): { position: string; note: string } {
  return splitDutyRole(item.role_detail)
}

/** หน้าที่ที่เลือกมีอยู่ในรายการแล้วหรือไม่ (กันข้อมูลหายตอนลบตำแหน่ง) */
function isOrphanedDuty(item: RosterItem): boolean {
  const pos = dutyOf(item).position
  if (!pos) return false
  return !props.positions.includes(pos)
}

/** ค่าป้ายสถานะ (dot สี) แบบ StudentList */
const statusDot = (status: string) => {
  if (status === 'attended') return 'bg-emerald-500'
  if (status === 'cancelled') return 'bg-red-500'
  return 'bg-amber-500'
}

/** สไตล์ปุ่มเช็คอิน (bottom action) — ต่างจาก dot เล็ก ๆ ตรงที่ต้องการให้กดชัดเจน */
const actionClass = (status: string) => {
  if (status === 'attended') return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (status === 'cancelled') return 'bg-red-50 text-red-700 border-red-200'
  return 'bg-white text-stone-500 border-stone-200 hover:border-emerald-300 hover:text-emerald-700'
}

/** ป้ายปุ่มเช็คอิน — "มาแล้ว" เมื่อ attend แล้ว, "ยังไม่มา" เมื่อยังไม่เช็คอิน */
const actionLabel = (status: string) => {
  if (status === 'attended') return 'มาแล้ว'
  if (status === 'cancelled') return 'ยกเลิก'
  return 'ยังไม่มา'
}

/** เปลี่ยนหน้าที่ (select) ของผู้เข้าร่วมคนนี้ */
function onDutyChange(e: Event, item: RosterItem) {
  emit('changeDuty', item.key, (e.target as HTMLSelectElement).value, dutyOf(item).note)
}

/** เปลี่ยนหมายเหตุหน้าที่ (input) ของผู้เข้าร่วมคนนี้ */
function onDutyNoteChange(e: Event, item: RosterItem) {
  emit('changeDuty', item.key, dutyOf(item).position, (e.target as HTMLInputElement).value)
}

// --- เมนูจุด 3 จุด (โหมด readOnly — "นำออก" แบบ StudentList) ---
const openMenu = ref<string | number | null>(null)

function toggleMenu(key: string | number, event: Event) {
  event.stopPropagation() // ป้องกันไม่ให้คลิกทะลุไปโดน Card
  openMenu.value = openMenu.value === key ? null : key
}

function closeMenu() {
  openMenu.value = null
}

/** ปุ่มในเมนู — ปิดเมนูก่อน แล้วค่อย emit ไปให้ parent จัดการ */
function handleMenuAction(action: 'remove', key: string | number) {
  closeMenu()
  emit(action, key)
}

/**
 * 🌟 โหมด readOnly: คลิกที่แถวของนักเรียน = เปิดข้อมูลเพิ่มเติม (แทนปุ่ม "i" ที่เอาออก)
 * โหมด selectable ไม่ทำ — กันชนกับ checkbox / select หน้าที่
 */
function onCardClick(item: RosterItem) {
  if (props.readOnly) emit('openInfo', item.key)
}

/** คีย์บอร์ด: Enter/Space บนแถวที่ focus = เปิดข้อมูลเพิ่มเติม (accessibility)
 * ปล่อยให้ Enter บนปุ่ม/input ข้างใน (เช็คอิน, เมนูจุด 3 จุด) ทำงานของมันเอง */
function onCardKeydown(e: KeyboardEvent, item: RosterItem) {
  if (!props.readOnly || (e.key !== 'Enter' && e.key !== ' ')) return
  const target = e.target as HTMLElement | null
  if (target && target.closest('button, input, select, a, textarea')) return
  e.preventDefault()
  emit('openInfo', item.key)
}

onMounted(() => document.addEventListener('click', closeMenu))
onUnmounted(() => document.removeEventListener('click', closeMenu))
</script>

<template>
  <div>
    <!-- Search + Toolbar -->
    <div class="mb-3 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <div class="relative w-full md:max-w-xs md:flex-1">
        <span
          class="pointer-events-none absolute inset-y-0 start-0 flex items-center ps-3.5 text-stone-400"
        >
          <i class="bi bi-search" aria-hidden="true"></i>
        </span>
        <input
          v-model="searchQuery"
          type="text"
          placeholder="ค้นหาชื่อ, เลขที่, หรือชื่อเล่น..."
          class="field ps-10"
        />
      </div>

      <div v-if="!readOnly && canManage !== false" class="flex flex-wrap items-center gap-2">
        <button
          v-if="(selectedKeys?.size ?? 0) > 0"
          type="button"
          class="btn-primary"
          @click="emit('batch')"
        >
          <i class="bi bi-lightning-charge-fill" aria-hidden="true"></i> ตั้งค่าแบบกลุ่ม ({{
            selectedKeys?.size ?? 0
          }})
        </button>
        <button type="button" class="btn-ghost-ui" @click="emit('selectAll')">
          <i class="bi bi-check-all" aria-hidden="true"></i> เลือกทั้งหมด
        </button>
        <button
          v-if="(selectedKeys?.size ?? 0) > 0"
          type="button"
          class="btn-ghost-ui"
          @click="emit('clearAll')"
        >
          <i class="bi bi-x-lg" aria-hidden="true"></i> ล้าง
        </button>
      </div>
    </div>

    <!-- Empty state -->
    <StateBlock
      v-if="filteredItems.length === 0"
      variant="empty"
      icon="bi-people"
      :title="emptyText || 'ไม่มีรายชื่อในรายการนี้'"
      :hint="
        searchQuery.trim()
          ? 'ลองปรับคำค้นหา หรือสะกดชื่อให้ต่างออกไป'
          : 'เพิ่มนักเรียนเข้าร่วมกิจกรรมก่อนเพื่อเริ่มต้น'
      "
    />

    <template v-else>
      <!-- 🖥️ Desktop: ตารางเต็ม (การ์ดมือถืออยู่ด้านล่าง) -->
      <div class="page-card hidden overflow-hidden lg:block">
        <div class="overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th v-if="selectable && !readOnly" class="w-10"></th>
                <th class="w-16">เลขที่</th>
                <th>ชื่อ-นามสกุล</th>
                <th class="w-32">สถานะ</th>
                <th>หน้าที่/ตำแหน่ง</th>
                <th>หมายเหตุ</th>
                <th class="w-16 text-right">ชม.</th>
                <th class="w-52 text-right">จัดการ</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in filteredItems"
                :key="item.key"
                :class="[
                  isSelected(item) ? 'bg-brand-50/60' : '',
                  isDisabled(item) ? 'opacity-70' : '',
                ]"
              >
                <!-- Checkbox (selectable mode) — ซ่อนในโหมด readOnly -->
                <td v-if="selectable && !readOnly">
                  <input
                    type="checkbox"
                    :checked="isSelected(item)"
                    @change="emit('toggleSelect', item.key)"
                    class="h-4 w-4 shrink-0 rounded accent-brand-700"
                  />
                </td>

                <td class="num font-bold text-stone-700">{{ item.student_no }}</td>

                <td>
                  <div class="min-w-0">
                    <p class="truncate font-bold text-stone-900">
                      {{ item.prefix ? item.prefix + ' ' : '' }}{{ displayName(item) }}
                    </p>
                    <p
                      v-if="item.nickname || item.nickname_en"
                      class="truncate text-[11px] text-stone-400"
                    >
                      {{ item.nickname || item.nickname_en }}
                    </p>
                  </div>
                </td>

                <td>
                  <span class="chip bg-stone-100 text-stone-600">
                    <span
                      class="h-1.5 w-1.5 shrink-0 rounded-full"
                      :class="statusDot(item.status)"
                      aria-hidden="true"
                    ></span>
                    {{ actionLabel(item.status) }}
                  </span>
                </td>

                <!-- หน้าที่/ตำแหน่ง -->
                <td>
                  <template v-if="readOnly || hideDutyEditor">
                    <span v-if="dutyOf(item).position" class="chip bg-brand-50 text-brand-700">
                      <i class="bi bi-diagram-3" aria-hidden="true"></i> {{ dutyOf(item).position }}
                    </span>
                    <span v-else class="text-stone-400">—</span>
                  </template>
                  <select
                    v-else
                    :value="dutyOf(item).position"
                    :disabled="isDisabled(item) || canManage === false"
                    @change="(e: Event) => onDutyChange(e, item)"
                    class="field min-w-[9rem]"
                  >
                    <option value="">— ไม่มีหน้าที่ —</option>
                    <option
                      v-if="isOrphanedDuty(item) && dutyOf(item).position"
                      :value="dutyOf(item).position"
                    >
                      {{ dutyOf(item).position }} (ถูกลบแล้ว)
                    </option>
                    <option v-for="pos in positions" :key="pos" :value="pos">{{ pos }}</option>
                  </select>
                </td>

                <!-- หมายเหตุ -->
                <td>
                  <template v-if="readOnly || hideDutyEditor">
                    <span v-if="dutyOf(item).note" class="text-stone-600">{{
                      dutyOf(item).note
                    }}</span>
                    <span v-else class="text-stone-400">—</span>
                  </template>
                  <input
                    v-else
                    :value="dutyOf(item).note"
                    type="text"
                    placeholder="หมายเหตุ (เพิ่มเติม)"
                    :disabled="isDisabled(item) || canManage === false"
                    @change="(e: Event) => onDutyNoteChange(e, item)"
                    class="field min-w-[9rem]"
                  />
                </td>

                <td class="num text-right font-bold text-stone-700">
                  {{ item.earned_hours > 0 ? item.earned_hours : '—' }}
                </td>

                <!-- จัดการ -->
                <td>
                  <div class="flex items-center justify-end gap-1.5">
                    <button
                      v-if="showStatusToggle"
                      type="button"
                      @click="emit('toggleStatus', item.key)"
                      class="inline-flex shrink-0 items-center justify-center gap-1 rounded-lg border px-2.5 py-1.5 text-[11px] font-bold transition-colors active:scale-[0.97]"
                      :class="actionClass(item.status)"
                    >
                      <i
                        class="bi"
                        :class="item.status === 'attended' ? 'bi-check-circle-fill' : 'bi-circle'"
                        aria-hidden="true"
                      ></i>
                      {{ actionLabel(item.status) }}
                    </button>

                    <!-- โหมดแก้ไข: ข้อมูลเพิ่มเติม; readOnly ใช้คลิกที่แถวแทน -->
                    <button
                      v-if="!readOnly"
                      type="button"
                      @click="emit('openInfo', item.key)"
                      :disabled="isDisabled(item)"
                      title="ข้อมูลเพิ่มเติม"
                      class="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg border border-stone-200 bg-white px-2.5 py-1.5 text-[11px] font-bold text-stone-600 transition-colors hover:border-brand-200 hover:bg-brand-50 hover:text-brand-700 disabled:pointer-events-none disabled:opacity-40 active:scale-[0.97]"
                    >
                      <i class="bi bi-info-circle" aria-hidden="true"></i> ข้อมูลเพิ่มเติม
                    </button>

                    <button
                      v-if="showRemove && (!readOnly || canManage)"
                      type="button"
                      @click="emit('remove', item.key)"
                      class="inline-flex shrink-0 items-center justify-center gap-1 rounded-lg px-2.5 py-1.5 text-[11px] font-bold text-stone-400 transition-colors hover:bg-red-50 hover:text-red-600 active:scale-[0.97]"
                    >
                      <i class="bi bi-trash3" aria-hidden="true"></i> นำออก
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 📱 มือถือ: การ์ดเรียงแนวตั้ง (แบบ StudentList) -->
      <div class="space-y-2.5 sm:space-y-3 lg:hidden">
        <div
          v-for="item in filteredItems"
          :key="item.key"
          class="page-card group p-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/40 sm:p-4"
          :class="[
            readOnly ? 'card-hover cursor-pointer' : '',
            isSelected(item) ? 'border-brand-200 bg-brand-50/60' : '',
            isDisabled(item) ? 'opacity-70' : '',
          ]"
          :role="readOnly ? 'button' : undefined"
          :tabindex="readOnly ? 0 : undefined"
          @click="onCardClick(item)"
          @keydown="onCardKeydown($event, item)"
        >
          <!-- แถวบน: เลขที่ + ชื่อ (min-w-0 → ชื่อไม่ถูกเบียดหาย) + ปุ่ม info + จุด 3 จุด -->
          <div class="flex items-center gap-2.5 sm:gap-3.5">
            <!-- Checkbox (selectable mode) — ซ่อนในโหมด readOnly -->
            <input
              v-if="selectable && !readOnly"
              type="checkbox"
              :checked="isSelected(item)"
              @change="emit('toggleSelect', item.key)"
              class="h-4 w-4 shrink-0 rounded accent-brand-700 sm:h-5 sm:w-5"
            />

            <!-- เลขที่ badge (เล็กลงบนมือถือ ให้ชื่อมีที่) -->
            <div
              class="num flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-stone-200 bg-stone-50 text-sm font-bold text-stone-600 transition-colors sm:h-12 sm:w-12 sm:text-lg"
              :class="
                readOnly
                  ? 'group-hover:border-brand-200 group-hover:bg-brand-50 group-hover:text-brand-700'
                  : ''
              "
            >
              {{ item.student_no }}
            </div>

            <!-- ข้อมูลหลัก — flex-1 min-w-0 เสมอ -->
            <div class="min-w-0 flex-1">
              <div class="mb-0.5 flex items-center gap-1.5">
                <span
                  class="h-2 w-2 shrink-0 rounded-full"
                  :class="statusDot(item.status)"
                  aria-hidden="true"
                ></span>
                <p class="truncate text-sm font-bold text-stone-900 sm:text-[15px]">
                  {{ item.prefix ? item.prefix + ' ' : '' }}{{ displayName(item) }}
                </p>
              </div>
              <div class="flex items-center gap-1.5 text-[11px] text-stone-400 sm:text-xs">
                <span v-if="item.nickname || item.nickname_en" class="truncate">{{
                  item.nickname || item.nickname_en
                }}</span>
                <template v-if="item.earned_hours > 0">
                  <span class="text-stone-300">•</span>
                  <span class="num whitespace-nowrap font-bold text-emerald-600"
                    >{{ item.earned_hours }} ชม.</span
                  >
                </template>
              </div>
            </div>

            <!-- ปุ่มเช็คอิน (readOnly) — กระชับ เล็ก ไม่กินพื้นที่ (คลิกที่แถว = ดูข้อมูล) -->
            <button
              v-if="readOnly && showStatusToggle"
              type="button"
              @click.stop="emit('toggleStatus', item.key)"
              class="inline-flex min-h-11 shrink-0 items-center justify-center gap-1 rounded-lg border px-3 py-2 text-xs font-bold transition-colors active:scale-[0.97] sm:text-[11px]"
              :class="actionClass(item.status)"
            >
              <i
                class="bi"
                :class="item.status === 'attended' ? 'bi-check-circle-fill' : 'bi-circle'"
                aria-hidden="true"
              ></i>
              {{ actionLabel(item.status) }}
            </button>

            <!-- ปุ่มข้อมูลเพิ่มเติม — เฉพาะโหมด selectable (แก้ไข); readOnly ใช้คลิกที่แถวแทน -->
            <button
              v-if="!readOnly"
              type="button"
              @click="emit('openInfo', item.key)"
              :disabled="isDisabled(item)"
              title="ข้อมูลเพิ่มเติม"
              aria-label="ข้อมูลเพิ่มเติม"
              class="inline-flex h-11 w-11 shrink-0 items-center justify-center gap-1.5 rounded-xl border border-stone-200 bg-white text-stone-600 transition-colors hover:border-brand-200 hover:bg-brand-50 hover:text-brand-700 disabled:pointer-events-none disabled:opacity-40 active:scale-[0.97] sm:h-auto sm:w-auto sm:px-3 sm:py-2"
            >
              <i class="bi bi-info-circle" aria-hidden="true"></i>
              <span class="hidden text-[11px] font-bold sm:inline">ข้อมูลเพิ่มเติม</span>
            </button>

            <!-- เมนูจุด 3 จุด (readOnly: "นำออก" ซ่อนไว้ที่นี่ แบบ StudentList) -->
            <div v-if="readOnly && showRemove && canManage" class="relative shrink-0">
              <button
                type="button"
                @click.stop="toggleMenu(item.key, $event)"
                class="flex h-11 w-11 items-center justify-center rounded-xl text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-700"
                aria-label="เมนูเพิ่มเติม"
              >
                <i class="bi bi-three-dots-vertical" aria-hidden="true"></i>
              </button>

              <transition name="fade">
                <div
                  v-if="openMenu === item.key"
                  class="absolute end-0 top-11 z-20 w-36 origin-top-right overflow-hidden rounded-xl border border-stone-200 bg-white py-1 shadow-[0_10px_30px_-14px_rgba(28,25,23,0.28)]"
                >
                  <button
                    type="button"
                    @click.stop="handleMenuAction('remove', item.key)"
                    class="flex w-full items-center gap-2.5 px-4 py-2.5 text-left text-sm font-bold text-red-600 transition-colors hover:bg-red-50"
                  >
                    <i class="bi bi-trash" aria-hidden="true"></i> นำออก
                  </button>
                </div>
              </transition>
            </div>
          </div>

          <!-- Duty + note -->
          <!-- readOnly: แสดงเป็น chip (อ่านอย่างเดียว) -->
          <div v-if="readOnly" class="mt-2.5 flex flex-wrap items-center gap-1.5">
            <span v-if="dutyOf(item).position" class="chip bg-brand-50 text-brand-700">
              <i class="bi bi-diagram-3" aria-hidden="true"></i> {{ dutyOf(item).position }}
            </span>
            <span v-if="dutyOf(item).note" class="chip bg-stone-100 text-stone-600">
              {{ dutyOf(item).note }}
            </span>
          </div>
          <!-- mode แก้ไข (ActivityForm): select หน้าที่ + input หมายเหตุ -->
          <div
            v-else-if="!hideDutyEditor"
            class="mt-3 grid grid-cols-2 gap-2 sm:flex sm:flex-row sm:items-center"
          >
            <select
              :value="dutyOf(item).position"
              :disabled="isDisabled(item) || canManage === false"
              @change="(e: Event) => onDutyChange(e, item)"
              class="field min-w-0 flex-1"
            >
              <option value="">— ไม่มีหน้าที่ —</option>
              <option
                v-if="isOrphanedDuty(item) && dutyOf(item).position"
                :value="dutyOf(item).position"
              >
                {{ dutyOf(item).position }} (ถูกลบแล้ว)
              </option>
              <option v-for="pos in positions" :key="pos" :value="pos">{{ pos }}</option>
            </select>
            <input
              :value="dutyOf(item).note"
              type="text"
              placeholder="หมายเหตุ (เพิ่มเติม)"
              :disabled="isDisabled(item) || canManage === false"
              @change="(e: Event) => onDutyNoteChange(e, item)"
              class="field min-w-0 flex-1"
            />
          </div>

          <!-- Detail actions (mode แก้ไข ActivityForm: ปุ่มสถานะ + นำออก) -->
          <div
            v-if="!readOnly && (showStatusToggle || showRemove)"
            class="mt-2.5 flex items-center gap-2"
          >
            <button
              v-if="showStatusToggle"
              type="button"
              @click="emit('toggleStatus', item.key)"
              class="min-h-11 shrink-0 rounded-lg border px-3 py-2 text-xs font-bold transition-colors active:scale-[0.97]"
              :class="actionClass(item.status)"
            >
              {{ actionLabel(item.status) }}
            </button>
            <button
              v-if="showRemove"
              type="button"
              @click="emit('remove', item.key)"
              class="inline-flex min-h-11 shrink-0 items-center gap-1 rounded-lg px-3 py-2 text-xs font-bold text-stone-400 transition-colors hover:bg-red-50 hover:text-red-600 active:scale-[0.97]"
            >
              <i class="bi bi-trash3" aria-hidden="true"></i> นำออก
            </button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* Animation สำหรับ Dropdown ตอนเด้งขึ้นมา */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: scale(0.95);
}
</style>
