<script setup lang="ts">
/**
 * 📎 กล่องดูหลักฐาน (ใช้กับหน้าประวัติรายการ ฯลฯ)
 */
import AppSheet from '@/components/ui/AppSheet.vue'
import FinanceEvidence from './FinanceEvidence.vue'
import type { FinanceAttachmentOwnerType } from '@/types/finance'

withDefaults(
  defineProps<{
    open: boolean
    ownerType: FinanceAttachmentOwnerType
    ownerId: number | null
    title?: string
    description?: string
    canManage?: boolean
  }>(),
  { title: 'ไฟล์หลักฐาน', description: '', canManage: false },
)

const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <AppSheet
    :open="open"
    label="ไฟล์หลักฐานการเงิน"
    :title="title"
    :description="description"
    size="dialog"
    @close="emit('close')"
  >
    <FinanceEvidence :owner-type="ownerType" :owner-id="ownerId" :can-manage="canManage" />
  </AppSheet>
</template>
