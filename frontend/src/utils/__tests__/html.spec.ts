/**
 * 🔒 H6 — SweetAlert2 ตีความ `title:` และ `html:` ด้วย innerHTML
 *
 * เทสต์ชุดนี้พิสูจน์กับ **SweetAlert2 ตัวจริง** (ไม่ใช่ stub) ว่า
 * 1. ช่องโหว่มีจริง — `title:` ที่มีแท็กจะถูกตีความเป็นมาร์กอัป
 * 2. `titleText:` / `text:` ปิดช่องได้ (Swal ใช้ `innerText` / `textContent`)
 * 3. `escapeHtml()` ปิดช่องได้เมื่อจำเป็นต้องใช้ `title:`/`html:` จริง ๆ
 *
 * ⚠️ ทำไมต้องเทสต์กับ DOM จริง: `npm run type-check` ผ่านและ unit test เดิม 172 ข้อ
 *    ผ่าน **ทั้งก่อนและหลังแก้** ⇒ ไม่มีอะไรในชุดเดิมจับคลาสบั๊กนี้ได้เลย
 *    การพิสูจน์ว่าปิดจริงจึงต้องดูว่า Swal เรนเดอร์อะไรออกมา
 *
 * ⚠️ ห้าม `await Swal.fire(...)` ตรง ๆ — promise จะ resolve ตอนปิดกล่อง
 *    ซึ่งไม่เกิดขึ้นเองถ้าไม่มีปุ่ม ⇒ เทสต์จะค้าง (ค้างจน timeout)
 */
import { afterEach, describe, expect, it } from 'vitest'
import Swal from 'sweetalert2'

import { escapeAttr, escapeHtml } from '@/utils/html'

/**
 * ⚠️ jsdom **ไม่ implement `innerText`** — แต่ Swal ใช้ `innerText` กับ `titleText`
 *    (dist บรรทัด 1913: `title.innerText = params.titleText`)
 *
 * ถ้าไม่ polyfill เทสต์จะ **ผ่านแบบหลอก ๆ**: `textContent` เป็น `''` และ
 * `querySelector('#pwn')` เป็น null — ซึ่งเป็นจริงเสมอไม่ว่าค่าที่ส่งมาจะเป็นอะไร
 * ⇒ พิสูจน์ไม่ได้ว่า `titleText` ทำงานจริง (อาจพังเงียบ ๆ แล้วเทสต์ยังเขียว)
 *
 * polyfill นี้ทำให้ jsdom เลียนแบบเบราว์เซอร์ ⇒ assertion กลับมามีความหมาย
 */
if (!('innerText' in HTMLElement.prototype)) {
  Object.defineProperty(HTMLElement.prototype, 'innerText', {
    get(this: HTMLElement) {
      return this.textContent
    },
    set(this: HTMLElement, value: string) {
      this.textContent = value
    },
    configurable: true,
  })
}

/** ยิง Swal แล้วรอให้ render จบ โดยไม่ await promise ที่จะ resolve ตอนปิด */
const render = async (params: Record<string, unknown>) => {
  void Swal.fire({ showConfirmButton: false, ...params })
  await new Promise((resolve) => setTimeout(resolve, 0))
}

const title = () => document.querySelector('.swal2-title')
const body = () => document.querySelector('.swal2-html-container')

afterEach(() => {
  Swal.close()
})

describe('escapeHtml / escapeAttr', () => {
  it('escape อักขระที่มีความหมายใน HTML ครบทั้ง 5 ตัว', () => {
    expect(escapeHtml(`&<>"'`)).toBe('&amp;&lt;&gt;&quot;&#39;')
  })

  it('escape `&` ก่อนตัวอื่น — ไม่เกิด double-escape', () => {
    // ถ้า escape `&` ทีหลัง จะได้ `&amp;lt;` ซึ่งแสดงผลเป็น `&lt;` ไม่ใช่ `<`
    expect(escapeHtml('<')).toBe('&lt;')
    expect(escapeHtml('&lt;')).toBe('&amp;lt;')
  })

  it('กันเครื่องหมายคำพูดหลุดออกจาก attribute', () => {
    // เคสจริง: ครูตั้งชื่อกระเป๋าว่า  กระเป๋า "ห้อง 1"
    expect(escapeAttr('กระเป๋า "ห้อง 1"')).not.toContain('"')
  })

  it('ทนค่า null / undefined / ตัวเลข', () => {
    expect(escapeHtml(null)).toBe('')
    expect(escapeHtml(undefined)).toBe('')
    expect(escapeHtml(0)).toBe('0')
    expect(escapeHtml(1250.5)).toBe('1250.5')
  })
})

describe('ช่องโหว่มีจริง (พิสูจน์กับ SweetAlert2 ตัวจริง)', () => {
  it('`title:` ตีความ HTML — แท็กกลายเป็น element จริง', async () => {
    await render({ title: '<b id="pwn">สวัสดี</b>' })

    expect(title()).not.toBeNull()
    expect(title()!.querySelector('#pwn')).not.toBeNull()
    // ข้อความที่ผู้ใช้เห็นไม่มีแท็กโผล่ — ดูจากจอไม่ออกว่าโค้ดอันตราย
    expect(title()!.textContent).toBe('สวัสดี')
  })

  it('`html:` ก็ตีความ HTML เช่นกัน', async () => {
    await render({ html: '<img id="pwn" src="x">' })

    expect(body()!.querySelector('#pwn')).not.toBeNull()
  })
})

describe('ทางที่ปลอดภัย', () => {
  it('`titleText:` ไม่ตีความ HTML', async () => {
    await render({ titleText: '<b id="pwn">สวัสดี</b>' })

    expect(title()).not.toBeNull()
    expect(title()!.querySelector('#pwn')).toBeNull()
    expect(title()!.textContent).toBe('<b id="pwn">สวัสดี</b>')
  })

  it('`text:` ไม่ตีความ HTML', async () => {
    await render({ text: '<img id="pwn" src="x">' })

    expect(body()!.querySelector('#pwn')).toBeNull()
    expect(body()!.textContent).toBe('<img id="pwn" src="x">')
  })

  it('escapeHtml ปิดช่องของ `title:` ได้ และยังอ่านออก', async () => {
    await render({ title: escapeHtml('<b id="pwn">สวัสดี</b>') })

    expect(title()!.querySelector('#pwn')).toBeNull()
    expect(title()!.textContent).toBe('<b id="pwn">สวัสดี</b>')
  })

  it('escapeHtml ปิดช่องของ `html:` แต่คงมาร์กอัปของเทมเพลตไว้', async () => {
    // รูปแบบที่ใช้จริง: มาร์กอัปเป็นของเรา ค่าที่ interpolate เป็นของผู้ใช้
    await render({ html: `ลบ <b>${escapeHtml('<i id="pwn">ชื่อ</i>')}</b> ?` })

    expect(body()!.querySelector('#pwn')).toBeNull() // ค่าผู้ใช้ไม่กลายเป็นแท็ก
    expect(body()!.querySelector('b')).not.toBeNull() // แต่มาร์กอัปของเรายังอยู่
    expect(body()!.textContent).toContain('<i id="pwn">ชื่อ</i>')
  })

  it('event handler ในชื่อถูกทำให้เป็นข้อความ ไม่ทำงาน', async () => {
    let fired = false
    ;(window as unknown as { __pwn: () => void }).__pwn = () => {
      fired = true
    }

    await render({ html: escapeHtml('<img src=x onerror="window.__pwn()">') })

    expect(body()!.querySelector('img')).toBeNull()
    expect(fired).toBe(false)
  })
})
