<script setup lang="ts">
/**
 * RowActionMenu — เมนูจุด 3 จุด (kebab) สำหรับ "การกระทำต่อแถว" ในตาราง/การ์ด
 *
 * ทำไมต้องเป็นคอมโพเนนต์กลาง (เดิมทั้ง repo มือเขียนเอง 4 สำเนา):
 *  1. การกระทำที่ทำลายข้อมูล (ยกเลิกรายการ / ลบ) ไม่ควรเป็นปุ่มเปลือยกลางแถว
 *     ซึ่งกดพลาดได้ง่าย — ซ่อนไว้ในเมนูแล้วต้องตั้งใจเปิด
 *  2. 🔴 เมนูแบบ `absolute` **ใช้ไม่ได้** กับตารางที่ครอบ `overflow-hidden`
 *     + `overflow-x-auto` (DESIGN.md §5 บังคับให้ครอบ) เพราะจะถูกตัดหายทั้งแผง
 *     ⇒ ที่นี่ใช้ **Teleport ไป `body` + `position: fixed`** แล้วคำนวณพิกัดจาก
 *       `getBoundingClientRect()` ของปุ่ม — ท่าเดียวกับ `MainLayout.vue` ที่ใช้อยู่
 *  3. พฤติกรรมที่ต้องเหมือนกันทุกที่: ปิดเมื่อคลิกนอก / Esc / Tab / scroll / resize / เลือกแล้ว
 *
 * @example
 * <RowActionMenu
 *   label="ตัวเลือกจัดการรายการ"
 *   :items="[
 *     { key: 'revert', label: 'ยกเลิกรายการ', icon: 'bi-arrow-counterclockwise', tone: 'danger' },
 *   ]"
 *   @select="handleRevert(t, $event)"
 * />
 * <!-- ⚠️ ต้องรับ `$event` (key) เสมอ แล้วเช็ค key ก่อนทำงาน — ถ้าเขียน @select="handleRevert(t)"
 *      ไว้ พอมีไอเทมที่ 2 เพิ่มเข้ามา มันจะเรียก handler เดิมกับทุกไอเทมแบบเงียบ ๆ -->
 * <!-- ไอเทมที่มี `to` จะเรนเดอร์เป็น RouterLink เอง ไม่ต้องดัก @select -->
 */
import { ref, nextTick, onBeforeUnmount } from 'vue';

/** 1 รายการในเมนู */
export interface RowActionItem {
  /** คีย์ที่ส่งกลับทาง `@select` */
  key: string;
  label: string;
  /** ไอคอน bootstrap-icons เช่น 'bi-trash3-fill' */
  icon: string;
  /** 'danger' = แดง — ใช้เฉพาะการกระทำที่ทำลายข้อมูล (DESIGN.md §3) */
  tone?: 'default' | 'danger';
  /** ใส่เส้นทาง → เรนเดอร์เป็น RouterLink แทนปุ่ม (ไม่ต้องดัก @select) */
  to?: string;
  disabled?: boolean;
}

const props = withDefaults(
  defineProps<{
    items: RowActionItem[];
    /** aria-label ของปุ่มจุด 3 จุด — ต้องบอกว่าของแถวไหน */
    label?: string;
  }>(),
  { label: 'เมนูเพิ่มเติม' },
);

const emit = defineEmits<{ select: [key: string] }>();

// ── ค่าคงที่ของแผง ────────────────────────────────────────────────────────────
// 🔴 ความกว้างถูกเซ็ตผ่าน inline style จาก PANEL_WIDTH ไม่ใช่คลาส `w-*`
//    ⇒ เลขที่ใช้วาด กับเลขที่ใช้คำนวณห้ามแยกกันอยู่คนละที่ (แก้ที่เดียวแล้วตรงกัน)
//    เป็นข้อยกเว้นที่ตั้งใจของ DESIGN.md §12 — `top`/`left` เป็นค่าที่ Tailwind ทำไม่ได้อยู่แล้ว
//    การใส่ `width` ไปพร้อมกันจึงทำให้ "ค่าที่วาด" กับ "ค่าที่คำนวณ" มีแหล่งเดียว
const PANEL_WIDTH = 208;
const PANEL_PADDING = 8; // py-1 (4px × 2)
const PANEL_BORDER = 2; // border (1px × 2) — ต้องนับ ไม่งั้นค่าประเมินเตี้ยกว่าของจริง
const ITEM_HEIGHT = 44; // = py-3 (24px) + line-height ของ text-sm (20px) ตาม DESIGN.md §2
const EDGE_GAP = 12;

