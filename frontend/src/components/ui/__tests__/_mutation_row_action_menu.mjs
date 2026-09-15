/**
 * 🧬 Mutation testing สำหรับ `RowActionMenu.vue`
 *
 * ทำไมต้องมีไฟล์นี้: เทสต์ถดถอยที่ "ผ่าน" ไม่ได้พิสูจน์ว่ามันจับบั๊กได้ — ต้อง
 * **ถอดการป้องกันออกแล้วเห็นเทสต์ล้มจริง** (docs/rules/testing.md บังคับ;
 * บทเรียน docs/skills.md) ตัวนี้คือคู่ขนานฝั่ง frontend ของ
 * `backend/tests/_mutation_jsonb_meta.py`
 *
 * วิธีรัน (จากโฟลเดอร์ frontend):
 *     node src/components/ui/__tests__/_mutation_row_action_menu.mjs
 *
 * ⚠️ บทเรียนที่ทำให้ไฟล์นี้ถูกเขียนใหม่ (2026-09-15): เวอร์ชันแรกมี 14 mutation และ
 * รายงาน "ถูกจับ 14/14 · รอด 0" — แต่ผู้รีวิวพิสูจน์ว่า **รายการนั้นครอบเฉพาะสาขาที่
 * เทสต์เขียนไว้** ส่วน positioning / keyboard / resize ซึ่งเป็นเหตุผลที่คอมโพเนนต์นี้
 * มีอยู่ กลับไม่มี mutation สักตัว ⇒ "14/14" ไม่ได้แปลว่าครอบคลุม
 * **ตัวเลขนี้วัด "รายการที่เราเลือกทดสอบ" ไม่ได้วัด "ความครอบคลุม"** — ห้ามอ่านเกินนั้น
 *
 * สคริปต์จะ (1) แก้ RowActionMenu.vue ทีละ mutation (2) รัน spec ที่เกี่ยวข้อง
 * (3) คืนไฟล์เดิมเสมอแม้ถูก Ctrl-C (4) แยกผลเป็น 3 กองที่ *ไม่* ปนกัน:
 *     รอด = เทสต์จับไม่ได้จริง (ต้องแก้เทสต์) · anchor ไม่ชัด = เครื่องมือตกขบวน
 *     (ต้องแก้ mutation) · คอมไพล์ไม่ผ่าน = วัดไม่ได้ว่าเทสต์จับได้ไหม
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { dirname, resolve } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const COMPONENT = resolve(HERE, '..', 'RowActionMenu.vue')
const SPEC = resolve(HERE, 'RowActionMenu.spec.ts')

/** (ชื่อ, ค้นหา, แทนด้วย) — แต่ละอันคือ "ถอดการป้องกันออก" หรือ "พังแบบใหม่" */
const MUTATIONS = [
  // ── การหลุดออกจาก overflow (เหตุผลที่ต้องมี Teleport) ──────────────────────────
  [
    '🔴 ถอด Teleport — เมนูกลับไปอยู่ใต้พ่อที่ overflow (บั๊ก clip ที่เทสต์ต้องจับ)',
    '<Teleport to="body">',
    '<Teleport to="body" disabled>',
  ],
  [
    'แผงไม่เป็น fixed ⇒ ยังถูก overflow ของพ่อ clip',
    'fixed z-[80] max-h-[calc(100vh_-_1.5rem)] overflow-y-auto',
    'absolute z-[80] max-h-[calc(100vh_-_1.5rem)] overflow-y-auto',
  ],

  // ── การวางตำแหน่ง (เดิมไม่มี mutation เลย = จุดบอดที่ใหญ่ที่สุด) ──────────────────
  [
    'ไม่ผูก :style เลย ⇒ แผงไม่ถูกวางตำแหน่ง (อยู่มุมซ้ายบนเสมอ)',
    ':style="panelStyle"',
    ':style="{ top: \'0px\', left: \'0px\' }"',
  ],
  [
    'ถอดการหนีบขอบบน/ล่าง ⇒ จอเตี้ยแล้วแผงหลุดขอบบน ไอเทมที่ถูกตัดกดไม่ได้',
    '    top: `${Math.min(Math.max(top, EDGE_GAP), maxTop)}px`,',
    '    top: `${top}px`,',
  ],
  [
    'ถอดการหนีบขอบขวา ⇒ ปุ่มชิดขวาแล้วแผงล้นออกนอกจอ',
    'const left = Math.min(Math.max(rect.right - PANEL_WIDTH, EDGE_GAP), maxLeft);',
    'const left = Math.max(rect.right - PANEL_WIDTH, EDGE_GAP);',
  ],
  [
    'ค่าคงที่ความกว้างแผงไม่ตรงกับที่คำนวณ (ค่าที่วาดกับค่าที่คำนวณคนละที่)',
    'const PANEL_WIDTH = 208;',
    'const PANEL_WIDTH = 240;',
  ],
  [
    'ถอดเพดานความสูงของแผง ⇒ แผงสูงเกินจอแล้วไอเทมท้าย ๆ กดไม่ได้',
    ' max-h-[calc(100vh_-_1.5rem)]',
    '',
  ],
  [
    'เปลี่ยน overflow-y-auto เป็น overflow-hidden ⇒ เพดานความสูงทำให้ไอเทมถูกตัดกดไม่ได้',
    'overflow-y-auto overscroll-contain',
    'overflow-hidden overscroll-contain',
  ],
  [
    'ถอด overscroll-contain ⇒ การเลื่อนในแผงลามไปเลื่อนหน้าข้างหลัง',
    'overflow-y-auto overscroll-contain',
    'overflow-y-auto',
  ],
  [
    'ฉาก backdrop ไม่มี z-index ⇒ ไปอยู่ใต้เนื้อหาอื่น คลิกนอกไม่ติด',
    'class="fixed inset-0 z-[70]"',
    'class="fixed inset-0"',
  ],

  // ── คีย์บอร์ด ─────────────────────────────────────────────────────────────────
  [
    '🔴 ลูกศรไม่เช็คโฟกัส ⇒ ยึดลูกศรของทั้งหน้าและกระชากโฟกัสจากช่องอื่นเข้ามา',
    '  if (!ownsFocus()) return;\n\n  const nodes = focusableNodes();',
    '  const nodes = focusableNodes();',
  ],
  [
    '🔴 Esc บังคับให้โฟกัสอยู่ที่เมนู ⇒ ผู้ใช้ Safari (คลิกแล้วโฟกัสไม่ย้าย) ปิดเมนูด้วย Esc ไม่ได้',
    "  if (event.key === 'Escape') {",
    "  if (event.key === 'Escape' && ownsFocus()) {",
  ],
  [
    'ถอดการดัก Tab ⇒ เมนูค้างเปิดพร้อมฉากหลังที่บล็อกทั้งหน้า',
    "  if (event.key === 'Tab') {",
    '  if (false) {',
  ],
  [
    'ถอดการนำทางด้วยลูกศรทั้งหมด ⇒ ใช้คีย์บอร์ดเลือกไอเทมไม่ได้',
    "  if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;",
    '  return;',
  ],
  [
    'ArrowUp กลายเป็น ArrowDown ⇒ ทิศทางลูกศรผิด',
    "  const step = event.key === 'ArrowDown' ? 1 : -1;",
    '  const step = 1;',
  ],
  [
    '🔴 ถอดการกัน current = -1 ⇒ ArrowUp จากปุ่มไปไอเทมรองสุดท้าย ไม่ใช่สุดท้าย',
    '  const next =\n    current === -1\n',
    '  const next =\n    false\n',
  ],
  [
    '🔴 ไม่กรองไอเทมที่ disable ออกจากเส้นทางลูกศร ⇒ ลูกศรตันที่ไอเทมนั้น',
    '.filter((node) => !(node as HTMLButtonElement).disabled);',
    '.filter(() => true);',
  ],
  [
    'เปิดด้วยคีย์บอร์ดไม่โฟกัสไอเทมแรก ⇒ คนใช้คีย์บอร์ดไม่รู้ว่าเมนูเปิดแล้ว',
    '    if (focusFirstItem) focusableNodes()[0]?.focus();',
    '    if (false) focusableNodes()[0]?.focus();',
  ],
  [
    'เปิดด้วยเมาส์ก็กระชากโฟกัสเข้าแผง ⇒ จอกระตุกบนมือถือ',
    'open(event.detail === 0);',
    'open(true);',
  ],
  [
    'เปิดด้วยคีย์บอร์ดไม่โฟกัสไอเทมแรก (กลับทาง)',
    'open(event.detail === 0);',
    'open(false);',
  ],
  [
    'เลือกไอเทมด้วยคีย์บอร์ดแล้วไม่คืนโฟกัส ⇒ โฟกัสตกไปที่ <body> ทั้งหน้า',
    "  closeAndRestoreFocus();\n  emit('select', item.key);",
    "  close();\n  emit('select', item.key);",
  ],

  // ── วงจรชีวิต / listener ───────────────────────────────────────────────────────
  [
    '🔴 ถอด listener ของ scroll โดยลืม capture flag ⇒ ไม่ถอดจริง รั่วสะสมทุกครั้งที่เข้า-ออกหน้า',
    "  window.removeEventListener('scroll', close, true);",
    "  window.removeEventListener('scroll', close);",
  ],
  [
    'ไม่ผูก listener ของ resize เลย ⇒ แผงลอยค้างคนละที่กับปุ่มหลังย่อ/ขยายจอ',
    "  window.addEventListener('resize', close);\n",
    '',
  ],
  [
    'ไม่ผูก listener ของ scroll เลย ⇒ แผงลอยค้างคนละที่กับปุ่มหลังเลื่อนจอ',
    "  window.addEventListener('scroll', close, true);\n",
    '',
  ],
  [
    'ไม่ถอด listener ตอน unmount ⇒ รั่วสะสมทุกครั้งที่เข้า-ออกหน้า',
    'onBeforeUnmount(close);',
    '',
  ],

  // ── การเลือกไอเทม ──────────────────────────────────────────────────────────────
  [
    'เลือกไอเทมแล้วไม่ส่ง @select ออกไป',
    "  closeAndRestoreFocus();\n  emit('select', item.key);",
    '  closeAndRestoreFocus();',
  ],
  [
    'เลือกไอเทมแล้วไม่ปิดเมนู',
    "  closeAndRestoreFocus();\n  emit('select', item.key);",
    "  emit('select', item.key);",
  ],
  [
    'ถอด guard disabled ⇒ ไอเทมที่ปิดอยู่ยิง event ได้',
    'const select = (item: RowActionItem) => {\n  if (item.disabled) return;',
    'const select = (item: RowActionItem) => {',
  ],
  [
    'ฉากรับคลิกนอกไม่ปิดเมนู',
    '<div v-if="isOpen" data-menu-backdrop class="fixed inset-0 z-[70]" @click="close"></div>',
    '<div v-if="isOpen" data-menu-backdrop class="fixed inset-0 z-[70]"></div>',
  ],
  [
    'ไอเทมที่มี `to` เรนเดอร์เป็นปุ่มธรรมดา (ลิงก์แก้ไขพัง)',
    '          <RouterLink\n            v-if="item.to"',
    '          <RouterLink\n            v-if="false"',
  ],

  // ── DESIGN.md (สี / พื้นที่กด / a11y) ──────────────────────────────────────────
  [
    '🔴 ไอเทมกดได้เตี้ยกว่า 44px (py-2.5 = 40px) ⇒ ต่ำกว่าพื้นที่กดขั้นต่ำที่ DESIGN.md §2 กำหนด',
    'px-4 py-3 text-left text-sm font-bold',
    'px-4 py-2.5 text-left text-sm font-bold',
  ],
  [
    'สีตัวอักษรของไอเทมที่ disable หลุดชุดที่ DESIGN.md §2 อนุญาต + คอนทราสต์อ่านไม่ออก',
    "'cursor-not-allowed text-stone-400'",
    "'cursor-not-allowed text-stone-300'",
  ],
  [
    'แยกโทน danger ออก ⇒ ปุ่มลบไม่แดง (ผู้ใช้แยกไม่ออกว่าอันไหนทำลายข้อมูล)',
    "      ? 'text-red-600 hover:bg-red-50'",
    "      ? 'text-stone-700 hover:bg-stone-50'",
  ],
  [
    'aria-expanded ค้างเป็น false ตลอด ⇒ screen reader ไม่รู้ว่าเมนูเปิดอยู่',
    ':aria-expanded="isOpen"',
    ':aria-expanded="false"',
  ],
  [
    'ถอด aria-controls ⇒ ความสัมพันธ์ปุ่ม↔แผงขาด (แผงถูก Teleport แยกออกไปแล้ว)',
    '    :aria-controls="isOpen ? panelId : undefined"\n',
    '',
  ],
  [
    'ถอด id ของแผง ⇒ aria-controls ชี้เป้าที่ไม่มีอยู่',
    '        :id="panelId"\n',
    '',
  ],
  [
    'ถอดชื่อ accessible name ของแผง',
    '        :aria-label="label"\n',
    '',
  ],
  [
    'ถอด role="menu" ⇒ ไม่ถูกประกาศเป็นเมนูให้ assistive tech',
    '        role="menu"\n',
    '',
  ],
  [
    'ถอด @click.stop ที่ปุ่ม ⇒ คลิกปุ่มแล้วไปกระตุ้น handler ของแถว/การ์ดข้างนอกด้วย',
    '@click.stop="toggle"',
    '@click="toggle"',
  ],
]

