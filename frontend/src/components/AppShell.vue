<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Activity,
  Bell,
  ChevronDown,
  Globe,
  LogOut,
  Menu as MenuIcon,
  Moon,
  Server,
  Settings,
  ShieldAlert,
  Sun,
} from 'lucide-vue-next'
import {
  Drawer,
  DrawerBackdrop,
  DrawerClose,
  DrawerContent,
  DrawerTitle,
  DrawerTrigger,
} from '@ui-sdk/vue/drawer'
import { Menu, MenuContent, MenuItem, MenuSeparator, MenuTrigger } from '@ui-sdk/vue/menu'
import { Switch, SwitchThumb } from '@ui-sdk/vue/switch'
import { toast } from '@ui-sdk/vue/toast'
import { useAuthStore } from '../stores/auth'
import { useTelemetryStore } from '../stores/telemetry'
import { useThemeStore } from '../stores/theme'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const telemetry = useTelemetryStore()
const theme = useThemeStore()
const mobileNavOpen = ref(false)

onMounted(() => {
  if (auth.isAuthenticated) {
    telemetry.connect()
  }
})

onUnmounted(() => {
  telemetry.disconnectAll()
})

const navItems = [
  { to: '/', label: 'Fleet', icon: Server, match: (path: string) => path === '/' || path.startsWith('/servers/') },
  { to: '/uptime', label: 'Uptime', icon: Globe, match: (path: string) => path.startsWith('/uptime') },
  { to: '/alerts', label: 'Alerts', icon: Bell, match: (path: string) => path.startsWith('/alerts') },
  { to: '/settings', label: 'Settings', icon: Settings, match: (path: string) => path.startsWith('/settings') },
]

async function handleUserAction(action: string) {
  if (action === 'settings') {
    router.push('/settings')
    return
  }
  if (action === 'logout') {
    await auth.logout()
    router.push('/login')
    return
  }
  if (action === 'logout-all') {
    await auth.logoutAll()
    toast.success('Signed out from all devices')
    router.push('/login')
  }
}

function handleThemeToggle(checked: boolean) {
  theme.setTheme(checked ? 'dark' : 'light')
}
</script>

