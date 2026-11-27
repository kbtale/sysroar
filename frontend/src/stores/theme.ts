import { defineStore } from 'pinia'

export type ThemeMode = 'dark' | 'light'

const STORAGE_KEY = 'sysroar_theme'

function applyThemeToDom(mode: ThemeMode) {
  if (typeof document === 'undefined') {
    return
  }
  document.documentElement.dataset.theme = mode
  document.documentElement.style.colorScheme = mode
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) {
    meta.setAttribute('content', mode === 'dark' ? '#0b0f17' : '#f8fafc')
  }
}

export const useThemeStore = defineStore('theme', {
  state: () => ({
    mode: 'dark' as ThemeMode,
  }),
  getters: {
    isDark: (state) => state.mode === 'dark',
  },
  actions: {
    initTheme() {
      const saved = typeof localStorage !== 'undefined' ? localStorage.getItem(STORAGE_KEY) : null
      const preferred: ThemeMode =
        saved === 'light' || saved === 'dark'
          ? saved
          : typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: light)').matches
            ? 'light'
            : 'dark'
      this.setTheme(preferred)
    },
    setTheme(mode: ThemeMode) {
      this.mode = mode
      if (typeof localStorage !== 'undefined') {
        localStorage.setItem(STORAGE_KEY, mode)
      }
      applyThemeToDom(mode)
    },
    toggleTheme() {
      this.setTheme(this.mode === 'dark' ? 'light' : 'dark')
    },
  },
})
