import { authApi } from '@/lib/authApi'

export interface AffectedAudience {
  visibility: string
  brands: string[]
  product_lines: string[]
  plans: string[]
  regions: string[]
  languages: string[]
  product_versions: string[]
  is_global: boolean
}

export interface PriorityItem {
  risk_id: string
  title: string
  risk_type: string
  urgency: string
  object_type: string
  object_ref: string
  why_now_summary: string
  audience_labels: string[]
  affected_audiences: AffectedAudience[]
  affected_surfaces: string[]
  owner_state: string
  queue_owner: string | null
  primary_command: string
  command_actions: string[]
}

export interface SituationFrame {
  briefing_note: string
  summary: string
  primary_tension: string
  urgent_items: number
  owner_gaps: number
  affected_surfaces: string[]
  recommended_commands: string[]
}

export interface CommandCenterSurface {
  surface_id: string
  headline: string
  situation_frame: SituationFrame
  priority_stack: PriorityItem[]
  available_commands: string[]
}

export async function fetchCommandCenter(): Promise<CommandCenterSurface> {
  return authApi<CommandCenterSurface>('/api/command-center')
}

export type GraphNodeKind = 'object' | 'evidence' | 'audience'

export interface KnowledgeGraphNode {
  id: string
  kind: GraphNodeKind
  label: string
  object_type?: string
  lifecycle_state?: string
  summary?: string
  source_type?: string
  freshness?: string
  source_ref?: string
  visibility?: string
  is_global?: boolean
}

export interface KnowledgeGraphEdge {
  source: string
  target: string
  kind: 'cites' | 'serves' | 'escalates_to'
}

export interface KnowledgeGraph {
  nodes: KnowledgeGraphNode[]
  edges: KnowledgeGraphEdge[]
  stats: { objects: number; evidence: number; audiences: number; edges: number }
}

export async function fetchKnowledgeGraph(): Promise<KnowledgeGraph> {
  return authApi<KnowledgeGraph>('/api/knowledge-graph')
}

// ============================================================
// Traceability — object → evidence → source → freshness chain.
// The product invariant "traceability first": every answer one
// click from its grounding evidence, source, and freshness state.
// ============================================================

export interface TraceEvidenceRef {
  evidence_id: string
  scope: string
  source_type: string
  source_ref: string
  title: string
  freshness: string // fresh | stale | unknown
  excerpt_ref: string
  updated_at: string | null
}

export interface TracePublicationRecord {
  channel: string
  publication_state: string
}

export interface TraceReviewHistoryItem {
  stage: string
  status: string
}

export interface SourceTrace {
  object_id: string
  version: number
  freshness: string
  evidence_refs: TraceEvidenceRef[]
  publication_records: TracePublicationRecord[]
  review_history_summary: TraceReviewHistoryItem[]
  blind_spots: string[]
}

export interface TraceabilitySurface {
  surface_id: string
  object: {
    object_id: string
    object_type: string
    title: string
    summary: string
    lifecycle_state: string
    supported_audiences: AffectedAudience[]
    publish_targets: string[]
  }
  trace: SourceTrace
  projection: PublishApplyResult | null
}

export async function fetchTraceability(objectId: string): Promise<TraceabilitySurface> {
  return authApi<TraceabilitySurface>(`/api/traceability/${encodeURIComponent(objectId)}`)
}

export interface DriftContext {
  proposal_ref: string
  title: string
  risk_type: string
  suggested_object_type: string
  urgency: string
  why_now: string
  evidence_ids: string[]
  event_refs: string[]
  event_types: string[]
  trigger_signals: string[]
  affected_audience_labels: string[]
  affected_surfaces: string[]
}

export interface DriftSurface {
  surface_id: string
  headline: string
  summary: string
  contexts: DriftContext[]
  available_commands: string[]
  proposal_lane: string[]
}

export async function fetchDriftSurface(): Promise<DriftSurface> {
  return authApi<DriftSurface>('/api/drift')
}

