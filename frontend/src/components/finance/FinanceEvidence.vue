<script setup lang="ts">
/**
 * 📎 หลักฐานของ record หนึ่ง (รายการ / การรับเงิน / event)
 *
 * รวม list + gallery + uploader ไว้ที่เดียว — ใช้ซ้ำได้ทุกหน้า
 *  - `canManage` = ผู้ใช้มี MANAGE_FINANCE ⇒ เห็นปุ่มแนบ/ลบ
 *  - สมาชิกธรรมดาดูได้อย่างเดียว (backend ใช้ `require_member` สำหรับ list/serve)
 */
import { computed, ref, watch } from 'vue'
import AppButton from '@/components/ui/AppButton.vue'
import { useDialog } from '@/composables/useDialog'
import { FinanceService } from '@/services/finance'
import { useAuthStore } from '@/stores/auth'
import FinanceFileGallery from './FinanceFileGallery.vue'
import FinanceFileUploader from './FinanceFileUploader.vue'
import type {
  FinanceAttachment,
  FinanceAttachmentKind,
  FinanceAttachmentLimits,
  FinanceAttachmentOwnerType,
} from '@/types/finance'

const props = withDefaults(
  defineProps<{
    ownerType: FinanceAttachmentOwnerType
    ownerId: number | null
    canManage?: boolean
    compact?: boolean
    kind?: FinanceAttachmentKind
  }>(),
  { canManage: false, compact: false },
)

const authStore = useAuthStore()
const dialog = useDialog()

const items = ref<FinanceAttachment[]>([])
const limits = ref<FinanceAttachmentLimits | null>(null)
const isLoading = ref(false)
const loadError = ref<string | null>(null)

const maxCount = computed(() => limits.value?.max_per_owner ?? 20)
const imageSizeLimitMb = computed(() => limits.value?.image_size_limit_mb ?? 10)
const documentSizeLimitMb = computed(() => limits.value?.document_size_limit_mb ?? 20)
const maxPerRequest = computed(() => limits.value?.max_per_request ?? 5)

async function load(): Promise<void> {
  if (props.ownerId == null) {
    items.value = []
    return
  }
  const roomId = authStore.currentRoomId as number
  isLoading.value = true
  loadError.value = null
  try {
    const res = await FinanceService.getFinanceAttachments(
      roomId,
      props.ownerType,
      props.ownerId,
    )
    items.value = res.items
    limits.value = res.limits
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : 'โหลดหลักฐานไม่สำเร็จ'
  } finally {
    isLoading.value = false
  }
}

watch(
  () => [props.ownerType, props.ownerId],
  () => void load(),
  { immediate: true },
)

function onUploaded(): void {
  void load()
}

async function onDelete(id: string): Promise<void> {
  if (props.ownerId == null) return
  try {
    await FinanceService.deleteFinanceAttachment(authStore.currentRoomId as number, id)
    await load()
  } catch (e) {
    void dialog.alert(
      'ลบไฟล์ไม่สำเร็จ',
      e instanceof Error ? e.message : 'เกิดข้อผิดพลาด กรุณาลองใหม่',
      'error',
    )
  }
}
</script>

<template>
  <div v-if="ownerId != null" :class="compact ? 'space-y-2' : 'space-y-3'">
    <div v-if="isLoading" class="flex items-center gap-2 py-3 text-sm text-ink-3">
      <span class="h-4 w-4 animate-spin rounded-full border-2 border-brand/30 border-t-brand" aria-hidden="true"></span>
      กำลังโหลดหลักฐาน…
    </div>

    <div v-else-if="loadError" class="flex flex-wrap items-center gap-2 text-sm text-danger">
      <span>{{ loadError }}</span>
      <AppButton variant="quiet" @click="load">
        <i class="bi bi-arrow-clockwise" aria-hidden="true"></i>
        ลองใหม่
      </AppButton>
    </div>

    <template v-else>
      <FinanceFileGallery
        v-if="items.length"
        :attachments="items"
        :can-manage="canManage"
        :compact="compact"
        @delete="onDelete"
        @refresh="load"
      />
      <p v-else class="text-sm text-ink-3">ยังไม่มีไฟล์หลักฐาน</p>

      <FinanceFileUploader
        v-if="canManage"
        :owner-type="ownerType"
        :owner-id="ownerId"
        :kind="kind"
        :max-count="maxCount"
        :existing-count="items.length"
        :image-size-limit-mb="imageSizeLimitMb"
        :document-size-limit-mb="documentSizeLimitMb"
        :max-per-request="maxPerRequest"
        @uploaded="onUploaded"
      />
    </template>
  </div>
</template>
