<script setup lang="ts">
/**
 * 📎 แนบไฟล์หลักฐานการเงิน — **รูปภาพ + PDF** ใช้ได้ 2 โหมด
 *
 * 1. **buffer mode** (ไม่ส่ง `ownerId`) — เลือก/พรีวิวเท่านั้น ยังไม่ยิง network
 *    ⇒ ฟอร์มที่สร้าง record ก่อน (AddTransaction / รับชำระหนี้) เก็บไฟล์ไว้ใน `v-model:files`
 *    แล้วค่อยอัปโหลดหลังสร้างสำเร็จ
 * 2. **immediate mode** (ส่ง `ownerId`) — เลือกแล้วกดปุ่มอัปโหลดทันที
 *
 * ⚠️ การตรวจชนิด/ขนาด/จำนวนฝั่งนี้เป็น **UX เท่านั้น** — server ตรวจซ้ำทุกครั้ง
 *    (PDF ถูก sanitize และรูปถูกแปลงใหม่ที่ backend)
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useDialog } from '@/composables/useDialog'
import { FinanceService } from '@/services/finance'
import { useAuthStore } from '@/stores/auth'
import { compressImages, isHeicLike } from '@/utils/imageCompress'
import { formatBytes } from '@/utils/media'
import type {
  FinanceAttachment,
  FinanceAttachmentKind,
  FinanceAttachmentOwnerType,
} from '@/types/finance'

const props = withDefaults(
  defineProps<{
    ownerType: FinanceAttachmentOwnerType
    /** `null` = buffer mode */
    ownerId?: number | null
    kind?: FinanceAttachmentKind
    /** เพดานไฟล์ต่อ record — ค่าจาก `limits` ของ server */
    maxCount: number
    /** จำนวนไฟล์ที่มีอยู่แล้วบน server (immediate mode) */
    existingCount?: number
    imageSizeLimitMb?: number
    documentSizeLimitMb?: number
    maxPerRequest?: number
    /** ไฟล์ที่เลือกไว้ — เฉพาะ buffer mode (ผูก `v-model:files`) */
    files?: File[]
    disabled?: boolean
  }>(),
  {
    ownerId: null,
    existingCount: 0,
    imageSizeLimitMb: 10,
    documentSizeLimitMb: 20,
    maxPerRequest: 5,
    files: () => [],
    disabled: false,
  },
)

const emit = defineEmits<{
  'update:files': [files: File[]]
  uploaded: [attachments: FinanceAttachment[]]
}>()

const dialog = useDialog()
const authStore = useAuthStore()
const currentRoomId = computed(() => authStore.currentRoomId as number)

const fileInput = ref<HTMLInputElement | null>(null)
const uploading = ref(false)
const picked = ref<File[]>([])

const isBuffer = computed(() => props.ownerId == null)
const usedCount = computed(() => props.existingCount + picked.value.length)
const remaining = computed(() => Math.max(0, props.maxCount - usedCount.value))

/** object URL ต่อไฟล์ — revoke เมื่อถอด/ทำลาย ไม่งั้นหน่วยความจำค้าง */
const previews = new Map<File, string>()

function previewFor(file: File): string {
  let url = previews.get(file)
  if (!url) {
    url = URL.createObjectURL(file)
    previews.set(file, url)
  }
  return url
}

function revoke(file: File): void {
  const url = previews.get(file)
  if (url) {
    URL.revokeObjectURL(url)
    previews.delete(file)
  }
}

watch(
  () => props.files,
  (next) => {
    if (!isBuffer.value) return
    for (const f of picked.value) if (!next.includes(f)) revoke(f)
    picked.value = [...next]
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  for (const f of picked.value) revoke(f)
})

function setPicked(next: File[]): void {
  for (const f of picked.value) if (!next.includes(f)) revoke(f)
  picked.value = next
  if (isBuffer.value) emit('update:files', next)
}

function fileKindOf(file: File): 'image' | 'pdf' | 'other' {
  if (file.type === 'application/pdf' || /\.pdf$/i.test(file.name)) return 'pdf'
  if (file.type.startsWith('image/') || isHeicLike(file)) return 'image'
  return 'other'
}

function limitFor(file: File): number {
  return fileKindOf(file) === 'pdf' ? props.documentSizeLimitMb : props.imageSizeLimitMb
}

