import { defineStore } from 'pinia'
import axios from 'axios'
import { useTelemetryStore } from './telemetry'

export type CompanyRole = 'owner' | 'admin' | 'member' | 'viewer'

export interface User {
  id: string
  username: string
  email: string
  role: CompanyRole
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
        requestUrl.includes('/api/accounts/auth/csrf/') ||
        requestUrl.includes('/api/accounts/setup/') ||
        requestUrl.includes('/api/accounts/invites/accept/')
      if ((status === 401 || status === 403) && !isAuthBootstrap) {
        const auth = useAuthStore()
        if (status === 401) {
          auth.clearSession()
          if (onUnauthorized) {
            onUnauthorized()
          }
        }
      }
      return Promise.reject(error)
    },
  )
}

const ROLE_RANK: Record<CompanyRole, number> = {
  viewer: 1,
  member: 2,
  admin: 3,
  owner: 4,
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as User | null,
    initialized: false,
    needsSetup: false,
    openRegistration: false,
  }),
  getters: {
    isAuthenticated: (state) => state.user !== null,
    canWrite: (state) => {
      if (!state.user) return false
      if (state.user.is_superuser) return true
      return (ROLE_RANK[state.user.role] ?? 0) >= ROLE_RANK.member
    },
    isAdmin: (state) => {
      if (!state.user) return false
      if (state.user.is_superuser) return true
      return (ROLE_RANK[state.user.role] ?? 0) >= ROLE_RANK.admin
    },
  },
  actions: {
    async ensureCsrf() {
      await axios.get('/api/accounts/auth/csrf/')
    },
    async fetchSetupStatus() {
      try {
        const response = await axios.get('/api/accounts/setup/status/')
        this.needsSetup = Boolean(response.data?.needs_setup)
        this.openRegistration = Boolean(response.data?.open_registration)
      } catch {
        this.needsSetup = false
      }
    },
    async initAuth() {
      axios.defaults.withCredentials = true
      axios.defaults.xsrfCookieName = 'csrftoken'
      axios.defaults.xsrfHeaderName = 'X-CSRFToken'
      try {
        await this.ensureCsrf()
        await this.fetchSetupStatus()
        if (!this.needsSetup) {
          const response = await axios.get('/api/accounts/auth/me/')
          this.user = response.data.user
        } else {
          this.user = null
        }
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
        this.needsSetup = false
        this.initialized = true
        return true
      } catch {
        return false
      }
    },
    async completeSetup(payload: { company_name: string; username: string; email: string; password: string }) {
      await this.ensureCsrf()
      const response = await axios.post('/api/accounts/setup/', payload)
      this.user = response.data.user
      this.needsSetup = false
      this.initialized = true
      return response.data
    },
    async acceptInvite(payload: { token: string; username: string; password: string }) {
      await this.ensureCsrf()
      const response = await axios.post('/api/accounts/invites/accept/', payload)
      this.user = response.data.user
      this.needsSetup = false
      this.initialized = true
      return response.data
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
