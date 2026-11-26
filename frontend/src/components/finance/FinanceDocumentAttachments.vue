<script setup lang="ts">
/**
 * 📎 ไฟล์หลักฐานในหน้ารายละเอียดเอกสาร — พรีวิว + เปิด + โหลด
 *
 * - รูป: แสดง thumbnail (กดเปิดดูเต็มในแท็บใหม่)
 * - PDF: การ์ดบอกจำนวนหน้า/ขนาด
 * - "โหลด" ต่อ `&download=1` ให้ backend เปลี่ยน Content-Disposition เป็น attachment
 *
 * ⚠️ signed URL มีอายุ 10–15 นาที — รูปที่โหลดไม่ได้ต้องบอกให้รีเฟรชหน้า
 */
import { computed, ref } from 'vue'
import { absoluteMediaUrl, formatBytes } from '@/utils/media'
import type { FinanceAttachment } from '@/types/finance'

const props = defineProps<{
  attachments: FinanceAttachment[]
}>()

const broken = ref<Set<string>>(new Set())

function thumbOf(file: FinanceAttachment): string {
  return absoluteMediaUrl(file.thumb_url ?? file.url)
}

function openUrl(file: FinanceAttachment): string {
  return absoluteMediaUrl(file.url)
}

/** ต่อ `download=1` — URL มี query อยู่แล้ว จึงใช้ `&` */
function downloadUrl(file: FinanceAttachment): string {
  return `${openUrl(file)}&download=1`
}

function markBroken(id: string): void {
  broken.value = new Set(broken.value).add(id)
}

function openAttachment(file: FinanceAttachment): void {
  window.open(openUrl(file), '_blank', 'noopener')
}

const hasFiles = computed(() => props.attachments.length > 0)
</script>

<template>
  <div v-if="hasFiles">
    <ul class="grid grid-cols-2 gap-2 sm:grid-cols-3">
      <li
        v-for="file in attachments"
        :key="file.id"
        class="min-w-0 overflow-hidden rounded-control border border-line bg-surface"
      >
        <template v-if="file.file_kind === 'image'">
          <button
            v-if="!broken.has(file.id)"
            type="button"
            class="block w-full"
            :aria-label="`เปิดดู ${file.original_name ?? 'รูปหลักฐาน'}`"
            @click="openAttachment(file)"
          >
            <img
              :src="thumbOf(file)"
              :alt="file.original_name ?? 'รูปหลักฐาน'"
              class="h-32 w-full object-cover"
              loading="lazy"
              @error="markBroken(file.id)"
            />
          </button>
          <p v-else class="flex h-32 items-center justify-center px-2 text-center text-[12px] text-ink-3">
            โหลดไม่ได้ · รีเฟรชหน้า
          </p>
        </template>

        <a
          v-else
          :href="openUrl(file)"
          target="_blank"
          rel="noopener noreferrer"
          class="flex h-32 flex-col items-center justify-center gap-1 px-2 text-center"
        >
          <i class="bi bi-file-earmark-pdf text-2xl text-danger" aria-hidden="true"></i>
          <span class="line-clamp-2 w-full break-all text-[11px] text-ink-2">
            {{ file.original_name ?? 'เอกสาร PDF' }}
          </span>
          <span class="text-[11px] text-ink-3">
            {{ file.page_count ? `${file.page_count} หน้า · ` : '' }}{{ formatBytes(file.bytes) }}
          </span>
        </a>

        <div class="flex items-center justify-between gap-1 border-t border-line px-1.5 py-1">
          <a
            :href="openUrl(file)"
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex min-h-9 items-center gap-1 rounded-control px-2 text-[12px] font-bold text-brand hover:bg-brand-tint"
          >
            <i class="bi bi-box-arrow-up-right" aria-hidden="true"></i>
            เปิด
          </a>
          <a
            :href="downloadUrl(file)"
            class="inline-flex min-h-9 items-center gap-1 rounded-control px-2 text-[12px] font-bold text-ink-2 hover:bg-canvas"
          >
            <i class="bi bi-download" aria-hidden="true"></i>
            โหลด
          </a>
        </div>
      </li>
    </ul>
  </div>
  <p v-else class="text-sm text-ink-3">ไม่มีไฟล์หลักฐานสำหรับเอกสารนี้</p>
</template>
