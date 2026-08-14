<script setup lang="ts">
import { useRouter } from 'vue-router'
import ActivityForm from '@/components/activities/ActivityForm.vue'

const router = useRouter()
</script>

<template>
  <ActivityForm mode="create" @saved="router.push('/activities')" />
</template>
