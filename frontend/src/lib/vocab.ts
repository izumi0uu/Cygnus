import { useTranslation } from 'react-i18next'
import type { AffectedAudience } from '@/lib/api'

// Frontend product vocabulary: maps STABLE backend identifiers/enums -> human {zh,en}.
// The backend keeps English identifiers (stable contract); the frontend owns the label.
type Pair = { zh: string; en: string }

const RISK_TYPE: Record<string, Pair> = {
  source_blindness: { zh: '来源失明', en: 'Source blindness' },
  drift: { zh: '答案漂移', en: 'Answer drift' },
  audience_mismatch: { zh: '受众错配', en: 'Audience mismatch' },
  ticket_pressure: { zh: '工单压力', en: 'Ticket pressure' },
  policy_conflict: { zh: '策略冲突', en: 'Policy conflict' },
  owner_gap: { zh: '责任缺口', en: 'Owner gap' },
}

const COMMAND: Record<string, Pair> = {
  open_review: { zh: '开始审阅', en: 'Open review' },
  restrict_publish: { zh: '限制发布', en: 'Restrict publish' },
  assign_owner: { zh: '指派责任人', en: 'Assign owner' },
  request_more_evidence: { zh: '补充证据', en: 'Request evidence' },
  refresh_sources: { zh: '刷新来源', en: 'Refresh sources' },
  mark_urgent: { zh: '标记紧急', en: 'Mark urgent' },
  split_variant: { zh: '拆分变体', en: 'Split variant' },
  hold_external: { zh: '暂停对外', en: 'Hold external' },
  republish_internal_only: { zh: '仅内部重发', en: 'Republish internal' },
  escalate: { zh: '升级', en: 'Escalate' },
  approve: { zh: '批准', en: 'Approve' },
  reject: { zh: '驳回', en: 'Reject' },
}

const SURFACE: Record<string, Pair> = {
  help_center: { zh: '帮助中心', en: 'Help Center' },
  copilot: { zh: 'Copilot', en: 'Copilot' },
  macro: { zh: '宏回复', en: 'Macro' },
  'queue-sidebar': { zh: '队列侧栏', en: 'Queue sidebar' },
  queue_sidebar: { zh: '队列侧栏', en: 'Queue sidebar' },
}

const OBJECT_TYPE: Record<string, Pair> = {
  known_issue_page: { zh: '已知问题页', en: 'Known issue page' },
  answer_card: { zh: '答案卡', en: 'Answer card' },
  troubleshooting_flow: { zh: '排障流', en: 'Troubleshooting flow' },
  policy_rule: { zh: '策略规则', en: 'Policy rule' },
  escalation_route: { zh: '升级路径', en: 'Escalation route' },
  audience_variant: { zh: '受众变体', en: 'Audience variant' },
}

const VISIBILITY: Record<string, Pair> = {
  external: { zh: '对外', en: 'External' },
  internal: { zh: '对内', en: 'Internal' },
}

const PLAN: Record<string, Pair> = {
  enterprise: { zh: '企业版', en: 'Enterprise' },
  free: { zh: '免费版', en: 'Free' },
  pro: { zh: '专业版', en: 'Pro' },
  team: { zh: '团队版', en: 'Team' },
}

const REGION: Record<string, Pair> = {
  eu: { zh: '欧盟', en: 'EU' },
  us: { zh: '美国', en: 'US' },
  apac: { zh: '亚太', en: 'APAC' },
  global: { zh: '全球', en: 'Global' },
}

const PRODUCT_LINE: Record<string, Pair> = {
  billing: { zh: '计费', en: 'Billing' },
  onboarding: { zh: '入门', en: 'Onboarding' },
  security: { zh: '安全', en: 'Security' },
}

function humanize(key: string): string {
  return key.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}
function pick(dict: Record<string, Pair>, key: string, zh: boolean): string {
  const p = dict[key]
  return p ? (zh ? p.zh : p.en) : humanize(key)
}

export function useVocab() {
  const { i18n } = useTranslation()
  const zh = i18n.language.startsWith('zh')
  const audienceSegment = (a: AffectedAudience): string => {
    const parts: string[] = [pick(VISIBILITY, a.visibility, zh)]
    a.product_lines.forEach((x) => parts.push(pick(PRODUCT_LINE, x, zh)))
    a.plans.forEach((x) => parts.push(pick(PLAN, x, zh)))
    a.regions.forEach((x) => parts.push(pick(REGION, x, zh)))
    a.languages.forEach((x) => parts.push(humanize(x)))
    if (a.is_global) parts.push(pick(REGION, 'global', zh))
    return parts.join(' · ')
  }
  return {
    riskType: (k: string) => pick(RISK_TYPE, k, zh),
    command: (k: string) => pick(COMMAND, k, zh),
    surface: (k: string) => pick(SURFACE, k, zh),
    objectType: (k: string) => pick(OBJECT_TYPE, k, zh),
    visibility: (k: string) => pick(VISIBILITY, k, zh),
    audienceSegment,
  }
}
