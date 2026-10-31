import { Activity, FlaskConical } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { MOCK, api } from './api/client'
import type { Device, Health } from './api/types'
import { href, useRoute } from './lib/hooks'
import { Backups } from './screens/Backups'
import { Devices } from './screens/Devices'
import { Monitor } from './screens/Monitor'
import { Plan } from './screens/Plan'
import { Report } from './screens/Report'

export function App() {
  const route = useRoute()
  const [section, param] = route
  const [devices, setDevices] = useState<Device[]>()
  const [devErr, setDevErr] = useState<Error>()
  const [serial, setSerial] = useState<string>()
  const [health, setHealth] = useState<Health>()
  const [selections, setSelections] = useState<Record<string, Set<string>>>({})
  const [lastScan, setLastScan] = useState<string>()
  const [lastPlan, setLastPlan] = useState<string>()

  const loadDevices = useCallback(() => {
    api.devices().then(
      (d) => {
        setDevices(d)
        setDevErr(undefined)
        setSerial((s) => (s && d.some((x) => x.serial === s) ? s : d.find((x) => x.state === 'device')?.serial ?? d[0]?.serial))
      },
      (e: Error) => setDevErr(e),
    )
  }, [])

  useEffect(() => {
    loadDevices()
    api.health().then(setHealth, () => undefined)
    // Device list refreshes on its own so an "unauthorized" device flips to ready once the prompt is accepted.
    const t = setInterval(loadDevices, 5000)
    return () => clearInterval(t)
  }, [loadDevices])

  useEffect(() => {
    if (section === 'informe' && param) setLastScan(param)
    if (section === 'plan' && param) setLastPlan(param)
  }, [section, param])

  useEffect(() => {
    if (!lastScan) api.scans().then((s) => s[0] && setLastScan((cur) => cur ?? s[0].id), () => undefined)
  }, [lastScan])

  const setSelection = useCallback((scanId: string) => (s: Set<string>) => setSelections((m) => ({ ...m, [scanId]: s })), [])

  const current = section ?? ''
  const dev = devices?.find((d) => d.serial === serial)
  const steps: { key: string; label: string; to?: string }[] = [
    { key: '', label: 'Dispositivos', to: href('') },
    { key: 'informe', label: 'Informe', to: lastScan ? href('informe', lastScan) : undefined },
    { key: 'plan', label: 'Plan y aplicar', to: lastPlan ? href('plan', lastPlan) : undefined },
    { key: 'copias', label: 'Copias', to: href('copias') },
  ]

  let screen
  if (section === 'informe' && param) {
    screen = <Report key={param} scanId={param} selection={selections[param]} setSelection={setSelection(param)} />
  } else if (section === 'plan' && param) {
    screen = <Plan planId={param} />
  } else if (section === 'copias') {
    screen = <Backups />
  } else if (section === 'monitor') {
    screen = <Monitor serial={serial} devices={devices} />
  } else {
    screen = <Devices devices={devices} devicesError={devErr} reloadDevices={loadDevices} onPick={setSerial} />
  }

  return (
    <div className="shell">
      <nav className="rail" aria-label="Secciones">
        <div className="brand">
          <span className="brand-mark" aria-hidden>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
              <rect x="6" y="2.5" width="12" height="19" rx="2.5" />
              <path d="M10 8h4M10 12h4" />
            </svg>
          </span>
          <span>
            Limpieza Android
            <small>device-cleanup</small>
          </span>
        </div>
        <ol className="steps">
          {steps.map((s, i) => (
            <li key={s.key}>
              <a
                href={s.to ?? '#'}
                aria-current={current === s.key ? 'page' : undefined}
                aria-disabled={!s.to || undefined}
              >
                <span className="step-n">{i + 1}</span>
                {s.label}
              </a>
            </li>
          ))}
        </ol>
        <ul className="steps" style={{ marginTop: -16 }}>
          <li>
            <a href={href('monitor')} aria-current={current === 'monitor' ? 'page' : undefined}>
              <span className="step-n" style={{ border: 0 }}><Activity size={15} /></span>
              Monitor
            </a>
          </li>
        </ul>
        <div className="rail-foot">
          {MOCK && (
            <span className="mock-flag" title="Datos de ejemplo del SM-T290; no hay backend real">
              <FlaskConical size={12} /> Modo simulado
            </span>
          )}
          {dev && (
            <div className="rail-device">
              <b>{dev.model ? dev.model.replace(/_/g, '-') : 'Dispositivo'}</b>
              <span className="mono">{dev.serial}</span>
              <span>{dev.state === 'device' ? 'Conectado' : dev.state === 'unauthorized' ? 'Sin autorizar' : 'Sin conexión'}</span>
            </div>
          )}
          {health && <span>Servidor {health.version}</span>}
        </div>
      </nav>
      <main className="main" id="main">
        {screen}
      </main>
    </div>
  )
}
