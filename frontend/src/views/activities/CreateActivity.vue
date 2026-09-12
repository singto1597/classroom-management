<script setup lang="ts">
import { useRouter } from 'vue-router'
import ActivityForm from '@/components/activities/ActivityForm.vue'

const router = useRouter()
</script>

<template>
  <!-- Wrapper เท่านั้น — หัวหน้า/ฟอร์มอยู่ใน ActivityForm -->
  <div class="space-y-4 sm:space-y-5">
    <ActivityForm mode="create" @saved="router.push('/activities')" />
  </div>
</template>
