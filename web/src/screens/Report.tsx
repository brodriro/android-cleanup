import {
  AlertTriangle, ArrowDown, ArrowRight, ArrowUp, ChevronDown, ChevronRight, ClipboardList, Loader2, PackageSearch,
  Search, X,
} from 'lucide-react'
import { Fragment, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import type { Action, Report as ReportT, Summary } from '../api/types'
import { ErrorBox, GroupMark, Lockout, RiskMark, Tag, Tags } from '../components/ui'
import { isFrequent, isLocked, normalize, type Row } from '../lib/classify'
import {
  ACTION_LABEL, BUCKET_LABEL, CATEGORY_LABEL, GROUP_HINT, REC_LABEL, RISK_LABEL, TAG_LABEL, bytes, date, int, kb, pct,
} from '../lib/format'
import { go, useAsync } from '../lib/hooks'

type SortKey = 'ram' | 'storage' | 'name'
const SPECIAL_TAGS = ['frequent', 'bloat', 'telemetry', 'background', 'running', 'unused', 'large', 'core', 'disabled']

export function suggestedAction(c: Row): Action {
  if (c.action === 'uninstall' || c.action === 'disable') return c.action
  return c.risk === 'caution' || c.group === 'system' ? 'disable' : 'uninstall'
}

export function Report({
  scanId, selection, setSelection,
}: {
  scanId: string
  selection: Set<string> | undefined
  setSelection: (s: Set<string>) => void
}) {
  const rep = useAsync(() => api.report(scanId, true), [scanId])
  const rows = useMemo(() => rep.data?.candidates.map(normalize) ?? [], [rep.data])

  // Default selection: what the analyzer recommends removing (never danger, never frequent without consent).
  useEffect(() => {
    if (rep.data && !selection) {
      setSelection(new Set(rows.filter((r) => r.recommendation === 'remove' && !isLocked(r) && !isFrequent(r)).map((r) => r.package)))
    }
  }, [rep.data, rows, selection, setSelection])

  if (rep.error) return <ErrorBox error={rep.error} onRetry={rep.reload} />
  if (!rep.data || !selection) return <ReportSkeleton />
  return <ReportBody report={rep.data} rows={rows} scanId={scanId} selection={selection} setSelection={setSelection} />
}

function ReportSkeleton() {
  return (
    <div style={{ display: 'grid', gap: 14 }} aria-busy>
      <div className="skeleton" style={{ height: 34, width: 320 }} />
      <div className="skeleton" style={{ height: 120 }} />
      <div className="skeleton" style={{ height: 420 }} />
    </div>
  )
}

function useEstimate(scanId: string, selection: Set<string>, initial: Summary) {
  const [summary, setSummary] = useState<Summary>(initial)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<Error>()
  useEffect(() => {
    const ctl = new AbortController()
    setPending(true)
    const t = setTimeout(() => {
      api.estimate(scanId, [...selection], ctl.signal).then(
        (s) => {
          setSummary(s)
          setError(undefined)
          setPending(false)
        },
        (e: Error) => {
          if (e.name === 'AbortError') return
          setError(e)
          setPending(false)
        },
      )
    }, 350)
    return () => {
      clearTimeout(t)
      ctl.abort()
    }
  }, [scanId, selection])
  return { summary, pending, error }
}

function ReportBody({
  report, rows, scanId, selection, setSelection,
}: {
  report: ReportT
  rows: Row[]
  scanId: string
  selection: Set<string>
  setSelection: (s: Set<string>) => void
}) {
  const [q, setQ] = useState('')
  const [group, setGroup] = useState<'all' | 'third_party' | 'system'>('all')
  const [rec, setRec] = useState<'all' | 'remove' | 'review' | 'keep'>('all')
  const [risk, setRisk] = useState<string>('all')
  const [tags, setTags] = useState<Set<string>>(new Set())
  const [onlySel, setOnlySel] = useState(false)
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'ram', desc: true })
  const [open, setOpen] = useState<string>()
  const [asking, setAsking] = useState<string>()
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<Error>()
  const est = useEstimate(scanId, selection, report.summary)

  const derived = rows.some((r) => r.derived)
  const dev = report.device
  const scanDate = report.scan?.created

  const presentTags = useMemo(() => {
    const s = new Set<string>()
    rows.forEach((r) => r.tags.forEach((t) => s.add(t)))
    return [...SPECIAL_TAGS.filter((t) => s.has(t)), ...[...s].filter((t) => !SPECIAL_TAGS.includes(t)).sort()]
  }, [rows])

  const base = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return rows.filter(
      (r) =>
        (!needle || r.package.toLowerCase().includes(needle) || r.label.toLowerCase().includes(needle)) &&
        (rec === 'all' || r.recommendation === rec) &&
        (risk === 'all' || r.risk === risk) &&
        [...tags].every((t) => r.tags.includes(t)) &&
        (!onlySel || selection.has(r.package)),
    )
  }, [rows, q, rec, risk, tags, onlySel, selection])

  const groupCount = useMemo(
    () => ({
      all: base.length,
      third_party: base.filter((r) => r.group === 'third_party').length,
      system: base.filter((r) => r.group === 'system').length,
    }),
    [base],
  )

  const visible = useMemo(() => {
    const list = base.filter((r) => group === 'all' || r.group === group)
    const val = (r: Row) => (sort.key === 'ram' ? r.pss_kb : sort.key === 'storage' ? r.reclaimable_bytes : 0)
    list.sort((a, b) => {
      if (sort.key === 'name') {
        const c = (a.label || a.package).localeCompare(b.label || b.package, 'es')
        return sort.desc ? -c : c
      }
      return sort.desc ? val(b) - val(a) : val(a) - val(b)
    })
    return list
  }, [base, group, sort])

  function toggle(r: Row, force = false) {
    if (isLocked(r)) return
    const next = new Set(selection)
    if (next.has(r.package)) {
      next.delete(r.package)
      setAsking(undefined)
    } else if (isFrequent(r) && !force) {
      setAsking(r.package)
      return
    } else {
      next.add(r.package)
      setAsking(undefined)
    }
    setSelection(next)
  }

  function selectVisible(on: boolean) {
    const next = new Set(selection)
    for (const r of visible) {
      if (isLocked(r)) continue
      if (on && isFrequent(r)) continue // frequent apps are only added one by one, with consent
      if (on) next.add(r.package)
      else next.delete(r.package)
    }
    setSelection(next)
  }

  function sortBy(key: SortKey) {
    setSort((s) => (s.key === key ? { key, desc: !s.desc } : { key, desc: key !== 'name' }))
  }

  async function createPlan() {
    setCreating(true)
    setCreateError(undefined)
    try {
      const items = rows.filter((r) => selection.has(r.package) && !isLocked(r)).map((r) => ({ package: r.package, action: suggestedAction(r) }))
      const plan = await api.createPlan(scanId, items)
      go('plan', plan.id)
    } catch (e) {
      setCreateError(e as Error)
      setCreating(false)
    }
  }

  const selFrequent = rows.filter((r) => selection.has(r.package) && isFrequent(r)).length
  const filtersOn = q || rec !== 'all' || risk !== 'all' || tags.size || onlySel || group !== 'all'
  const SortIcon = sort.desc ? ArrowDown : ArrowUp

  return (
    <>
      <header className="page-head" style={{ marginBottom: 14 }}>
        <div>
          <h1>
            {dev.manufacturer ? dev.manufacturer[0].toUpperCase() + dev.manufacturer.slice(1) : ''} {dev.model ?? dev.serial}
          </h1>
          <div className="nameplate">
            <span>Android <b>{dev.android ?? '—'}</b></span>
            <span>RAM <b>{kb(dev.mem_total_kb ?? report.summary.mem_total_kb)}</b></span>
            <span><b>{int(rows.length)}</b> paquetes</span>
            <span className="mono">{dev.serial}</span>
            {scanDate && <span>Escaneado el {date(scanDate)}</span>}
          </div>
        </div>
      </header>

      <div className="meter-dock">
        <Meter summary={est.summary} pending={est.pending}>
          <button className="btn ghost sm" onClick={() => setSelection(new Set())} disabled={!selection.size}>
            Vaciar
          </button>
          <button className="btn primary" onClick={createPlan} disabled={!selection.size || creating}>
            {creating ? <Loader2 size={16} className="spin" /> : <ClipboardList size={16} />}
            Crear plan con {selection.size}
            <ArrowRight size={16} />
          </button>
        </Meter>
        {(selFrequent > 0 || est.error || createError) && (
          <div className="row" style={{ marginTop: 8 }}>
            {selFrequent > 0 && (
              <span className="chip frequent">
                <AlertTriangle size={12} /> {selFrequent} de uso frecuente en la selección
              </span>
            )}
            {est.error && <span className="faint">No se pudo recalcular: {est.error.message}</span>}
            {createError && <span style={{ color: 'var(--danger)', fontWeight: 600 }}>{createError.message}</span>}
          </div>
        )}
      </div>

      <div className="mobile-cta">
        <span>
          <b className="num">{kb(est.summary.ram_kb)}</b> RAM · <b className="num">{bytes(est.summary.storage_bytes)}</b>
        </span>
        <button className="btn primary" onClick={createPlan} disabled={!selection.size || creating}>
          <ClipboardList size={16} /> Plan ({selection.size})
        </button>
      </div>

      <div className="toolbar">
        <div className="row">
          <div className="search">
            <Search size={16} />
            <input
              className="input"
              type="search"
              placeholder="Buscar por nombre o paquete"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              aria-label="Buscar"
            />
          </div>
          <div className="seg" role="group" aria-label="Grupo">
            {(['all', 'third_party', 'system'] as const).map((g) => (
              <button key={g} aria-pressed={group === g} onClick={() => setGroup(g)} title={g === 'all' ? undefined : GROUP_HINT[g]}>
                {g === 'all' ? 'Todos' : g === 'third_party' ? 'Terceros' : 'Sistema'}
                <span className="count">{groupCount[g]}</span>
              </button>
            ))}
          </div>
          <select className="select" value={rec} onChange={(e) => setRec(e.target.value as typeof rec)} aria-label="Recomendación">
            <option value="all">Toda recomendación</option>
            {(['remove', 'review', 'keep'] as const).map((r) => (
              <option key={r} value={r}>{REC_LABEL[r]}</option>
            ))}
          </select>
          <select className="select" value={risk} onChange={(e) => setRisk(e.target.value)} aria-label="Riesgo">
            <option value="all">Todo riesgo</option>
            {['safe', 'caution', 'unknown', 'danger'].map((r) => (
              <option key={r} value={r}>{RISK_LABEL[r]}</option>
            ))}
          </select>
          <select
            className="select"
            value={`${sort.key}:${sort.desc ? 'd' : 'a'}`}
            onChange={(e) => {
              const [key, d] = e.target.value.split(':')
              setSort({ key: key as SortKey, desc: d === 'd' })
            }}
            aria-label="Ordenar"
          >
            <option value="ram:d">Más RAM primero</option>
            <option value="storage:d">Más almacenamiento primero</option>
            <option value="name:a">Nombre (A–Z)</option>
          </select>
          <span className="spacer" />
          <button className="btn ghost sm" onClick={() => selectVisible(true)} title="Las apps de uso frecuente y las bloqueadas no se añaden en bloque">
          Marcar visibles
        </button>
          <button className="btn ghost sm" onClick={() => selectVisible(false)}>
          Desmarcar visibles
        </button>
        </div>
        <div className="tagbar">
          <span className="lbl">Etiquetas</span>
          {presentTags.map((t) => (
            <button
              key={t}
              className={`chip ${t}`}
              aria-pressed={tags.has(t)}
              onClick={() => {
                const n = new Set(tags)
                if (n.has(t)) n.delete(t)
                else n.add(t)
                setTags(n)
              }}
            >
              {TAG_LABEL[t] ?? t}
            </button>
          ))}
          <label className="row" style={{ gap: 6, fontSize: '0.84rem', marginLeft: 8, cursor: 'pointer' }}>
            <input type="checkbox" checked={onlySel} onChange={(e) => setOnlySel(e.target.checked)} />
            Solo seleccionados
          </label>
          {filtersOn ? (
            <button
              className="btn ghost sm"
              onClick={() => {
                setQ('')
                setGroup('all')
                setRec('all')
                setRisk('all')
                setTags(new Set())
                setOnlySel(false)
              }}
            >
              <X size={14} /> Quitar filtros
            </button>
          ) : null}
        </div>
        {derived && (
          <p className="faint" style={{ fontSize: '0.8rem' }}>
            El servidor aún no envía grupo ni etiquetas: se calculan en el panel a partir del riesgo y el uso.
          </p>
        )}
      </div>

      <div className="panel sched" role="table" aria-label="Paquetes">
        <div className="sched-head" role="row">
          <span role="columnheader"><span className="sr-only">Seleccionar</span></span>
          <span role="columnheader">
            <button onClick={() => sortBy('name')}>App {sort.key === 'name' && <SortIcon size={12} />}</button>
          </span>
          <span role="columnheader" className="c-group">Grupo</span>
          <span role="columnheader" className="c-tags">Etiquetas</span>
          <span role="columnheader" className="c-risk">Riesgo</span>
          <span role="columnheader" className="c-rec">Sugerido</span>
          <span role="columnheader" className="r">
            <button onClick={() => sortBy('ram')}>RAM {sort.key === 'ram' && <SortIcon size={12} />}</button>
          </span>
          <span role="columnheader" className="r">
            <button onClick={() => sortBy('storage')}>Espacio {sort.key === 'storage' && <SortIcon size={12} />}</button>
          </span>
        </div>
        {visible.length === 0 && (
          <div className="empty">
            <PackageSearch size={32} />
            <b>Ningún paquete coincide con estos filtros</b>
            <span>Prueba a quitar alguna etiqueta o cambia el grupo.</span>
          </div>
        )}
        {visible.map((r) => (
          <Fragment key={r.package}>
            <CandidateRow
              r={r}
              selected={selection.has(r.package)}
              open={open === r.package}
              onToggle={() => toggle(r)}
              onOpen={() => setOpen(open === r.package ? undefined : r.package)}
            />
            {asking === r.package && (
              <div className="confirm-inline" role="alertdialog" aria-label="Confirmar app de uso frecuente">
                <AlertTriangle size={18} />
                <span style={{ flex: '1 1 320px' }}>
                  <b>Usas {r.label || r.package} a menudo.</b> Si la quitas dejará de estar disponible
                  {r.last_used_days === 0 ? ' (la usaste hoy)' : r.last_used_days ? ` (último uso hace ${r.last_used_days} días)` : ''}.
                  Se puede restaurar desde Copias.
                </span>
                <button className="btn sm" onClick={() => setAsking(undefined)} autoFocus>
                  Mantenerla
                </button>
                <button className="btn sm primary" onClick={() => toggle(r, true)}>
                  Marcar igualmente
                </button>
              </div>
            )}
            {open === r.package && <Detail r={r} />}
          </Fragment>
        ))}
      </div>
    </>
  )
}

