<script setup lang="ts">
defineOptions({ name: 'LandingView' });

/**
 * 🏠 หน้าแรกสาธารณะ (ก่อนล็อกอิน)
 *
 * เนื้อหาคงที่ทั้งหมด — backend ของห้องเรียนไม่มี public endpoint สำหรับสถิติ
 * หรือประกาศ ⇒ **ห้ามใส่ตัวเลขสมมติที่ดูเหมือนข้อมูลจริง** การ์ดฝั่งขวาเป็น
 * ภาพตัวอย่างหน้าจอ (มีป้ายกำกับชัดเจน) ไม่ใช่ข้อมูลสด
 *
 * หลักการออกแบบเดียวกับ PIRIvoice: fixed header, hero แบบ editorial,
 * กระดาษจุด (dotted canvas), การ์ดเส้นบาง ไม่มี gradient/glass
 */
import { onBeforeUnmount, onMounted, ref } from 'vue';
import { RouterLink } from 'vue-router';

const isScrolled = ref(false);
const onScroll = () => {
  isScrolled.value = window.scrollY > 12;
};

onMounted(() => {
  onScroll();
  window.addEventListener('scroll', onScroll, { passive: true });
});
onBeforeUnmount(() => window.removeEventListener('scroll', onScroll));

const features = [
  {
    icon: 'bi-people',
    title: 'ทะเบียนนักเรียน',
    desc: 'รายชื่อ เลขที่ และข้อมูลพื้นฐาน ค้นหาไว แก้ไขแล้วเห็นตรงกันทุกคน',
  },
  {
    icon: 'bi-clipboard-check',
    title: 'งานและโน้ต',
    desc: 'มอบหมายงาน ติดตามสถานะ และบันทึกโน้ตของห้องไว้ในที่เดียว',
  },
  {
    icon: 'bi-calendar-event',
    title: 'ตารางเรียน',
    desc: 'ตารางเรียนร่วมกันของทั้งห้อง พร้อมปีการศึกษาและเทอมที่ชัดเจน',
  },
  {
    icon: 'bi-wallet2',
    title: 'การเงินห้องเรียน',
    desc: 'เก็บเงิน โปรเจกต์ ใบเสร็จ และยอดค้างชำระ ตรวจสอบย้อนหลังได้',
  },
  {
    icon: 'bi-calendar-heart',
    title: 'กิจกรรมและประกาศ',
    desc: 'สร้างกิจกรรม รับสมัครผู้เข้าร่วม และประกาศข่าวสารถึงทุกคน',
  },
  {
    icon: 'bi-discord',
    title: 'แจ้งเตือนผ่าน Discord',
    desc: 'งานใหม่ ประกาศ และยอดค้างชำระ ส่งตรงถึงเซิร์ฟเวอร์ของห้อง',
  },
] as const;

const steps = [
  {
    icon: 'bi-person-check',
    title: 'เข้าสู่ระบบ',
    desc: 'ใช้บัญชี Google หรือ Discord ที่มีอยู่แล้ว ไม่ต้องจำรหัสผ่านใหม่',
  },
  {
    icon: 'bi-door-open',
    title: 'เลือกหรือสร้างห้อง',
    desc: 'เลือกห้องเรียนที่คุณเป็นสมาชิก หรือสร้างห้องใหม่เมื่อเริ่มเทอม',
  },
  {
    icon: 'bi-grid-1x2',
    title: 'เริ่มใช้งาน',
    desc: 'ทุกเมนูอยู่ในแถบล่างและหน้าเพิ่มเติม ใช้ได้ทันทีทั้งมือถือและคอมพิวเตอร์',
  },
] as const;

const roles = [
  { label: 'ผู้ดูแลระบบ', desc: 'จัดการสมาชิก สิทธิ์ และตั้งค่าห้อง' },
  { label: 'เหรัญญิก', desc: 'บันทึกรายรับรายจ่ายและออกเอกสารการเงิน' },
  { label: 'กรรมการ', desc: 'ดูแลงาน กิจกรรม และประกาศตามหน้าที่' },
  { label: 'สมาชิก', desc: 'ดูข้อมูลของห้องและยอดที่ต้องชำระของตัวเอง' },
] as const;
</script>

