import { ArchiveRestore, ArrowLeft, Copy, FlaskConical, Loader2, PlugZap, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { api, pollJob } from '../api/client'
import type { Action, Job, JobResultItem, Plan as PlanT, PlanItem } from '../api/types'
import { SerialConfirm, Results } from '../components/SerialConfirm'
import { Callout, ErrorBox, GroupMark, JobLog, ProgressBar, RiskMark, Tag } from '../components/ui'
import { date } from '../lib/format'
import { go, href, useAsync } from '../lib/hooks'

const sameItems = (a: PlanItem[], b: PlanItem[]) =>
  a.length === b.length && a.every((x, i) => x.package === b[i].package && x.action === b[i].action)

export function Plan({ planId }: { planId: string }) {
  const plan = useAsync(() => api.plan(planId), [planId])
  if (plan.error) return <ErrorBox error={plan.error} onRetry={plan.reload} />
  if (!plan.data) return <div className="skeleton" style={{ height: 420 }} aria-busy />
  return <PlanBody key={plan.data.id} plan={plan.data} />
}

function PlanBody({ plan }: { plan: PlanT }) {
  const [items, setItems] = useState<PlanItem[]>(plan.items)
  const [saved, setSaved] = useState<PlanT>(plan)
  const [dry, setDry] = useState<Job>()
  const [dryFor, setDryFor] = useState<PlanItem[]>()
  const [run, setRun] = useState<Job>()
  const [busy, setBusy] = useState<'dry' | 'apply' | 'save'>()
  const [error, setError] = useState<Error>()
  const [copied, setCopied] = useState(false)

  const dirty = !sameItems(items, saved.items)
  const simulated = !!dryFor && sameItems(dryFor, items) && dry?.status === 'done'
  const applying = run && (run.status === 'queued' || run.status === 'running')
  const finished = run && (run.status === 'done' || run.status === 'failed')
  const results: JobResultItem[] = run?.result && 'results' in run.result ? run.result.results : []
  const backupId = run?.result && 'backup_id' in run.result ? run.result.backup_id : undefined
  const counts = useMemo(
    () => ({ uninstall: items.filter((i) => i.action === 'uninstall').length, disable: items.filter((i) => i.action === 'disable').length }),
    [items],
  )

  useEffect(() => {
    if (!copied) return
    const t = setTimeout(() => setCopied(false), 1600)
    return () => clearTimeout(t)
  }, [copied])

  /** Plans are immutable on the server: edits are saved as a new plan before running. */
  async function ensureSaved(): Promise<PlanT> {
    if (!dirty) return saved
    setBusy('save')
    const p = await api.createPlan(saved.scan_id, items.map(({ package: pkg, action }) => ({ package: pkg, action })))
    setSaved(p)
    window.history.replaceState(null, '', href('plan', p.id))
    return p
  }

  async function simulate() {
    setError(undefined)
    setRun(undefined)
    try {
      const p = await ensureSaved()
      setBusy('dry')
      const snapshot = items
      const id = await api.apply(p.id, true, '')
      const final = await pollJob(id, setDry)
      if (final.status === 'done') setDryFor(snapshot)
    } catch (e) {
      setError(e as Error)
    } finally {
      setBusy(undefined)
    }
  }

  async function apply(serial: string) {
    setError(undefined)
    try {
      setBusy('apply')
      const id = await api.apply(saved.id, false, serial)
      await pollJob(id, setRun)
    } catch (e) {
      setError(e as Error)
    } finally {
      setBusy(undefined)
    }
  }

  const setAction = (pkg: string, action: Action) => setItems(items.map((i) => (i.package === pkg ? { ...i, action } : i)))
  const remove = (pkg: string) => setItems(items.filter((i) => i.package !== pkg))
  const locked = !!applying || !!finished

  return (
    <>
      <header className="page-head">
        <div>
          <a href={href('informe', saved.scan_id)} className="row" style={{ gap: 4, fontSize: '0.88rem', textDecoration: 'none' }}>
            <ArrowLeft size={14} /> Volver al informe
          </a>
          <h1 style={{ marginTop: 8 }}>Plan de limpieza</h1>
          <p>
            {items.length} paquetes · {counts.uninstall} a desinstalar, {counts.disable} a desactivar ·{' '}
            <span className="mono">{saved.serial}</span> · creado {date(saved.created)}
          </p>
        </div>
      </header>

      <div className="plan-grid">
        <section className="panel" aria-label="Paquetes del plan">
          {items.length === 0 && (
            <div className="empty">
              <b>El plan está vacío</b>
              <span>Vuelve al informe y marca los paquetes que quieras quitar.</span>
            </div>
          )}
          {items.map((it) => {
            const freq = it.tags?.includes('frequent')
            return (
              <div className={`prow${freq ? ' frequent' : ''}`} key={it.package}>
                <div style={{ minWidth: 0 }}>
                  <div className="row" style={{ gap: 8 }}>
                    <b>{it.label || it.package.split('.').slice(-1)[0]}</b>
                    {freq && <Tag tag="frequent" />}
                  </div>
                  <div className="app-pkg">{it.package}</div>
                  <div className="row" style={{ gap: 14, marginTop: 2 }}>
                    {it.group && <GroupMark group={it.group} />}
                    {it.risk && <RiskMark risk={it.risk} />}
                  </div>
                </div>
                <span />
                <select
                  className="select"
                  value={it.action}
                  onChange={(e) => setAction(it.package, e.target.value as Action)}
                  disabled={locked}
                  aria-label={`Acción para ${it.package}`}
                >
                  <option value="uninstall">Desinstalar</option>
                  <option value="disable">Desactivar</option>
                </select>
                <button className="btn ghost icon" onClick={() => remove(it.package)} disabled={locked} aria-label={`Quitar ${it.package} del plan`} title="Quitar del plan">
                  <Trash2 size={16} />
                </button>
              </div>
            )
          })}
        </section>

        <aside className="plan-side">
          <Callout kind="info" icon={<ArchiveRestore size={18} />}>
            Todo es reversible: <b>Desinstalar</b> lo quita solo para el usuario (<code>--user 0</code>) y
            <b> Desactivar</b> lo congela. Antes de aplicar se guarda una copia para restaurar.
          </Callout>

          <div className="panel step-card">
            <h3><FlaskConical size={18} /> 1 · Simular</h3>
            <p className="muted">Muestra los comandos adb exactos sin tocar el dispositivo.</p>
            <button className="btn primary" onClick={simulate} disabled={!items.length || !!busy || locked}>
              {busy === 'dry' || busy === 'save' ? <Loader2 size={16} className="spin" /> : <FlaskConical size={16} />}
              {dirty ? 'Guardar cambios y simular' : simulated ? 'Simular de nuevo' : 'Simular'}
            </button>
            {dry && dry.status !== 'done' && dry.status !== 'failed' && <ProgressBar done={dry.progress?.done} total={dry.progress?.total} />}
            {dry && dryFor && !simulated && dry.status === 'done' && (
              <p className="faint">Has cambiado el plan desde la última simulación.</p>
            )}
            {dry && (
              <>
                <JobLog job={dry} dryRun />
                {dry.log.length > 0 && (
                  <button className="btn sm" style={{ justifySelf: 'start' }} onClick={() => navigator.clipboard?.writeText(dry.log.join('\n')).then(() => setCopied(true))}>
                    <Copy size={14} /> {copied ? 'Copiado' : 'Copiar comandos'}
                  </button>
                )}
              </>
            )}
          </div>

          <div className="panel step-card">
            <h3><PlugZap size={18} /> 2 · Aplicar en el dispositivo</h3>
            {!simulated && !finished && <p className="muted">Primero simula el plan tal como está ahora.</p>}
            {simulated && !run && (
              <SerialConfirm serial={saved.serial} label={`Aplicar ${items.length} cambios`} busy={busy === 'apply'} onConfirm={apply} />
            )}
            {run && (
              <>
                {applying && (
                  <>
                    <ProgressBar done={run.progress?.done} total={run.progress?.total} />
                    <p className="faint mono" style={{ fontSize: '0.8rem' }}>
                      {run.progress?.done ?? 0}/{run.progress?.total ?? items.length} · {run.progress?.current}
                    </p>
                  </>
                )}
                {run.status === 'failed' && <ErrorBox error={new Error(run.error ?? 'La aplicación ha fallado.')} />}
                {results.length > 0 && <Results results={results} />}
                {finished && backupId && (
                  <Callout kind="info">
                    Copia guardada: <span className="mono">{backupId}</span>.{' '}
                    <a href={href('copias')}>Ver copias y restaurar</a>
                  </Callout>
                )}
                {finished && (
                  <button className="btn" onClick={() => go('')}>
                    Volver a escanear para ver el efecto
                  </button>
                )}
              </>
            )}
          </div>
          {error && <ErrorBox error={error} />}
        </aside>
      </div>
    </>
  )
}
