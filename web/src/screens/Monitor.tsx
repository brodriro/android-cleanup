import { BatteryCharging, BatteryFull, BatteryMedium, Cpu, HardDrive, MemoryStick, Pause, RefreshCw, Smartphone } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import type { Device, Monitor as MonitorT } from '../api/types'
import { Callout, ErrorBox } from '../components/ui'
import { href, usePageVisible } from '../lib/hooks'

const POLL_MS = 5000
const STALE_MS = 15000
const DASH = '—'

const n1 = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 1 })
const n0 = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 0 })
const ok = (v: number | null | undefined): v is number => typeof v === 'number' && Number.isFinite(v)

const kbStr = (v: number | null | undefined) => (!ok(v) ? DASH : v >= 1024 * 1024 ? `${n1.format(v / 1048576)} GB` : `${n0.format(v / 1024)} MB`)
const bStr = (v: number | null | undefined) => (!ok(v) ? DASH : v >= 1024 ** 3 ? `${n1.format(v / 1024 ** 3)} GB` : `${n0.format(v / 1024 ** 2)} MB`)
const pStr = (v: number | null | undefined) => (ok(v) ? `${n1.format(v)} %` : DASH)
const txt = (v: string | number | null | undefined) => (v === null || v === undefined || v === '' ? DASH : String(v))

function uptime(s: number | null | undefined) {
  if (!ok(s)) return DASH
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  return d ? `${d} d ${h} h` : h ? `${h} h ${m} min` : `${m} min`
}

const BATT_STATUS: Record<string, string> = {
  charging: 'Cargando', discharging: 'Descargando', full: 'Completa', not_charging: 'No carga', unknown: 'Desconocido',
}
const PLUGGED: Record<string, string> = { usb: 'USB', ac: 'Cargador', wireless: 'Inalámbrica', none: 'Desenchufada' }
const HEALTH: Record<string, string> = {
  good: 'Buena', overheat: 'Sobrecalentada', dead: 'Agotada', over_voltage: 'Sobretensión', cold: 'Fría', unknown: 'Desconocida',
  unspecified_failure: 'Fallo',
}

/** Level → tone for a fill: calm under 75 %, amber to 90 %, red above. */
const tone = (p: number | null | undefined, invert = false) => {
  if (!ok(p)) return ''
  const v = invert ? 100 - p : p
  return v >= 90 ? 'hot' : v >= 75 ? 'warm' : ''
}

