// In-browser mock of the backend (VITE_MOCK=1). Fixture: the real SM-T290 report in src/mock/report.json.
// It emits contract-shaped data, including the classifier fields, so the UI exercises the final shapes.

import fixture from '../mock/report.json'
import type { Api } from './client'
import { fallbackGroup, fallbackTags } from '../lib/classify'
import type { Backup, Candidate, Device, Job, Monitor, Plan, Report, ScanInfo, Summary } from './types'
import { ApiError } from './types'

const base = fixture as unknown as Report
const SERIAL = base.device.serial

const candidates: Candidate[] = base.candidates.map((c) => {
  const tags = fallbackTags(c)
  return {
    ...c,
    group: fallbackGroup(c),
    origin: c.system ? 'preinstalled' : 'user',
    tags,
    last_used_days: tags.includes('frequent') ? 0 : c.bucket === 'rare' ? 21 : c.bucket === 'never' ? null : 3,
    confidence: c.risk === 'unknown' ? 'low' : 'high',
  }
})
const byPkg = new Map(candidates.map((c) => [c.package, c]))

const delay = (ms = 120) => new Promise((r) => setTimeout(r, ms))
let seq = 1
const id = (p: string) => `${p}-${Date.now().toString(36)}-${seq++}`

const scans: ScanInfo[] = [
  {
    id: `${SERIAL}-20261031-095412`,
    serial: SERIAL,
    model: base.device.model ?? '',
    manufacturer: base.device.manufacturer ?? '',
    android: base.device.android ?? '',
    created: '2026-10-31T09:54:12',
  },
]
const plans = new Map<string, Plan>()
const backups: (Backup & { plan: Plan })[] = []
const jobs = new Map<string, Job>()

function summarize(packages: string[]): Summary {
  const memTotal = base.device.mem_total_kb ?? base.summary.mem_total_kb
  const memAvail = base.device.mem_available_kb ?? base.summary.mem_available_kb
  const s: Summary = {
    selected: 0, ram_kb: 0, ram_sustained_kb: 0, ram_pct: 0, mem_total_kb: memTotal, mem_available_kb: memAvail,
    mem_available_after_kb: memAvail, processes: 0, services: 0, storage_bytes: 0, by_category: {}, by_action: {},
  }
  for (const p of packages) {
    const c = byPkg.get(p)
    if (!c) continue
    const action = c.action === 'none' ? (c.risk === 'caution' ? 'disable' : 'uninstall') : c.action
    s.selected++
    s.ram_kb += c.pss_kb
    if (c.services > 0) s.ram_sustained_kb += c.pss_kb
    s.processes += c.processes
    s.services += c.services
    s.storage_bytes += action === 'disable' ? c.cache_bytes : c.reclaimable_bytes
    s.by_category[c.category] = (s.by_category[c.category] ?? 0) + 1
    s.by_action[action] = (s.by_action[action] ?? 0) + 1
  }
  s.ram_pct = memTotal ? (s.ram_kb / memTotal) * 100 : 0
  s.mem_available_after_kb = memAvail + s.ram_kb
  return s
}

function cmd(serial: string, action: string, pkg: string, restore = false) {
  if (restore) {
    return action === 'disable'
      ? `adb -s ${serial} shell pm enable --user 0 ${pkg}`
      : `adb -s ${serial} shell cmd package install-existing --user 0 ${pkg}`
  }
  return action === 'disable'
    ? `adb -s ${serial} shell pm disable-user --user 0 ${pkg}`
    : `adb -s ${serial} shell pm uninstall -k --user 0 ${pkg}`
}

function runJob(job: Job, steps: number, tick: (i: number) => void, finish: () => void, ms = 350) {
  jobs.set(job.id, job)
  let i = 0
  const t = setInterval(() => {
    job.status = 'running'
    if (i < steps) {
      tick(i)
      i++
    } else {
      clearInterval(t)
      finish()
      job.status = 'done'
    }
  }, ms)
}

// Live monitor: realistic SM-T290 values (1.8 GB RAM ~88 % used, 32 GB eMMC) with a gentle random walk.
const bootAt = Date.now() - 123456 * 1000
let memUsedPct = 88
let cpuPct = 34
let battery = 82
const jitter = (v: number, step: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v + (Math.random() - 0.5) * step))
const TOP = [
  ['com.android.systemui', 116812], ['com.sec.android.app.launcher', 73423], ['com.google.android.gms', 98000],
  ['com.google.android.gms.persistent', 64000], ['com.netflix.mediaclient', 152000], ['system_server', 188000],
  ['com.google.android.googlequicksearchbox:search', 61000], ['com.samsung.android.honeyboard', 42000],
] as const

