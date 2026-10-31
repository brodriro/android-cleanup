# device-cleanup

Herramienta de línea de comandos para auditar y "desbloatear" dispositivos Android (teléfonos y
tablets) vía USB, sin root.

## Objetivo

Los fabricantes y operadoras preinstalan apps, procesos y servicios que el usuario final no usa.
`device-cleanup`:

1. **Inventaria** todas las apps (sistema / usuario, habilitadas / deshabilitadas / ya removidas),
   los procesos en ejecución, los servicios en segundo plano, el *standby bucket* de cada app
   (active … rare / never) y el almacenamiento que ocupa.
2. **Clasifica** cada paquete contra una base de conocimiento (`src/device_cleanup/data/knowledge.json`)
   con nivel de riesgo: `safe` (bloat conocido), `caution` (quita una función), `danger` (núcleo,
   nunca se toca) y heurísticas de uso para paquetes desconocidos.
3. **Estima la mejora**: RAM liberada (PSS actual y "sostenida" de apps con servicios), % de la RAM
   total, MemAvailable antes/después, procesos y servicios que dejan de correr, almacenamiento
   recuperado.
4. **Ejecuta** la limpieza de forma reversible: `pm uninstall -k --user 0` (desinstala para el
   usuario, el APK queda en /system) o `pm disable-user`. Siempre guarda un backup y por defecto
   solo hace *dry-run*.

## Requisitos

- [Android CLI](https://developer.android.com/tools) (`android`) con platform-tools
  (`android sdk install platform-tools`). El `adb` se resuelve desde `android info sdk`.
- `uv` y Python ≥ 3.11.
- Depuración USB activada en el dispositivo y la huella RSA del PC aceptada.

## Uso

```bash
uv sync
uv run device-cleanup devices                 # ver dispositivos y estado adb
uv run device-cleanup scan                    # inventario (guarda out/scan-*.json)
uv run device-cleanup report --md out/report.md --json out/report.json
uv run device-cleanup report --review         # incluir items "review" en la estimación
uv run device-cleanup plan out/plan.json      # plan editable
uv run device-cleanup apply out/plan.json     # dry-run
uv run device-cleanup apply out/plan.json --yes
uv run device-cleanup restore out/backups/<serial>-<fecha>.json
```

Con varios dispositivos conectados usar `--serial/-s`. Para analizar sin dispositivo:
`report --snapshot out/scan-*.json`.

## Panel web

```bash
uv run device-cleanup serve                   # API + panel en http://127.0.0.1:8765
```

El panel (`web/`, una vez compilado en `web/dist`) recorre el mismo flujo: dispositivos → escaneo →
reporte con estimación en vivo → plan → *dry-run* → aplicar (hay que escribir el serial para
confirmar) → backups / restaurar, más un monitor en vivo del dispositivo (RAM, almacenamiento, CPU,
batería). Escucha solo en `127.0.0.1` por defecto; los archivos se guardan en `out/` (cambiar con
`DEVICE_CLEANUP_OUT`). La API está documentada en `docs/api-contract.md`.

### Desarrollo del panel (`web/`)

```bash
cd web && npm install
npm run dev:mock      # http://localhost:5173 con datos de ejemplo del SM-T290 (VITE_MOCK=1, sin backend)
npm run dev           # http://localhost:5173, /api se redirige a http://127.0.0.1:8765
npm run build         # comprueba tipos y compila en web/dist (lo sirve el backend en /)
```

El cliente tipado de la API está en `web/src/api/` (`types.ts` refleja `docs/api-contract.md`; `mock.ts` es el modo
simulado). Si el servidor aún no envía `group`/`tags`, el panel los deduce de `risk`, `system` y el uso.
