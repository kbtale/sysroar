import { defineStore } from 'pinia'
import axios from 'axios'
import { useTelemetryStore } from './telemetry'

export interface User {
  id: string
  username: string
  email: string
  company_id: string | null
  company_name: string | null
  is_superuser: boolean
}

axios.defaults.withCredentials = true
axios.defaults.xsrfCookieName = 'csrftoken'
axios.defaults.xsrfHeaderName = 'X-CSRFToken'

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
      const isAuthBootstrap =
        requestUrl.includes('/api/accounts/auth/login/') ||
        requestUrl.includes('/api/accounts/auth/me/') ||
        requestUrl.includes('/api/accounts/auth/csrf/')
      if ((status === 401 || status === 403) && !isAuthBootstrap) {
        const auth = useAuthStore()
        auth.clearSession()
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
    user: null as User | null,
    initialized: false,
  }),
  getters: {
    isAuthenticated: (state) => state.user !== null,
  },
  actions: {
    async ensureCsrf() {
      await axios.get('/api/accounts/auth/csrf/')
    },
    async initAuth() {
      axios.defaults.withCredentials = true
      axios.defaults.xsrfCookieName = 'csrftoken'
      axios.defaults.xsrfHeaderName = 'X-CSRFToken'
      try {
        await this.ensureCsrf()
        const response = await axios.get('/api/accounts/auth/me/')
        this.user = response.data.user
      } catch {
        this.user = null
      } finally {
        this.initialized = true
      }
    },
    async login(username: string, password: string) {
      try {
        await this.ensureCsrf()
        const response = await axios.post('/api/accounts/auth/login/', {
          username,
          password,
        })
        this.user = response.data.user
        this.initialized = true
        return true
      } catch (error) {
        console.error('Login failed', error)
        return false
      }
    },
    clearSession() {
      const telemetry = useTelemetryStore()
      telemetry.disconnectAll()
      this.user = null
    },
    async logout() {
      try {
        await axios.post('/api/accounts/auth/logout/')
      } catch {
        this.user = null
      } finally {
        this.clearSession()
      }
    },
    async logoutAll() {
      try {
        await axios.post('/api/accounts/auth/logout-all/')
      } finally {
        this.clearSession()
      }
    },
  },
})
