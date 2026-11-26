<script setup lang="ts">
/**
 * 📎 แกลเลอรีไฟล์หลักฐาน — รูปแสดงเป็น thumbnail (กดดูเต็ม) · PDF แสดงเป็นการ์ดไฟล์
 *
 * ⚠️ signed URL มีอายุ 10–15 นาที ⇒ รูปที่ `@error` ต้องให้ parent refetch list
 *    (emit `refresh`) ไม่ใช่แสดงไอคอนแตกค้าง
 */
import { ref } from 'vue'
import AppSheet from '@/components/ui/AppSheet.vue'
import { useDialog } from '@/composables/useDialog'
import { absoluteMediaUrl, formatBytes } from '@/utils/media'
import type { FinanceAttachment } from '@/types/finance'

withDefaults(
  defineProps<{
    attachments: FinanceAttachment[]
    canManage?: boolean
    compact?: boolean
  }>(),
  { canManage: false, compact: false },
)

const emit = defineEmits<{
  delete: [id: string]
  refresh: []
}>()

const dialog = useDialog()
const broken = ref<Set<string>>(new Set())
const previewUrl = ref<string | null>(null)
const previewName = ref('')

function isBroken(id: string): boolean {
  return broken.value.has(id)
}

function markBroken(id: string): void {
  broken.value = new Set(broken.value).add(id)
}

function openImage(file: FinanceAttachment): void {
  previewUrl.value = absoluteMediaUrl(file.url)
  previewName.value = file.original_name ?? 'ไฟล์หลักฐาน'
}

function closePreview(): void {
  previewUrl.value = null
  previewName.value = ''
}

async function askDelete(file: FinanceAttachment): Promise<void> {
  const { isConfirmed } = await dialog.confirm(
    'ลบไฟล์หลักฐานนี้?',
    file.original_name ?? 'ไฟล์ที่แนบไว้',
    { icon: 'warning', confirmButtonText: 'ลบ' },
  )
  if (isConfirmed) emit('delete', file.id)
}
</script>

<template>
  <div>
    <ul class="grid grid-cols-2 gap-2 sm:grid-cols-3">
      <li
        v-for="file in attachments"
        :key="file.id"
        class="relative min-w-0 overflow-hidden rounded-control border border-line bg-surface"
      >
        <!-- รูปภาพ -->
        <template v-if="file.file_kind === 'image'">
          <button
            v-if="!isBroken(file.id)"
            type="button"
            class="block w-full"
            :aria-label="`ดูรูป ${file.original_name ?? ''}`"
            @click="openImage(file)"
          >
            <img
              :src="absoluteMediaUrl(file.thumb_url ?? file.url)"
              :alt="file.original_name ?? 'รูปหลักฐาน'"
              class="h-28 w-full object-cover"
              loading="lazy"
              @error="markBroken(file.id)"
            />
          </button>
          <button
            v-else
            type="button"
            class="flex h-28 w-full flex-col items-center justify-center gap-1 text-[12px] text-ink-3"
            @click="emit('refresh')"
          >
            <i class="bi bi-arrow-clockwise" aria-hidden="true"></i>
            โหลดไม่ได้ · ลองใหม่
          </button>
        </template>

        <!-- PDF -->
        <a
          v-else
          :href="absoluteMediaUrl(file.url)"
          target="_blank"
          rel="noopener noreferrer"
          class="flex h-28 flex-col items-center justify-center gap-1 px-2 text-center"
        >
          <i class="bi bi-file-earmark-pdf text-2xl text-danger" aria-hidden="true"></i>
          <span class="line-clamp-2 w-full break-all text-[11px] text-ink-2">
            {{ file.original_name ?? 'เอกสาร PDF' }}
          </span>
          <span class="text-[11px] text-ink-3">
            {{ file.page_count ? `${file.page_count} หน้า · ` : '' }}{{ formatBytes(file.bytes) }}
          </span>
        </a>

        <button
          v-if="canManage"
          type="button"
          class="absolute right-1 top-1 flex h-7 w-7 items-center justify-center rounded-full bg-ink-1/80 text-white"
          :aria-label="`ลบไฟล์ ${file.original_name ?? ''}`"
          @click="askDelete(file)"
        >
          <i class="bi bi-trash text-xs" aria-hidden="true"></i>
        </button>
      </li>
    </ul>

    <AppSheet
      :open="previewUrl !== null"
      label="ดูไฟล์หลักฐาน"
      :title="previewName"
      size="full"
      @close="closePreview"
    >
      <img
        v-if="previewUrl"
        :src="previewUrl"
        :alt="previewName"
        class="mx-auto max-h-[70vh] w-auto max-w-full rounded-control object-contain"
      />
    </AppSheet>
  </div>
</template>
