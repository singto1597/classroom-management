<script setup lang="ts">
import { getDiscordAuthUrl, getGoogleAuthUrl } from '@/services/auth';

const handleDiscordLogin = () => {
  window.location.href = getDiscordAuthUrl();
};

const handleGoogleLogin = () => {
  window.location.href = getGoogleAuthUrl();
};
</script>

<template>
  <div class="relative min-h-screen selection:bg-blue-500/30 selection:text-blue-900 bg-[#FAFAFC] text-slate-900 font-sans overflow-x-hidden">
    
    <!-- 🎨 พื้นหลังตกแต่ง: Premium Subtle Glow (ลดความฉูดฉาด เน้นความหรูหรา) -->
    <div class="absolute inset-0 pointer-events-none overflow-hidden">
      <div class="absolute -top-[10%] -right-[5%] w-[800px] h-[800px] rounded-full bg-gradient-to-b from-blue-100/50 to-transparent blur-3xl opacity-60"></div>
      <div class="absolute top-[40%] -left-[10%] w-[600px] h-[600px] rounded-full bg-gradient-to-t from-indigo-100/40 to-transparent blur-3xl opacity-50"></div>
      <div class="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAiIGhlaWdodD0iMjAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PGNpcmNsZSBjeD0iMSIgY3k9IjEiIHI9IjEiIGZpbGw9InJnYmEoMCwgMCwgMCwgMC4wNCkiLz48L3N2Zz4=')] [mask-image:linear-gradient(to_bottom,white,transparent)] opacity-50"></div>
    </div>

    <!-- ⚡ Navbar: Minimalist -->
    <header class="relative z-20 flex items-center justify-between px-6 py-6 mx-auto max-w-7xl lg:px-8 animate-fade-in">
      <a href="/" class="flex items-center gap-3 group">
        <div class="flex items-center justify-center w-10 h-10 transition-transform duration-500 bg-white border shadow-sm rounded-xl border-slate-200/60 shadow-slate-200/50 group-hover:scale-105 group-hover:border-blue-200">
          <i class="text-xl text-blue-600 bi bi-box-fill"></i>
        </div>
        <span class="text-lg font-bold tracking-tight text-slate-800">SYNC<span class="font-normal text-slate-400">ROOM</span></span>
      </a>
      <div class="hidden sm:flex">
        <span class="px-3 py-1 text-xs font-medium border rounded-full text-slate-500 bg-white/50 border-slate-200 backdrop-blur-sm">
          Classroom Management System
        </span>
      </div>
    </header>

    <main class="relative z-10">
      <!-- 🌟 Section 1: Hero & Login (บนมือถือจะเห็นปุ่ม Login ทันที) -->
      <section class="px-6 pt-10 pb-20 mx-auto max-w-7xl lg:px-8 lg:pt-20 lg:pb-32">
        <div class="grid items-center grid-cols-1 gap-16 lg:grid-cols-2 lg:gap-24">
          
          <!-- ฝั่งซ้าย: Typography เน้นๆ แบบ Apple/Stripe -->
          <div class="order-2 text-center lg:order-1 lg:text-left animate-slide-up-fade">
            <div class="inline-flex items-center gap-2 px-3 py-1.5 mb-6 text-sm font-medium text-blue-700 bg-blue-50/80 border border-blue-100 rounded-full shadow-sm">
              <span class="relative flex w-2 h-2">
                <span class="absolute inline-flex w-full h-full bg-blue-400 rounded-full opacity-75 animate-ping"></span>
                <span class="relative inline-flex w-2 h-2 bg-blue-500 rounded-full"></span>
              </span>
              SYNCROOM 2.0 พร้อมใช้งานแล้ว
            </div>
            
            <h1 class="text-4xl font-extrabold tracking-tight text-slate-900 sm:text-5xl lg:text-6xl leading-[1.1]">
              จัดการห้องเรียน <br class="hidden lg:block" />
              <span class="text-transparent bg-clip-text bg-gradient-to-r from-blue-600 to-indigo-600">อย่างมืออาชีพ</span>
            </h1>
            
            <p class="mt-6 text-lg leading-relaxed text-slate-500 sm:text-xl lg:max-w-xl font-medium">
              แพลตฟอร์มที่เชื่อมต่อครูและนักเรียนเข้าด้วยกัน จัดการรายชื่อ เช็คชื่อ ตารางเรียน และงานที่มอบหมาย จบครบในที่เดียว พร้อมระบบแจ้งเตือนผ่าน Discord
            </p>

            <div class="flex items-center justify-center gap-6 mt-10 lg:justify-start">
              <div class="flex flex-col items-center gap-2 sm:flex-row sm:gap-4">
                <div class="flex -space-x-2">
                  <img class="w-10 h-10 border-2 border-white rounded-full" src="https://ui-avatars.com/api/?name=Teacher&background=0D8ABC&color=fff" alt="User" />
                  <img class="w-10 h-10 border-2 border-white rounded-full" src="https://ui-avatars.com/api/?name=Student+1&background=F59E0B&color=fff" alt="User" />
                  <img class="w-10 h-10 border-2 border-white rounded-full" src="https://ui-avatars.com/api/?name=Student+2&background=10B981&color=fff" alt="User" />
                </div>
                <div class="text-sm font-medium text-slate-500">
                  <span class="font-bold text-slate-800">10,000+</span> ผู้ใช้งานในระบบ
                </div>
              </div>
            </div>
          </div>

          <!-- ฝั่งขวา: Login Card (Clean & Focused) -->
          <div class="order-1 lg:order-2 animate-slide-up-fade" style="animation-delay: 100ms;">
            <div class="relative w-full max-w-md mx-auto">
              <!-- การ์ดพื้นหลังสร้างมิติบางๆ -->
              <div class="absolute inset-0 transform translate-y-4 rounded-[2.5rem] bg-gradient-to-b from-slate-100 to-slate-50 border border-slate-200/50 scale-[0.96] -z-10"></div>
              
              <div class="relative bg-white/80 backdrop-blur-xl border border-white/80 shadow-[0_20px_40px_-15px_rgba(0,0,0,0.05)] rounded-[2rem] p-8 sm:p-10">
                <div class="text-center mb-8">
                  <h2 class="text-2xl font-bold tracking-tight text-slate-900">เข้าสู่ระบบ</h2>
                  <p class="mt-2 text-sm text-slate-500">เลือกบัญชีของคุณเพื่อดำเนินการต่อ</p>
                </div>

                <div class="flex flex-col gap-3.5">
                  <button
                    @click="handleGoogleLogin"
                    class="relative flex items-center justify-center w-full h-14 gap-3 px-4 text-base font-semibold transition-all bg-white border border-slate-200 rounded-2xl text-slate-700 hover:bg-slate-50 hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-slate-200 focus:ring-offset-2 active:scale-[0.98]"
                  >
                    <svg class="w-5 h-5" viewBox="0 0 24 24" aria-hidden="true">
                      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1Z"/>
                      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23Z"/>
                      <path fill="#FBBC05" d="M5.84 14.1a6.6 6.6 0 0 1 0-4.2V7.06H2.18a11 11 0 0 0 0 9.88l3.66-2.84Z"/>
                      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15A11 11 0 0 0 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52Z"/>
                    </svg>
                    ดำเนินการต่อด้วย Google
                  </button>

                  <button
                    @click="handleDiscordLogin"
                    class="relative flex items-center justify-center w-full h-14 gap-3 px-4 text-base font-semibold text-white transition-all bg-[#5865F2] hover:bg-[#4752C4] border border-transparent rounded-2xl shadow-sm hover:shadow focus:outline-none focus:ring-2 focus:ring-[#5865F2]/50 focus:ring-offset-2 active:scale-[0.98]"
                  >
                    <i class="text-xl bi bi-discord"></i>
                    ดำเนินการต่อด้วย Discord
                  </button>
                </div>

                <div class="mt-8">
                  <p class="text-xs text-center text-slate-400 leading-relaxed">
                    การเข้าสู่ระบบแสดงว่าคุณยอมรับ <a href="#" class="text-slate-600 hover:text-blue-600 underline underline-offset-2">ข้อตกลงการใช้งาน</a> และ <a href="#" class="text-slate-600 hover:text-blue-600 underline underline-offset-2">นโยบายความเป็นส่วนตัว</a>
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 🌟 Section 2: Features (ย้ายลงมาด้านล่าง ให้ดูเป็นเว็บ App มากขึ้น) -->
      <section class="border-t bg-white/50 border-slate-200/50 backdrop-blur-md">
        <div class="px-6 py-16 mx-auto max-w-7xl lg:px-8 lg:py-24">
          <div class="max-w-2xl mx-auto text-center animate-slide-up-fade" style="animation-delay: 200ms;">
            <h2 class="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">ฟีเจอร์ที่ออกแบบมาเพื่อห้องเรียนยุคใหม่</h2>
            <p class="mt-4 text-slate-500">ลดงานเอกสารซ้ำซ้อน เพิ่มเวลาให้กับการเรียนการสอนอย่างเต็มที่</p>
          </div>

          <div class="grid grid-cols-1 gap-6 mt-12 sm:grid-cols-2 lg:grid-cols-3 animate-slide-up-fade" style="animation-delay: 300ms;">
            <!-- Feature 1 -->
            <div class="p-6 transition-colors bg-white border rounded-2xl border-slate-200/70 hover:border-slate-300 shadow-sm shadow-slate-100/50">
              <div class="flex items-center justify-center w-12 h-12 mb-4 rounded-xl bg-blue-50 text-blue-600">
                <i class="text-xl bi bi-people-fill"></i>
              </div>
              <h3 class="text-base font-semibold text-slate-900">ทะเบียนนักเรียน</h3>
              <p class="mt-2 text-sm leading-relaxed text-slate-500">จัดการข้อมูลพื้นฐาน รายชื่อ เลขที่ อย่างเป็นระบบ ค้นหาง่าย อัปเดตได้แบบเรียลไทม์</p>
            </div>
            
            <!-- Feature 2 -->
            <div class="p-6 transition-colors bg-white border rounded-2xl border-slate-200/70 hover:border-slate-300 shadow-sm shadow-slate-100/50">
              <div class="flex items-center justify-center w-12 h-12 mb-4 rounded-xl bg-emerald-50 text-emerald-600">
                <i class="text-xl bi bi-clipboard2-check-fill"></i>
              </div>
              <h3 class="text-base font-semibold text-slate-900">ระบบเช็คชื่ออัจฉริยะ</h3>
              <p class="mt-2 text-sm leading-relaxed text-slate-500">บันทึกการเข้าเรียน ขาด ลา มาสาย ได้รวดเร็ว พร้อมสรุปสถิติรายสัปดาห์แบบอัตโนมัติ</p>
            </div>

            <!-- Feature 3 -->
            <div class="p-6 transition-colors bg-white border rounded-2xl border-slate-200/70 hover:border-slate-300 shadow-sm shadow-slate-100/50">
              <div class="flex items-center justify-center w-12 h-12 mb-4 rounded-xl bg-violet-50 text-violet-600">
                <i class="text-xl bi bi-calendar2-event-fill"></i>
              </div>
              <h3 class="text-base font-semibold text-slate-900">ตารางเรียนร่วมกัน</h3>
              <p class="mt-2 text-sm leading-relaxed text-slate-500">ซิงค์ตารางเรียนให้ทุกคนในห้องเห็นตรงกัน แจ้งเตือนเมื่อมีการเปลี่ยนคาบหรือยกเลิกคลาส</p>
            </div>

            <!-- Feature 4 -->
            <div class="p-6 transition-colors bg-white border rounded-2xl border-slate-200/70 hover:border-slate-300 shadow-sm shadow-slate-100/50">
              <div class="flex items-center justify-center w-12 h-12 mb-4 rounded-xl bg-amber-50 text-amber-600">
                <i class="text-xl bi bi-cash-coin"></i>
              </div>
              <h3 class="text-base font-semibold text-slate-900">จัดการเหรัญญิก</h3>
              <p class="mt-2 text-sm leading-relaxed text-slate-500">เก็บเงินค่าห้อง โปร่งใส ตรวจสอบง่าย หมดปัญหาการตามทวงเงินที่วุ่นวาย</p>
            </div>

            <!-- Feature 5 -->
            <div class="p-6 transition-colors bg-white border rounded-2xl border-slate-200/70 hover:border-slate-300 shadow-sm shadow-slate-100/50">
              <div class="flex items-center justify-center w-12 h-12 mb-4 rounded-xl bg-rose-50 text-rose-600">
                <i class="text-xl bi bi-card-checklist"></i>
              </div>
              <h3 class="text-base font-semibold text-slate-900">ติดตามงานที่มอบหมาย</h3>
              <p class="mt-2 text-sm leading-relaxed text-slate-500">ศูนย์รวมการบ้านและโปรเจกต์ ดูสถานะการส่งงานของนักเรียนแต่ละคนได้อย่างละเอียด</p>
            </div>

            <!-- Feature 6 -->
            <div class="p-6 transition-colors bg-white border rounded-2xl border-slate-200/70 hover:border-slate-300 shadow-sm shadow-slate-100/50">
              <div class="flex items-center justify-center w-12 h-12 mb-4 rounded-xl bg-[#5865F2]/10 text-[#5865F2]">
                <i class="text-xl bi bi-discord"></i>
              </div>
              <h3 class="text-base font-semibold text-slate-900">เชื่อมต่อ Discord</h3>
              <p class="mt-2 text-sm leading-relaxed text-slate-500">ส่งประกาศ แจ้งเตือนการบ้าน และอัปเดตกิจกรรมต่างๆ เข้าไปยังเซิร์ฟเวอร์โดยตรง</p>
            </div>
          </div>
        </div>
      </section>
    </main>

    <!-- Footer -->
    <footer class="py-8 text-center bg-white border-t border-slate-200/50">
      <p class="text-sm font-medium text-slate-400">
        &copy; 2026 SYNCROOM. All rights reserved.
      </p>
    </footer>
  </div>
</template>

<style scoped>
/* Animations ที่ดูเป็นธรรมชาติแบบงาน Premium */
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes slideUpFade {
  from { 
    opacity: 0; 
    transform: translateY(20px) scale(0.98); 
  }
  to { 
    opacity: 1; 
    transform: translateY(0) scale(1); 
  }
}

.animate-fade-in {
  animation: fadeIn 0.8s ease-out forwards;
}

.animate-slide-up-fade {
  opacity: 0;
  animation: slideUpFade 0.8s cubic-bezier(0.16, 1, 0.3, 1) forwards;
}
</style>