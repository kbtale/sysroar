import { defineStore } from 'pinia'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('sysroar_token') || null,
    user: null,
  }),
  actions: {
    setToken(token: string) {
      this.token = token
      localStorage.setItem('sysroar_token', token)
    },
    logout() {
      this.token = null
      localStorage.removeItem('sysroar_token')
    }
  }
})