function CandidateRow({ r, selected, open, onToggle, onOpen }: { r: Row; selected: boolean; open: boolean; onToggle: () => void; onOpen: () => void }) {
  const locked = isLocked(r)
  const freq = isFrequent(r)
  return (
    <div className={`crow${selected ? ' sel' : ''}${freq ? ' frequent' : ''}${locked ? ' locked' : ''}`} role="row">
      <span role="cell">
        {locked ? (
          <Lockout />
        ) : (
          <button
            className={`breaker${freq ? ' warn' : ''}`}
            role="switch"
            aria-checked={selected}
            aria-label={`${selected ? 'Desmarcar' : 'Marcar'} ${r.label || r.package}`}
            onClick={onToggle}
          />
        )}
      </span>
      <button className="app" role="cell" onClick={onOpen} aria-expanded={open}>
        <span className="app-name">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} className="faint" />}
          <span className="app-label">{r.label || r.package.split('.').slice(-1)[0]}</span>
        </span>
        <span className="app-pkg">{r.package}</span>
      </button>
      <span role="cell" className="c-group"><GroupMark group={r.group} /></span>
      <span role="cell" className="c-tags"><Tags tags={r.tags} max={2} /></span>
      <span role="cell" className="c-risk"><RiskMark risk={r.risk} /></span>
      <span role="cell" className={`c-rec rec ${r.recommendation}`}>{REC_LABEL[r.recommendation]}</span>
      <span role="cell" className={`num r c-ram${r.pss_kb ? '' : ' zero'}`}>{r.pss_kb ? kb(r.pss_kb) : '—'}</span>
      <span role="cell" className={`num r c-sto${r.reclaimable_bytes ? '' : ' zero'}`}>{bytes(r.reclaimable_bytes)}</span>
      <span className="c-meta">
        <GroupMark group={r.group} />
        <RiskMark risk={r.risk} />
        {freq && <Tag tag="frequent" />}
        <span className="num faint">{bytes(r.reclaimable_bytes)}</span>
      </span>
    </div>
  )
}