export interface SourceBlindnessContext {
  proposal_ref: string
  title: string
  risk_type: string
  suggested_object_type: string
  evidence_ids: string[]
  source_refs: string[]
  source_types: string[]
  freshness_states: string[]
  affected_audience_labels: string[]
  affected_surfaces: string[]
  business_consequence: string
  propagation_risk_summary: string
  signal_loss_summary: string
}

export interface SourceBlindnessSurface {
  surface_id: string
  headline: string
  summary: string
  contexts: SourceBlindnessContext[]
  available_commands: string[]
  proposal_lane: string[]
}

export async function fetchSourceBlindnessSurface(): Promise<SourceBlindnessSurface> {
  return authApi<SourceBlindnessSurface>('/api/source-blindness')
}

export interface GovernanceOpenLoop {
  command_id: string
  command_type: string
  object_title: string
  assessment: string
  closeable: boolean
  residual_risk_count: number
  unacceptable_residual_count: number
  pending_propagation_count: number
  pending_propagation_summary: string
  recovery_proof_summary: string
  top_next_command: string
  open_loop_label: string
}

export interface GovernanceOpenLoopRank {
  command_id: string
  label: string
  rank: number
  leverage_score: number
  residual_risk_count: number
  unacceptable_residual_count: number
  pending_propagation_count: number
  recovery_status: string
}

export interface GovernanceOverviewSurface {
  surface_id: string
  headline: string
  summary: string
  open_loops: GovernanceOpenLoop[]
  open_loop_ranks: GovernanceOpenLoopRank[]
  highest_leverage_command: string | null
  next_command_ribbon: string[]
  command_horizon: string[]
  governance_notes: string[]
}

export async function fetchGovernanceOverview(): Promise<GovernanceOverviewSurface> {
  return authApi<GovernanceOverviewSurface>('/api/recovery/overview')
}

export interface ReviewIntakeBundle {
  proposal_id: string
  object_type: string
  action: string
  title: string
  summary: string
  evidence_ids: string[]
  urgency: string
  evidence_sufficiency: string
  review_owner: string
  why_now: string
  audience_notes: string[]
}

export interface ReviewIntakeSurface {
  bundles: ReviewIntakeBundle[]
  review_home: CommandCenterSurface
}

export async function fetchReviewIntake(): Promise<ReviewIntakeSurface> {
  return authApi<ReviewIntakeSurface>('/api/review-intake')
}

// ============================================================
// Publish preview — blast radius before any outward command
// ============================================================

export interface PublishSituationFrame {
  briefing_note: string
  truth_boundary: string
  consequence_summary: string
  blocked_paths: number
  new_paths: number
  stopped_paths: number
  affected_surfaces: string[]
  recommended_commands: string[]
}

export interface PublishActionPreset {
  command_key: string
  summary: string
  reason: string
  audience_labels: string[]
  channels: string[]
  consequence_hint: string
  recommended: boolean
}

export interface PublishActionEcho {
  selected_action: string
  summary: string
  action_log: string[]
  opened_bindings: PublishBinding[]
  removed_bindings: PublishBinding[]
  held_bindings: PublishConflict[]
}

export interface PublishBinding {
  audience_filter: AffectedAudience
  audience_label: string
  channel: string
}

export interface PublishConflict extends PublishBinding {
  reason: string
}

export interface BlastRadiusImpact {
  audience_filter: AffectedAudience
  audience_label: string
  channel: string
  effect: string // new_exposure | continuing_exposure | stopped_exposure | conflict
  reason: string
}

export interface ChannelGateSummary {
  channel: string
  new_exposure: number
  continuing_exposure: number
  stopped_exposure: number
  conflicts: number
}

export interface AudienceScopeSummary {
  total_audiences: number
  visibility_mix: string[]
  audience_labels: string[]
  affected_channels: string[]
}

