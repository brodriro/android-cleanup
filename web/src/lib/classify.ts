import type { Candidate, Group } from '../api/types'

// Fallbacks for the classifier fields (group, tags). The backend fills them per the contract; until it does,
// the panel derives an equivalent from risk / system / bucket so every screen keeps working.

const BLOAT_CATEGORIES = new Set(['oem', 'carrier', 'google', 'third_party', 'telemetry'])
const UNUSED_BUCKETS = new Set(['rare', 'restricted', 'never'])
const LARGE_BYTES = 200 * 1024 * 1024

export function fallbackGroup(c: Candidate): Group {
  if (c.risk === 'safe') return 'third_party'
  if (c.risk === 'danger' || c.risk === 'caution') return 'system'
  if (c.category === 'core' || c.category === 'system') return 'system'
  return c.system ? 'system' : 'third_party'
}

export function fallbackTags(c: Candidate): string[] {
  const t: string[] = []
  const usedOften = c.bucket === 'active' || c.bucket === 'working_set' || c.bucket === 'frequent'
  if (usedOften && c.risk !== 'danger' && (!c.system || c.processes > 0)) t.push('frequent')
  if (c.risk === 'safe' && BLOAT_CATEGORIES.has(c.category)) t.push('bloat')
  if (c.category === 'telemetry') t.push('telemetry')
  if (c.category === 'core') t.push('core')
  if (c.services > 0) t.push('background')
  if (c.processes > 0) t.push('running')
  if (UNUSED_BUCKETS.has(c.bucket)) t.push('unused')
  if (!c.enabled) t.push('disabled')
  if (c.reclaimable_bytes >= LARGE_BYTES) t.push('large')
  return t
}

export interface Row extends Candidate {
  group: Group
  tags: string[]
  /** true when group/tags came from the panel fallback rather than the classifier */
  derived: boolean
}

export function normalize(c: Candidate): Row {
  const derived = c.group === undefined || c.tags === undefined
  return {
    ...c,
    label: c.label ?? '',
    reasons: c.reasons ?? [],
    group: c.group ?? fallbackGroup(c),
    tags: c.tags ?? fallbackTags(c),
    derived,
  }
}

export const isLocked = (c: { risk?: string }) => c.risk === 'danger'
export const isFrequent = (c: { tags?: string[] }) => !!c.tags?.includes('frequent')