function mockMonitor(): Monitor {
  memUsedPct = jitter(memUsedPct, 1.6, 84, 92)
  cpuPct = jitter(cpuPct, 14, 8, 78)
  battery = Math.max(5, battery - (Math.random() < 0.15 ? 1 : 0))
  const total = base.device.mem_total_kb ?? 1892156
  const used = Math.round((total * memUsedPct) / 100)
  const swapTotal = 1048572
  const dataTotal = 24_918_118_400
  const dataUsed = 19_143_655_424
  const sysTotal = 4_294_967_296
  const sysUsed = 3_986_391_040
  return {
    serial: SERIAL,
    taken_at: new Date().toISOString().slice(0, 19),
    device: {
      manufacturer: base.device.manufacturer ?? 'samsung', model: base.device.model ?? 'SM-T290', android: '11', sdk: 30,
      build: 'T290XXU3CVG3', abi: 'armeabi-v7a', cpu_cores: 4, screen: '800x1280',
      uptime_s: Math.round((Date.now() - bootAt) / 1000),
    },
    memory: {
      total_kb: total, available_kb: total - used, used_kb: used, used_pct: Math.round(memUsedPct * 10) / 10,
      cached_kb: Math.round(jitter(402000, 30000, 340000, 460000)),
      swap_total_kb: swapTotal, swap_used_kb: Math.round(jitter(612000, 24000, 560000, 680000)),
    },
    storage: [
      { mount: '/data', total_bytes: dataTotal, used_bytes: dataUsed, free_bytes: dataTotal - dataUsed, used_pct: Math.round((dataUsed / dataTotal) * 1000) / 10 },
      { mount: '/system', total_bytes: sysTotal, used_bytes: sysUsed, free_bytes: sysTotal - sysUsed, used_pct: Math.round((sysUsed / sysTotal) * 1000) / 10 },
      { mount: '/sdcard', total_bytes: null, used_bytes: null, free_bytes: null, used_pct: null },
    ],
    cpu: { usage_pct: Math.round(cpuPct * 10) / 10, load_avg: [jitter(3.1, 0.6, 1.5, 5), jitter(2.8, 0.3, 1.5, 4), 2.5].map((v) => Math.round(v * 100) / 100) },
    battery: { level: battery, status: 'charging', plugged: 'usb', temperature_c: Math.round(jitter(31.2, 0.6, 29, 34) * 10) / 10, health: 'good' },
    counts: { packages: candidates.length, user_packages: candidates.filter((c) => !c.system).length, processes: 149 },
    top_processes: TOP.map(([name, rss], i) => ({ pid: 1200 + i * 137, name, rss_kb: Math.round(jitter(rss, rss * 0.06, rss * 0.85, rss * 1.15)) }))
      .sort((a, b) => (b.rss_kb ?? 0) - (a.rss_kb ?? 0)),
  }
}

