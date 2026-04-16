import { useEffect, useState } from 'react'
import type { KitchenState } from '../../hooks/useKitchenSync'

interface Props {
  kitchenState: KitchenState | null
  wsConnected: boolean
}

function clock(): string {
  return new Date().toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

export default function Header({ kitchenState, wsConnected }: Props) {
  const [time, setTime] = useState(clock())

  useEffect(() => {
    const id = setInterval(() => setTime(clock()), 1000)
    return () => clearInterval(id)
  }, [])

  const dispLabel = kitchenState?.disp_id ?? '—'

  return (
    <header
      className="flex items-center justify-between px-4 py-3 border-b"
      style={{ background: '#1a1e2e', borderColor: '#2e3352' }}
    >
      {/* Left: title + place badge */}
      <div className="flex items-center gap-3">
        <h1 className="text-white font-bold text-base tracking-wide">직원 Panel</h1>
        {kitchenState && (
          <span
            className="text-xs font-semibold px-2 py-0.5 rounded-full"
            style={{ background: '#2e3352', color: '#a5b4fc' }}
          >
            {dispLabel}
          </span>
        )}
      </div>

      {/* Right: task badge + WS dot + clock */}
      <div className="flex items-center gap-3">
        {kitchenState && (
          <span
            className="text-xs px-2 py-0.5 rounded-full font-medium hidden sm:inline"
            style={{ background: '#2e3352', color: '#94a3b8' }}
          >
            #{kitchenState.task_id.slice(-6)} · {kitchenState.menu_name}
          </span>
        )}

        {/* WS status dot */}
        <span className="flex items-center gap-1.5">
          <span
            className={`w-2 h-2 rounded-full ${wsConnected ? 'bg-green-400 animate-pulse' : 'bg-red-500'}`}
          />
          <span className="text-xs" style={{ color: '#64748b' }}>
            {wsConnected ? 'WS' : 'OFF'}
          </span>
        </span>

        <span className="text-xs tabular-nums" style={{ color: '#64748b' }}>
          {time}
        </span>
      </div>
    </header>
  )
}
