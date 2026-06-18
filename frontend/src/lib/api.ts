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
  const res = await fetch('/api/command-center')
  if (!res.ok) throw new Error(`API ${res.status}`)
  return res.json()
}
