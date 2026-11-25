<script setup lang="ts">
/**
 * 💰 MoneyInput — ช่องกรอกเงินของหน้าจอการเงิน (FIN-V2 / P2.3)
 *
 * 🔴 ทำไมไม่ใช้ `type="number"`: บนมือถือ/เดสก์ท็อป ปุ่มลูกศรและล้อเมาส์เปลี่ยนยอดเงิน
 *    ได้โดยไม่ตั้งใจ ⇒ พิมพ์ "1000" แล้วล้อเมาส์หมุนนิดเดียวกลายเป็น 1001 หรือ 990
 *    ซึ่งเป็นเงินที่บันทึกจริง ⇒ ใช้ `type="text"` + `inputmode="decimal"`
 *
 * 🎯 สัญญา: ค่าที่ emit เป็น **number หรือ null** ตามที่พิมพ์ — ห้ามปัดเศษเอง
 *    (การปัดเป็นสตางค์เป็นหน้าที่ของผู้สร้าง payload ตอนส่ง: `roundMoney(...).toFixed(2)`)
 *
 * @example
 * <MoneyInput v-model="amount" label="เงินสดที่รับ" hint="ใส่ 0 ได้ถ้าใช้เครดิตล้วน" />
 */
import { nextTick, onMounted, ref, useId, watch } from 'vue'
import { formatAmount } from '@/utils/money'

const model = defineModel<number | null>({ default: null })

const props = withDefaults(
  defineProps<{
    label: string
    hint?: string
    disabled?: boolean
    autofocus?: boolean
    invalid?: boolean
  }>(),
  { hint: '', disabled: false, autofocus: false, invalid: false },
)

const inputId = `money-input-${useId()}`
const hintId = `${inputId}-hint`
const inputEl = ref<HTMLInputElement | null>(null)
const isFocused = ref(false)

/** number → ข้อความบนจอ (คั่นหลักพัน, 2 ตำแหน่ง) */
const toText = (value: number | null): string => {
  if (value === null || !Number.isFinite(value)) return ''
  return formatAmount(value)
}

/** ข้อความบนจอ → number (ค่าว่าง/จุดลอย = null) */
const parseText = (raw: string): number | null => {
  const cleaned = raw.replace(/[,\s]/g, '')
  if (cleaned === '' || cleaned === '.') return null
  const value = Number(cleaned)
  return Number.isFinite(value) ? value : null
}

/**
 * 🧹 ล้างสิ่งที่พิมพ์ให้เหลือ "เลข + จุดเดียว + ทศนิยม ≤2"
 *
 * ⚠️ ต้องเขียนเองแทน `type=number` เพราะต้องการให้พิมพ์ "1,250.50" ผ่านการวางได้
 *    และไม่ให้ทศนิยมที่ 3 หลุดเข้า model (15.999 เงินที่บันทึกได้มีแค่ 15.99)
 */
const sanitize = (raw: string): string => {
  let digits = ''
  let seenDot = false
  let decimals = 0
  for (const ch of raw) {
    if (ch >= '0' && ch <= '9') {
      if (seenDot) {
        if (decimals >= 2) continue
        decimals += 1
      }
      digits += ch
    } else if (ch === '.' && !seenDot) {
      seenDot = true
      digits += ch
    }
  }
  return digits
}

const text = ref<string>(toText(model.value))

const onInput = (event: Event) => {
  const target = event.target as HTMLInputElement
  const cleaned = sanitize(target.value)
  text.value = cleaned
  // 🛡️ เขียนค่าที่ล้างแล้วกลับเข้าช่องทันที — ถ้าปล่อยให้ DOM แสดงตัวอักษรที่ถูกปฏิเสธ
  //    ผู้ใช้จะเห็นตัวเลขที่ไม่มีอยู่ใน model (พิมพ์ต่อแล้วได้ยอดที่ไม่ตรงกับที่เห็น)
  target.value = cleaned
  model.value = parseText(cleaned)
}

const onFocus = () => {
  isFocused.value = true
  // ✍️ ตอนแก้ไขโชว์เลขล้วน (ไม่มี comma) เพื่อให้เคอร์เซอร์/เลือกข้อความทำงานปกติ
  text.value = text.value.replace(/,/g, '')
}

const onBlur = () => {
  isFocused.value = false
  text.value = toText(model.value)
}

/** ค่าถูกตั้งจากภายนอก (เช่น รีเซ็ตตอนเปิดแผ่น) → อัปเดตช่อง ยกเว้นระหว่างผู้ใช้พิมพ์อยู่ */
watch(model, (value) => {
  if (isFocused.value) return
  if (parseText(text.value) !== value) text.value = toText(value)
})

onMounted(() => {
  if (!props.autofocus) return
  void nextTick(() => inputEl.value?.focus())
})
</script>

<template>
  <div>
    <label class="field-label" :for="inputId">{{ label }}</label>
    <div class="relative">
      <input
        :id="inputId"
        ref="inputEl"
        class="field num pe-10"
        :class="invalid ? 'border-danger-500' : ''"
        type="text"
        inputmode="decimal"
        autocomplete="off"
        :value="text"
        :disabled="disabled"
        :aria-invalid="invalid ? 'true' : undefined"
        :aria-describedby="hint ? hintId : undefined"
        @input="onInput"
        @focus="onFocus"
        @blur="onBlur"
      />
      <button
        v-if="text !== '' && !disabled"
        type="button"
        class="absolute end-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-control text-ink-3 hover:bg-canvas hover:text-ink-1"
        aria-label="ล้างยอดเงิน"
        @click="model = null"
      >
        <i class="bi bi-x-circle" aria-hidden="true"></i>
      </button>
    </div>
    <p v-if="hint" :id="hintId" class="mt-1 text-caption text-ink-3">{{ hint }}</p>
  </div>
</template>