const original = readFileSync(COMPONENT, 'utf8')

// 🔴 สำรองต้นฉบับไว้นอก repo — ระหว่างรันสคริปต์ ไฟล์จริง "ถูกแก้โดยเจตนา" เสมอ
//    ถ้าถูกฆ่าในช่วงนั้น (Ctrl-C, TaskStop, เครื่องดับ) handler อาจไม่ได้ทำงาน
//    ⇒ ไฟล์จะค้างอยู่ในสภาพ mutated และ **กู้ไม่ได้เพราะยังไม่ถูก commit**
//    (เกิดจริง 2026-09-15: TaskStop ฆ่า process ระหว่างสคริปต์กำลังรัน vitest
//     แล้ว RowActionMenu.vue ค้างที่ mutation ':style' — กู้ด้วยการเทียบ anchor)
const BACKUP = resolve(tmpdir(), '_RowActionMenu.original.vue')
writeFileSync(BACKUP, original, 'utf8')
console.log(`📦 สำรองต้นฉบับไว้ที่ ${BACKUP} (ถ้าไฟล์จริงค้าง mutated ให้คัดลอกจากไฟล์นี้)`)

const survived = []
const anchorMismatch = []
const notCompiling = []

const restore = () => writeFileSync(COMPONENT, original, 'utf8')
for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => {
    restore()
    console.log(`\n⚠️  ถูกสัญญาณ ${sig} — คืนไฟล์ RowActionMenu.vue แล้ว`)
    process.exit(130)
  })
}