export interface BlastRadiusPreview {
  object_id: string
  object_type: string
  title: string
  action_type: string
  audience_scope: AudienceScopeSummary
  channel_gate_matrix: ChannelGateSummary[]
  impacts: BlastRadiusImpact[]
  warnings: string[]
}

export interface PublishPreviewSurface {
  surface_id: string
  headline: string
  summary: string
  situation_frame: PublishSituationFrame
  selected_card: PriorityItem | null
  selected_preview: BlastRadiusPreview | null
  selected_position: number
  total_items: number
  previous_object_ref: string | null
  next_object_ref: string | null
  available_commands: string[]
  context_notes: string[]
  action_presets: PublishActionPreset[]
  selected_action: string | null
  action_echo: PublishActionEcho | null
}

export async function fetchPublishPreview(
  objectRef?: string,
  actionKey?: string,
): Promise<PublishPreviewSurface> {
  const params = new URLSearchParams()
  if (objectRef) params.set('object_ref', objectRef)
  if (actionKey) params.set('action_key', actionKey)
  const qs = params.toString()
  return authApi<PublishPreviewSurface>(`/api/publish-preview${qs ? `?${qs}` : ''}`)
}

// ============================================================
// Publish apply — the write path. Runs the real governance
// executor (POST /api/publish/apply) and returns the full
// result: opened / removed / held bindings + action_log.
// `persisted` is false because the store is fixture-backed; the
// loop is real (the executor actually runs) but not durable.
// ============================================================

export interface PublishApplyResult {
  selected_action: string
  action_log: string[]
  opened_bindings: PublishBinding[]
  removed_bindings: PublishBinding[]
  held_bindings: PublishConflict[]
  updated_candidate: unknown
  preview: BlastRadiusPreview
  rehearsal: boolean
  persisted: boolean
}

export async function applyPublishAction(
  objectRef: string | undefined,
  actionKey: string,
): Promise<PublishApplyResult> {
  return authApi<PublishApplyResult>('/api/publish/apply', {
    method: 'POST',
    body: { object_ref: objectRef ?? null, action_key: actionKey },
  })
}

// ============================================================
// Publish propagation — downstream ledger after a command
// ============================================================

export interface PropagationLedgerSummary {
  synced: number
  pending: number
  failed: number
  manual_action_required: number
}

export interface SurfacePropagationRecord {
  surface_id: string
  status: string // synced | pending | failed | manual_action_required
  reason: string
  channel_refs: string[]
  binding_refs: PublishBinding[]
  follow_up_commands: string[]
}

export interface PublishPropagationLedger {
  object_id: string
  title: string
  action_log: string[]
  summary: PropagationLedgerSummary
  records: SurfacePropagationRecord[]
  unresolved_surfaces: string[]
  continue_commands: string[]
}

export interface PropagationStatusLane {
  status: string
  headline: string
  note: string
  count: number
  surface_ids: string[]
}

export interface PublishPropagationSurface {
  surface_id: string
  headline: string
  summary: string
  selected_card: PriorityItem
  propagation_ledger: PublishPropagationLedger
  status_lanes: PropagationStatusLane[]
  selected_position: number
  total_items: number
  action_presets: PublishActionPreset[]
  selected_action: string | null
  action_echo: PublishActionEcho | null
  previous_object_ref: string | null
  next_object_ref: string | null
  context_notes: string[]
}

export async function fetchPublishPropagation(
  objectRef?: string,
  actionKey?: string,
): Promise<PublishPropagationSurface> {
  const params = new URLSearchParams()
  if (objectRef) params.set('object_ref', objectRef)
  if (actionKey) params.set('action_key', actionKey)
  const qs = params.toString()
  return authApi<PublishPropagationSurface>(`/api/publish-propagation${qs ? `?${qs}` : ''}`)
}

// ============================================================
// Recovery window — before/after command impact proof
// ============================================================

export interface GovernanceCommandRef {
  command_id: string
  command_type: string
  object_id: string
  object_title: string
  issued_by: string
  issued_at: string
  rationale: string
  affected_surfaces: string[]
}