function Detail({ r }: { r: Row }) {
  return (
    <div className="detail">
      <div>
        <h3 style={{ marginBottom: 6 }}>Por qué</h3>
        <ul>
          {r.reasons.length ? r.reasons.map((x, i) => <li key={i}>{x}</li>) : <li>Sin motivos registrados.</li>}
        </ul>
        {isLocked(r) && (
          <p style={{ marginTop: 8, color: 'var(--danger)', fontWeight: 600 }}>Paquete crítico: quitarlo puede dejar el dispositivo inutilizable.</p>
        )}
        <div className="tags" style={{ marginTop: 10 }}>
          {r.tags.map((t) => <Tag key={t} tag={t} />)}
        </div>
      </div>
      <dl>
        <dt>Categoría</dt><dd>{CATEGORY_LABEL[r.category] ?? r.category}</dd>
        <dt>Origen</dt><dd>{r.origin === 'user' ? 'Instalada por el usuario' : r.origin === 'preinstalled' || r.system ? 'Preinstalada' : 'Instalada por el usuario'}</dd>
        <dt>Estado</dt><dd>{r.enabled ? 'Activada' : 'Desactivada'}</dd>
        <dt>Uso</dt><dd>{BUCKET_LABEL[r.bucket] ?? (r.bucket || '—')}{r.last_used_days != null ? ` · hace ${r.last_used_days} d` : ''}</dd>
        <dt>Acción sugerida</dt><dd>{ACTION_LABEL[r.action]}</dd>
        {r.confidence && (<><dt>Confianza</dt><dd>{{ high: 'alta', medium: 'media', low: 'baja' }[r.confidence]}</dd></>)}
      </dl>
      <dl>
        <dt>Procesos</dt><dd className="num">{r.processes}</dd>
        <dt>Servicios</dt><dd className="num">{r.services}</dd>
        <dt>RAM (PSS)</dt><dd className="num">{kb(r.pss_kb)}</dd>
        <dt>App</dt><dd className="num">{bytes(r.code_bytes)}</dd>
        <dt>Datos</dt><dd className="num">{bytes(r.data_bytes)}</dd>
        <dt>Caché</dt><dd className="num">{bytes(r.cache_bytes)}</dd>
      </dl>
    </div>
  )
}

