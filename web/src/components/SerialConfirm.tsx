import { CheckCircle2, KeyRound, XCircle } from 'lucide-react'
import { useId, useState } from 'react'
import type { JobResultItem } from '../api/types'
import { ACTION_LABEL } from '../lib/format'

/** The lockout key: the destructive button only arms when the typed serial matches exactly. */
export function SerialConfirm({
  serial, label, busy, disabled, onConfirm, danger = true,
}: {
  serial: string
  label: string
  busy?: boolean
  disabled?: boolean
  danger?: boolean
  onConfirm: (typed: string) => void
}) {
  const [typed, setTyped] = useState('')
  const id = useId()
  const match = typed.trim() === serial
  return (
    <form
      className="serial-field"
      onSubmit={(e) => {
        e.preventDefault()
        if (match && !busy && !disabled) onConfirm(typed.trim())
      }}
    >
      <label htmlFor={id}>
        Escribe el número de serie <b className="mono">{serial}</b> para confirmar
      </label>
      <input
        id={id}
        className={`input${match ? ' match' : ''}`}
        value={typed}
        onChange={(e) => setTyped(e.target.value)}
        autoComplete="off"
        spellCheck={false}
        placeholder={serial}
        disabled={busy || disabled}
        aria-invalid={typed.length > 0 && !match}
      />
      <button type="submit" className={`btn ${danger ? 'danger' : 'primary'}`} disabled={!match || busy || disabled}>
        <KeyRound size={16} />
        {label}
      </button>
    </form>
  )
}

export function Results({ results }: { results: JobResultItem[] }) {
  const ok = results.filter((r) => r.ok).length
  return (
    <div className="results">
      <p className="muted" style={{ marginBottom: 6 }}>
        <b style={{ color: 'var(--safe)' }}>{ok} correctos</b>
        {results.length - ok > 0 && (
          <>
            {' · '}
            <b style={{ color: 'var(--danger)' }}>{results.length - ok} con error</b>
          </>
        )}
      </p>
      {results.map((r) => (
        <div className="res" key={r.package + r.action}>
          {r.ok ? <CheckCircle2 size={16} className="ok" /> : <XCircle size={16} className="fail" />}
          <span className="mono" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {r.package}
          </span>
          <span className="faint">{ACTION_LABEL[r.action] ?? r.action}</span>
          {r.output && <span className="res-out">{r.output}</span>}
        </div>
      ))}
    </div>
  )
}
