import type { Action, Backup, Device, Health, Job, Monitor, Plan, Report, ScanInfo, Summary } from './types'
import { ApiError } from './types'

export interface Api {
  health(): Promise<Health>
  devices(): Promise<Device[]>
  monitor(serial: string, signal?: AbortSignal): Promise<Monitor>
  startScan(serial: string | null): Promise<string>
  scans(): Promise<ScanInfo[]>
  report(scanId: string, includeReview?: boolean): Promise<Report>
  estimate(scanId: string, packages: string[], signal?: AbortSignal): Promise<Summary>
  createPlan(scanId: string, items: { package: string; action: Action }[]): Promise<Plan>
  plans(): Promise<Plan[]>
  plan(planId: string): Promise<Plan>
  apply(planId: string, dryRun: boolean, confirmSerial: string): Promise<string>
  backups(): Promise<Backup[]>
  restore(backupId: string, confirmSerial: string): Promise<string>
  job(jobId: string): Promise<Job>
}

async function req<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new ApiError(0, 'network', 'No se pudo contactar con el servidor local (¿está arrancado en el puerto 8765?).')
  }
  const text = await res.text()
  let data: unknown = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) {
    const err = (data as { error?: { code?: string; message?: string } } | null)?.error
    throw new ApiError(res.status, err?.code ?? `http_${res.status}`, err?.message ?? `Error ${res.status} en ${path}`)
  }
  return data as T
}

export const httpApi: Api = {
  health: () => req<Health>('GET', '/health'),
  devices: async () => (await req<{ devices: Device[] }>('GET', '/devices')).devices,
  monitor: (serial, signal) => req<Monitor>('GET', `/devices/${encodeURIComponent(serial)}/monitor`, undefined, signal),
  startScan: async (serial) => (await req<{ job_id: string }>('POST', '/scans', { serial })).job_id,
  scans: async () => (await req<{ scans: ScanInfo[] }>('GET', '/scans')).scans,
  report: (scanId, includeReview = true) =>
    req<Report>('GET', `/scans/${encodeURIComponent(scanId)}/report?include_review=${includeReview}`),
  estimate: async (scanId, packages, signal) =>
    (await req<{ summary: Summary }>('POST', `/scans/${encodeURIComponent(scanId)}/estimate`, { packages }, signal))
      .summary,
  createPlan: async (scan_id, items) => (await req<{ plan: Plan }>('POST', '/plans', { scan_id, items })).plan,
  plans: async () => (await req<{ plans: Plan[] }>('GET', '/plans')).plans,
  plan: async (id) => (await req<{ plan: Plan }>('GET', `/plans/${encodeURIComponent(id)}`)).plan,
  apply: async (id, dry_run, confirm_serial) =>
    (await req<{ job_id: string }>('POST', `/plans/${encodeURIComponent(id)}/apply`, { dry_run, confirm_serial }))
      .job_id,
  backups: async () => (await req<{ backups: Backup[] }>('GET', '/backups')).backups,
  restore: async (id, confirm_serial) =>
    (await req<{ job_id: string }>('POST', `/backups/${encodeURIComponent(id)}/restore`, { confirm_serial })).job_id,
  job: (id) => req<Job>('GET', `/jobs/${encodeURIComponent(id)}`),
}

export const MOCK = import.meta.env.VITE_MOCK === '1' || import.meta.env.VITE_MOCK === 'true'

// The mock (and its 180 KB fixture) is only loaded in mock mode, so production bundles never carry it.
export const api: Api = MOCK ? (await import('./mock')).mockApi : httpApi

/** Poll a job every second until it settles. Calls onUpdate on each tick. */
export async function pollJob(jobId: string, onUpdate: (j: Job) => void, signal?: AbortSignal): Promise<Job> {
  for (;;) {
    if (signal?.aborted) throw new DOMException('aborted', 'AbortError')
    const j = await api.job(jobId)
    onUpdate(j)
    if (j.status === 'done' || j.status === 'failed') return j
    await new Promise((r) => setTimeout(r, 1000))
  }
}
