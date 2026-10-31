// Types mirroring docs/api-contract.md. Keep in sync with the contract, not with the backend code.

export type Risk = 'safe' | 'caution' | 'danger' | 'unknown'
export type Recommendation = 'remove' | 'review' | 'keep'
export type Action = 'uninstall' | 'disable'
export type SuggestedAction = Action | 'none'
export type Group = 'system' | 'third_party'
export type Bucket = 'exempted' | 'active' | 'working_set' | 'frequent' | 'rare' | 'restricted' | 'never' | ''

export interface Candidate {
  package: string
  label: string
  category: string
  risk: Risk
  system: boolean
  enabled: boolean
  installed: boolean
  processes: number
  pss_kb: number
  rss_kb: number
  services: number
  bucket: Bucket | string
  code_bytes: number
  data_bytes: number
  cache_bytes: number
  reclaimable_bytes: number
  recommendation: Recommendation
  action: SuggestedAction
  reasons: string[]
  // Added by the classifier. Optional until it ships; see lib/classify.ts for fallbacks.
  group?: Group
  origin?: 'preinstalled' | 'user'
  tags?: string[]
  last_used_days?: number | null
  confidence?: 'high' | 'medium' | 'low'
}

export interface Summary {
  selected: number
  ram_kb: number
  ram_sustained_kb: number
  ram_pct: number
  mem_total_kb: number
  mem_available_kb: number
  mem_available_after_kb: number
  processes: number
  services: number
  storage_bytes: number
  by_category: Record<string, number>
  by_action: Record<string, number>
}

export type DeviceState = 'device' | 'unauthorized' | 'offline' | string

export interface Device {
  serial: string
  state: DeviceState
  model: string
}

export interface Health {
  ok: boolean
  version: string
  adb: string
}

export interface ScanInfo {
  id: string
  serial: string
  model: string
  manufacturer: string
  android: string
  created: string
}

export interface ReportDevice {
  serial: string
  manufacturer?: string
  model?: string
  android?: string
  sdk?: number
  mem_total_kb?: number
  mem_available_kb?: number
}

export interface Report {
  scan?: Partial<ScanInfo>
  device: ReportDevice
  summary: Summary
  candidates: Candidate[]
}

export interface PlanItem {
  package: string
  action: Action
  label?: string
  risk?: Risk
  group?: Group
  tags?: string[]
}

export interface Plan {
  id: string
  serial: string
  scan_id: string
  created: string
  items: PlanItem[]
}

export interface Backup {
  id: string
  serial: string
  created: string
  items: number
}

export interface JobResultItem {
  package: string
  action: string
  ok: boolean
  output: string
}

export type JobResult =
  | { scan_id: string }
  | { backup_id?: string | null; results: JobResultItem[] }
  | null

export interface Job {
  id: string
  kind: 'scan' | 'apply' | 'restore'
  status: 'queued' | 'running' | 'done' | 'failed'
  progress: { done: number; total: number; current: string } | null
  log: string[]
  result: JobResult
  error: string | null
}

export class ApiError extends Error {
  code: string
  status: number
  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

// ---- Device monitor (GET /api/devices/{serial}/monitor). Unreadable fields are null, keys never omitted. ----
export interface MonitorStorage {
  mount: string
  total_bytes: number | null
  used_bytes: number | null
  free_bytes: number | null
  used_pct: number | null
}

export interface Monitor {
  serial: string
  taken_at: string
  device: {
    manufacturer: string | null
    model: string | null
    android: string | null
    sdk: number | null
    build: string | null
    abi: string | null
    cpu_cores: number | null
    screen: string | null
    uptime_s: number | null
  }
  memory: {
    total_kb: number | null
    available_kb: number | null
    used_kb: number | null
    used_pct: number | null
    cached_kb: number | null
    swap_total_kb: number | null
    swap_used_kb: number | null
  }
  storage: MonitorStorage[]
  cpu: { usage_pct: number | null; load_avg: number[] | null }
  battery: {
    level: number | null
    status: 'charging' | 'discharging' | 'full' | 'not_charging' | 'unknown' | string | null
    plugged: 'usb' | 'ac' | 'wireless' | 'none' | string | null
    temperature_c: number | null
    health: string | null
  }
  counts: { packages: number | null; user_packages: number | null; processes: number | null }
  top_processes: { pid: number; name: string; rss_kb: number | null }[]
}
