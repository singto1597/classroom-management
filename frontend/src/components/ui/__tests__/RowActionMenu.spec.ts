import { describe, expect, it, vi, afterEach } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'

import RowActionMenu, { type RowActionItem } from '@/components/ui/RowActionMenu.vue'

/**
 * 🗂️ `RowActionMenu` — เมนูจุด 3 จุดสำหรับ "การกระทำต่อแถว"
 *
 * ⚠️ บทเรียนที่ทำให้ไฟล์นี้ถูกเขียนใหม่ (2026-09-15): เวอร์ชันแรกมี 11 เทสต์และ mutation
 * "14/14 ถูกจับ · รอด 0" — แต่ผู้รีวิวจับได้ว่า **mutation list ครอบเฉพาะสาขาที่เทสต์เขียนไว้**
 * ส่วน positioning / keyboard / resize ซึ่งเป็นเหตุผลที่คอมโพเนนต์นี้มีอยู่ กลับ **ไม่มี
 * mutation สักตัว** ⇒ ตัวเลข 14/14 ไม่ได้แปลว่าครอบคลุม ห้ามอ่านเป็นความมั่นใจ
 *
 * บั๊กที่เทสต์ชุดนี้กันไว้:
 *  1. 🔴 **แผงถูก clip หาย** — ตารางการเงินทุกหน้าครอบ `overflow-hidden` + `overflow-x-auto`
 *     (DESIGN.md §5 บังคับ) ⇒ เมนูแบบ `absolute` จะถูกตัดทั้งแผงโดยไม่มีอะไรฟ้อง
 *  2. 🔴 **แผงหลุดขอบจอ** — จอเตี้ย (มือถือแนวนอน) ทำให้แผงที่พลิกขึ้นบนล้นออกด้านบน
 *     และเพราะแผง clip ที่ขอบตัวเอง ไอเทมที่ถูกตัดจะกดไม่ได้
 *  3. 🔴 **ตัวดักคีย์ยึดทั้งหน้า** — listener ผูกที่ `window` (จำเป็น เพราะแผงถูก Teleport)
 *     ถ้าไม่เช็คโฟกัส ลูกศร/ Esc จะถูกเมนูของแถวหนึ่งจับไปทั้งหน้า
 *  4. **listener รั่ว** — ต้องถอด (type, fn, capture) ตัวเดิมจริง ไม่ใช่แค่ชื่อ
 *  5. **ปุ่มที่ทำลายข้อมูล** ต้องไม่ยิง event เมื่อถูก disable และต้องไม่ขึ้นเป็นเป้าของลูกศร
 */

// RouterLink เป็นของ vue-router — เทสต์นี้สนใจ "เรนเดอร์เป็นลิงก์" ไม่ใช่การนำทาง
const RouterLinkStub = defineComponent({
  props: { to: { type: [String, Object], required: true } },
  setup(props, { slots }) {
    return () =>
      h(
        'a',
        { href: String(props.to), 'data-menu-item': '', role: 'menuitem' },
        slots.default?.(),
      )
  },
})

const ITEMS: RowActionItem[] = [
  { key: 'toggle', label: 'ติ๊กเสร็จ', icon: 'bi-check-circle-fill' },
  { key: 'edit', label: 'แก้ไข', icon: 'bi-pencil-square', to: '/tasks/7/edit' },
  { key: 'delete', label: 'ลบงาน', icon: 'bi-trash3-fill', tone: 'danger' },
]

/** ไอเทมกลางถูก disable — ใช้พิสูจน์ว่าลูกศร "ข้าม" ไอเทมที่โฟกัสไม่ได้ */
const ITEMS_MIDDLE_DISABLED: RowActionItem[] = [
  { key: 'toggle', label: 'ติ๊กเสร็จ', icon: 'bi-check-circle-fill' },
  { key: 'edit', label: 'แก้ไข', icon: 'bi-pencil-square', disabled: true },
  { key: 'delete', label: 'ลบงาน', icon: 'bi-trash3-fill', tone: 'danger' },
]

const LABEL = 'ตัวเลือกจัดการงาน'
const VIEWPORT_W = 1024
const VIEWPORT_H = 768

let wrapper: VueWrapper | null = null
const hosts: HTMLElement[] = []

