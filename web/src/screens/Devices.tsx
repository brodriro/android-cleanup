import { FileText, Loader2, RefreshCw, ScanLine, Smartphone, Unplug } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, pollJob } from '../api/client'
import type { Device, Job } from '../api/types'
import { Callout, ErrorBox, JobLog, ProgressBar } from '../components/ui'
import { date } from '../lib/format'
import { go, href, useAsync } from '../lib/hooks'

const STATE_LABEL: Record<string, string> = { device: 'Conectado', unauthorized: 'Sin autorizar', offline: 'Sin conexión' }

export function Devices({
  devices, devicesError, reloadDevices, onPick,
}: {
  devices: Device[] | undefined
  devicesError: Error | undefined
  reloadDevices: () => void
  onPick: (serial: string) => void
}) {
  const scans = useAsync(() => api.scans(), [])
  const [job, setJob] = useState<Job>()
  const [scanError, setScanError] = useState<Error>()
  const [elapsed, setElapsed] = useState(0)
  const abort = useRef<AbortController>(undefined)

  useEffect(() => () => abort.current?.abort(), [])
  useEffect(() => {
    if (!job || job.status === 'done' || job.status === 'failed') return
    const t = setInterval(() => setElapsed((e) => e + 1), 1000)
    return () => clearInterval(t)
  }, [job])

  async function scan(serial: string) {
    onPick(serial)
    setScanError(undefined)
    setElapsed(0)
    abort.current = new AbortController()
    try {
      const id = await api.startScan(serial)
      setJob({ id, kind: 'scan', status: 'queued', progress: null, log: [], result: null, error: null })
      const final = await pollJob(id, setJob, abort.current.signal)
      if (final.status === 'done' && final.result && 'scan_id' in final.result) go('informe', final.result.scan_id)
    } catch (e) {
      if ((e as Error).name !== 'AbortError') setScanError(e as Error)
    }
  }

  const scanning = job && (job.status === 'queued' || job.status === 'running')

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Dispositivos</h1>
          <p>Conecta la tablet o el móvil por USB con la depuración USB activada. El escaneo solo lee: no cambia nada.</p>
        </div>
        <button className="btn" onClick={reloadDevices}>
          <RefreshCw size={16} />
          Actualizar
        </button>
      </header>

      {devicesError && <ErrorBox error={devicesError} onRetry={reloadDevices} />}

      {!devices && !devicesError && (
        <div className="device-list">
          <div className="skeleton" style={{ height: 76 }} />
        </div>
      )}

      {devices && devices.length === 0 && (
        <div className="panel empty">
          <Unplug size={32} />
          <h2>No hay ningún dispositivo conectado</h2>
          <p style={{ maxWidth: '52ch' }}>
            Conecta el dispositivo con un cable de datos y activa <b>Opciones de desarrollador → Depuración USB</b>. Esta
            lista se actualiza sola.
          </p>
        </div>
      )}

      {devices && devices.length > 0 && (
        <div className="device-list">
          {devices.map((d) => (
            <article key={d.serial} className={`panel device state-${d.state}`}>
              <div className="device-ico">
                <Smartphone size={22} />
              </div>
              <div style={{ minWidth: 0 }}>
                <div className="row" style={{ gap: 8 }}>
                  <span className="device-name">{d.model ? d.model.replace(/_/g, '-') : 'Dispositivo desconocido'}</span>
                  <span className={`state-pill ${d.state}`}>{STATE_LABEL[d.state] ?? d.state}</span>
                </div>
                <div className="mono faint">{d.serial}</div>
              </div>
              {d.state === 'device' ? (
                <button className="btn primary" onClick={() => scan(d.serial)} disabled={!!scanning}>
                  {scanning ? <Loader2 size={16} className="spin" /> : <ScanLine size={16} />}
                  Escanear
                </button>
              ) : (
                <span />
              )}
              {d.state === 'unauthorized' && (
                <Callout kind="warn">
                  <b>Falta autorizar este ordenador.</b> Desbloquea el dispositivo y acepta el aviso
                  «¿Permitir depuración USB?».
                  <ol>
                    <li>Marca «Permitir siempre desde este ordenador» para no repetirlo.</li>
                    <li>Si el aviso no aparece, desconecta y vuelve a conectar el cable.</li>
                    <li>
                      Si sigue sin aparecer: Opciones de desarrollador → <b>Revocar autorizaciones de depuración USB</b> y
                      reconecta.
                    </li>
                  </ol>
                </Callout>
              )}
              {d.state === 'offline' && (
                <Callout kind="danger">
                  <b>El dispositivo no responde.</b> Reconecta el cable (mejor en un puerto directo, sin hub) y comprueba que
                  la pantalla esté desbloqueada. Si persiste, reinicia adb con <code>adb kill-server</code>.
                </Callout>
              )}
            </article>
          ))}
        </div>
      )}

      {(job || scanError) && (
        <section className="panel scanbox" aria-live="polite">
          <div className="row">
            <h3>
              {job?.status === 'failed' || scanError
                ? 'El escaneo ha fallado'
                : job?.status === 'done'
                  ? 'Escaneo completado'
                  : 'Escaneando…'}
            </h3>
            <span className="spacer" />
            {scanning && <span className="num faint">{elapsed} s · suele tardar 30–60 s</span>}
          </div>
          {scanning && <ProgressBar indeterminate />}
          {job && <JobLog job={job} />}
          {(job?.error || scanError) && <ErrorBox error={scanError ?? new Error(job?.error ?? '')} />}
        </section>
      )}

      <section className="section">
        <h2>Escaneos anteriores</h2>
        {scans.error && <ErrorBox error={scans.error} onRetry={scans.reload} />}
        {scans.data && scans.data.length === 0 && (
          <p className="muted">Todavía no hay escaneos. Pulsa «Escanear» en un dispositivo conectado para empezar.</p>
        )}
        {scans.data && scans.data.length > 0 && (
          <div className="panel list">
            {scans.data.map((s) => (
              <div className="list-row" key={s.id}>
                <div style={{ minWidth: 0 }}>
                  <b>
                    {s.manufacturer && s.manufacturer[0].toUpperCase() + s.manufacturer.slice(1)} {s.model}
                  </b>{' '}
                  <span className="faint">· Android {s.android}</span>
                  <div className="faint" style={{ fontSize: '0.84rem' }}>
                    {date(s.created)} · <span className="mono">{s.serial}</span>
                  </div>
                </div>
                <a className="btn sm" href={href('informe', s.id)}>
                  <FileText size={15} />
                  Abrir informe
                </a>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  )
}
