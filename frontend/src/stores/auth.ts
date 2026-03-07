import { defineStore } from 'pinia'
import axios from 'axios'

interface User {
  id: string
  username: string
  company: string
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('sysroar_token') || null,
    user: null as User | null,
  }),
  getters: {
    isAuthenticated: (state) => !!state.token,
  },
  actions: {
    async login(username: string, password: string) {
      try {
        const response = await axios.post('/api/accounts/auth/login/', {
          username,
          password
        })
        const token = response.data.token
        this.setToken(token)
        return true
      } catch (error) {
        console.error('Login failed', error)
        return false
      }
    },
    setToken(token: string) {
      this.token = token
      localStorage.setItem('sysroar_token', token)
      axios.defaults.headers.common['Authorization'] = `Token ${token}`
    },
    logout() {
      this.token = null
      this.user = null
      localStorage.removeItem('sysroar_token')
      delete axios.defaults.headers.common['Authorization']
    }
  }
})