/** คืน (outcome, สรุปบรรทัดท้าย) — outcome ∈ caught | survived | broken | harness */
const runSpec = () => {
  // ⚠️ ห้ามใส่ `--reporter=basic` — vitest 4 ไม่มี reporter นี้แล้ว และจะตีความ
  //    เป็น **path ของ reporter ที่ผู้เขียนเอง** ⇒ "Startup Error: Failed to load
  //    custom Reporter from basic" ทุกครั้ง ⇒ เครื่องมือรายงาน 0/14 หลอก ๆ
  //    (เจอจริงตอนรันครั้งแรก 2026-09-15 — guard ข้างล่างจับได้จึงไม่หลอกว่า "จับได้ครบ")
  const proc = spawnSync('npx', ['vitest', 'run', SPEC], {
    cwd: resolve(HERE, '..', '..', '..', '..'),
    encoding: 'utf8',
    env: { ...process.env, CI: 'true', NO_COLOR: '1' },
  })
  const out = `${proc.stdout || ''}${proc.stderr || ''}`
  const lines = out.split('\n').filter((l) => l.trim())
  const summary =
    lines.find((l) => /Tests\s+.*(passed|failed)/.test(l)) ||
    lines[lines.length - 1] ||
    `(ไม่มี output, exit=${proc.status})`

  // เครื่องมือ/การเก็บเทสต์พัง ⇒ ห้ามนับเป็นการจับ
  const harnessBroken =
    /Startup Error|No test files found|Failed to load|Failed to load custom Reporter/.test(out) ||
    !/Tests\s+/.test(out)
  if (harnessBroken) return { outcome: 'harness', summary }

  // mutation ทำให้ไฟล์คอมไพล์ไม่ผ่าน ⇒ "เทสต์ล้ม" เกิดจาก parse ไม่ใช่จากเทสต์จับได้
  // ⇒ ต้องแยกออก ไม่ให้นับเป็นความสำเร็จของเทสต์
  if (/Transform failed|Pre-transform error|Failed to parse|Parse failure/.test(out)) {
    return { outcome: 'broken', summary }
  }

  const failedMatch = out.match(/Tests\s+(\d+) failed/)
  const caught = proc.status !== 0 || (failedMatch !== null && Number(failedMatch[1]) > 0)
  return { outcome: caught ? 'caught' : 'survived', summary }
}