<template>
  <div id="top" class="min-h-[100dvh] scroll-smooth bg-canvas font-sans text-ink-1">
    <!-- ── Header ─────────────────────────────────────────────────── -->
    <header
      class="fixed inset-x-0 top-0 z-50 border-b transition-colors duration-200"
      :class="isScrolled ? 'border-line bg-surface' : 'border-transparent bg-canvas'"
    >
      <nav
        class="mx-auto flex h-[76px] max-w-7xl items-center justify-between gap-4 px-5 sm:px-6 lg:px-8"
        aria-label="เมนูหน้าแรก"
      >
        <RouterLink to="/" class="flex min-w-0 items-center gap-3">
          <span
            class="flex h-9 w-9 shrink-0 items-center justify-center rounded-control bg-brand text-white"
          >
            <i class="bi bi-box-fill text-base" aria-hidden="true"></i>
          </span>
          <span class="font-display truncate text-lg font-bold text-ink-1">
            SYNC<span class="font-normal text-ink-3">ROOM</span>
          </span>
        </RouterLink>

        <div class="hidden items-center gap-8 lg:flex">
          <a
            href="#features"
            class="text-sm font-semibold text-ink-2 transition-colors hover:text-ink-1"
            >ฟีเจอร์</a
          >
          <a
            href="#steps"
            class="text-sm font-semibold text-ink-2 transition-colors hover:text-ink-1"
            >ขั้นตอน</a
          >
          <a
            href="#security"
            class="text-sm font-semibold text-ink-2 transition-colors hover:text-ink-1"
            >ความปลอดภัย</a
          >
        </div>

        <RouterLink to="/login" class="btn-primary h-11 px-5 text-[13.5px]">
          เข้าสู่ระบบ
          <i class="bi bi-arrow-right text-xs" aria-hidden="true"></i>
        </RouterLink>
      </nav>
    </header>

    <main class="pt-[76px]">
      <!-- ── Hero ─────────────────────────────────────────────────── -->
      <section class="relative overflow-hidden">
        <div
          class="pointer-events-none absolute inset-0 -z-10 opacity-60 [background-image:radial-gradient(var(--line)_1px,transparent_1px)] [background-size:20px_20px]"
          aria-hidden="true"
        ></div>

        <div
          class="mx-auto max-w-7xl px-5 pb-20 pt-14 sm:px-6 sm:pt-20 lg:grid lg:grid-cols-[1.05fr_0.95fr] lg:items-center lg:gap-14 lg:px-8 lg:pb-28"
        >
          <div class="max-w-2xl">
            <p
              class="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1.5 text-sm font-semibold text-ink-2"
            >
              <span class="h-2 w-2 rounded-full bg-brand" aria-hidden="true"></span>
              ระบบจัดการห้องเรียนครบวงจร
            </p>

            <h1
              class="font-display mt-6 text-[2.5rem] font-bold leading-[1.18] text-ink-1 sm:text-5xl lg:text-[3.4rem]"
            >
              จัดการห้องเรียน
              <span class="text-brand">ให้จบในที่เดียว</span>
            </h1>

            <p class="mt-5 max-w-lg text-[16px] leading-relaxed text-ink-2 sm:text-[17px]">
              รวมรายชื่อนักเรียน งานและโน้ต ตารางเรียน การเงิน กิจกรรม และประกาศ
              ไว้ในระบบเดียวที่ทุกคนในห้องเห็นตรงกัน ใช้งานได้ทั้งมือถือและคอมพิวเตอร์
            </p>

            <div class="mt-8 flex flex-wrap items-center gap-3">
              <RouterLink to="/login" class="btn-primary h-12 px-6 text-[15px]">
                <i class="bi bi-box-arrow-in-right text-base" aria-hidden="true"></i>
                เริ่มใช้งาน
              </RouterLink>
              <a href="#features" class="btn-ghost-ui h-12 px-6 text-[15px]">ดูฟีเจอร์ทั้งหมด</a>
            </div>

            <p class="mt-5 text-sm text-ink-3">
              เข้าสู่ระบบด้วย Google หรือ Discord · ฟรีสำหรับห้องเรียน
            </p>
          </div>

          <!-- ภาพตัวอย่างหน้าจอ (ไม่ใช่ข้อมูลจริง) -->
          <div class="relative mt-14 lg:mt-0" aria-label="ตัวอย่างหน้าจอระบบ">
            <p class="mb-3 text-right text-xs font-semibold text-ink-3">ตัวอย่างหน้าจอ</p>

            <div class="space-y-3">
              <div class="rounded-card border border-line bg-surface p-4 shadow-sm sm:p-5">
                <div class="flex items-center justify-between gap-3">
                  <p class="text-sm font-bold text-ink-1">รายชื่อนักเรียน</p>
                  <span class="rounded-full bg-brand-tint px-2.5 py-1 text-xs font-bold text-brand">
                    40 คน
                  </span>
                </div>
                <ul class="mt-3 space-y-2">
                  <li
                    v-for="(name, index) in ['กิตติ', 'ณัฐวุฒิ', 'พิมพ์ชนก']"
                    :key="name"
                    class="flex items-center gap-3 rounded-control bg-canvas px-3 py-2"
                  >
                    <span
                      class="flex h-8 w-8 items-center justify-center rounded-full bg-surface text-xs font-bold text-ink-2"
                    >
                      {{ name.charAt(0) }}
                    </span>
                    <span class="flex-1 text-sm font-semibold text-ink-1">{{ name }}</span>
                    <span class="text-xs font-medium text-ink-3">เลขที่ {{ index + 1 }}</span>
                  </li>
                </ul>
              </div>

              <div class="grid gap-3 sm:grid-cols-2">
                <div class="rounded-card border border-line bg-surface p-4 shadow-sm">
                  <p class="text-xs font-semibold text-ink-3">งานที่มอบหมาย</p>
                  <p class="mt-1 text-title-m font-bold text-ink-1">แบบฝึกหัดบทที่ 3</p>
                  <div class="mt-3 h-1.5 overflow-hidden rounded-full bg-canvas">
                    <div class="h-full w-3/4 rounded-full bg-brand"></div>
                  </div>
                  <p class="mt-2 text-xs font-medium text-ink-3">ส่งแล้ว 30 จาก 40 คน</p>
                </div>

                <div class="rounded-card border border-line bg-surface p-4 shadow-sm">
                  <p class="text-xs font-semibold text-ink-3">เงินคงเหลือของห้อง</p>
                  <p class="font-display mt-1 text-title-m font-bold text-ink-1">฿ 4,250</p>
                  <p class="mt-3 flex items-center gap-1.5 text-xs font-semibold text-ok-700">
                    <i class="bi bi-arrow-down-left" aria-hidden="true"></i>
                    รายรับล่าสุด ฿ 1,200
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ── Features ─────────────────────────────────────────────── -->
      <section id="features" class="scroll-mt-24 border-t border-line bg-surface py-16 lg:py-24">
        <div class="mx-auto max-w-7xl px-5 sm:px-6 lg:px-8">
          <div class="max-w-2xl">
            <p class="text-sm font-bold text-brand">ฟีเจอร์</p>
            <h2 class="font-display mt-2 text-2xl font-bold text-ink-1 sm:text-3xl">
              ทุกงานของห้อง อยู่ในที่เดียว
            </h2>
            <p class="mt-3 text-[15px] leading-relaxed text-ink-2">
              ออกแบบจากงานจริงของห้องเรียน ลดการจดใส่สมุดและการถามซ้ำ
              ทุกคนเห็นข้อมูลชุดเดียวกัน
            </p>
          </div>

          <div class="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div v-for="feature in features" :key="feature.title" class="page-card p-5">
              <span
                class="flex h-11 w-11 items-center justify-center rounded-control bg-brand-tint text-brand"
              >
                <i :class="['bi', feature.icon, 'text-lg']" aria-hidden="true"></i>
              </span>
              <h3 class="mt-4 text-title-m font-bold text-ink-1">{{ feature.title }}</h3>
              <p class="mt-1.5 text-sm leading-relaxed text-ink-2">{{ feature.desc }}</p>
            </div>
          </div>
        </div>
      </section>

      <!-- ── Steps ────────────────────────────────────────────────── -->
      <section id="steps" class="scroll-mt-24 py-16 lg:py-24">
        <div class="mx-auto max-w-7xl px-5 sm:px-6 lg:px-8">
          <div class="max-w-2xl">
            <p class="text-sm font-bold text-brand">ขั้นตอนการใช้งาน</p>
            <h2 class="font-display mt-2 text-2xl font-bold text-ink-1 sm:text-3xl">
              เริ่มใช้ได้ในสามขั้นตอน
            </h2>
          </div>

          <ol class="mt-10 grid gap-4 lg:grid-cols-3">
            <li v-for="(step, index) in steps" :key="step.title" class="page-card p-5">
              <div class="flex items-center gap-3">
                <span
                  class="flex h-9 w-9 items-center justify-center rounded-full bg-brand text-sm font-bold text-white"
                >
                  {{ index + 1 }}
                </span>
                <i :class="['bi', step.icon, 'text-lg text-ink-3']" aria-hidden="true"></i>
              </div>
              <h3 class="mt-4 text-title-m font-bold text-ink-1">{{ step.title }}</h3>
              <p class="mt-1.5 text-sm leading-relaxed text-ink-2">{{ step.desc }}</p>
            </li>
          </ol>
        </div>
      </section>

      <!-- ── Security / roles ─────────────────────────────────────── -->
      <section id="security" class="scroll-mt-24 bg-ink-1 py-16 text-white lg:py-24">
        <div class="mx-auto max-w-7xl px-5 sm:px-6 lg:px-8">
          <div class="grid gap-10 lg:grid-cols-[0.9fr_1.1fr] lg:items-center">
            <div>
              <p class="text-sm font-bold text-brand-300">สิทธิ์และความปลอดภัย</p>
              <h2 class="font-display mt-2 text-2xl font-bold sm:text-3xl">
                ทุกคนเห็นเท่าที่ควรเห็น
              </h2>
              <p class="mt-3 text-[15px] leading-relaxed text-white/70">
                สิทธิ์ถูกกำหนดรายห้อง งานที่เขียนข้อมูลจะถูกบันทึกในบันทึกกิจกรรม
                และการเข้าสู่ระบบใช้นโยบาย OAuth ของ Google/Discord โดยไม่เก็บรหัสผ่าน
              </p>

              <ul class="mt-6 space-y-2 text-sm text-white/80">
                <li class="flex items-center gap-2">
                  <i class="bi bi-check-circle text-brand-300" aria-hidden="true"></i>
                  แยกสิทธิ์ตามบทบาทของแต่ละห้อง
                </li>
                <li class="flex items-center gap-2">
                  <i class="bi bi-check-circle text-brand-300" aria-hidden="true"></i>
                  บันทึกการแก้ไขย้อนหลังได้
                </li>
                <li class="flex items-center gap-2">
                  <i class="bi bi-check-circle text-brand-300" aria-hidden="true"></i>
                  ไม่เก็บรหัสผ่านของผู้ใช้
                </li>
              </ul>
            </div>

            <div class="grid gap-3 sm:grid-cols-2">
              <div
                v-for="role in roles"
                :key="role.label"
                class="rounded-card border border-white/10 bg-surface/5 p-5"
              >
                <p class="text-sm font-bold text-white">{{ role.label }}</p>
                <p class="mt-1.5 text-sm leading-relaxed text-white/60">{{ role.desc }}</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ── Final CTA ────────────────────────────────────────────── -->
      <section class="relative overflow-hidden py-16 lg:py-24">
        <div
          class="pointer-events-none absolute inset-0 -z-10 opacity-60 [background-image:radial-gradient(var(--line)_1px,transparent_1px)] [background-size:20px_20px]"
          aria-hidden="true"
        ></div>
        <div class="mx-auto max-w-3xl px-5 text-center sm:px-6">
          <h2 class="font-display text-2xl font-bold text-ink-1 sm:text-3xl">
            พร้อมเริ่มจัดการห้องเรียนหรือยัง
          </h2>
          <p class="mt-3 text-[15px] leading-relaxed text-ink-2">
            เข้าสู่ระบบด้วยบัญชีที่คุณมี แล้วเลือกห้องเรียนเพื่อเริ่มใช้งานได้ทันที
          </p>
          <div class="mt-7 flex flex-wrap items-center justify-center gap-3">
            <RouterLink to="/login" class="btn-primary h-12 px-7 text-[15px]">
              เข้าสู่ระบบ
            </RouterLink>
            <a href="#features" class="btn-ghost-ui h-12 px-6 text-[15px]">ย้อนดูฟีเจอร์</a>
          </div>
        </div>
      </section>
    </main>

    <!-- ── Footer ───────────────────────────────────────────────────── -->
    <footer class="border-t border-line bg-surface">
      <div
        class="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 px-5 py-6 text-xs text-ink-3 sm:flex-row sm:px-6 lg:px-8"
      >
        <p class="font-semibold">&copy; 2026 SYNCROOM</p>
        <div class="flex items-center gap-4">
          <RouterLink to="/login" class="font-semibold text-ink-2 hover:text-ink-1">
            เข้าสู่ระบบ
          </RouterLink>
          <a href="#top" class="font-semibold text-ink-2 hover:text-ink-1">กลับขึ้นด้านบน</a>
        </div>
      </div>
    </footer>
  </div>
</template>