export interface RecoveryMetricDelta {
  metric_key: string
  label: string
  before_value: number
  after_value: number
  delta: number
  improved: boolean
  status: string // improved | worsened | flat
  explanation: string
}

export interface AlignmentPlaneChange {
  plane_key: string
  label: string
  before_state: string // misaligned | partial | aligned | split_brain
  after_state: string
  before_score: number
  after_score: number
  improved: boolean
  residual_reasons: string[]
}

export interface BeforeAfterAlignmentView {
  before_score: number
  after_score: number
  delta: number
  plane_changes: AlignmentPlaneChange[]
  improved_truth_planes: string[]
  residual_truth_planes: string[]
}

export interface ResidualRisk {
  command_id: string
  risk_id: string
  label: string
  severity: string // critical | elevated | emerging | watch
  truth_plane: string
  summary: string
  acceptable_residual: boolean
  recommended_command: string
  owner: string | null
  blocking_surface: string | null
  evidence_refs: string[]
}

export interface ClosureJudge {
  assessment: string // recovery_incomplete | recovery_confirmed | false_recovery | drift_rebound
  recommendation: string // continue_with_lightweight_follow_up | close_and_monitor | reopen_drift_route
  closeable: boolean
  rationale: string
  improved_metrics: string[]
  residual_truth_planes: string[]
  next_commands: string[]
  monitor_targets: string[]
  closure_blockers: string[]
}

export interface RecoveryWindowSurface {
  surface_id: string
  headline: string
  summary: string
  command_ref: GovernanceCommandRef
  assessment: string
  before_after_alignment_view: BeforeAfterAlignmentView
  rewrite_delta: RecoveryMetricDelta
  drift_delta: RecoveryMetricDelta
  escalation_delta: RecoveryMetricDelta
  coverage_gap_delta: RecoveryMetricDelta
  publish_conflict_delta: RecoveryMetricDelta
  residual_risks: ResidualRisk[]
  closure_judge: ClosureJudge
  continue_commands: string[]
  monitor_targets: string[]
  supporting_links: string[]
}

export async function fetchRecoveryWindow(commandId: string): Promise<RecoveryWindowSurface> {
  return authApi<RecoveryWindowSurface>(`/api/recovery/window/${encodeURIComponent(commandId)}`)
}

// ============================================================
// Downstream reality check — frontline feedback signals
// ============================================================

export interface DownstreamFeedbackSignal {
  signal_id: string
  surface_id: string
  signal_type: string // copilot_accepted | human_rewrite | reject_after_suggestion | escalation_after_suggestion | unresolved_conversation
  command_ref: GovernanceCommandRef
  audience_label: string
  session_ref: string
  summary: string
  changed_behavior: string
  event_at: string
  queue_owner: string | null
  source_refs: string[]
  follow_up_actions: string[]
}

export interface RealityCheckStrip {
  command_id: string
  command_type: string
  object_title: string
  frontline_changed: boolean
  converging_surfaces: string[]
  lagging_surfaces: string[]
  unresolved_signal_count: number
  next_actions: string[]
}

export interface MismatchByAudience {
  audience_label: string
  rewrite_count: number
  reject_count: number
  escalation_count: number
  unresolved_count: number
  affected_surfaces: string[]
}

export interface DownstreamRealityCheckSurface {
  surface_id: string
  headline: string
  summary: string
  reality_check_strip: RealityCheckStrip
  feedback_feed: DownstreamFeedbackSignal[]
  mismatch_by_audience: MismatchByAudience[]
  upstream_object_links: string[]
  send_back_commands: string[]
}

export async function fetchDownstreamRealityCheck(commandId: string): Promise<DownstreamRealityCheckSurface> {
  return authApi<DownstreamRealityCheckSurface>(`/api/recovery/downstream-reality-check/${encodeURIComponent(commandId)}`)
}
