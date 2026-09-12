# SYNCROOM — Design Contract ("Academic Ledger")

> **สัญญาการออกแบบฉบับบังคับ** — ทุกไฟล์ใน `frontend/src/` ต้องเป็นไปตามเอกสารนี้
> เป้าหมาย: ทั้งระบบหน้าตาเป็นภาษาเดียวกัน อ่านง่ายบนมือถือก่อน แล้วค่อยขยายขึ้นจอใหญ่
> ธีม: **กระดาษ stone + น้ำเงินเข้มสีเดียว + เส้นบาง hairline** — ไม่มี gradient / glass / glow

---

## 1. หลักการ 5 ข้อ (อ่านก่อนแตะโค้ด)

1. **สีเดียว** — น้ำเงินเข้ม `brand-700` (#1D4ED8) เป็นสีเน้นเดียวของทั้งระบบ ใช้เฉพาะกับ "สิ่งที่กดได้" และ "สิ่งที่ต้องดู"
2. **เส้นบาง ไม่ใช่เงา** — แบ่งส่วนด้วย `border-stone-200` (hairline) ไม่ใช่ `shadow-*` หรือ `backdrop-blur`
3. **แบน** — ไม่มี `bg-gradient-*`, `blur-[*]`, `backdrop-blur-*`, `shadow-{color}`, `rounded-[2rem]` เหลืออยู่ในระบบ
4. **มือถือคือพลเมืองชั้นหนึ่ง** — ออกแบบจากจอ 375px ขึ้นไป แล้วใช้ `sm:` / `lg:` เสริม
5. **ทุกสถานะต้องมีหน้าตา** — กำลังโหลด / ว่างเปล่า / ผิดพลาด ต้องมี UI ของตัวเอง ไม่ปล่อยจอขาว

---

## 2. Design Tokens

### สี — ใช้ได้เฉพาะคลาสเหล่านี้

| บทบาท | คลาส | หมายเหตุ |
|---|---|---|
| พื้นหลังหน้า | `bg-paper` | กำหนดที่ `body` แล้ว **ห้ามใส่ซ้ำที่ view** |
| พื้นการ์ด | `bg-white` | |
| พื้นรอง / แถบหัวตาราง | `bg-stone-50`, `bg-stone-50/70`, `bg-stone-100` | |
| เส้นคั่น | `border-stone-200` (หลัก), `border-stone-100` (เบา) | |
| ตัวอักษรหลัก | `text-stone-900` | ใช้กับหัวข้อ |
| ตัวอักษรรอง | `text-stone-600` / `text-stone-500` | เนื้อหา |
| ตัวอักษรเบา | `text-stone-400` | คำอธิบาย, placeholder |
| **สีเน้น** | `text-brand-700` / `bg-brand-700` / `bg-brand-50` / `border-brand-200` | |
| สำเร็จ | `emerald-*` | เฉพาะสถานะบวก |
| เตือน | `amber-*` | เฉพาะสถานะรอ |
| อันตราย | `red-*` | เฉพาะลบ/ผิดพลาด |
| ข้อมูล | `sky-*` | เฉพาะป้ายข้อมูล |

**ห้ามใช้เด็ดขาด:** `slate-*`, `gray-*`, `zinc-*`, `neutral-*` (ใช้ `stone-*` แทนทั้งหมด), `indigo-*`, `violet-*`, `purple-*`, `blue-*` (ใช้ `brand-*` แทนทั้งหมด)

### ฟอนต์

- `font-display` = **Anuphan** → หัวข้อทุกระดับ (`h1`, `h2`, ชื่อการ์ด, ตัวเลขใหญ่)
- ค่าเริ่มต้น (`font-sans`) = **Noto Sans Thai** → เนื้อหา, ปุ่ม, ตาราง
- ตัวเลขที่ต้องอ่านเทียบกันให้ใส่ `.num` (`tabular-nums`)

### ระยะห่าง

- ระยะห่างระหว่างการ์ด: `space-y-4` (มือถือ) → `sm:space-y-5`
- Padding ในการ์ด: `p-4 sm:p-5` (การ์ดเนื้อหา), `p-5 sm:p-6` (การ์ดฟอร์ม/แดชบอร์ด)
- ระยะขอบหน้า: จัดการโดย `MainLayout` แล้ว — view **ไม่ต้องใส่** `px-*` ระดับหน้าเอง

---

## 3. คลาสกลาง — ใช้ก่อนคิดสร้างเอง

ทั้งหมดนิยามใน `src/assets/main.css` `@layer components`

| คลาส | ใช้เมื่อ |
|---|---|
| `.page-card` | กล่องเนื้อหาทุกกล่อง → `rounded-2xl border border-stone-200 bg-white` |
| `.card-hover` | การ์ดที่กดได้ทั้งใบ → เติม `hover:-translate-y-px` |
| `.eyebrow` | ป้ายเล็กเหนือหัวข้อ (อังกฤษ พิมพ์ใหญ่) |
| `.page-title` | `h1` ของหน้า |
| `.page-lede` | คำโปรยใต้ `h1` |
| `.section-title` | หัวข้อย่อยในหน้า |
| `.btn-primary` | ปุ่มหลัก (น้ำเงินทึบ) — **1 ปุ่มต่อ 1 พื้นที่** |
| `.btn-ghost-ui` | ปุ่มรอง (ขาวขอบเทา) |
| `.btn-danger` | ปุ่มลบ |
| `.field` | `input` / `select` / `textarea` ทุกตัว |
| `.field-label` | ป้ายกำกับฟิลด์ |
| `.data-table` | ตาราง desktop (พร้อม `thead th` / `tbody td` / hover) |
| `.chip` | ป้ายสถานะเล็ก |
| `.num` | ตัวเลขเรียงหลักตรงกัน |
| `.page-wrap` | `mx-auto w-full max-w-7xl` |

### คอมโพเนนต์กลางใน `src/components/ui/`

| ไฟล์ | หน้าที่ |
|---|---|
| `PageHeader.vue` | หัวหน้าทุกหน้า: `eyebrow` → `title` → `description` + slot `#actions` |
| `StateBlock.vue` | สถานะ `error` (เส้นประ + ปุ่มลองใหม่) และ `empty` (เส้นประ + ช่องใส่ปุ่ม) |
| `SkeletonRows.vue` | โครงร่างระหว่างโหลด (`rows`, `height`) |

**ทุก view ที่มีหัวหน้าต้องใช้ `PageHeader`** — ห้ามเขียน `<h1>` เอง
**ทุก view ที่มี fetch ต้องมีครบ 3 สถานะ**: `SkeletonRows` → `StateBlock variant="error"` → `StateBlock variant="empty"`

---

## 4. รูปทรงหน้า استانดาร์ด

```vue
<script setup lang="ts">
import PageHeader from '@/components/ui/PageHeader.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader eyebrow="Academic Records" title="ทะเบียนนักเรียน"
                description="ข้อมูลนักเรียนทั้งหมดในห้องนี้">
      <template #actions>
        <button class="btn-primary"><i class="bi bi-plus-lg" /> เพิ่มนักเรียน</button>
      </template>
    </PageHeader>

    <SkeletonRows v-if="isLoading" :rows="6" height="h-16" />
    <StateBlock v-else-if="hasError" variant="error" @retry="load" />
    <StateBlock v-else-if="!items.length" variant="empty"
                title="ยังไม่มีนักเรียน" hint="เพิ่มนักเรียนคนแรกเพื่อเริ่มต้น" />

    <template v-else>
      <!-- เนื้อหา -->
    </template>
  </div>
</template>
```

> **ห้าม** ใส่ `max-w-*` / `mx-auto` / `p-*` ระดับหน้าอีก — ซ้อนกับ `MainLayout` แล้วจะเยื้อง

---

## 5. ตาราง ↔ การ์ดคู่กัน (กฎเหล็กของมือถือ)

ตาราง `data-table` **กว้างเกินจอมือถือเสมอ** → ต้องมีสองเรนเดอร์

```vue
<!-- 🖥️ Desktop: ตารางเต็ม -->
<div class="page-card hidden overflow-hidden lg:block">
  <div class="overflow-x-auto">
    <table class="data-table"> ... </table>
  </div>
</div>

<!-- 📱 มือถือ: การ์ดเรียงแนวตั้ง -->
<div class="space-y-2.5 lg:hidden">
  <div v-for="row in items" :key="row.id" class="page-card card-hover p-4">
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <p class="truncate font-bold text-stone-900">{{ row.name }}</p>
        <p class="mt-0.5 text-xs text-stone-500">เลขที่ {{ row.no }}</p>
      </div>
      <span class="chip shrink-0 bg-brand-50 text-brand-700">สถานะ</span>
    </div>
  </div>
</div>
```

**ป้ายหัวตารางบนมือถือ:** ถ้าตารางเล็กล้นน้อย ใช้ `<div class="overflow-x-auto">` ครอบได้

---

## 6. กฎมือถือ (ต้องทำทุกหน้า)

| กฎ | วิธีทำ |
|---|---|
| ข้อความยาวต้องตัด ไม่ดันจอ | `min-w-0` ที่กล่องพ่อ + `truncate` ที่ตัวข้อความ |
| องค์ประกอบต้องไม่หดตัว | `shrink-0` ที่ avatar / ป้าย / ปุ่มกลม |
| ลิสต์ยาวจัดกลางด้วย flex | `flex-1` + `min-w-0` ทุกชั้น |
| ปุ่มต้องรู้สึกว่าโดนกด | `active:scale-[0.97]` (มีใน `.btn-*` แล้ว) |
| แถวที่แตะได้ทั้งแถว | ห่อด้วย `RouterLink` / `<button class="w-full text-left">` |
| เลื่อนในชีตไม่ลากหน้าหลัง | `overscroll-contain` ที่กล่อง scroll |
| รองรับรอยบาก iPhone | `pb-[calc(env(safe-area-inset-bottom)+…)]` — `MainLayout` จัดให้แล้ว |
| `input` ไม่ทำให้ iOS ซูม | `main.css` ตั้ง `16px` ให้แล้ว — **อย่า override ด้วย `text-xs`/`text-sm` บน input บนมือถือ** |
| พื้นที่กดขั้นต่ำ | 44×44px (`h-11 w-11` ขึ้นไป สำหรับปุ่มกลม) |

---

## 7. ชุดป้ายสถานะ (chip)

```vue
<span class="chip bg-emerald-50 text-emerald-700"><i class="bi bi-check-circle-fill" /> ชำระแล้ว</span>
<span class="chip bg-amber-50 text-amber-700"><i class="bi bi-clock-fill" /> ค้างชำระ</span>
<span class="chip bg-red-50 text-red-700"><i class="bi bi-x-circle-fill" /> ยกเลิก</span>
<span class="chip bg-sky-50 text-sky-700"><i class="bi bi-info-circle-fill" /> ข้อมูล</span>
<span class="chip bg-stone-100 text-stone-600">ทั่วไป</span>
<span class="chip bg-brand-50 text-brand-700">บทบาท</span>
```

**ค่าเงิน** ต้องใช้ `.num` + `toLocaleString('th-TH')` + `฿` — ห้ามปล่อยเป็น float ดิบ
**วันที่/เวลา** ต้องจัดรูปแบบไทย + `Asia/Bangkok` เสมอ

---

## 8. SweetAlert2 — ธีมเดียวทั้งระบบ

`Swal.fire` เป็นช่องทางแจ้งเตือนเดียว (ห้าม `alert()` / toast)

```ts
// แจ้งผล
Swal.fire({ icon: 'success', title: 'บันทึกแล้ว', text: '...', confirmButtonColor: '#1d4ed8' })

// ยืนยันลบ
const ok = await Swal.fire({
  icon: 'warning', title: 'ยืนยันการลบ?', text: 'กู้คืนไม่ได้',
  showCancelButton: true, confirmButtonText: 'ลบ', cancelButtonText: 'ยกเลิก',
  confirmButtonColor: '#dc2626', cancelButtonColor: '#78716c',
})
if (!ok.isConfirmed) return

// กำลังโหลด
Swal.fire({ title: 'กำลังโหลดข้อมูล...', allowOutsideClick: false, didOpen: () => Swal.showLoading() })
```

**ห้ามใส่ `customClass.popup` เป็น `rounded-[2rem] shadow-2xl`** — ปล่อยค่าเริ่มต้น หรือใช้ `rounded-2xl` เท่านั้น
ถ้าใส่ HTML เอง ให้ใช้ inline style (Swal ไม่ผ่าน Tailwind JIT) — ฟอนต์ใช้ `font-family:Anuphan`, สีปุ่ม `#1d4ed8`

---

## 9. ฟอร์ม

```vue
<div class="page-card p-5 sm:p-6">
  <form class="space-y-4" @submit.prevent="submit">
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <div>
        <label class="field-label" for="firstName">ชื่อ</label>
        <input id="firstName" v-model="form.firstName" class="field" required />
      </div>
    </div>

    <!-- ปุ่ม: มือถือเต็มความกว้าง -->
    <div class="flex flex-col-reverse gap-2 border-t border-stone-100 pt-4 sm:flex-row sm:justify-end">
      <button type="button" class="btn-ghost-ui" @click="router.back()">ยกเลิก</button>
      <button type="submit" class="btn-primary" :disabled="isSaving">บันทึก</button>
    </div>
  </form>
</div>
```

- ฟิลด์ที่ผิด → `class="field border-red-300 focus:ring-red-500/15"` + `<p class="mt-1 text-xs font-bold text-red-600">`
- ฟิลด์ที่ห้ามแก้ → `disabled` (`.field` จัดสีให้แล้ว)
- ปุ่ม submit ต้อง `:disabled="isSaving"` และแสดง spinner ระหว่างบันทึก

---

## 10. สถิติ / KPI

```vue
<div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
  <div class="page-card p-4 sm:p-5">
    <p class="text-[11px] font-bold uppercase tracking-[0.16em] text-stone-400">นักเรียนทั้งหมด</p>
    <p class="font-display num mt-2 text-2xl font-bold text-stone-900 sm:text-3xl">42</p>
    <p class="mt-1 text-xs font-bold text-emerald-600"><i class="bi bi-arrow-up-short" /> +3 เดือนนี้</p>
  </div>
</div>
```

- ตัวเลขใหญ่ใช้ `font-display` + `.num`
- **ห้าม** การ์ด KPI พื้นหลังทึบสี / gradient — พื้นขาว + เส้นขอบ เสมอ
- ไฮไลต์ได้ด้วยแถบซ้าย: `<div class="page-card p-4 border-s-4 border-s-brand-700">`

---

## 11. ช่องว่าง / ไอคอน

- ไอคอนจาก **bootstrap-icons** เท่านั้น: `<i class="bi bi-xxx" aria-hidden="true" />`
- ไอคอนสื่อความหมายเดี่ยว ๆ ต้องมี `aria-label` ที่ปุ่มพ่อ
- ไอคอนไม่ต้องมีขนาดเกิน `text-2xl` ยกเว้นสถานะว่าง (`text-3xl`)
- ไอคอนที่อยู่ในปุ่ม `.btn-*` ไม่ต้องใส่สีเอง — รับสีจากปุ่ม

---

## 12. Checklist ก่อนส่งงาน (ตรวจทุกไฟล์)

- [ ] ไม่มี `slate-` / `gray-` / `indigo-` / `violet-` / `blue-` / `zinc-` / `neutral-` เหลืออยู่
- [ ] ไม่มี `bg-gradient-`, `from-`, `via-`, `to-`, `backdrop-blur`, `blur-[`, `shadow-{color}`
- [ ] ไม่มี `rounded-[2rem]` / `rounded-[2.5rem]` (สูงสุดที่ใช้คือ `rounded-3xl` เฉพาะ bottom sheet)
- [ ] ไม่มี `animate-bounce` / `animate-ping` / `animate-pulse` (ยกเว้น `SkeletonRows`)
- [ ] ไม่มี `alert(` / `toast` — ใช้ `Swal.fire` เท่านั้น
- [ ] ไม่มี `any` ใน TypeScript
- [ ] view ไม่เรียก `api.get/post` ตรง — ผ่าน `services/` เท่านั้น
- [ ] มีครบ 3 สถานะ: โหลด / ว่าง / ผิดพลาด
- [ ] ทุกหน้ามี `PageHeader`
- [ ] ตารางมีเวอร์ชันการ์ดสำหรับมือถือ
- [ ] ข้อความยาวมี `min-w-0` + `truncate`
- [ ] ไม่มี `<style>` ที่ไม่จำเป็น — ใช้ Tailwind เป็นหลัก
- [ ] ไม่มี inline `style=""` ยกเว้นค่าที่ Tailwind ทำไม่ได้ (เช่น `env(safe-area-inset-*)`)

---

## 13. สิ่งที่ห้ามแตะ

- `src/assets/main.css` — token กลาง แก้แล้วกระทบทั้งระบบ
- `tailwind.config.js` — ชุดสี/ฟอนต์กลาง
- `src/services/*` — นอกจากจะแก้ type ให้ถูกต้องขึ้น
- logic การเรียก API, สิทธิ์ RBAC, เงื่อนไขการนำทาง — **เปลี่ยนได้แค่หน้าตา ห้ามเปลี่ยนพฤติกรรม**
