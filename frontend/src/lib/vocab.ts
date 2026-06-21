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
  open_urgent_review: { zh: '紧急审阅', en: 'Open urgent review' },
  freeze_external_publish: { zh: '冻结对外发布', en: 'Freeze external publish' },
  force_audience_recheck: { zh: '强制重查受众', en: 'Force audience recheck' },
  repair_source: { zh: '修复来源', en: 'Repair source' },
  restrict_propagation: { zh: '限制传播', en: 'Restrict propagation' },
  route_to_human_review: { zh: '转人工审阅', en: 'Route to human review' },
  publish: { zh: '发布', en: 'Publish' },
  republish: { zh: '重发', en: 'Republish' },
  check_propagation_status: { zh: '检查传播状态', en: 'Check propagation' },
  resolve_surface_hold: { zh: '解除暂停', en: 'Resolve hold' },
  inspect_feedback_sessions: { zh: '检查反馈会话', en: 'Inspect feedback' },
  recheck_propagation: { zh: '复查传播', en: 'Recheck propagation' },
  repair_source_chain: { zh: '修复来源链', en: 'Repair source chain' },
}

const BLAST_EFFECT: Record<string, Pair> = {
  new_exposure: { zh: '新增暴露', en: 'New exposure' },
  continuing_exposure: { zh: '持续暴露', en: 'Continuing' },
  stopped_exposure: { zh: '停止暴露', en: 'Stopped' },
  conflict: { zh: '冲突阻断', en: 'Conflict' },
}

const PROP_STATUS: Record<string, Pair> = {
  synced: { zh: '已同步', en: 'Synced' },
  pending: { zh: '待确认', en: 'Pending' },
  failed: { zh: '阻断', en: 'Failed' },
  manual_action_required: { zh: '需人工', en: 'Manual action' },
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

const RECOVERY_ASSESSMENT: Record<string, Pair> = {
  recovery_incomplete: { zh: '恢复未完成', en: 'Recovery incomplete' },
  recovery_confirmed: { zh: '恢复确认', en: 'Recovery confirmed' },
  false_recovery: { zh: '假性恢复', en: 'False recovery' },
  drift_rebound: { zh: '漂移反弹', en: 'Drift rebound' },
}

const RECOVERY_DECISION: Record<string, Pair> = {
  continue_with_lightweight_follow_up: { zh: '继续轻量跟进', en: 'Continue w/ follow-up' },
  close_and_monitor: { zh: '关闭并监控', en: 'Close & monitor' },
  reopen_drift_route: { zh: '重开漂移路径', en: 'Reopen drift route' },
}

const FEEDBACK_SIGNAL: Record<string, Pair> = {
  copilot_accepted: { zh: 'Copilot 采纳', en: 'Copilot accepted' },
  human_rewrite: { zh: '人工重写', en: 'Human rewrite' },
  reject_after_suggestion: { zh: '建议后拒绝', en: 'Reject after suggestion' },
  escalation_after_suggestion: { zh: '建议后升级', en: 'Escalation after suggestion' },
  unresolved_conversation: { zh: '未解决对话', en: 'Unresolved conversation' },
}

const TRUTH_PLANE: Record<string, Pair> = {
  misaligned: { zh: '错位', en: 'Misaligned' },
  partial: { zh: '部分对齐', en: 'Partial' },
  aligned: { zh: '已对齐', en: 'Aligned' },
  split_brain: { zh: '分裂态', en: 'Split brain' },
}

const SEVERITY: Record<string, Pair> = {
  critical: { zh: '严重', en: 'Critical' },
  elevated: { zh: '升高', en: 'Elevated' },
  emerging: { zh: '新兴', en: 'Emerging' },
  watch: { zh: '观察', en: 'Watch' },
}

const METRIC_STATUS: Record<string, Pair> = {
  improved: { zh: '改善', en: 'Improved' },
  worsened: { zh: '恶化', en: 'Worsened' },
  flat: { zh: '持平', en: 'Flat' },
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
  const audienceFacets = (a: AffectedAudience): string[] => {
    const out: string[] = []
    a.product_lines.forEach((x) => out.push(pick(PRODUCT_LINE, x, zh)))
    a.plans.forEach((x) => out.push(pick(PLAN, x, zh)))
    a.regions.forEach((x) => out.push(pick(REGION, x, zh)))
    a.languages.forEach((x) => out.push(humanize(x)))
    if (a.is_global) out.push(pick(REGION, 'global', zh))
    return out
  }
  return {
    riskType: (k: string) => pick(RISK_TYPE, k, zh),
    command: (k: string) => pick(COMMAND, k, zh),
    surface: (k: string) => pick(SURFACE, k, zh),
    objectType: (k: string) => pick(OBJECT_TYPE, k, zh),
    visibility: (k: string) => pick(VISIBILITY, k, zh),
    blastEffect: (k: string) => pick(BLAST_EFFECT, k, zh),
    propStatus: (k: string) => pick(PROP_STATUS, k, zh),
    recoveryAssessment: (k: string) => pick(RECOVERY_ASSESSMENT, k, zh),
    recoveryDecision: (k: string) => pick(RECOVERY_DECISION, k, zh),
    feedbackSignal: (k: string) => pick(FEEDBACK_SIGNAL, k, zh),
    truthPlane: (k: string) => pick(TRUTH_PLANE, k, zh),
    severity: (k: string) => pick(SEVERITY, k, zh),
    metricStatus: (k: string) => pick(METRIC_STATUS, k, zh),
    audienceSegment,
    audienceFacets,
  }
}
