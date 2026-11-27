import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { VueQueryPlugin } from '@tanstack/vue-query'
import router from './router'
import App from './App.vue'
import './style.css'
import { setupAuthInterceptor, useAuthStore } from './stores/auth'
import { useThemeStore } from './stores/theme'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(VueQueryPlugin, {
  queryClientConfig: {
    defaultOptions: {
      queries: {
        staleTime: 10_000,
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  },
})

const theme = useThemeStore(pinia)
theme.initTheme()

const auth = useAuthStore(pinia)
setupAuthInterceptor(() => {
  if (router.currentRoute.value.path !== '/login' && router.currentRoute.value.path !== '/setup') {
    router.push('/login')
  }
})

auth.initAuth().finally(() => {
  app.use(router)
  app.mount('#app')
})
