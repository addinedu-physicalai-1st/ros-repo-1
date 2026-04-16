import type { ActivityEntry } from '../types'

interface Props {
  entries: ActivityEntry[]
}

export default function ActivityLog({ entries }: Props) {
  return (
    <div
      className="rounded-xl p-4 mt-4"
      style={{ background: '#242840' }}
    >
      <h3 className="text-xs font-semibold mb-3 uppercase tracking-widest" style={{ color: '#64748b' }}>
        활동 로그
      </h3>
      {entries.length === 0 ? (
        <p className="text-xs text-center py-4" style={{ color: '#475569' }}>
          활동 기록 없음
        </p>
      ) : (
        <ul className="space-y-2 max-h-48 overflow-y-auto">
          {[...entries].reverse().map(entry => (
            <li key={entry.id} className="flex items-start gap-2">
              <span
                className="text-xs tabular-nums shrink-0 mt-0.5"
                style={{ color: '#475569' }}
              >
                {entry.time}
              </span>
              <span className="text-xs" style={{ color: '#94a3b8' }}>
                {entry.text}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
