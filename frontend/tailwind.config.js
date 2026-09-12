/** @type {import('tailwindcss').Config} */
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
        // ใช้ brand-* เท่านั้น ห้าม hardcode hex ในเทมเพลต
        brand: {
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
        // กระดาษและหมึก (โทน stone)
        paper: '#FAFAF9',
        ink: '#1C1917',
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
