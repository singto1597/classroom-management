<script setup lang="ts">
defineOptions({ name: 'LoginView' });

import PageHeader from '@/components/ui/PageHeader.vue';
import { getDiscordAuthUrl, getGoogleAuthUrl } from '@/services/auth';

const handleDiscordLogin = () => {
  window.location.href = getDiscordAuthUrl();
};

const handleGoogleLogin = () => {
  window.location.href = getGoogleAuthUrl();
};
</script>

<template>
  <div class="min-h-screen min-h-dvh bg-paper font-sans text-ink">
    <!-- ── แถบหัวเรื่อง: เส้นบาง ไม่มีกระจก ─────────────────────────── -->
    <header class="border-b border-stone-200 bg-white">
      <div class="page-wrap flex h-16 items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
        <a href="/" class="flex min-w-0 items-center gap-2.5">
          <div
            class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-700 text-white"
          >
            <i class="bi bi-box-fill text-base" aria-hidden="true"></i>
          </div>
          <span class="font-display truncate text-lg font-bold tracking-[0.2em] text-stone-900">
            SYNC<span class="font-normal text-stone-400">ROOM</span>
          </span>
        </a>
        <span class="chip hidden bg-stone-100 text-stone-600 sm:inline-flex">
          Classroom Management System
        </span>
      </div>
    </header>

    <main>
      <!-- ⚠️ หน้านี้อยู่นอก MainLayout จึงต้องจัดระยะขอบเอง -->
      <div class="grid lg:grid-cols-2">
        <!-- ── ฝั่งซ้าย: แผงแบรนด์พื้นทึบ (สลับลำดับบนมือถือ) ── -->
        <section class="order-2 flex bg-stone-900 lg:order-1">
          <div class="flex w-full px-4 py-12 sm:px-6 lg:justify-end lg:py-20 lg:pe-14">
            <div class="w-full max-w-lg">
              <p class="eyebrow text-brand-300">Syncroom Classroom</p>

              <h2
                class="font-display mt-3 text-3xl font-bold leading-tight tracking-tight text-white sm:text-4xl lg:text-5xl"
              >
                จัดการห้องเรียน<br class="hidden sm:block" />
                อย่างเป็นระบบ
              </h2>

              <p class="mt-4 text-sm leading-relaxed text-stone-300 sm:text-base">
                แพลตฟอร์มที่เชื่อมต่อครูและนักเรียนเข้าด้วยกัน จัดการรายชื่อ ตารางเรียน
                งานที่มอบหมาย และการเงินของห้อง จบครบในที่เดียว
              </p>

              <!-- จุดขาย — คั่นด้วยเส้น hairline ไม่ใช่การ์ด -->
              <ul class="mt-8 divide-y divide-white/10 border-y border-white/10">
                <li class="flex items-start gap-3.5 py-4">
                  <i class="bi bi-people-fill mt-0.5 shrink-0 text-base text-brand-300" aria-hidden="true"></i>
                  <div class="min-w-0">
                    <p class="text-sm font-bold text-white">ทะเบียนนักเรียน</p>
                    <p class="mt-0.5 text-xs leading-relaxed text-stone-400">
                      ข้อมูลเป็นระบบ ค้นหาไว อัปเดตได้ทันที
                    </p>
                  </div>
                </li>
                <li class="flex items-start gap-3.5 py-4">
                  <i class="bi bi-calendar2-event-fill mt-0.5 shrink-0 text-base text-brand-300" aria-hidden="true"></i>
                  <div class="min-w-0">
                    <p class="text-sm font-bold text-white">ตารางเรียนร่วมกัน</p>
                    <p class="mt-0.5 text-xs leading-relaxed text-stone-400">
                      ทุกคนในห้องเห็นตรงกัน แจ้งเตือนเมื่อมีคาบเปลี่ยนแปลง
                    </p>
                  </div>
                </li>
                <li class="flex items-start gap-3.5 py-4">
                  <i class="bi bi-cash-coin mt-0.5 shrink-0 text-base text-brand-300" aria-hidden="true"></i>
                  <div class="min-w-0">
                    <p class="text-sm font-bold text-white">การเงินห้องเรียน</p>
                    <p class="mt-0.5 text-xs leading-relaxed text-stone-400">
                      เก็บเงินค่าห้องโปร่งใส ตรวจสอบย้อนหลังได้ตลอด
                    </p>
                  </div>
                </li>
                <li class="flex items-start gap-3.5 py-4">
                  <i class="bi bi-discord mt-0.5 shrink-0 text-base text-brand-300" aria-hidden="true"></i>
                  <div class="min-w-0">
                    <p class="text-sm font-bold text-white">แจ้งเตือนผ่าน Discord</p>
                    <p class="mt-0.5 text-xs leading-relaxed text-stone-400">
                      ประกาศและงานที่มอบหมายถึงเซิร์ฟเวอร์โดยตรง
                    </p>
                  </div>
                </li>
              </ul>
            </div>
          </div>
        </section>

        <!-- ── ฝั่งขวา: ทางเข้าสู่ระบบ ── -->
        <section class="order-1 flex bg-paper lg:order-2">
          <div class="flex w-full px-4 py-10 sm:px-6 lg:justify-start lg:py-20 lg:ps-14">
            <div class="w-full max-w-md">
              <PageHeader
                eyebrow="Sign In"
                title="เข้าสู่ระบบ"
                description="เลือกบัญชีของคุณเพื่อดำเนินการต่อ"
              />

              <div class="page-card p-5 sm:p-6">
                <div class="flex flex-col gap-3">
                  <button
                    type="button"
                    class="flex h-12 w-full items-center justify-center gap-3 rounded-xl border border-stone-200 bg-white px-4 text-sm font-bold text-stone-800 transition-colors hover:border-stone-300 hover:bg-stone-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/30 focus-visible:ring-offset-2 active:scale-[0.97]"
                    @click="handleGoogleLogin"
                  >
                    <svg class="h-5 w-5 shrink-0" viewBox="0 0 24 24" aria-hidden="true">
                      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1Z"/>
                      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23Z"/>
                      <path fill="#FBBC05" d="M5.84 14.1a6.6 6.6 0 0 1 0-4.2V7.06H2.18a11 11 0 0 0 0 9.88l3.66-2.84Z"/>
                      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15A11 11 0 0 0 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52Z"/>
                    </svg>
                    ดำเนินการต่อด้วย Google
                  </button>

                  <button
                    type="button"
                    class="flex h-12 w-full items-center justify-center gap-3 rounded-xl border border-stone-200 bg-white px-4 text-sm font-bold text-stone-800 transition-colors hover:border-stone-300 hover:bg-stone-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/30 focus-visible:ring-offset-2 active:scale-[0.97]"
                    @click="handleDiscordLogin"
                  >
                    <i class="bi bi-discord shrink-0 text-xl" aria-hidden="true"></i>
                    ดำเนินการต่อด้วย Discord
                  </button>
                </div>

                <p
                  class="mt-5 border-t border-stone-100 pt-4 text-center text-xs leading-relaxed text-stone-400"
                >
                  การเข้าสู่ระบบแสดงว่าคุณยอมรับ
                  <a
                    href="#"
                    class="font-bold text-stone-600 underline underline-offset-2 transition-colors hover:text-brand-700"
                    >ข้อตกลงการใช้งาน</a
                  >
                  และ
                  <a
                    href="#"
                    class="font-bold text-stone-600 underline underline-offset-2 transition-colors hover:text-brand-700"
                    >นโยบายความเป็นส่วนตัว</a
                  >
                </p>
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>

    <!-- ── ฟีเจอร์ ─────────────────────────────────────────────────── -->
    <section class="border-t border-stone-200 bg-white">
      <div class="page-wrap px-4 py-12 sm:px-6 sm:py-16 lg:px-8">
        <p class="eyebrow">Features</p>
        <h2 class="section-title mt-1.5 text-xl sm:text-2xl">
          ฟีเจอร์ที่ออกแบบมาเพื่อห้องเรียนยุคใหม่
        </h2>
        <p class="page-lede mt-2">
          ลดงานเอกสารซ้ำซ้อน เพิ่มเวลาให้กับการเรียนการสอนอย่างเต็มที่
        </p>

        <div class="mt-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <div class="page-card p-5">
            <div
              class="flex h-11 w-11 items-center justify-center rounded-xl bg-stone-100 text-stone-700"
            >
              <i class="bi bi-people-fill text-lg" aria-hidden="true"></i>
            </div>
            <h3 class="section-title mt-4">ทะเบียนนักเรียน</h3>
            <p class="mt-1.5 text-sm leading-relaxed text-stone-500">
              จัดการข้อมูลพื้นฐาน รายชื่อ เลขที่ อย่างเป็นระบบ ค้นหาง่าย อัปเดตได้แบบเรียลไทม์
            </p>
          </div>

          <div class="page-card p-5">
            <div
              class="flex h-11 w-11 items-center justify-center rounded-xl bg-stone-100 text-stone-700"
            >
              <i class="bi bi-clipboard2-check-fill text-lg" aria-hidden="true"></i>
            </div>
            <h3 class="section-title mt-4">ระบบเช็คชื่ออัจฉริยะ</h3>
            <p class="mt-1.5 text-sm leading-relaxed text-stone-500">
              บันทึกการเข้าเรียน ขาด ลา มาสาย ได้รวดเร็ว พร้อมสรุปสถิติรายสัปดาห์แบบอัตโนมัติ
            </p>
          </div>

          <div class="page-card p-5">
            <div
              class="flex h-11 w-11 items-center justify-center rounded-xl bg-stone-100 text-stone-700"
            >
              <i class="bi bi-calendar2-event-fill text-lg" aria-hidden="true"></i>
            </div>
            <h3 class="section-title mt-4">ตารางเรียนร่วมกัน</h3>
            <p class="mt-1.5 text-sm leading-relaxed text-stone-500">
              ซิงค์ตารางเรียนให้ทุกคนในห้องเห็นตรงกัน แจ้งเตือนเมื่อมีการเปลี่ยนคาบหรือยกเลิกคลาส
            </p>
          </div>

          <div class="page-card p-5">
            <div
              class="flex h-11 w-11 items-center justify-center rounded-xl bg-stone-100 text-stone-700"
            >
              <i class="bi bi-cash-coin text-lg" aria-hidden="true"></i>
            </div>
            <h3 class="section-title mt-4">จัดการเหรัญญิก</h3>
            <p class="mt-1.5 text-sm leading-relaxed text-stone-500">
              เก็บเงินค่าห้อง โปร่งใส ตรวจสอบง่าย หมดปัญหาการตามทวงเงินที่วุ่นวาย
            </p>
          </div>

          <div class="page-card p-5">
            <div
              class="flex h-11 w-11 items-center justify-center rounded-xl bg-stone-100 text-stone-700"
            >
              <i class="bi bi-card-checklist text-lg" aria-hidden="true"></i>
            </div>
            <h3 class="section-title mt-4">ติดตามงานที่มอบหมาย</h3>
            <p class="mt-1.5 text-sm leading-relaxed text-stone-500">
              ศูนย์รวมการบ้านและโปรเจกต์ ดูสถานะการส่งงานของนักเรียนแต่ละคนได้อย่างละเอียด
            </p>
          </div>

          <div class="page-card p-5">
            <div
              class="flex h-11 w-11 items-center justify-center rounded-xl bg-stone-100 text-stone-700"
            >
              <i class="bi bi-discord text-lg" aria-hidden="true"></i>
            </div>
            <h3 class="section-title mt-4">เชื่อมต่อ Discord</h3>
            <p class="mt-1.5 text-sm leading-relaxed text-stone-500">
              ส่งประกาศ แจ้งเตือนการบ้าน และอัปเดตกิจกรรมต่างๆ เข้าไปยังเซิร์ฟเวอร์โดยตรง
            </p>
          </div>
        </div>
      </div>
    </section>

    <!-- ── ท้ายหน้า ────────────────────────────────────────────────── -->
    <footer class="border-t border-stone-200 bg-white">
      <div
        class="page-wrap flex flex-col items-center justify-between gap-2 px-4 py-6 text-xs text-stone-400 sm:flex-row sm:px-6 lg:px-8"
      >
        <p class="font-semibold">&copy; 2026 SYNCROOM. All rights reserved.</p>
        <p class="flex items-center gap-2">
          <span>พัฒนาโดย</span>
          <a
            href="https://www.singto1597.xyz/"
            target="_blank"
            rel="noopener noreferrer"
            class="font-bold text-stone-600 underline underline-offset-2 transition-colors hover:text-brand-700"
          >
            นายพัฒนพล สุธรรม
          </a>
        </p>
      </div>
    </footer>
  </div>
</template>