export function Monitor({ serial, devices }: { serial: string | undefined; devices: Device[] | undefined }) {
  const visible = usePageVisible()
  const [data, setData] = useState<MonitorT>()
  const [error, setError] = useState<Error>()
  const [lastOk, setLastOk] = useState<number>()
  const [now, setNow] = useState(Date.now())
  const [paused, setPaused] = useState(false)
  const [fetching, setFetching] = useState(false)
  const kick = useRef(0)
  const [tick, setTick] = useState(0)

  const dev = devices?.find((d) => d.serial === serial)
  const ready = !!serial && dev?.state === 'device'

  useEffect(() => {
    setData(undefined)
    setError(undefined)
    setLastOk(undefined)
  }, [serial])

  // Poll only while this section is mounted, the tab is visible and the user has not paused it.
  useEffect(() => {
    if (!ready || !visible || paused) return
    let alive = true
    let timer: ReturnType<typeof setTimeout>
    const ctl = new AbortController()
    const once = async () => {
      setFetching(true)
      try {
        const m = await api.monitor(serial, ctl.signal)
        if (!alive) return
        setData(m)
        setError(undefined)
        setLastOk(Date.now())
      } catch (e) {
        if (!alive || (e as Error).name === 'AbortError') return
        setError(e as Error)
      } finally {
        if (alive) {
          setFetching(false)
          timer = setTimeout(once, POLL_MS)
        }
      }
    }
    once()
    return () => {
      alive = false
      ctl.abort()
      clearTimeout(timer)
    }
  }, [serial, ready, visible, paused, tick])

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])

  const age = lastOk ? Math.max(0, Math.round((now - lastOk) / 1000)) : undefined
  const stale = !!lastOk && now - lastOk > STALE_MS

  if (!serial || !dev) {
    return (
      <>
        <MonitorHead />
        <Callout kind="warn">
          No hay un dispositivo elegido. Ve a <a href={href('')}>Dispositivos</a> y conecta uno.
        </Callout>
      </>
    )
  }
  if (!ready) {
    return (
      <>
        <MonitorHead />
        <Callout kind="warn">
          El dispositivo <span className="mono">{serial}</span> no está listo ({dev.state}). Revisa la conexión en{' '}
          <a href={href('')}>Dispositivos</a>.
        </Callout>
      </>
    )
  }

  const m = data
  const mem = m?.memory
  const memUsed = ok(mem?.used_kb) ? mem.used_kb : ok(mem?.total_kb) && ok(mem?.available_kb) ? mem.total_kb - mem.available_kb : null
  const memUsedPct = ok(mem?.used_pct) ? mem.used_pct : ok(memUsed) && ok(mem?.total_kb) && mem.total_kb ? (memUsed / mem.total_kb) * 100 : null
  const cachedPct = ok(mem?.cached_kb) && ok(mem?.total_kb) && mem.total_kb && ok(mem?.available_kb)
    ? (Math.min(mem.cached_kb, mem.available_kb) / mem.total_kb) * 100 : 0
  const swapPct = ok(mem?.swap_total_kb) && mem.swap_total_kb > 0 && ok(mem?.swap_used_kb) ? (mem.swap_used_kb / mem.swap_total_kb) * 100 : null
  const cores = m?.device.cpu_cores
  const topMax = Math.max(1, ...(m?.top_processes ?? []).map((p) => p.rss_kb ?? 0))
  const batt = m?.battery
  const BattIcon = batt?.status === 'charging' ? BatteryCharging : ok(batt?.level) && batt.level > 80 ? BatteryFull : BatteryMedium

  return (
    <>
      <MonitorHead>
        <span className={`live${stale || error ? ' stale' : ''}${paused ? ' paused' : ''}`} aria-live="polite">
          <i aria-hidden />
          {paused ? 'En pausa' : !lastOk ? 'Conectando…' : stale ? `Sin datos nuevos desde hace ${age} s` : `Actualizado hace ${age} s`}
        </span>
        <button className="btn sm" onClick={() => setPaused((p) => !p)} aria-pressed={paused}>
          {paused ? <RefreshCw size={14} /> : <Pause size={14} />}
          {paused ? 'Reanudar' : 'Pausar'}
        </button>
        <button className="btn sm ghost" onClick={() => { kick.current++; setTick(kick.current) }} disabled={fetching || paused} aria-label="Actualizar ahora">
          <RefreshCw size={14} className={fetching ? 'spin' : undefined} />
        </button>
      </MonitorHead>

      {error && (stale || !m) && (
        <div style={{ marginBottom: 16 }}>
          <ErrorBox error={new Error(`No se pudo leer el dispositivo: ${error.message}${m ? ' Los datos de abajo están desactualizados.' : ''}`)} />
        </div>
      )}

      {!m && !error && <div className="mon-grid"><div className="skeleton" style={{ height: 180 }} /><div className="skeleton" style={{ height: 180 }} /><div className="skeleton" style={{ height: 180 }} /></div>}

      {m && (
        <div className={`mon${stale ? ' is-stale' : ''}`}>
          <section className="panel ident">
            <div className="ident-name">
              <Smartphone size={20} />
              <b>{[m.device.manufacturer && m.device.manufacturer[0].toUpperCase() + m.device.manufacturer.slice(1), m.device.model].filter(Boolean).join(' ') || DASH}</b>
              <span className="mono faint">{m.serial}</span>
            </div>
            <dl className="ident-dl">
              <Item k="Android" v={m.device.android ? `${m.device.android}${ok(m.device.sdk) ? ` · API ${m.device.sdk}` : ''}` : DASH} />
              <Item k="Compilación" v={<span className="mono">{txt(m.device.build)}</span>} />
              <Item k="CPU" v={`${ok(cores) ? `${cores} núcleos` : DASH}${m.device.abi ? ` · ${m.device.abi}` : ''}`} />
              <Item k="Pantalla" v={m.device.screen ? m.device.screen.replace('x', ' × ') : DASH} />
              <Item k="Encendido" v={uptime(m.device.uptime_s)} />
            </dl>
          </section>

          <div className="mon-grid">
            <Instrument icon={<MemoryStick size={18} />} title="Memoria RAM" big={pStr(memUsedPct)} sub={`${kbStr(memUsed)} en uso de ${kbStr(mem?.total_kb)}`}>
              <div className="gauge" role="img" aria-label={`RAM en uso ${pStr(memUsedPct)}`}>
                <span className={`fill ${tone(memUsedPct)}`} style={{ width: `${memUsedPct ?? 0}%` }} />
                <span className="cache" style={{ width: `${cachedPct}%` }} />
              </div>
              <dl className="kv">
                <Item k={<><i className="sw used" />En uso</>} v={kbStr(memUsed)} />
                <Item k={<><i className="sw cache" />Caché</>} v={kbStr(mem?.cached_kb)} />
                <Item k={<><i className="sw free" />Disponible</>} v={kbStr(mem?.available_kb)} />
              </dl>
              <div className="subgauge">
                <div className="row" style={{ justifyContent: 'space-between' }}>
                  <span className="faint">Swap / zram</span>
                  <span className="num">{kbStr(mem?.swap_used_kb)} de {kbStr(mem?.swap_total_kb)}</span>
                </div>
                <div className="gauge thin"><span className={`fill ${tone(swapPct)}`} style={{ width: `${swapPct ?? 0}%` }} /></div>
              </div>
            </Instrument>

            <Instrument icon={<HardDrive size={18} />} title="Almacenamiento">
              {m.storage.length === 0 && <p className="faint">{DASH}</p>}
              {m.storage.map((s) => (
                <div className="mount" key={s.mount}>
                  <div className="row" style={{ justifyContent: 'space-between' }}>
                    <b className="mono">{s.mount}</b>
                    <span className="num">{pStr(s.used_pct)}</span>
                  </div>
                  <div className="gauge thin"><span className={`fill ${tone(s.used_pct)}`} style={{ width: `${s.used_pct ?? 0}%` }} /></div>
                  <span className="faint" style={{ fontSize: '0.82rem' }}>
                    {bStr(s.used_bytes)} usados · {bStr(s.free_bytes)} libres de {bStr(s.total_bytes)}
                  </span>
                </div>
              ))}
            </Instrument>

            <Instrument icon={<Cpu size={18} />} title="Procesador" big={pStr(m.cpu.usage_pct)} sub="uso total">
              <div className="gauge"><span className={`fill ${tone(m.cpu.usage_pct)}`} style={{ width: `${m.cpu.usage_pct ?? 0}%` }} /></div>
              <dl className="kv">
                {['1 min', '5 min', '15 min'].map((lbl, i) => (
                  <Item key={lbl} k={`Carga ${lbl}`} v={ok(m.cpu.load_avg?.[i]) ? n1.format(m.cpu.load_avg[i]) : DASH} />
                ))}
              </dl>
              {ok(cores) && <p className="faint" style={{ fontSize: '0.8rem' }}>Con {cores} núcleos, una carga por encima de {cores} indica cola de espera.</p>}
            </Instrument>

            <Instrument icon={<BattIcon size={18} />} title="Batería" big={ok(batt?.level) ? `${batt.level} %` : DASH} sub={batt?.status ? BATT_STATUS[batt.status] ?? batt.status : DASH}>
              <div className="gauge"><span className={`fill batt ${tone(batt?.level, true)}`} style={{ width: `${batt?.level ?? 0}%` }} /></div>
              <dl className="kv">
                <Item k="Alimentación" v={batt?.plugged ? PLUGGED[batt.plugged] ?? batt.plugged : DASH} />
                <Item k="Temperatura" v={ok(batt?.temperature_c) ? `${n1.format(batt.temperature_c)} °C` : DASH} />
                <Item k="Salud" v={batt?.health ? HEALTH[batt.health] ?? batt.health : DASH} />
              </dl>
            </Instrument>
          </div>

          <div className="mon-grid two">
            <section className="panel instrument">
              <h3>Recuento</h3>
              <dl className="counts">
                <div><dt>Paquetes</dt><dd className="num">{ok(m.counts.packages) ? n0.format(m.counts.packages) : DASH}</dd></div>
                <div><dt>Instalados por el usuario</dt><dd className="num">{ok(m.counts.user_packages) ? n0.format(m.counts.user_packages) : DASH}</dd></div>
                <div><dt>Procesos</dt><dd className="num">{ok(m.counts.processes) ? n0.format(m.counts.processes) : DASH}</dd></div>
              </dl>
            </section>
            <section className="panel instrument">
              <h3>Procesos que más RAM usan</h3>
              {m.top_processes.length === 0 && <p className="faint">{DASH}</p>}
              <ol className="top">
                {m.top_processes.slice(0, 8).map((p) => (
                  <li key={p.pid}>
                    <span className="top-name mono" title={p.name}>{p.name}</span>
                    <span className="top-bar"><span style={{ width: `${((p.rss_kb ?? 0) / topMax) * 100}%` }} /></span>
                    <span className="num">{kbStr(p.rss_kb)}</span>
                  </li>
                ))}
              </ol>
            </section>
          </div>
        </div>
      )}
    </>
  )
}

function MonitorHead({ children }: { children?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <h1>Monitor</h1>
        <p>Datos en vivo del dispositivo, solo lectura. Se actualiza cada 5 s mientras esta sección está abierta.</p>
      </div>
      {children && <div className="row">{children}</div>}
    </header>
  )
}

function Instrument({ icon, title, big, sub, children }: { icon: ReactNode; title: string; big?: string; sub?: string; children: ReactNode }) {
  return (
    <section className="panel instrument">
      <h3>{icon}{title}</h3>
      {big !== undefined && (
        <div className="readout">
          <span className="big num">{big}</span>
          {sub && <span className="faint">{sub}</span>}
        </div>
      )}
      {children}
    </section>
  )
}

function Item({ k, v }: { k: ReactNode; v: ReactNode }) {
  return (
    <div>
      <dt>{k}</dt>
      <dd>{v}</dd>
    </div>
  )
}