export const mockApi: Api = {
  async health() {
    await delay()
    return { ok: true, version: '0.1.0-mock', adb: '/opt/android-sdk/platform-tools/adb' }
  },
  async devices() {
    await delay(300)
    const list: Device[] = [
      { serial: SERIAL, state: 'device', model: (base.device.model ?? '').replace('-', '_') },
      { serial: 'RF8M33XKZPL', state: 'unauthorized', model: '' },
    ]
    return list
  },
  async monitor(serial, signal) {
    await delay(260)
    if (signal?.aborted) throw new DOMException('aborted', 'AbortError')
    if (serial !== SERIAL) throw new ApiError(409, 'device_unauthorized', 'El dispositivo no ha autorizado la depuración USB.')
    return mockMonitor()
  },
  async startScan(serial) {
    await delay()
    const s = serial ?? SERIAL
    if (s !== SERIAL) throw new ApiError(409, 'device_unauthorized', 'El dispositivo no ha autorizado la depuración USB.')
    const job: Job = { id: id('job'), kind: 'scan', status: 'queued', progress: null, log: [], result: null, error: null }
    const phases = [
      'pm list packages -f -U -u --user 0',
      'ps -A -o PID,UID,RSS,NAME',
      'dumpsys meminfo',
      'dumpsys activity services',
      'am get-standby-bucket',
      'dumpsys diskstats',
      'cat /proc/meminfo',
    ]
    runJob(
      job,
      phases.length,
      (i) => job.log.push(`adb -s ${s} shell ${phases[i]}`),
      () => {
        const info: ScanInfo = { ...scans[0], id: id(s), created: new Date().toISOString().slice(0, 19) }
        scans.unshift(info)
        job.result = { scan_id: info.id }
      },
      600,
    )
    return job.id
  },
  async scans() {
    await delay()
    return [...scans]
  },
  async report(scanId) {
    await delay(250)
    const scan = scans.find((s) => s.id === scanId)
    if (!scan) throw new ApiError(404, 'not_found', `No existe el escaneo ${scanId}.`)
    return { scan, device: base.device, summary: base.summary, candidates }
  },
  async estimate(_scanId, packages, signal) {
    await delay(180)
    if (signal?.aborted) throw new DOMException('aborted', 'AbortError')
    return summarize(packages)
  },
  async createPlan(scanId, items) {
    await delay()
    const bad = items.filter((i) => byPkg.get(i.package)?.risk === 'danger')
    if (bad.length) throw new ApiError(422, 'danger_package', `Paquetes peligrosos en el plan: ${bad.map((b) => b.package).join(', ')}`)
    const plan: Plan = {
      id: id('plan'),
      serial: SERIAL,
      scan_id: scanId,
      created: new Date().toISOString().slice(0, 19),
      items: items.map((i) => {
        const c = byPkg.get(i.package)
        return { ...i, label: c?.label ?? '', risk: c?.risk, group: c?.group, tags: c?.tags }
      }),
    }
    plans.set(plan.id, plan)
    return plan
  },
  async plans() {
    await delay()
    return [...plans.values()].reverse()
  },
  async plan(planId) {
    await delay()
    const p = plans.get(planId)
    if (!p) throw new ApiError(404, 'not_found', `No existe el plan ${planId}.`)
    return p
  },
  async apply(planId, dryRun, confirmSerial) {
    await delay()
    const plan = plans.get(planId)
    if (!plan) throw new ApiError(404, 'not_found', `No existe el plan ${planId}.`)
    if (!dryRun && confirmSerial !== plan.serial)
      throw new ApiError(400, 'confirm_mismatch', 'El número de serie no coincide con el del plan.')
    const job: Job = {
      id: id('job'), kind: 'apply', status: 'queued', progress: { done: 0, total: plan.items.length, current: '' },
      log: [], result: null, error: null,
    }
    const results: { package: string; action: string; ok: boolean; output: string }[] = []
    runJob(
      job,
      plan.items.length,
      (i) => {
        const it = plan.items[i]
        const c = cmd(plan.serial, it.action, it.package)
        const ok = dryRun || !it.package.includes('knox')
        const output = dryRun ? '(simulación)' : ok ? 'Success' : 'Failure [DELETE_FAILED_USER_RESTRICTED]'
        job.log.push(dryRun ? c : `${c} → ${output}`)
        results.push({ package: it.package, action: it.action, ok, output })
        job.progress = { done: i + 1, total: plan.items.length, current: it.package }
      },
      () => {
        let backup_id: string | null = null
        if (!dryRun) {
          backup_id = id(`${plan.serial}`)
          backups.unshift({ id: backup_id, serial: plan.serial, created: new Date().toISOString().slice(0, 19), items: plan.items.length, plan })
        }
        job.result = { backup_id, results }
      },
      dryRun ? 60 : 380,
    )
    return job.id
  },
  async backups() {
    await delay()
    if (!backups.length) {
      // a pre-existing backup so the restore screen has content in mock mode
      const plan: Plan = {
        id: 'plan-seed', serial: SERIAL, scan_id: scans[0].id, created: '2026-10-30T18:02:11',
        items: candidates.filter((c) => c.recommendation === 'remove').slice(0, 9).map((c) => ({ package: c.package, action: 'uninstall' as const })),
      }
      backups.push({ id: `${SERIAL}-20261030-180211`, serial: SERIAL, created: plan.created, items: plan.items.length, plan })
    }
    return backups.map(({ plan: _p, ...b }) => b)
  },
  async restore(backupId, confirmSerial) {
    await delay()
    const b = backups.find((x) => x.id === backupId)
    if (!b) throw new ApiError(404, 'not_found', `No existe la copia ${backupId}.`)
    if (confirmSerial !== b.serial) throw new ApiError(400, 'confirm_mismatch', 'El número de serie no coincide.')
    const items = b.plan.items
    const job: Job = {
      id: id('job'), kind: 'restore', status: 'queued', progress: { done: 0, total: items.length, current: '' },
      log: [], result: null, error: null,
    }
    const results: { package: string; action: string; ok: boolean; output: string }[] = []
    runJob(
      job,
      items.length,
      (i) => {
        const it = items[i]
        job.log.push(`${cmd(b.serial, it.action, it.package, true)} → Success`)
        results.push({ package: it.package, action: it.action === 'disable' ? 'enable' : 'install-existing', ok: true, output: 'Success' })
        job.progress = { done: i + 1, total: items.length, current: it.package }
      },
      () => {
        job.result = { results }
      },
    )
    return job.id
  },
  async job(jobId) {
    await delay(60)
    const j = jobs.get(jobId)
    if (!j) throw new ApiError(404, 'not_found', `No existe el trabajo ${jobId}.`)
    return structuredClone(j)
  },
}
