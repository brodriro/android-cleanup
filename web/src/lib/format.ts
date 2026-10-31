const nf1 = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 1, minimumFractionDigits: 0 })
const nf0 = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 0 })

export function kb(kbValue: number): string {
  if (!kbValue) return '0 MB'
  const mb = kbValue / 1024
  if (mb >= 1024) return `${nf1.format(mb / 1024)} GB`
  if (mb >= 10) return `${nf0.format(mb)} MB`
  return `${nf1.format(mb)} MB`
}

export function bytes(b: number): string {
  if (!b) return '0 MB'
  const mb = b / 1024 / 1024
  if (mb >= 1024) return `${nf1.format(mb / 1024)} GB`
  if (mb >= 10) return `${nf0.format(mb)} MB`
  if (mb >= 0.1) return `${nf1.format(mb)} MB`
  return `${nf0.format(b / 1024)} KB`
}

export const pct = (p: number) => `${nf1.format(p)} %`
export const int = (n: number) => nf0.format(n)

export function date(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('es-ES', { dateStyle: 'medium', timeStyle: 'short' })
}

export const RISK_LABEL: Record<string, string> = {
  safe: 'Seguro',
  caution: 'Precaución',
  danger: 'Peligro',
  unknown: 'Desconocido',
}

export const REC_LABEL: Record<string, string> = {
  remove: 'Quitar',
  review: 'Revisar',
  keep: 'Mantener',
}

export const ACTION_LABEL: Record<string, string> = {
  uninstall: 'Desinstalar',
  disable: 'Desactivar',
  none: '—',
}

export const GROUP_LABEL: Record<string, string> = {
  third_party: 'Terceros',
  system: 'Sistema',
}

export const GROUP_HINT: Record<string, string> = {
  third_party: 'Se puede quitar sin riesgo',
  system: 'Quitarlo puede causar problemas',
}

export const TAG_LABEL: Record<string, string> = {
  frequent: 'Uso frecuente',
  bloat: 'Bloat',
  telemetry: 'Telemetría',
  core: 'Núcleo',
  background: 'Segundo plano',
  running: 'En ejecución',
  unused: 'Sin uso',
  disabled: 'Desactivado',
  large: 'Ocupa mucho',
}

export const CATEGORY_LABEL: Record<string, string> = {
  oem: 'Fabricante',
  google: 'Google',
  carrier: 'Operador',
  third_party: 'Terceros',
  telemetry: 'Telemetría',
  core: 'Núcleo',
  system: 'Sistema',
  user: 'Usuario',
}

export const BUCKET_LABEL: Record<string, string> = {
  exempted: 'exenta',
  active: 'activa',
  working_set: 'habitual',
  frequent: 'frecuente',
  rare: 'rara vez',
  restricted: 'restringida',
  never: 'nunca',
}