/** นับเพิ่มต่ออินสแตนซ์ เพื่อผูก `aria-controls` ของปุ่มเข้ากับแผงที่ถูก Teleport ออกไป */
let menuSeq = 0;
const panelId = `row-action-menu-${(menuSeq += 1)}`;

const isOpen = ref(false);
const triggerRef = ref<HTMLButtonElement | null>(null);
const panelRef = ref<HTMLElement | null>(null);
const panelStyle = ref<Record<string, string>>({
  top: '0px',
  left: '0px',
  width: `${PANEL_WIDTH}px`,
});

const itemNodes = (): HTMLElement[] =>
  Array.from(panelRef.value?.querySelectorAll<HTMLElement>('[data-menu-item]') ?? []);

/** ไอเทมที่ "โฟกัสได้จริง" — `.focus()` บนปุ่มที่ disabled ไม่เกิดอะไร ⇒ ต้องตัดออกจากเส้นทางลูกศร */
const focusableNodes = (): HTMLElement[] =>
  itemNodes().filter((node) => !(node as HTMLButtonElement).disabled);

/** วางแผงชิดขอบขวาของปุ่ม แล้วหนีบไม่ให้ล้นจอทั้งแนวนอนและแนวตั้ง */
const positionPanel = () => {
  const trigger = triggerRef.value;
  if (!trigger) return;

  const rect = trigger.getBoundingClientRect();

  const maxLeft = Math.max(EDGE_GAP, window.innerWidth - PANEL_WIDTH - EDGE_GAP);
  const left = Math.min(Math.max(rect.right - PANEL_WIDTH, EDGE_GAP), maxLeft);

  // ครั้งแรกยังวัดไม่ได้ (DOM ยังไม่ patch) ⇒ ประเมินจากจำนวนไอเทมก่อน
  // แล้ววัดของจริงใน nextTick ซึ่งยังไม่ทัน paint ⇒ ไม่เห็นการกระตุก
  const measured = panelRef.value?.offsetHeight ?? 0;
  const height =
    measured > 0 ? measured : props.items.length * ITEM_HEIGHT + PANEL_PADDING + PANEL_BORDER;

  // เปิดลงล่างถ้าที่พอ ไม่งั้นพลิกขึ้นบน
  const spaceBelow = window.innerHeight - rect.bottom - EDGE_GAP;
  const top = spaceBelow >= height ? rect.bottom + 6 : rect.top - 6 - height;

  // 🔴 ต้องหนีบทั้งสองทาง — จอเตี้ย (มือถือแนวนอน) ทำให้แผงที่พลิกขึ้นบนล้นออกทางด้านบน
  //    และเพราะแผง clip ที่ขอบตัวเอง ไอเทมที่ถูกตัดจะกดไม่ได้เลย
  //    เพดาน `max-h` ที่ตัวแผงรับประกันว่า height ≤ innerHeight - 2×EDGE_GAP ⇒ ช่วงนี้ไม่ว่าง
  const maxTop = Math.max(EDGE_GAP, window.innerHeight - height - EDGE_GAP);

  panelStyle.value = {
    top: `${Math.min(Math.max(top, EDGE_GAP), maxTop)}px`,
    left: `${left}px`,
    width: `${PANEL_WIDTH}px`,
  };
};

/** ปิดเฉย ๆ — ⚠️ ห้ามรับ event เข้ามา ไม่งั้นใช้เป็น listener ของ scroll/resize ไม่ได้ */
const close = () => {
  if (!isOpen.value) return;
  isOpen.value = false;
  window.removeEventListener('keydown', onKeydown);
  window.removeEventListener('scroll', close, true);
  window.removeEventListener('resize', close);
};

/** ปิดแล้วคืนโฟกัสให้ปุ่ม — ใช้เมื่อผู้ใช้กด Esc (คนใช้คีย์บอร์ดจะได้ไม่หลงที่) */
const closeAndRestoreFocus = () => {
  const wasOpen = isOpen.value;
  close();
  if (wasOpen) triggerRef.value?.focus();
};

