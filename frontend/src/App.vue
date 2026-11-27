<script setup lang="ts">
import { Toast, ToastDescription, ToastRegion, ToastTitle } from '@ui-sdk/vue/toast'
</script>

<template>
  <a href="#main-content" class="skip-link">Skip to main content</a>
  <router-view />
  <ToastRegion side="bottom" align="end">
    <Toast>
      <div>
        <ToastTitle />
        <ToastDescription />
      </div>
    </Toast>
  </ToastRegion>
</template>