console.log(`เทสต์เป้าหมาย 1 ไฟล์ · mutation ${MUTATIONS.length} แบบ`)
console.log('='.repeat(100))

try {
  for (const [name, find, replace] of MUTATIONS) {
    const hits = original.split(find).length - 1
    if (hits !== 1) {
      // ⚠️ anchor ไม่ชัด = "เครื่องมือตกขบวน" ไม่ใช่ "เทสต์จับไม่ได้" — คนละเรื่องกัน
      //    เดิมสองเรื่องนี้ถูกโยนรวมกันแล้วรายงานเป็น "รอด" ซึ่งทำให้อ่านผิดได้
      console.log(`⚠️  ข้าม: ${name}`)
      console.log(`${' '.repeat(4)}anchor เจอ ${hits} ครั้ง (ต้องเป็น 1) — mutation ไม่ได้ถูกทดสอบจริง`)
      anchorMismatch.push(name)
      continue
    }
    writeFileSync(COMPONENT, original.replace(find, replace), 'utf8')
    // คืนไฟล์ทันทีหลังวัดเสร็จ ⇒ ช่วงที่ไฟล์ถูกแก้สั้นที่สุด (เฉพาะระหว่างรัน vitest)
    let result
    try {
      result = runSpec()
    } finally {
      restore()
    }
    const { outcome, summary } = result
    const badge =
      outcome === 'caught'
        ? '✅ ถูกจับ'
        : outcome === 'survived'
          ? '❌ รอด (เทสต์จับไม่ได้!)'
          : outcome === 'broken'
            ? '🧨 คอมไพล์ไม่ผ่าน (วัดไม่ได้)'
            : '⚠️  เครื่องมือเทสต์พัง'
    console.log(`${badge}  ${name}`)
    console.log(`${' '.repeat(4)}${summary.trim()}`)
    if (outcome === 'survived') survived.push([name, summary.trim()])
    else if (outcome === 'broken') notCompiling.push([name, summary.trim()])
    else if (outcome === 'harness')
      survived.push([name, `⚠️ เครื่องมือเทสต์พัง (ไม่ใช่เทสต์จับได้) — ${summary}`])
  }
} finally {
  restore()
  console.log('='.repeat(100))
  console.log('คืนไฟล์ RowActionMenu.vue เรียบร้อยแล้ว')
}

const caughtCount = MUTATIONS.length - survived.length - anchorMismatch.length - notCompiling.length
console.log(
  `\nสรุป: ถูกจับ ${caughtCount}/${MUTATIONS.length} · รอด ${survived.length}` +
    ` · anchor ไม่ชัด ${anchorMismatch.length} · คอมไพล์ไม่ผ่าน ${notCompiling.length}`,
)
for (const [name, summary] of survived) console.log(`  ❌ ${name} — ${summary}`)
for (const name of anchorMismatch) console.log(`  ⚠️  anchor ไม่ชัด: ${name}`)
for (const [name, summary] of notCompiling) console.log(`  🧨 ${name} — ${summary}`)
console.log(
  '\n⚠️  ตัวเลขนี้แปลว่า "mutation ที่เลือกมาถูกจับกี่ตัว" ไม่ได้แปลว่า "เทสต์ครอบคลุมครบ"',
)
process.exit(survived.length || anchorMismatch.length || notCompiling.length ? 1 : 0)
