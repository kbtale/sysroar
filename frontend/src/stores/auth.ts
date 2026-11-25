import { defineStore } from 'pinia'
import axios from 'axios'
import { useTelemetryStore } from './telemetry'

interface User {
  id: string
  username: string
  company: string
}

let responseInterceptorId: number | null = null

export function ejectAuthInterceptor() {
  if (responseInterceptorId !== null) {
    axios.interceptors.response.eject(responseInterceptorId)
    responseInterceptorId = null
  }
}

export function setupAuthInterceptor(onUnauthorized?: () => void) {
  ejectAuthInterceptor()
  responseInterceptorId = axios.interceptors.response.use(
    (response) => response,
    (error) => {
      const status = error?.response?.status
      const requestUrl: string = error?.config?.url || ''
      if (status === 401 && !requestUrl.includes('/api/accounts/auth/login/')) {
        const auth = useAuthStore()
        auth.logout()
        if (onUnauthorized) {
          onUnauthorized()
        }
      }
      return Promise.reject(error)
    },
  )
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
    initAuth() {
      const storedToken = localStorage.getItem('sysroar_token')
      this.token = storedToken
      if (storedToken) {
        axios.defaults.headers.common['Authorization'] = `Token ${storedToken}`
      } else {
        delete axios.defaults.headers.common['Authorization']
      }
    },
    async login(username: string, password: string) {
      try {
        const response = await axios.post('/api/accounts/auth/login/', {
          username,
          password,
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
      const telemetry = useTelemetryStore()
      telemetry.disconnectAll()
      this.token = null
      this.user = null
      localStorage.removeItem('sysroar_token')
      delete axios.defaults.headers.common['Authorization']
    },
  },
})
