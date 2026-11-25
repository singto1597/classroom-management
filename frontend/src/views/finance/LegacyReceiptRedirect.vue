<script setup lang="ts">
/**
 * 🔁 [FIN-V2 / P6.5] ตัวแปลง "เลขที่เอกสาร" → หน้า detail ของทะเบียนเอกสาร
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ทำไมยังมีหน้านี้
 * ═══════════════════════════════════════════════════════════════════════════
 * ลิงก์ที่แชร์ออกไปแล้ว (Discord, ใบเสร็จที่พิมพ์, บุ๊กมาร์ก) อยู่นอกระบบเรา —
 * `/finance/receipts/REC-2569-0042` ต้องทำงานต่อ ไม่ใช่ 404
 * ⇒ route เก่าคงไว้ แต่ component เปลี่ยนเป็น "แปลงแล้วพาไป" ไม่ใช่หน้าจอเดิม
 *
 * 🔑 กติกาที่ห้ามพลาด
 *  1. backend เป็นผู้บอก (`doc_type`, `doc_id`) ผ่าน `GET /finance/documents/by-no/{doc_no}`
 *     — **ห้ามเดาจาก prefix ของเลข** (CERT 4 ตัวอักษร / RPT ไม่มีเลขก่อน finalized)
 *  2. `router.replace` ไม่ใช่ `push` — ปุ่ม back ต้องไม่วนกลับมาที่ redirect
 *  3. 404 = "ไม่พบเอกสารเลขที่นี้" + ทางออกไปทะเบียน (ไม่ใช่ error กลาง ๆ ที่ผู้ใช้แก้ไม่ได้)
 *  4. รับได้ทั้ง `:receiptNo` (route เก่า) และ `:docNo` (route ใหม่ `/finance/documents/by-no/...`)
 *
 * @example route
 *   path: '/finance/receipts/:receiptNo'      — legacy deep link
 *   path: '/finance/documents/by-no/:docNo'   — ทางเข้าปกติของโค้ดใหม่
 */
import { onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import StateBlock from '@/components/ui/StateBlock.vue'

import { FinanceService } from '@/services/finance'
import { apiStatus } from '@/services/api'
import { useAuthStore } from '@/stores/auth'
import { createLatestGuard } from '@/utils/latest'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const isLoading = ref(true)
const hasError = ref(false)
const notFound = ref(false)
/** เลขที่ผู้ใช้ขอ — ใช้แสดงใน empty state (ไม่ใช่ `route.params` หลัง unmount) */
const requestedNo = ref('')

const guard = createLatestGuard()

const readParam = (): string => {
  const raw = route.params.docNo ?? route.params.receiptNo
  const value = Array.isArray(raw) ? (raw[0] ?? '') : raw
  return value ?? ''
}

const load = async () => {
  const docNo = readParam()
  requestedNo.value = docNo
  const token = guard.begin()
  isLoading.value = true
  hasError.value = false
  notFound.value = false
  try {
    const roomId = authStore.currentRoomId
    if (!roomId) throw new Error('ไม่พบห้องปัจจุบัน')
    const doc = await FinanceService.resolveDocumentByNo(roomId, docNo)
    if (!guard.isCurrent(token)) return
    await router.replace({
      name: 'finance-document-detail',
      params: { docType: doc.doc_type, docId: String(doc.doc_id) },
    })
  } catch (error: unknown) {
    if (!guard.isCurrent(token)) return
    if (apiStatus(error) === 404) notFound.value = true
    else hasError.value = true
  } finally {
    if (guard.isCurrent(token)) isLoading.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="space-y-4">
    <SkeletonRows v-if="isLoading" :rows="2" height="h-20" />

    <StateBlock
      v-else-if="notFound"
      variant="empty"
      icon="bi-file-earmark-x"
      title="ไม่พบเอกสารเลขที่นี้"
      :hint="`ไม่พบเอกสาร ${requestedNo} ในทะเบียนของห้องนี้ — อาจถูกพิมพ์ผิด หรืออยู่ในห้องอื่น`"
    >
      <RouterLink to="/finance/documents" class="btn-ghost-ui">
        <i class="bi bi-archive" aria-hidden="true"></i>
        เปิดทะเบียนเอกสาร
      </RouterLink>
    </StateBlock>

    <StateBlock v-else-if="hasError" variant="error" @retry="load" />
  </div>
</template>