/** สร้างโฮสต์ที่มีพ่อเป็น overflow-hidden + overflow-x-auto เหมือนตารางจริง */
const createClippingHost = (): HTMLElement => {
  const host = document.createElement('div')
  host.className = 'page-card overflow-hidden'
  const scroller = document.createElement('div')
  scroller.className = 'overflow-x-auto'
  host.appendChild(scroller)
  document.body.appendChild(host)
  hosts.push(host)
  return scroller
}

const mountMenu = (items: RowActionItem[] = ITEMS, attachTo?: HTMLElement) => {
  wrapper = mount(RowActionMenu, {
    props: { items, label: LABEL },
    attachTo: attachTo ?? document.body,
    global: { stubs: { RouterLink: RouterLinkStub } },
  })
  return wrapper
}

const trigger = () => wrapper!.get('button[aria-haspopup="menu"]')
const triggerEl = () => trigger().element as HTMLElement
const menuInBody = () => document.body.querySelector<HTMLElement>('[role="menu"]')
const menuItems = () => Array.from(document.body.querySelectorAll<HTMLElement>('[role="menuitem"]'))
const activeText = () => (document.activeElement as HTMLElement | null)?.textContent?.trim()

/**
 * ⚠️ ต้องยิงเองแทน `trigger('click')` เพราะ VTU สร้าง MouseEvent ที่ `detail` เป็น 0 เสมอ
 * ซึ่งคอมโพเนนต์ตีความเป็น "เปิดด้วยคีย์บอร์ด" ⇒ โฟกัสจะย้ายเข้าไอเทมแรก
 * ทำให้ทดสอบเส้นทาง "เปิดด้วยเมาส์" (โฟกัสยังอยู่ที่ปุ่ม) ไม่ได้
 */
const clickTrigger = async (detail: number) => {
  triggerEl().dispatchEvent(new MouseEvent('click', { bubbles: true, detail }))
  await nextTick()
}

const press = async (key: string) => {
  window.dispatchEvent(new KeyboardEvent('keydown', { key, cancelable: true, bubbles: true }))
  await nextTick()
}

/**
 * ดึงค่า z-index จากคลาส arbitrary ของ Tailwind เช่น `z-[70]` → 70 (คืน null ถ้าไม่มี)
 * ⚠️ ตรวจแบบ "โทเคนทั้งคำ" ไม่ใช่ `toContain('z-')` ซึ่งผ่านได้กับคลาสอื่นที่ไม่ใช่ z-index เลย
 */
const zIndexOf = (el: HTMLElement): number | null => {
  const cls = Array.from(el.classList).find((c) => /^z-\[\d+\]$/.test(c))
  return cls ? Number(cls.slice(3, -1)) : null
}

const setViewport = (width: number, height: number) => {
  Object.defineProperty(window, 'innerWidth', { value: width, configurable: true, writable: true })
  Object.defineProperty(window, 'innerHeight', { value: height, configurable: true, writable: true })
}

/** บังคับพิกัดของปุ่ม (jsdom คืน 0 ทั้งหมดถ้าไม่ stub) */
const stubTriggerRect = (top: number, right: number, height = 44) => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    x: right - 44,
    y: top,
    top,
    right,
    bottom: top + height,
    left: right - 44,
    width: 44,
    height,
    toJSON: () => ({}),
  } as DOMRect)
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  hosts.splice(0).forEach((h) => h.remove())
  document.body.innerHTML = ''
  setViewport(VIEWPORT_W, VIEWPORT_H)
  vi.restoreAllMocks()
})

