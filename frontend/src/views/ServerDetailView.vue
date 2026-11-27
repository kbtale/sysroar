<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()
</script>

<template>
  <section class="page-head">
    <h1>Server Detail</h1>
    <p class="muted mono">{{ route.params.id }}</p>
  </section>
</template>

<style scoped>
.muted {
  color: var(--ink-muted);
}
</style>
