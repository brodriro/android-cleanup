import { ArchiveRestore, ChevronDown, ChevronRight, History } from 'lucide-react'
import { useState } from 'react'
import { api, pollJob } from '../api/client'
import type { Backup, Job, JobResultItem } from '../api/types'
import { Results, SerialConfirm } from '../components/SerialConfirm'
import { ErrorBox, JobLog, ProgressBar } from '../components/ui'
import { date } from '../lib/format'
import { useAsync } from '../lib/hooks'

export function Backups() {
  const list = useAsync(() => api.backups(), [])
  const [open, setOpen] = useState<string>()
  return (
    <>
      <header className="page-head">
        <div>
          <h1>Copias y restauración</h1>
          <p>
            Cada vez que se aplica un plan se guarda una copia. Restaurarla reinstala los paquetes desinstalados
            (<code>install-existing</code>) y reactiva los desactivados.
          </p>
        </div>
      </header>
      {list.error && <ErrorBox error={list.error} onRetry={list.reload} />}
      {!list.data && !list.error && <div className="skeleton" style={{ height: 140 }} aria-busy />}
      {list.data && list.data.length === 0 && (
        <div className="panel empty">
          <History size={32} />
          <b>Todavía no hay copias</b>
          <span>Aparecerán aquí cuando apliques tu primer plan.</span>
        </div>
      )}
      {list.data && list.data.length > 0 && (
        <div className="panel list">
          {list.data.map((b) => (
            <BackupRow key={b.id} b={b} open={open === b.id} onOpen={() => setOpen(open === b.id ? undefined : b.id)} />
          ))}
        </div>
      )}
    </>
  )
}

function BackupRow({ b, open, onOpen }: { b: Backup; open: boolean; onOpen: () => void }) {
  const [job, setJob] = useState<Job>()
  const [error, setError] = useState<Error>()
  const [busy, setBusy] = useState(false)
  const results: JobResultItem[] = job?.result && 'results' in job.result ? job.result.results : []
  const running = job && (job.status === 'queued' || job.status === 'running')

  async function restore(serial: string) {
    setBusy(true)
    setError(undefined)
    try {
      const id = await api.restore(b.id, serial)
      await pollJob(id, setJob)
    } catch (e) {
      setError(e as Error)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ borderTop: '1px solid var(--rule)' }} className="backup">
      <div className="list-row" style={{ borderTop: 0 }}>
        <div style={{ minWidth: 0 }}>
          <b>{date(b.created)}</b> <span className="faint">· {b.items} paquetes</span>
          <div className="faint mono" style={{ fontSize: '0.8rem', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {b.serial} · {b.id}
          </div>
        </div>
        <button className="btn sm" onClick={onOpen} aria-expanded={open}>
          {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          <ArchiveRestore size={15} />
          Restaurar
        </button>
      </div>
      {open && (
        <div style={{ padding: '4px 16px 18px', display: 'grid', gap: 12, maxWidth: 560 }}>
          {!job && (
            <SerialConfirm serial={b.serial} label={`Restaurar ${b.items} paquetes`} busy={busy} danger={false} onConfirm={restore} />
          )}
          {running && <ProgressBar done={job.progress?.done} total={job.progress?.total} />}
          {job && <JobLog job={job} />}
          {job?.status === 'failed' && <ErrorBox error={new Error(job.error ?? 'La restauración ha fallado.')} />}
          {results.length > 0 && <Results results={results} />}
          {error && <ErrorBox error={error} />}
        </div>
      )}
    </div>
  )
}
