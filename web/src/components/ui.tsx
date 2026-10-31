import {
  Activity, AlertTriangle, BarChart3, Ban, CheckCircle2, Cpu, Database, HardDrive, Layers, Lock, Moon, Radio,
  ShieldAlert, ShieldCheck, Trash2, XCircle,
} from 'lucide-react'
import type { ReactNode } from 'react'
import type { Job } from '../api/types'
import { GROUP_HINT, GROUP_LABEL, RISK_LABEL, TAG_LABEL } from '../lib/format'

const TAG_ICON: Record<string, ReactNode> = {
  frequent: <Activity size={12} strokeWidth={2.4} />,
  bloat: <Trash2 size={12} strokeWidth={2.2} />,
  telemetry: <Radio size={12} strokeWidth={2.2} />,
  core: <Cpu size={12} strokeWidth={2.2} />,
  background: <Layers size={12} strokeWidth={2.2} />,
  running: <BarChart3 size={12} strokeWidth={2.2} />,
  unused: <Moon size={12} strokeWidth={2.2} />,
  disabled: <Ban size={12} strokeWidth={2.2} />,
  large: <HardDrive size={12} strokeWidth={2.2} />,
}

export function Tag({ tag }: { tag: string }) {
  return (
    <span className={`chip ${tag}`}>
      {TAG_ICON[tag] ?? <Database size={12} />}
      {TAG_LABEL[tag] ?? tag}
    </span>
  )
}

/** Tags ordered so `frequent` always leads. */
export function Tags({ tags, max = 4 }: { tags: string[]; max?: number }) {
  const sorted = [...tags].sort((a, b) => (a === 'frequent' ? -1 : b === 'frequent' ? 1 : 0))
  const shown = sorted.slice(0, max)
  return (
    <span className="tags">
      {shown.map((t) => (
        <Tag key={t} tag={t} />
      ))}
      {sorted.length > max && (
        <span className="chip" title={sorted.slice(max).map((t) => TAG_LABEL[t] ?? t).join(', ')}>
          +{sorted.length - max}
        </span>
      )}
    </span>
  )
}

export function RiskMark({ risk }: { risk?: string }) {
  const r = risk ?? 'unknown'
  return (
    <span className={`risk ${r}`}>
      <i aria-hidden />
      {RISK_LABEL[r] ?? r}
    </span>
  )
}

export function GroupMark({ group }: { group?: string }) {
  const g = group ?? 'system'
  return (
    <span className={`group ${g}`} title={GROUP_HINT[g]}>
      {g === 'third_party' ? <ShieldCheck size={15} /> : <ShieldAlert size={15} />}
      {GROUP_LABEL[g] ?? g}
    </span>
  )
}

export function Lockout() {
  return (
    <span className="lockout" title="Bloqueado: paquete crítico del sistema, no se puede quitar" role="img" aria-label="Bloqueado">
      <Lock size={13} strokeWidth={2.4} />
    </span>
  )
}

export function Callout({ kind = 'info', icon, children }: { kind?: 'info' | 'warn' | 'danger'; icon?: ReactNode; children: ReactNode }) {
  return (
    <div className={`callout ${kind}`} role={kind === 'danger' ? 'alert' : undefined}>
      {icon ?? (kind === 'info' ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />)}
      <div>{children}</div>
    </div>
  )
}

export function ErrorBox({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <Callout kind="danger" icon={<XCircle size={18} />}>
      <div className="row">
        <span>{error.message}</span>
        {onRetry && (
          <button className="btn sm" onClick={onRetry}>
            Reintentar
          </button>
        )}
      </div>
    </Callout>
  )
}

export function JobLog({ job, dryRun }: { job: Job; dryRun?: boolean }) {
  if (!job.log.length) return null
  return (
    <pre className="log" aria-label={dryRun ? 'Comandos que se ejecutarían' : 'Registro'}>
      {job.log.map((l, i) => {
        const cls = /→\s*Success/i.test(l) ? 'ok' : /→\s*(Failure|Error)/i.test(l) ? 'fail' : undefined
        return (
          <div key={i} className={cls}>
            {l}
          </div>
        )
      })}
    </pre>
  )
}

export function ProgressBar({ done, total, indeterminate }: { done?: number; total?: number; indeterminate?: boolean }) {
  const pctDone = total ? Math.round(((done ?? 0) / total) * 100) : 0
  return (
    <div
      className={`bar${indeterminate ? ' indet' : ''}`}
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate ? undefined : pctDone}
    >
      <span style={indeterminate ? undefined : { width: `${pctDone}%` }} />
    </div>
  )
}
