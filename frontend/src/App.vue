<script setup lang="ts">
// พื้นฐานพื้นหลัง/ฟอนต์ถูกกำหนดที่ src/assets/main.css ทั้งหมด
// (ไม่ประกาศซ้ำที่นี่ เพื่อกันสีพื้นหลังชนกันหลายชั้น)
import { RouterView } from 'vue-router';
import AppDialogHost from '@/components/ui/AppDialogHost.vue';
</script>

<template>
  <RouterView />
  <!-- กล่องสนทนา/ข้อความแจ้งเตือนกลาง — ใช้ได้ทุกหน้า ไม่ผูกกับ layout -->
  <AppDialogHost />
</template>
