<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function handleLogin() {
  loading.value = true
  error.value = ''
  const success = await auth.login(username.value, password.value)
  loading.value = false
  
  if (success) {
    router.push('/')
  } else {
    error.value = 'Invalid username or password'
  }
}
</script>

<template>
  <div class="login-container">
    <div class="login-card">
      <div class="logo">
        <span class="roar">SYS</span>ROAR
      </div>
      <h1>Welcome Back</h1>
      <p class="subtitle">Secure infrastructure monitoring</p>
      
      <form @submit.prevent="handleLogin">
        <div class="form-group">
          <label>Username</label>
          <input v-model="username" type="text" placeholder="Enter username" required />
        </div>
        <div class="form-group">
          <label>Password</label>
          <input v-model="password" type="password" placeholder="Enter password" required />
        </div>
        
        <p v-if="error" class="error-msg">{{ error }}</p>
        
        <button type="submit" :disabled="loading">
          {{ loading ? 'Authenticating...' : 'Sign In' }}
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100vh;
  background: radial-gradient(circle at top right, #1e293b, #0f172a);
}

.login-card {
  background: rgba(30, 41, 59, 0.7);
  backdrop-filter: blur(12px);
  padding: 3rem;
  border-radius: 1.5rem;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
  width: 100%;
  max-width: 400px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  text-align: center;
}

.logo {
  font-size: 2rem;
  font-weight: 800;
  letter-spacing: -1px;
  margin-bottom: 2rem;
}

.roar { color: #10b981; }

h1 { margin: 0; font-size: 1.5rem; font-weight: 600; }
.subtitle { color: #94a3b8; margin-top: 0.5rem; margin-bottom: 2.5rem; font-size: 0.875rem; }

.form-group {
  text-align: left;
  margin-bottom: 1.5rem;
}

label {
  display: block;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #94a3b8;
  margin-bottom: 0.5rem;
  font-weight: 700;
}

input {
  width: 100%;
  box-sizing: border-box;
  padding: 0.75rem 1rem;
  background: #0f172a;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 0.75rem;
  color: white;
  font-size: 1rem;
  transition: all 0.2s ease;
}

input:focus {
  outline: none;
  border-color: #10b981;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.2);
}

.error-msg {
  color: #ef4444;
  font-size: 0.875rem;
  margin-bottom: 1.5rem;
}

button {
  width: 100%;
  padding: 0.75rem;
  background: #10b981;
  color: #0f172a;
  border: none;
  border-radius: 0.75rem;
  font-weight: 700;
  font-size: 1rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

button:hover:not(:disabled) {
  background: #34d399;
  transform: translateY(-1px);
}

button:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}
</style>
