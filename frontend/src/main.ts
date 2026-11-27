import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import App from './App.vue'
import './style.css'
import { setupAuthInterceptor, useAuthStore } from './stores/auth'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)

const auth = useAuthStore(pinia)
setupAuthInterceptor(() => {
  if (router.currentRoute.value.path !== '/login') {
    router.push('/login')
  }
})

auth.initAuth().finally(() => {
  app.use(router)
  app.mount('#app')
})
