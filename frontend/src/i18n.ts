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
    landing: {
      eyebrow: 'Support Brain · 支持知识操作系统',
      default: '支持知识',
      sub: '把分散的支持知识收归为可信、可治理、可追溯的知识对象 —— 给人与 AI 一个统一的来源。',
      enter: '进入指挥中心',
      docs: '查看文档',
    },
    horizon: { risks: '治理风险', urgent: '紧急', ownerGaps: '责任缺口', surfaces: '下游面', cycle: 'CYCLE · 晨间简报' },
    ribbon: { open: '未关闭', top: '最高风险', pending: '{{urgent}} 紧急 · {{gaps}} 责任缺口 待命令' },
    nav: { govGroup: '治理', obsGroup: '观测', reviewQueue: '审阅队列', objects: '知识对象', sources: '来源与证据', audience: '受众与发布', drift: '覆盖与漂移', propagation: '传播账本', audit: '审计' },
    queue: { subtitle: 'REVIEW QUEUE · 晨间简报', search: '搜索风险 / 对象…', all: '全部', urgent: '紧急', unassigned: '无主', sort: '排序：风险', command: '发命令', statRisks: '治理风险', statSurfaces: '下游面', thUrgency: '紧急度', thRisk: '风险', thScope: '作用域', thOwner: '责任人', thCommand: '主命令', scopeFmt: '{{a}} 受众 · {{s}} 面', soon: '此区建设中' },
    detail: {
      whyNow: '为什么现在重要',
      scope: '作用域 / 爆炸半径',
      audiences: '受影响受众',
      surfaces: '下游面',
      owner: '责任人',
      unassigned: '无人负责',
      commands: '可发命令',
      commandNote: '命令执行需打通写路径（后续接入治理内核）',
      close: '关闭',
    },
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
    landing: {
      eyebrow: 'Support Brain · Support Knowledge OS',
      default: 'SUPPORT',
      sub: 'Compile scattered support knowledge into trusted, governable, traceable objects — one source for humans and AI.',
      enter: 'Enter Console',
      docs: 'View Docs',
    },
    horizon: { risks: 'risks', urgent: 'urgent', ownerGaps: 'owner gaps', surfaces: 'surfaces', cycle: 'CYCLE · MORNING BRIEF' },
    ribbon: { open: 'OPEN', top: 'top risk', pending: '{{urgent}} urgent · {{gaps}} owner gaps pending' },
    nav: { govGroup: 'Governance', obsGroup: 'Observe', reviewQueue: 'Review Queue', objects: 'Knowledge Objects', sources: 'Sources & Evidence', audience: 'Audience & Publish', drift: 'Coverage & Drift', propagation: 'Propagation', audit: 'Audit' },
    queue: { subtitle: 'REVIEW QUEUE · MORNING BRIEF', search: 'Search risks / objects…', all: 'All', urgent: 'Urgent', unassigned: 'Unassigned', sort: 'Sort: risk', command: 'Command', statRisks: 'risks', statSurfaces: 'surfaces', thUrgency: 'urgency', thRisk: 'risk', thScope: 'scope', thOwner: 'owner', thCommand: 'command', scopeFmt: '{{a}} aud · {{s}} surf', soon: 'Section under construction' },
    detail: {
      whyNow: 'Why now',
      scope: 'Scope / blast radius',
      audiences: 'Affected audiences',
      surfaces: 'Affected surfaces',
      owner: 'Owner',
      unassigned: 'unassigned',
      commands: 'Commands',
      commandNote: 'Command execution needs the write path (kernel wiring, next)',
      close: 'Close',
    },
  },
}

i18n.use(initReactI18next).init({
  resources: { zh, en },
  lng: localStorage.getItem('cygnus-lang') || 'zh',
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
})

export default i18n
