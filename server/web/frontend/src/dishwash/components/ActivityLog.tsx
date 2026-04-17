import { useEffect, useRef } from 'react'
import type { ActivityEntry } from '../types'

interface Props {
  entries: ActivityEntry[]
}

const colorMap: Record<ActivityEntry['color'], string> = {
  green: '#51cf66',
  blue: '#4c6ef5',
  orange: '#ff922b',
  red: '#ff6b6b',
  gray: '#6b7280',
}

export default function ActivityLog({ entries }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [entries])

  return (
    <div
      className="flex flex-col mx-4 mb-4 rounded-xl overflow-hidden"
      style={{ background: '#1a1e2e', border: '1px solid #2e3250' }}
    >
      <div
        className="px-4 py-2 text-xs font-semibold uppercase tracking-wider"
        style={{ background: '#242840', color: '#6b7280', borderBottom: '1px solid #2e3250' }}
      >
        활동 로그
      </div>
      <div className="overflow-y-auto max-h-40 px-4 py-2 flex flex-col gap-1">
        {entries.length === 0 && (
          <span className="text-xs italic" style={{ color: '#4a5568' }}>활동 없음</span>
        )}
        {entries.map(entry => (
          <div key={entry.id} className="flex items-start gap-2 text-xs">
            <span className="font-mono shrink-0" style={{ color: '#4a5568' }}>{entry.time}</span>
            <span style={{ color: colorMap[entry.color] }}>{entry.text}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
