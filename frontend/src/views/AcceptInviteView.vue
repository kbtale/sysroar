<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Activity, Eye, EyeOff } from 'lucide-vue-next'
import { Button } from '@ui-sdk/vue/button'
import { Field, FieldLabel } from '@ui-sdk/vue/field'
import { Input } from '@ui-sdk/vue/input'
import {
  PasswordInput,
  PasswordInputControl,
  PasswordInputToggle,
} from '@ui-sdk/vue/password-input'
import { toast } from '@ui-sdk/vue/toast'
import { extractApiError } from '../api/client'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const token = ref(typeof route.query.token === 'string' ? route.query.token : '')
const username = ref('')
const password = ref('')
const error = ref('')
const submitting = ref(false)

async function handleAccept() {
  submitting.value = true
  error.value = ''
  try {
    await auth.acceptInvite({
      token: token.value.trim(),
      username: username.value.trim(),
      password: password.value,
    })
    toast.success('Invitation accepted')
    router.push('/')
  } catch (err) {
    error.value = extractApiError(err, 'Invite token is invalid or expired.')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <main id="main-content" class="auth-page">
    <section class="auth-card card">
      <div class="auth-brand" translate="no">
        <Activity class="brand-icon" :size="24" aria-hidden="true" />
        <span class="brand-accent">SYS</span><span>ROAR</span>
      </div>
      <h1>Accept Team Invite</h1>
      <p class="auth-sub">Set your username and password to join the workspace.</p>

      <form class="auth-form" @submit.prevent="handleAccept">
        <Field name="token">
          <FieldLabel>Invite Token</FieldLabel>
          <Input v-model="token" :spellcheck="false" placeholder="sri_…" required />
        </Field>

        <Field name="username">
          <FieldLabel>Username</FieldLabel>
          <Input
            v-model="username"
            autocomplete="username"
            :spellcheck="false"
            placeholder="alex…"
            required
          />
        </Field>

        <Field name="password">
          <FieldLabel>Password</FieldLabel>
          <PasswordInput v-model="password" auto-complete="new-password" required>
            <PasswordInputControl placeholder="Minimum 8 characters…" />
            <PasswordInputToggle v-slot="{ state }" aria-label="Show password">
              <EyeOff v-if="state.visible" :size="16" aria-hidden="true" />
              <Eye v-else :size="16" aria-hidden="true" />
            </PasswordInputToggle>
          </PasswordInput>
        </Field>

        <p v-if="error" class="banner-error" role="alert">{{ error }}</p>

        <Button type="submit" data-variant="solid" :disabled="submitting">
          {{ submitting ? 'Joining…' : 'Join Workspace' }}
        </Button>
      </form>
    </section>
  </main>
</template>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px 16px;
}

.auth-card {
  width: min(440px, 100%);
  padding: 32px;
}

.auth-brand {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 1.25rem;
  font-weight: 800;
  margin-bottom: 20px;
}

.brand-icon,
.brand-accent {
  color: var(--accent);
}

h1 {
  font-size: 1.5rem;
  margin-bottom: 6px;
}

.auth-sub {
  margin: 0 0 24px;
  color: var(--ink-muted);
  font-size: 0.875rem;
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
</style>
