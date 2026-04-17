import { useEffect, useState } from 'react'

interface Props {
  wsConnected: boolean
}

function formatTime(d: Date): string {
  return d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export default function Header({ wsConnected }: Props) {
  const [time, setTime] = useState(() => formatTime(new Date()))

  useEffect(() => {
    const timer = setInterval(() => setTime(formatTime(new Date())), 1000)
    return () => clearInterval(timer)
  }, [])

  return (
    <header
      className="flex items-center justify-between px-5 py-3 border-b"
      style={{ background: '#1a1e2e', borderColor: '#2e3250' }}
    >
      <div className="flex items-center gap-3">
        <span className="text-lg font-bold text-white">설거지장 Panel</span>
        <span
          className="text-xs font-semibold px-2 py-0.5 rounded"
          style={{ background: '#2e3250', color: '#a0aec0' }}
        >
          설거지장
        </span>
      </div>
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5">
          <span
            className="inline-block w-2 h-2 rounded-full"
            style={{ background: wsConnected ? '#51cf66' : '#ff6b6b' }}
          />
          <span className="text-xs" style={{ color: wsConnected ? '#51cf66' : '#ff6b6b' }}>
            {wsConnected ? 'LIVE' : 'OFF'}
          </span>
        </div>
        <span className="text-sm font-mono" style={{ color: '#a0aec0' }}>{time}</span>
      </div>
    </header>
  )
}