/**
 * 🔴 ตัวดักคีย์ผูกที่ `window` (จำเป็น เพราะแผงถูก Teleport ออกจาก subtree ของปุ่ม)
 * ⇒ ต้องเช็คเองว่า "โฟกัสยังอยู่กับเมนูนี้" ไม่งั้นจะยึดลูกศรของทั้งหน้า
 *   และกด Esc ที่ไหนก็ปิดเมนูของแถวนี้พร้อมกระชากโฟกัสกลับมาที่ปุ่มของมัน
 */
const ownsFocus = (): boolean =>
  panelRef.value?.contains(document.activeElement) === true ||
  document.activeElement === triggerRef.value;

const onKeydown = (event: KeyboardEvent) => {
  if (!isOpen.value) return;

  if (event.key === 'Tab') {
    // แผงอยู่นอกลำดับ Tab ของปุ่ม ⇒ ปล่อยไว้จะค้างเปิดพร้อมฉากหลังที่บล็อกทั้งหน้า
    // ขณะที่โฟกัสไปอยู่ที่อื่นแล้ว · ปิดแล้วปล่อยให้เบราว์เซอร์ย้ายโฟกัสเอง (ไม่ preventDefault)
    close();
    return;
  }

  if (event.key === 'Escape') {
    // ⚠️ ห้ามผูกกับ ownsFocus() — เมนูที่เปิดอยู่มีฉากหลังคลุมทั้งหน้า = overlay บนสุด
    //    ⇒ Esc ที่ไหนก็ควรปิด และ **Safari (macOS) ไม่ย้ายโฟกัสมาที่ปุ่มเมื่อคลิกด้วยเมาส์**
    //    ถ้าเช็คโฟกัส ผู้ใช้ Safari จะกด Esc แล้วเมนูไม่ปิดเลย
    closeAndRestoreFocus();
    return;
  }

  if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;

  // 🔴 ลูกศร "ต้อง" ผูกกับโฟกัส — นี่คือบั๊กที่รีวิวจับได้: ถ้าไม่เช็ค ลูกศรของทั้งหน้าจะถูก
  //    preventDefault และโฟกัสถูกกระชากจากช่องอื่นเข้ามาในแผง (เช่นกดลูกศรใน <select>
  //    ของตัวกรอง แล้วโฟกัสเด้งเข้าเมนู)
  if (!ownsFocus()) return;

  const nodes = focusableNodes();
  if (!nodes.length) return;
  event.preventDefault();

  const current = nodes.indexOf(document.activeElement as HTMLElement);
  const step = event.key === 'ArrowDown' ? 1 : -1;
  // current = -1 คือ "โฟกัสยังไม่ถึงไอเทมไหน" (เพิ่งเปิดด้วยเมาส์ ปุ่มยังถือโฟกัสอยู่)
  // ⇒ ArrowDown ไปไอเทมแรก, ArrowUp ไปไอเทมสุดท้าย — สูตร modulo ตรง ๆ จะให้รองสุดท้าย (off-by-one)
  const next =
    current === -1
      ? step === 1
        ? 0
        : nodes.length - 1
      : (current + step + nodes.length) % nodes.length;
  nodes[next]?.focus();
};

const open = (focusFirstItem: boolean) => {
  isOpen.value = true;
  positionPanel();
  void nextTick(() => {
    positionPanel();
    if (focusFirstItem) focusableNodes()[0]?.focus();
  });
  // ปิดเมื่อหน้าเลื่อน/ย่อขยาย — ไม่งั้นแผงลอยค้างอยู่คนละที่กับปุ่ม
  window.addEventListener('keydown', onKeydown);
  window.addEventListener('scroll', close, true);
  window.addEventListener('resize', close);
};

const toggle = (event: MouseEvent) => {
  if (isOpen.value) {
    close();
    return;
  }
  // `event.detail === 0` = เปิดด้วยคีย์บอร์ด (Enter/Space) ⇒ โฟกัสไอเทมแรกให้เลย
  // แต่ถ้าเปิดด้วยนิ้ว/เมาส์ อย่าเพิ่งโฟกัส — บนมือถือจะทำให้จอกระตุก
  open(event.detail === 0);
};