export function Meter({ summary: s, pending, children }: { summary: Summary; pending?: boolean; children?: ReactNode }) {
  const total = s.mem_total_kb || 1
  const used = Math.max(0, s.mem_total_kb - s.mem_available_kb)
  const freed = Math.min(s.ram_kb, used)
  return (
    <div className="panel meter-card" aria-live="polite">
      <div className="meter-top">
        <span className="gain">
          {kb(s.ram_kb)} <small>de RAM liberada · {pct(s.ram_pct)} del total</small>
        </span>
        <span className="spacer" />
        <span className="calc">
          {pending ? <><Loader2 size={12} className="spin" /> recalculando</> : `${int(s.selected)} seleccionados`}
        </span>
        {children}
      </div>
      <div className="meter" role="img" aria-label={`Memoria: ${kb(used)} en uso de ${kb(s.mem_total_kb)}; se liberarían ${kb(freed)}`}>
        <span className="used" style={{ width: `${((used - freed) / total) * 100}%` }} />
        <span className="freed" style={{ width: `${(freed / total) * 100}%` }} />
      </div>
      <div className="facts">
        <span>
          Disponible <b>{kb(s.mem_available_kb)}</b> <span className="arrow">→</span> <b>{kb(s.mem_available_after_kb)}</b>
        </span>
        <span><b>{int(s.processes)}</b> procesos y <b>{int(s.services)}</b> servicios detenidos</span>
        <span><b>{bytes(s.storage_bytes)}</b> de almacenamiento recuperado</span>
        {s.ram_sustained_kb !== s.ram_kb && <span>Ahorro sostenido <b>{kb(s.ram_sustained_kb)}</b></span>}
      </div>
    </div>
  )
}
