/** @type {import('tailwindcss').Config} */
import colors from 'tailwindcss/colors'

// ═══════════════════════════════════════════════════════════════════════════
// 🎨 ตารางสีของ SYNCROOM — มีสองแกน ไม่ใช่แค่ "สีสวย"
//
//  แกนแบรนด์ (สีเน้นเดียว)        แกนสถานะ (ความหมาย ไม่ใช่สี)
//  ─────────────────────         ─────────────────────────────────────────
//  brand-*   #1D4ED8             ok-*     สำเร็จ / ชำระแล้ว / อนุมัติ
//           สิ่งที่กดได้,         warn-*   รอ / ค้าง / ใกล้ครบกำหนด
//           สิ่งที่ต้องดู         danger-* ลบ / ผิดพลาด / ยกเลิก / ค้างชำระ
//                                info-*   ป้ายข้อมูล / กำลังจะมา
//
//  ⚠️ กติกา: ใน `src/` ห้ามเขียน `emerald-*` / `amber-*` / `red-*` / `sky-*`
//     ตรง ๆ อีก — ใช้ชื่อความหมายแทน เพื่อให้เปลี่ยนพาเลตต์ได้ที่เดียว
//     ด่าน `npm run lint:palette` บังคับข้อนี้ (สคริปต์ตัดคอมเมนต์ก่อนตรวจ)
//
//  ⚠️ ไฟล์นี้กับ `src/assets/main.css` เป็น **สองที่เดียว** ที่มี hex ได้
//     (บวก Login.vue สำหรับโลโก้ Google ที่แบรนด์กำหนดตายตัว)
//     ด่าน `npm run lint:colors` บังคับข้อนี้
//
//  ค่า hex ของแต่ละสเกลมาจาก Tailwind ดิบ (emerald/amber/red/sky) ทั้งชุด
//  ⇒ หน้าตาไม่เปลี่ยนแม้แต่เฉดเดียวจากการเปลี่ยนชื่อ ต่างกันแค่ความหมาย
// ═══════════════════════════════════════════════════════════════════════════
export default {
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        // เนื้อหา — Noto Sans Thai
        sans: ['"Noto Sans Thai"', 'system-ui', 'sans-serif'],
        // หัวข้อ/ตัวเลขเด่น — Anuphan (ทรงเรขาคณิต อ่านไทยชัด)
        display: ['"Anuphan"', '"Noto Sans Thai"', 'system-ui', 'sans-serif'],
      },
      colors: {
        // 🎨 สีเน้นเดียวของ SYNCROOM — น้ำเงินเข้ม #1D4ED8
        // PIRIvoice ใช้ `brand` (DEFAULT/strong/tint) — คงสเกลตัวเลขเดิมไว้
        // เพื่อไม่ให้คลาส brand-700 ที่มีอยู่ทั่วโปรเจกต์แตก
        brand: {
          DEFAULT: '#1D4ED8', // brand-700
          strong: '#1E40AF', // brand-800
          tint: '#EFF6FF', // brand-50
          50: '#EFF6FF',
          100: '#DBEAFE',
          200: '#BFDBFE',
          300: '#93C5FD',
          400: '#60A5FA',
          500: '#3B82F6',
          600: '#2563EB',
          700: '#1D4ED8',
          800: '#1E40AF',
          900: '#1E3A8A',
          950: '#172554',
        },
        // ── PIRIvoice neutrals ──────────────────────────────────────────
        // canvas = พื้นหลังแอป · surface = การ์ด/ชีต · line = เส้นบาง · ink = ตัวอักษร
        canvas: '#F7F7F8',
        surface: '#FFFFFF',
        line: '#E7E7EA',
        // คง `paper` ไว้เป็น alias เพื่อไม่ต้องแก้ทุกหน้าในคอมมิตเดียว
        paper: '#F7F7F8',
        ink: {
          DEFAULT: '#1F2328',
          1: '#1F2328',
          2: '#5F6368',
          3: '#6B6F76',
        },
        // สถานะ — ใช้ชื่อความหมาย ไม่ใช่ชื่อสี
        ok: colors.emerald,
        warn: colors.amber,
        danger: colors.red,
        info: colors.sky,
      },
      borderRadius: {
        // PIRIvoice: การ์ด 16 · คอนโทรล 12 · ชีต 24
        card: '16px',
        control: '12px',
        sheet: '24px',
      },
      boxShadow: {
        // เงาน้อยที่สุดเท่าที่จำเป็น — ใช้กับ FAB/ชีตเท่านั้น
        fab: '0 10px 30px -10px rgb(31 35 40 / 0.35)',
        sheet: '0 -16px 48px -24px rgb(31 35 40 / 0.35)',
      },
      fontSize: {
        // PIRIvoice type scale (line-height อยู่ในค่าเดียวกัน)
        caption: ['12px', '18px'],
        body: ['16px', '26px'],
        'title-m': ['18px', '28px'],
        'title-l': ['22px', '32px'],
      },
      maxWidth: {
        '8xl': '88rem',
      },
      transitionTimingFunction: {
        smooth: 'cubic-bezier(0.2, 0.8, 0.2, 1)',
      },
    },
  },
  plugins: [],
}
