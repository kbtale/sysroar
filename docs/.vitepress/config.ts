import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'SysRoar',
  description: 'Self-hosted, multi-tenant server monitoring, uptime checks, smart alerts, and pluggable logs.',
  base: '/sysroar/',
  srcExclude: ['REVIEW_AND_ROADMAP.md'],
  cleanUrls: true,
  themeConfig: {
    nav: [
      { text: 'Install', link: '/install' },
      { text: 'Agent', link: '/agent' },
      { text: 'Alerting', link: '/alerting' },
      { text: 'API', link: '/api' },
    ],
    sidebar: [
      {
        text: 'Getting Started',
        items: [
          { text: 'Overview', link: '/' },
          { text: 'Installation & Demo Mode', link: '/install' },
          { text: 'Upgrading & Backups', link: '/UPGRADING' },
        ],
      },
      {
        text: 'Telemetry & Monitoring',
        items: [
          { text: 'Rust Agent & Open Ingestion', link: '/agent' },
          { text: 'Uptime Checks & Status Pages', link: '/uptime-status' },
          { text: 'Alerting, Grouping & Anomalies', link: '/alerting' },
          { text: 'Pluggable Logs (Loki / ELK)', link: '/logs' },
        ],
      },
      {
        text: 'Reference',
        items: [{ text: 'REST & WebSocket API', link: '/api' }],
      },
    ],
    socialLinks: [{ icon: 'github', link: 'https://github.com/kbtale/sysroar' }],
  },
})