describe('RowActionMenu', () => {
  describe('ปุ่มและสถานะเริ่มต้น', () => {
    it('เริ่มต้นยังไม่เปิด — และปุ่มบอกสถานะด้วย aria ให้ screen reader รู้', () => {
      mountMenu()
      expect(trigger().attributes('aria-expanded')).toBe('false')
      expect(trigger().attributes('aria-haspopup')).toBe('menu')
      // ไอคอนต้องไม่ถูกอ่านออกเสียงซ้ำ ต้องมี aria-label ที่ปุ่มพ่อ (DESIGN.md §11)
      expect(trigger().attributes('aria-label')).toBe(LABEL)
      expect(trigger().get('i').attributes('aria-hidden')).toBe('true')
      // ยังไม่เปิด ⇒ ยังไม่ชี้ไปที่แผง (aria-controls ที่ชี้เป้าที่ไม่มีอยู่จริงแย่กว่าไม่มี)
      expect(trigger().attributes('aria-controls')).toBeUndefined()
      expect(menuInBody()).toBeNull()
    })

    it('ไอคอนต้องมี aria-hidden (DESIGN.md §11) และปุ่มต้องมีชื่อ', () => {
      mountMenu()
      const icons = menuInBody() === null ? [trigger().get('i')] : []
      icons.forEach((i) => expect(i.attributes('aria-hidden')).toBe('true'))
    })
  })

  describe('เปิด/ปิด และโครงสร้างเมนู', () => {
    it('กดปุ่มแล้วเปิดเมนู พร้อมไอเทมครบตามลำดับที่ส่งมา', async () => {
      mountMenu()
      await clickTrigger(1)

      expect(trigger().attributes('aria-expanded')).toBe('true')
      expect(menuInBody()).not.toBeNull()

      const items = menuItems()
      expect(items).toHaveLength(3)
      expect(items.map((el) => el.textContent?.trim())).toEqual(['ติ๊กเสร็จ', 'แก้ไข', 'ลบงาน'])
    })

    it('แผงที่ถูก Teleport มีชื่อ accessible name และปุ่มชี้มาที่มันด้วย aria-controls', async () => {
      mountMenu()
      await clickTrigger(1)

      const panel = menuInBody()!
      expect(panel.getAttribute('aria-label')).toBe(LABEL)
      // ความสัมพันธ์ปุ่ม↔แผงอ่อนลงเพราะ Teleport แยกออกจาก subtree ⇒ ต้องมี id/aria-controls คู่กัน
      expect(panel.id).toBeTruthy()
      expect(trigger().attributes('aria-controls')).toBe(panel.id)
    })

    it('คลิกฉากหลัง (นอกเมนู) แล้วปิด', async () => {
      mountMenu()
      await clickTrigger(1)

      const backdrop = document.body.querySelector<HTMLElement>('[data-menu-backdrop]')
      expect(backdrop).not.toBeNull()
      backdrop!.click()
      await nextTick()

      expect(menuInBody()).toBeNull()
      expect(trigger().attributes('aria-expanded')).toBe('false')
    })

    it('🔴 ฉากหลังมี z-index และแผงอยู่เหนือฉากหลัง (ถ้าฉากหลังไม่มีชั้น จะคลิกนอกไม่ติด)', async () => {
      mountMenu()
      await clickTrigger(1)

      const backdrop = document.body.querySelector<HTMLElement>('[data-menu-backdrop]')!
      const panel = menuInBody()!
      const zBackdrop = zIndexOf(backdrop)
      const zPanel = zIndexOf(panel)

      // jsdom ไม่คิด stacking จริง ⇒ พิสูจน์ได้แค่ว่า "ประกาศลำดับชั้นไว้"
      // ส่วนพฤติกรรมจริง (คลิกนอกแล้วโดนองค์ประกอบอื่นบนหน้าแทน) ต้องดูด้วยตา
      expect(zBackdrop).not.toBeNull()
      expect(zPanel).not.toBeNull()
      expect(zPanel!).toBeGreaterThan(zBackdrop!)
    })

    it('🔴 คลิกที่ปุ่มต้องไม่ลามไปถึง handler ของแถว/การ์ดที่ห่ออยู่ (@click.stop)', async () => {
      // ในการ์ด/แถวที่ "กดได้ทั้งใบ" การกดจุด 3 จุดต้องไม่ไปกระตุ้น handler ของแถว
      // (เปิดโมดัล/นำทาง) พร้อมกับเปิดเมนู — เกิดได้จริงทุกหน้าที่ RowActionMenu อยู่บนแถวที่กดได้
      const host = document.createElement('div')
      document.body.appendChild(host)
      hosts.push(host)
      let rowClicks = 0
      host.addEventListener('click', () => {
        rowClicks += 1
      })

      mountMenu(ITEMS, host)
      expect(host.contains(triggerEl())).toBe(true)

      await clickTrigger(1)

      expect(menuInBody()).not.toBeNull()
      expect(rowClicks).toBe(0)
    })

    it('เลื่อนหน้าจอแล้วปิด (ไม่งั้นแผงลอยค้างคนละที่กับปุ่ม)', async () => {
      mountMenu()
      await clickTrigger(1)
      expect(menuInBody()).not.toBeNull()

      window.dispatchEvent(new Event('scroll'))
      await nextTick()

      expect(menuInBody()).toBeNull()
    })

    it('ย่อ/ขยายหน้าต่างแล้วปิด (แผงคำนวณพิกัดจากวิวพอร์ตเดิม)', async () => {
      mountMenu()
      await clickTrigger(1)
      expect(menuInBody()).not.toBeNull()

      window.dispatchEvent(new Event('resize'))
      await nextTick()

      expect(menuInBody()).toBeNull()
    })
  })

  describe('🔴 การวางตำแหน่ง (เหตุผลที่ต้องมี Teleport + fixed)', () => {
    it('แผงหลุดออกจากพ่อที่ overflow-hidden + overflow-x-auto (ถอด Teleport ออกแล้วเทสต์นี้จะล้ม)', async () => {
      const scroller = createClippingHost()
      const host = scroller.parentElement as HTMLElement

      mountMenu(ITEMS, scroller)
      // ยืนยันก่อนว่าปุ่มอยู่ในพ่อที่ clip จริง ไม่ใช่เทสต์สุ่มสี่สุ่มห้า
      expect(host.contains(triggerEl())).toBe(true)

      await clickTrigger(1)

      const menu = menuInBody()
      expect(menu).not.toBeNull()
      expect(host.contains(menu)).toBe(false)
      // ⚠️ ต้องเช็คแบบ "โทเคนทั้งคำ" — `toContain('fixed')` ผ่านได้กับ `bg-fixed` ที่ไม่ได้
      //    ทำให้เป็น position: fixed เลย (เจอจริงจากการรีวิว 2026-09-15)
      expect(menu!.classList.contains('fixed')).toBe(true)
    })

    it('วางลงล่างของปุ่มชิดขอบขวา เมื่อมีที่ว่างด้านล่างพอ', async () => {
      setViewport(1024, 768)
      stubTriggerRect(100, 400) // top 100, bottom 144
      mountMenu()
      await clickTrigger(1)

      const style = menuInBody()!.style
      // 144 + 6 = 150 · right(400) - กว้างแผง(208) = 192 และยังไม่ชนขอบขวา
      expect(style.top).toBe('150px')
      expect(style.left).toBe('192px')
    })

    it('หนีบขอบขวา — ปุ่มชิดขวาจอแล้วแผงต้องไม่ล้นออกนอกจอ', async () => {
      setViewport(400, 768)
      stubTriggerRect(100, 390)
      mountMenu()
      await clickTrigger(1)

      // 390 - 208 = 182 แต่เพดานคือ 400 - 208 - 12 = 180 ⇒ ต้องถูกหนีบเป็น 180
      expect(menuInBody()!.style.left).toBe('180px')
    })

    it('หนีบขอบซ้าย — ปุ่มชิดซ้ายจอแล้วแผงต้องไม่ล้นออกนอกจอ', async () => {
      setViewport(400, 768)
      stubTriggerRect(100, 20)
      mountMenu()
      await clickTrigger(1)

      // 20 - 208 = -188 ⇒ ต้องถูกหนีบขึ้นมาเป็น EDGE_GAP = 12
      expect(menuInBody()!.style.left).toBe('12px')
    })

    it('🔴 จอเตี้ย: แผงต้องไม่หลุดขอบบนของจอ (หลุดแล้วไอเทมที่ถูกตัดจะกดไม่ได้)', async () => {
      // ปุ่มอยู่บนสุดของจอที่เตี้ยมาก — ที่ด้านล่างไม่พอ ⇒ พลิกขึ้นบน
      // แล้วแผงสูงกว่าจอ ⇒ สูตรดิบให้ top ติดลบ ต้องถูกหนีบไว้ที่ EDGE_GAP
      setViewport(1024, 100)
      stubTriggerRect(0, 400)
      mountMenu()
      await clickTrigger(1)

      expect(menuInBody()!.style.top).toBe('12px')
    })

    it('แผงมีเพดานความสูง + เลื่อนในตัว กันไอเทมถูกตัดจนกดไม่ได้', async () => {
      mountMenu()
      await clickTrigger(1)

      const cls = menuInBody()!.className
      expect(cls).toContain('overflow-y-auto')
      expect(cls).toContain('overscroll-contain')
      // ⚠️ Tailwind เขียน `calc()` ที่มีช่องว่างด้วย `_` — ถ้าเผลอเขียน `calc(100vh-1.5rem)`
      //    (ไม่มี `_`) เบราว์เซอร์จะทิ้งทั้งประกาศ แล้วเพดานความสูงจะไม่มีผลเงียบ ๆ
      expect(cls).toContain('max-h-[calc(100vh_-_1.5rem)]')
    })

    it('แผงกว้างเท่าค่าคงที่ที่ใช้คำนวณ (ค่าที่วาดกับค่าที่คำนวณต้องมาจากที่เดียว)', async () => {
      mountMenu()
      await clickTrigger(1)

      expect(menuInBody()!.style.width).toBe('208px')
    })
  })

  describe('⌨️ คีย์บอร์ด', () => {
    it('เปิดด้วยคีย์บอร์ด (Enter/Space) แล้วโฟกัสไปที่ไอเทมแรกทันที', async () => {
      mountMenu()
      // detail: 0 = เปิดด้วยคีย์บอร์ด ตามสัญญาของ MouseEvent
      await clickTrigger(0)

      expect(document.activeElement).toBe(menuItems()[0])
    })

    it('เปิดด้วยเมาส์แล้วโฟกัส "ไม่" ถูกย้ายเข้าแผง (กันจอกระตุกบนมือถือ)', async () => {
      mountMenu()
      await clickTrigger(1)

      expect(menuItems()).not.toContain(document.activeElement)
      expect(activeText()).not.toBe('ติ๊กเสร็จ')
    })

    it('ArrowDown จากปุ่ม (ยังไม่โฟกัสไอเทมไหน) ไปไอเทมแรก', async () => {
      mountMenu()
      await clickTrigger(1)
      // เบราว์เซอร์จริงย้ายโฟกัสมาที่ปุ่มเมื่อคลิก (jsdom ไม่ทำ) — จำลองให้ตรงความจริง
      triggerEl().focus()
      await press('ArrowDown')

      expect(activeText()).toBe('ติ๊กเสร็จ')
    })

    it('🔴 ArrowUp จากปุ่มไปไอเทม "สุดท้าย" ไม่ใช่รองสุดท้าย (off-by-one ตอน current = -1)', async () => {
      mountMenu()
      await clickTrigger(1)
      triggerEl().focus()
      await press('ArrowUp')

      expect(activeText()).toBe('ลบงาน')
    })

    it('ลูกศรวนรอบทั้งสองทาง', async () => {
      mountMenu()
      await clickTrigger(0) // โฟกัสไอเทมแรก
      await press('ArrowUp') // ย้อนจากไอเทมแรก ⇒ ต้องไปไอเทมสุดท้าย
      expect(activeText()).toBe('ลบงาน')

      await press('ArrowDown') // วนกลับไปไอเทมแรก
      expect(activeText()).toBe('ติ๊กเสร็จ')
    })

    it('🔴 ลูกศรต้องข้ามไอเทมที่ disable (`.focus()` บนปุ่ม disabled ไม่เกิดอะไร ⇒ จะตัน)', async () => {
      mountMenu(ITEMS_MIDDLE_DISABLED)
      await clickTrigger(0)
      expect(activeText()).toBe('ติ๊กเสร็จ')

      await press('ArrowDown') // ข้าม 'แก้ไข' ที่ disabled ไปที่ 'ลบงาน'
      expect(activeText()).toBe('ลบงาน')

      await press('ArrowUp') // และย้อนกลับก็ต้องข้ามด้วย
      expect(activeText()).toBe('ติ๊กเสร็จ')
    })

    it('กด Esc แล้วปิด และคืนโฟกัสกลับที่ปุ่ม (คนใช้คีย์บอร์ดไม่หลงที่)', async () => {
      mountMenu()
      await clickTrigger(1)
      const el = triggerEl()

      await press('Escape')

      expect(menuInBody()).toBeNull()
      expect(document.activeElement).toBe(el)
    })

    it('Esc ปิดเมนูได้แม้โฟกัสไม่ได้อยู่ที่ปุ่ม (Safari ไม่ย้ายโฟกัสเมื่อคลิกด้วยเมาส์)', async () => {
      mountMenu()
      await clickTrigger(1)

      const outside = document.createElement('button')
      document.body.appendChild(outside)
      outside.focus()

      await press('Escape')

      // เมนูที่เปิดอยู่มีฉากหลังคลุมทั้งหน้า = overlay บนสุด ⇒ Esc ต้องปิดเสมอ
      // ⚠️ ถ้าผูก Esc กับ "โฟกัสต้องอยู่ที่เมนู" ผู้ใช้ Safari (ซึ่งคลิกแล้วโฟกัสไม่ย้ายมาที่ปุ่ม)
      //    จะกด Esc แล้วเมนูไม่ปิดเลย — ต่างจากลูกศรที่ "ต้อง" ผูกกับโฟกัส (ดูเทสต์ถัดไป)
      expect(menuInBody()).toBeNull()
      expect(document.activeElement).toBe(triggerEl())
    })

    it('🔴 ลูกศรต้องไม่ยึดทั้งหน้า — โฟกัสอยู่ที่อื่นแล้วต้องไม่ถูก preventDefault/กระชากโฟกัส', async () => {
      mountMenu()
      await clickTrigger(1)

      const outside = document.createElement('input')
      document.body.appendChild(outside)
      outside.focus()

      const event = new KeyboardEvent('keydown', { key: 'ArrowDown', cancelable: true, bubbles: true })
      window.dispatchEvent(event)
      await nextTick()

      expect(event.defaultPrevented).toBe(false)
      expect(document.activeElement).toBe(outside)
      // และเมนูต้องยังเปิดอยู่ (ไม่ถูกยุ่งจากการกดปุ่มของที่อื่น)
      expect(menuInBody()).not.toBeNull()
    })

    it('กด Tab แล้วปิดเมนู (ไม่งั้นค้างเปิดพร้อมฉากหลังที่บล็อกทั้งหน้า)', async () => {
      mountMenu()
      await clickTrigger(0)
      expect(menuInBody()).not.toBeNull()

      await press('Tab')

      expect(menuInBody()).toBeNull()
    })

    it('เลือกไอเทมด้วยคีย์บอร์ดแล้วโฟกัสต้องกลับมาที่ปุ่ม ไม่ตกไปที่ <body>', async () => {
      mountMenu()
      await clickTrigger(0) // โฟกัสไอเทมแรก
      const el = triggerEl()

      menuItems()[0]!.click() // เทียบเท่ากด Enter บนไอเทมที่โฟกัสอยู่
      await nextTick()

      expect(wrapper!.emitted('select')).toEqual([['toggle']])
      // ไอเทมถูกถอดออกจาก DOM ⇒ ถ้าไม่คืนโฟกัสก่อน activeElement จะกลายเป็น <body>
      expect(document.activeElement).toBe(el)
    })
  })

  describe('การเลือกไอเทม', () => {
    it('เลือกไอเทมแล้วส่ง key ออกไป และปิดเมนูทันที', async () => {
      mountMenu()
      await clickTrigger(1)

      const deleteItem = menuItems()[2]
      expect(deleteItem).toBeDefined()
      deleteItem!.click()
      await nextTick()

      expect(wrapper!.emitted('select')).toEqual([['delete']])
      expect(menuInBody()).toBeNull()
    })

    it('ไอเทมที่เป็นลิงก์ (มี `to`) เรนเดอร์เป็น <a> ไม่ยิง @select', async () => {
      mountMenu()
      await clickTrigger(1)

      const editItem = menuItems()[1]
      expect(editItem?.tagName).toBe('A')
      expect(editItem?.getAttribute('href')).toBe('/tasks/7/edit')
      expect(wrapper!.emitted('select')).toBeUndefined()
    })

    it('ไอเทมที่ถูก disable กดไม่ได้ทั้งทางตาและทาง event', async () => {
      mountMenu([{ ...ITEMS[2]!, disabled: true }])
      await clickTrigger(1)

      const item = menuItems()[0]!
      // ทางตา/ทาง screen reader: ต้องถูกประกาศว่าปิด และเห็นชัดว่ากดไม่ได้
      expect(item.hasAttribute('disabled')).toBe(true)
      expect(item.className).toContain('cursor-not-allowed')
      // สีต้องอยู่ในชุดที่ DESIGN.md §2 อนุญาต (stone-300 ไม่อยู่ และคอนทราสต์อ่านไม่ออก)
      expect(item.className).toContain('text-stone-400')

      // ทาง event: ยิง click เข้ามาตรง ๆ (ข้ามการกันของเบราว์เซอร์) ก็ต้องไม่ผ่าน
      // ⚠️ ต้องใช้ dispatchEvent ไม่ใช่ `.click()` — `.click()` บนปุ่ม `disabled`
      //    ถูกเบราว์เซอร์/jsdom กลืนทิ้งตั้งแต่ยังไม่ถึง handler ⇒ เทสต์จะ **เขียวหลอก**
      //    (เจอจริง: mutation "ถอด guard disabled" รอดทั้งที่เทสต์ผ่าน — 2026-09-15)
      item.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      await nextTick()

      expect(wrapper!.emitted('select')).toBeUndefined()
      expect(menuInBody()).not.toBeNull()
    })

    it('โทน danger ได้สีแดง ส่วนไอเทมปกติได้สีเทา (DESIGN.md §2 ใช้ได้เฉพาะ stone-*/brand-*/red-*)', async () => {
      mountMenu()
      await clickTrigger(1)

      const [toggle, , del] = menuItems()
      expect(del!.className).toContain('text-red-600')
      expect(del!.className).not.toContain('text-stone-700')
      expect(toggle!.className).toContain('text-stone-700')
      expect(toggle!.className).not.toContain('text-red-600')
    })

    it('ไอเทมที่กดได้ต้องสูง ≥44px ตาม DESIGN.md §2 (เดิม py-2.5 = 40px ไม่ผ่าน)', async () => {
      mountMenu()
      await clickTrigger(1)

      // `py-3` (24px) + line-height ของ text-sm (20px) = 44px
      expect(menuItems()[0]!.className).toContain('py-3')
      expect(menuItems()[0]!.className).not.toContain('py-2.5')
    })
  })

  describe('วงจรชีวิตและ listener', () => {
    it('🔴 unmount ระหว่างเปิดเมนูอยู่ ต้องถอด listener ตัวเดิม (type + fn + capture) ครบทุกตัว', async () => {
      const addSpy = vi.spyOn(window, 'addEventListener')
      const removeSpy = vi.spyOn(window, 'removeEventListener')

      mountMenu()
      await clickTrigger(0)

      // เก็บ "ลายนิ้วมือ" ของ listener ที่เมนูนี้เพิ่มเข้าไป — เทียบชื่ออย่างเดียวไม่พอ
      // เพราะ removeEventListener('scroll', close) ที่ลืม `true` จะไม่ถอดอะไรเลย
      // แต่ชื่อ 'scroll' ก็ยังโผล่ในรายการ ⇒ เทสต์แบบเทียบชื่อจะเขียวหลอก
      const watched = ['keydown', 'scroll', 'resize'] as const
      const added = addSpy.mock.calls.filter((c) =>
        watched.includes(c[0] as (typeof watched)[number]),
      )
      expect(added.length).toBeGreaterThanOrEqual(3)

      wrapper!.unmount()
      wrapper = null

      const unmatched = added.filter(
        ([type, fn, opts]) =>
          !removeSpy.mock.calls.some(([t, f, o]) => t === type && f === fn && o === opts),
      )
      expect(unmatched.map(([type]) => type)).toEqual([])

      // Teleport ต้องถูกเก็บกวาดไปพร้อมคอมโพเนนต์ ไม่ค้างทับหน้าถัดไป
      expect(menuInBody()).toBeNull()
      expect(document.body.querySelector('[data-menu-backdrop]')).toBeNull()
    })

    it('เปิด-ปิดซ้ำหลายรอบต้องไม่สะสม listener (ตัวนับ add/remove ต้องกลับมาเท่ากัน)', async () => {
      const addSpy = vi.spyOn(window, 'addEventListener')
      const removeSpy = vi.spyOn(window, 'removeEventListener')

      mountMenu()
      for (let i = 0; i < 3; i += 1) {
        await clickTrigger(1) // เปิด
        await clickTrigger(1) // ปิด (กดปุ่มเดิม)
      }

      const count = (calls: unknown[][]) =>
        calls.filter((c) => ['keydown', 'scroll', 'resize'].includes(c[0] as string)).length
      expect(count(addSpy.mock.calls)).toBe(count(removeSpy.mock.calls))
      expect(menuInBody()).toBeNull()
    })
  })
})