function onFiles(event: Event): void {
  const input = event.target as HTMLInputElement
  const incoming = Array.from(input.files ?? [])
  input.value = ''

  const accepted: File[] = []
  let slots = remaining.value
  let skippedType = 0
  let skippedBig = 0
  let skippedCount = 0

  for (const file of incoming) {
    if (fileKindOf(file) === 'other') {
      skippedType++
      continue
    }
    if (file.size > limitFor(file) * 1024 * 1024) {
      skippedBig++
      continue
    }
    if (slots <= 0) {
      skippedCount++
      continue
    }
    accepted.push(file)
    slots--
  }

  if (skippedType || skippedBig || skippedCount) {
    const parts: string[] = []
    if (skippedType) parts.push(`${skippedType} ไฟล์ไม่ใช่รูปหรือ PDF`)
    if (skippedBig) parts.push(`${skippedBig} ไฟล์ใหญ่เกินขนาดที่กำหนด`)
    if (skippedCount) parts.push(`${skippedCount} ไฟล์เกินจำนวนที่แนบได้ (${props.maxCount} ไฟล์)`)
    void dialog.alert('แนบไฟล์ไม่ได้', parts.join(' · '), 'warning')
  }

  if (accepted.length) setPicked([...picked.value, ...accepted])
}

function removeAt(index: number): void {
  setPicked(picked.value.filter((_, i) => i !== index))
}

/** immediate mode — ย่อรูปในเครื่องก่อน (PDF ส่งดิบ) แล้วอัปเป็นชุดละ `maxPerRequest` */
async function uploadNow(): Promise<void> {
  const ownerId = props.ownerId
  if (
    isBuffer.value ||
    ownerId == null ||
    !picked.value.length ||
    uploading.value ||
    props.disabled
  ) {
    return
  }

  uploading.value = true
  try {
    const prepared = await compressImages(picked.value)
    const uploaded: FinanceAttachment[] = []
    for (let i = 0; i < prepared.length; i += props.maxPerRequest) {
      const batch = prepared.slice(i, i + props.maxPerRequest)
      const res = await FinanceService.uploadFinanceAttachments(
        currentRoomId.value,
        props.ownerType,
        ownerId,
        batch,
        props.kind,
      )
      uploaded.push(...res.items)
    }
    setPicked([])
    emit('uploaded', uploaded)
  } catch (e) {
    void dialog.alert(
      'แนบไฟล์ไม่สำเร็จ',
      e instanceof Error ? e.message : 'เกิดข้อผิดพลาด กรุณาลองใหม่',
      'error',
    )
  } finally {
    uploading.value = false
  }
}

defineExpose({ uploadNow })
</script>

<template>
  <div class="rounded-card border border-line bg-canvas p-3">
    <div class="flex flex-wrap items-center gap-2">
      <input
        ref="fileInput"
        type="file"
        accept="image/*,application/pdf"
        multiple
        class="hidden"
        data-testid="finance-file-input"
        @change="onFiles"
      />
      <AppButton
        variant="secondary"
        :disabled="disabled || uploading || remaining <= 0"
        @click="fileInput?.click()"
      >
        <i class="bi bi-paperclip" aria-hidden="true"></i>
        เลือกไฟล์
      </AppButton>

      <span class="ml-auto text-[13px] font-medium tabular-nums text-ink-3">
        {{ usedCount }}/{{ maxCount }} ไฟล์
      </span>
    </div>

    <p class="mt-2 flex items-start gap-1.5 text-[12px] leading-relaxed text-ink-3">
      <i class="bi bi-eye mt-0.5 shrink-0" aria-hidden="true"></i>
      <span>ไฟล์นี้เห็นได้โดยสมาชิกในห้อง · รองรับรูปภาพและ PDF</span>
    </p>

    <ul v-if="picked.length" class="mt-3 grid grid-cols-3 gap-2">
      <li
        v-for="(file, i) in picked"
        :key="`${file.name}-${i}`"
        class="relative min-w-0 rounded-control border border-line bg-surface p-1"
      >
        <img
          v-if="fileKindOf(file) === 'image'"
          :src="previewFor(file)"
          :alt="`ไฟล์ที่เลือก ${i + 1}: ${file.name}`"
          class="h-24 w-full rounded-control object-cover"
          loading="lazy"
        />
        <div v-else class="flex h-24 flex-col items-center justify-center gap-1 px-1 text-center">
          <i class="bi bi-file-earmark-pdf text-2xl text-danger" aria-hidden="true"></i>
          <span class="line-clamp-2 w-full break-all text-[11px] text-ink-2">{{ file.name }}</span>
          <span class="text-[11px] text-ink-3">{{ formatBytes(file.size) }}</span>
        </div>
        <button
          type="button"
          class="absolute -right-1.5 -top-1.5 flex h-7 w-7 items-center justify-center rounded-full bg-ink-1 text-white shadow-sm"
          :aria-label="`เอาไฟล์ ${file.name} ออก`"
          :disabled="uploading"
          @click="removeAt(i)"
        >
          <i class="bi bi-x-lg text-xs" aria-hidden="true"></i>
        </button>
      </li>
    </ul>

    <div v-if="!isBuffer && picked.length" class="mt-3">
      <AppButton block :loading="uploading" @click="uploadNow">
        <i class="bi bi-cloud-arrow-up" aria-hidden="true"></i>
        แนบ {{ picked.length }} ไฟล์
      </AppButton>
    </div>
  </div>
</template>
