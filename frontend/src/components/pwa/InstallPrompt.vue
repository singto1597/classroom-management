<script setup lang="ts">
/**
 * 📲 แถบชวนติดตั้งแอป (PWA) — แสดงเฉพาะเมื่อ "มีโอกาสสำเร็จจริง"
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * เงื่อนไขที่ต้องผ่านครบ (ทุกข้อ — ไม่ใช่ข้อใดข้อหนึ่ง)
 * ═══════════════════════════════════════════════════════════════════════════
 *   1. อุปกรณ์ชี้แบบหยาบ (`pointer: coarse`) — เดสก์ท็อปไม่ต้องติดตั้ง
 *   2. ยังไม่ได้เปิดแบบ standalone — คนที่ติดตั้งแล้วไม่ควรเห็นซ้ำ
 *   3. ยังไม่เคยกดปิด — ความจำอยู่ที่เครื่อง (ไม่ถูกล้างตอนล็อกเอาต์)
 *   4. มีทางติดตั้งจริง — Android: `beforeinstallprompt` · iOS: แนะนำเมนู "แชร์"
 *      (iOS ไม่ยิง `beforeinstallprompt` เลย ⇒ ต้องสอนเส้นทางของ Safari แทน
 *      การซ่อนไปเฉย ๆ ซึ่งทำให้ผู้ใช้ iPhone ไม่มีทางรู้ว่าติดตั้งได้)
 *
 * ⚠️ ปุ่ม "ปิด" ต้องเก็บค่าทันที ไม่งั้นผู้ใช้จะเห็นแถบเดิมทุกครั้งที่เปลี่ยนหน้า
 *    (คอมโพเนนต์ mount ใหม่ทุกครั้งเพราะ layout อยู่ใน `<RouterView>`)
 */

import { computed, onMounted, ref } from 'vue'
import {
  getInstallPrompt,
  isCoarsePointer,
  isIOS,
  isStandalone,
  promptInstall,
} from '@/services/pwa'

/** คีย์เฉพาะเครื่อง — ไม่อยู่ใน `ALL_LOCAL_STORAGE_KEYS` เพราะไม่ใช่ข้อมูลบัญชี */
const DISMISS_KEY = 'syncroom_install_prompt_dismissed'

const visible = ref(false)
const busy = ref(false)
const dismissed = ref(false)
const showIosHelp = ref(false)

const canPrompt = computed(() => getInstallPrompt() !== null)
const iosDevice = computed(() => isIOS())

const readDismissed = (): boolean => {
  try {
    return localStorage.getItem(DISMISS_KEY) === '1'
  } catch {
    // storage ถูกบล็อก (โหมดส่วนตัวบางรุ่น) — ถือว่ายังไม่เคยปิด
    return false
  }
}

onMounted(() => {
  dismissed.value = readDismissed()
  if (dismissed.value) return
  if (!isCoarsePointer() || isStandalone()) return
  // iOS ไม่มี event ⇒ เช็คแค่ "เป็น iOS" ก็พอ; Android/Chrome ต้องมี event จริง
  visible.value = iosDevice.value || canPrompt.value
})

const rememberDismiss = () => {
  dismissed.value = true
  visible.value = false
  try {
    localStorage.setItem(DISMISS_KEY, '1')
  } catch {
    /* เขียนไม่ได้ก็แค่เห็นซ้ำครั้งหน้า — ไม่ใช่ error ที่ต้องรบกวนผู้ใช้ */
  }
}

const install = async () => {
  if (iosDevice.value && !canPrompt.value) {
    showIosHelp.value = true
    return
  }
  busy.value = true
  try {
    const outcome = await promptInstall()
    if (outcome === 'accepted') rememberDismiss()
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div
    v-if="visible && !dismissed"
    class="fixed inset-x-3 bottom-[calc(var(--app-nav-h)+env(safe-area-inset-bottom,0px)+1rem)] z-40 lg:inset-x-auto lg:end-6 lg:bottom-6 lg:w-80"
    role="region"
    aria-label="ติดตั้งแอป SYNCROOM"
  >
    <div class="rounded-card border border-line bg-surface p-3.5 shadow-sheet">
      <div class="flex items-start gap-3">
        <img
          src="/icons/icon-192.png"
          alt=""
          width="40"
          height="40"
          class="h-10 w-10 shrink-0 rounded-xl"
          aria-hidden="true"
        />
        <div class="min-w-0 flex-1">
          <p class="text-sm font-bold text-stone-900">ติดตั้ง SYNCROOM ไว้หน้าจอโฮม</p>
          <p class="mt-0.5 text-[13px] leading-snug text-stone-600">
            เปิดเต็มจอ และรับแจ้งเตือนได้แม้ปิดแอป
          </p>

          <div class="mt-2.5 flex items-center gap-2">
            <button
              type="button"
              class="min-h-11 rounded-xl bg-brand-700 px-3.5 text-sm font-bold text-white transition-colors hover:bg-brand-800 disabled:opacity-60"
              :disabled="busy"
              @click="install"
            >
              {{ busy ? 'กำลังเปิด…' : iosDevice && !canPrompt ? 'วิธีติดตั้ง' : 'ติดตั้ง' }}
            </button>
            <button
              type="button"
              class="min-h-11 rounded-xl px-3 text-sm font-bold text-stone-600 transition-colors hover:bg-stone-100"
              @click="rememberDismiss"
            >
              ไม่ใช่ตอนนี้
            </button>
          </div>

          <p v-if="showIosHelp" class="mt-2.5 rounded-xl bg-stone-50 p-2.5 text-[13px] leading-relaxed text-stone-700">
            แตะปุ่ม <strong>แชร์</strong> (สี่เหลี่ยมมีลูกศรขึ้น) ที่แถบล่างของ Safari
            แล้วเลือก <strong>เพิ่มไปยังหน้าจอโฮม</strong>
          </p>

          <!-- 🔎 สำหรับตรวจสาเหตุว่าแถบไม่ขึ้น (support/QA) — ไม่รบกวนผู้ใช้ทั่วไป -->
          <details class="mt-2 text-[12px] text-stone-500">
            <summary class="cursor-pointer select-none">ทำไมถึงเห็นป้ายนี้</summary>
            <ul class="mt-1.5 space-y-0.5 ps-4">
              <li>มือถือ/แท็บเล็ต: {{ isCoarsePointer() ? 'ใช่' : 'ไม่ใช่' }}</li>
              <li>ติดตั้งแล้ว: {{ isStandalone() ? 'ใช่' : 'ไม่ใช่' }}</li>
              <li>เบราว์เซอร์เสนอติดตั้งได้: {{ canPrompt ? 'ได้' : 'ไม่ได้ (iOS ใช้เมนูแชร์)' }}</li>
              <li>เคยกดปิดไว้: {{ readDismissed() ? 'ใช่' : 'ไม่เคย' }}</li>
            </ul>
          </details>
        </div>
      </div>
    </div>
  </div>
</template>
