import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

const zh = {
  translation: {
    app: { surface: '指挥中心', brief: '晨间简报' },
    frame: { label: '态势简报', urgent: '紧急', ownerGaps: '责任缺口', tension: '首要张力' },
    stack: { label: '优先级栈', note: '按风险重排，而非按时间' },
    urgency: { urgent: '紧急', high: '高', medium: '中', low: '低' },
    owner: { gap: '责任缺口', assigned: '负责人' },
    commands: { label: '可用命令' },
    state: {
      loading: '正在加载指挥简报…',
      error: '无法连接 Cygnus API。请确认后端已启动：uvicorn cygnus.api.app:app --port 8077',
      retry: '重试',
      empty: '当前没有待处理的治理风险',
    },
    toggle: { theme: '主题', system: '跟随系统', light: '浅色', dark: '深色' },
  },
}

const en = {
  translation: {
    app: { surface: 'Command Center', brief: 'Morning Brief' },
    frame: { label: 'Situation Frame', urgent: 'urgent', ownerGaps: 'owner gaps', tension: 'Primary tension' },
    stack: { label: 'Priority Stack', note: 'risk-ranked, not by time' },
    urgency: { urgent: 'urgent', high: 'high', medium: 'medium', low: 'low' },
    owner: { gap: 'owner gap', assigned: 'owner' },
    commands: { label: 'Available commands' },
    state: {
      loading: 'Loading command brief…',
      error: 'Cannot reach the Cygnus API. Start the backend: uvicorn cygnus.api.app:app --port 8077',
      retry: 'Retry',
      empty: 'No governance risks pending right now',
    },
    toggle: { theme: 'Theme', system: 'System', light: 'Light', dark: 'Dark' },
  },
}

i18n.use(initReactI18next).init({
  resources: { zh, en },
  lng: localStorage.getItem('cygnus-lang') || 'zh',
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
})

export default i18n