<template>
  <div class="app-shell">
    <aside class="desktop-sidebar" aria-label="Primary navigation">
      <div class="brand-row">
        <router-link to="/" class="brand-link" translate="no">
          <Activity class="brand-icon" :size="20" aria-hidden="true" />
          <span class="brand-accent">SYS</span><span>ROAR</span>
        </router-link>
        <span v-if="auth.user?.company_name" class="company-pill" :title="auth.user.company_name">
          {{ auth.user.company_name }}
        </span>
      </div>

      <nav class="nav-list">
        <router-link
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="nav-item"
          :class="{ active: item.match(route.path) }"
        >
          <component :is="item.icon" :size="17" aria-hidden="true" />
          <span>{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <label class="theme-row">
          <span class="theme-label">
            <Moon v-if="theme.isDark" :size="15" aria-hidden="true" />
            <Sun v-else :size="15" aria-hidden="true" />
            <span>Dark mode</span>
          </span>
          <Switch :checked="theme.isDark" @checked-change="handleThemeToggle">
            <SwitchThumb />
          </Switch>
        </label>

        <Menu @action="handleUserAction">
          <MenuTrigger class="user-trigger">
            <div class="user-meta">
              <span class="user-name">{{ auth.user?.username || 'Account' }}</span>
              <span class="user-role">{{ auth.user?.role || 'member' }}</span>
            </div>
            <ChevronDown :size="16" aria-hidden="true" />
          </MenuTrigger>
          <MenuContent side="top" align="start" :side-offset="8">
            <MenuItem value="settings">
              <Settings :size="15" aria-hidden="true" />
              <span>Workspace Settings</span>
            </MenuItem>
            <MenuSeparator />
            <MenuItem value="logout">
              <LogOut :size="15" aria-hidden="true" />
              <span>Sign Out</span>
            </MenuItem>
            <MenuItem value="logout-all">
              <ShieldAlert :size="15" aria-hidden="true" />
              <span>Sign Out Everywhere</span>
            </MenuItem>
          </MenuContent>
        </Menu>
      </div>
    </aside>

    <div class="main-column">
      <header class="mobile-bar">
        <Drawer v-model:open="mobileNavOpen" side="left">
          <DrawerTrigger class="mobile-menu-btn" aria-label="Open navigation menu">
            <MenuIcon :size="20" aria-hidden="true" />
          </DrawerTrigger>
          <DrawerBackdrop />
          <DrawerContent side="left">
            <div class="drawer-head">
              <DrawerTitle class="brand-link" translate="no">
                <Activity class="brand-icon" :size="18" aria-hidden="true" />
                <span class="brand-accent">SYS</span><span>ROAR</span>
              </DrawerTitle>
              <DrawerClose class="btn btn-ghost">Close</DrawerClose>
            </div>
            <nav class="nav-list">
              <router-link
                v-for="item in navItems"
                :key="item.to"
                :to="item.to"
                class="nav-item"
                :class="{ active: item.match(route.path) }"
                @click="mobileNavOpen = false"
              >
                <component :is="item.icon" :size="17" aria-hidden="true" />
                <span>{{ item.label }}</span>
              </router-link>
            </nav>
            <div class="sidebar-footer">
              <label class="theme-row">
                <span class="theme-label">Dark mode</span>
                <Switch :checked="theme.isDark" @checked-change="handleThemeToggle">
                  <SwitchThumb />
                </Switch>
              </label>
              <button type="button" class="btn btn-danger" @click="handleUserAction('logout')">
                <LogOut :size="15" aria-hidden="true" />
                <span>Sign Out</span>
              </button>
            </div>
          </DrawerContent>
        </Drawer>

        <router-link to="/" class="brand-link" translate="no">
          <span class="brand-accent">SYS</span><span>ROAR</span>
        </router-link>
      </header>

      <main id="main-content" class="page-content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  min-height: 100vh;
  background: var(--bg);
}

.desktop-sidebar {
  width: 244px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 20px 14px;
  border-inline-end: 1px solid var(--border);
  background: var(--surface);
}

.brand-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0 8px;
}

.brand-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 1.125rem;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: var(--ink);
  text-decoration: none;
}

.brand-icon,
.brand-accent {
  color: var(--accent);
}

.company-pill {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.75rem;
  color: var(--ink-muted);
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: var(--surface-raised);
  border: 1px solid var(--border);
}

.nav-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border-radius: var(--radius-md);
  color: var(--ink-muted);
  text-decoration: none;
  font-size: 0.875rem;
  font-weight: 500;
  transition: background-color 140ms var(--ease-out), color 140ms var(--ease-out);
}

.nav-item:hover {
  background: var(--surface-hover);
  color: var(--ink);
}

.nav-item.active {
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 600;
}

.sidebar-footer {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.theme-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
  font-size: 0.8125rem;
  color: var(--ink-muted);
  cursor: pointer;
}

.theme-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.user-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 8px 10px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  background: var(--surface-raised);
  color: var(--ink);
  cursor: pointer;
  text-align: left;
}

.user-trigger:hover {
  border-color: var(--border-strong);
  background: var(--surface-hover);
}

.user-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.user-name {
  font-size: 0.8125rem;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-role {
  font-size: 0.72rem;
  color: var(--ink-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.main-column {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.mobile-bar {
  display: none;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}

.mobile-menu-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-strong);
  background: var(--surface-raised);
  color: var(--ink);
  cursor: pointer;
}

.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.page-content {
  flex: 1;
  min-width: 0;
  padding: 24px 28px;
  max-width: 1440px;
  width: 100%;
  margin: 0 auto;
}

@media (max-width: 1024px) {
  .desktop-sidebar {
    display: none;
  }

  .mobile-bar {
    display: flex;
  }

  .page-content {
    padding: 16px;
  }
}
</style>