const select = (item: RowActionItem) => {
  if (item.disabled) return;
  // คืนโฟกัส "ก่อน" ที่ไอเทมจะถูกถอดออกจาก DOM ไม่งั้นโฟกัสตกไปที่ <body> ทั้งหน้า
  // (เส้นทางนี้เกิดกับคนใช้คีย์บอร์ดที่กด Enter บนไอเทม)
  closeAndRestoreFocus();
  emit('select', item.key);
};

const itemClass = (item: RowActionItem) => [
  // `py-3` ไม่ใช่ `py-2.5` — แถวที่กดได้ต้อง ≥44px (DESIGN.md §2) เท่ากับ `ITEM_HEIGHT` ข้างบน
  'flex w-full items-center gap-3 px-4 py-3 text-left text-sm font-bold transition-colors',
  'focus-visible:outline-none focus-visible:bg-stone-100',
  // `text-stone-400` = "ตัวอักษรเบา" ตัวสุดท้ายที่ DESIGN.md §2 อนุญาต
  // (stone-300 ไม่อยู่ในชุดที่อนุญาต และคอนทราสต์ ~1.6:1 อ่านไม่ออก)
  item.disabled
    ? 'cursor-not-allowed text-stone-400'
    : item.tone === 'danger'
      ? 'text-red-600 hover:bg-red-50'
      : 'text-stone-700 hover:bg-stone-50',
];

// ออกจากหน้าไปทั้ง component (เช่น RouterLink ในเมนู หรือเปลี่ยน route)
// ⇒ ต้องถอน listener ให้ครบ ไม่งั้นรั่วสะสมทุกครั้งที่เข้า-ออกหน้า
onBeforeUnmount(close);
</script>

<template>
  <button
    ref="triggerRef"
    type="button"
    class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-stone-400 transition-colors hover:bg-stone-100 hover:text-stone-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-stone-300 active:scale-[0.97]"
    :title="label"
    :aria-label="label"
    aria-haspopup="menu"
    :aria-expanded="isOpen"
    :aria-controls="isOpen ? panelId : undefined"
    @click.stop="toggle"
  >
    <i class="bi bi-three-dots-vertical text-lg" aria-hidden="true"></i>
  </button>

  <!-- 🗂️ Teleport ไป body — หลุดจาก overflow-hidden / overflow-x-auto ของตาราง -->
  <Teleport to="body">
    <!-- ฉากรับคลิกนอก: กว้างเต็มจอ อยู่ใต้แผง -->
    <div v-if="isOpen" data-menu-backdrop class="fixed inset-0 z-[70]" @click="close"></div>

    <Transition name="row-menu">
      <div
        v-if="isOpen"
        :id="panelId"
        ref="panelRef"
        role="menu"
        :aria-label="label"
        :style="panelStyle"
        class="fixed z-[80] max-h-[calc(100vh_-_1.5rem)] overflow-y-auto overscroll-contain rounded-xl border border-stone-200 bg-white py-1 shadow-[0_16px_40px_-16px_rgba(28,25,23,0.3)]"
      >
        <template v-for="item in items" :key="item.key">
          <RouterLink
            v-if="item.to"
            :to="item.to"
            data-menu-item
            role="menuitem"
            :class="itemClass(item)"
            @click="close"
          >
            <i class="bi" :class="item.icon" aria-hidden="true"></i>
            {{ item.label }}
          </RouterLink>

          <button
            v-else
            type="button"
            data-menu-item
            role="menuitem"
            :disabled="item.disabled"
            :class="itemClass(item)"
            @click="select(item)"
          >
            <i class="bi" :class="item.icon" aria-hidden="true"></i>
            {{ item.label }}
          </button>
        </template>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.row-menu-enter-active,
.row-menu-leave-active {
  transition:
    opacity 120ms ease,
    transform 120ms ease;
}
/* ระหว่าง 120ms ที่ของกำลังจาง Vue ยังไม่ถอดแผงออกจาก DOM
   ⇒ ต้องกันไม่ให้มันกลืนคลิกของผู้ใช้ที่กดไปที่อื่นแล้ว */
.row-menu-leave-active {
  pointer-events: none;
}
.row-menu-enter-from,
.row-menu-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.98);
}

@media (prefers-reduced-motion: reduce) {
  .row-menu-enter-active,
  .row-menu-leave-active {
    transition: none;
  }
}
</style>
