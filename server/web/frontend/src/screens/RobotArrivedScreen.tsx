import { useEffect, useState } from 'react'
import type { Flow, MenuItem } from '../types'

const COUNTDOWN_SEC = 15

interface Props {
  flow: Flow
  onOk: () => void
  onRetry: () => void
  currentWaypoint?: MenuItem | null
  waypointIndex?: number
  totalWaypoints?: number
}

export default function RobotArrivedScreen({
  flow,
  onOk,
  onRetry,
  currentWaypoint,
  waypointIndex = 0,
  totalWaypoints = 1,
}: Props) {
  const [countdown, setCountdown] = useState(COUNTDOWN_SEC)

  useEffect(() => {
    setCountdown(COUNTDOWN_SEC)
  }, [waypointIndex])

  useEffect(() => {
    if (countdown <= 0) {
      onOk()
      return
    }
    const id = setInterval(() => setCountdown(c => c - 1), 1000)
    return () => clearInterval(id)
  }, [countdown])

  const isMulti = flow === 'menu' && totalWaypoints > 1
  const progressPct = ((COUNTDOWN_SEC - countdown) / COUNTDOWN_SEC) * 100

  const title = flow === 'menu'
    ? isMulti
      ? `${waypointIndex + 1}번째 목적지 도착`
      : '도착완료'
    : '로봇이 테이블에 도착했습니다'

  const sub = flow === 'menu'
    ? currentWaypoint
      ? `"${currentWaypoint.name}" 위치에 도착했습니다`
      : '안내 로봇이 준비되었습니다'
    : '로봇이 화장실 안내를 시작할 준비가 되었습니다'

  const okLabel = flow === 'menu' && isMulti && waypointIndex < totalWaypoints - 1
    ? '안내 시작'
    : 'OK'

  return (
    <div className="flex flex-col min-h-screen bg-[#f7f5f2] px-5 pt-12 pb-8">
      <div className="flex-1 flex flex-col items-center justify-center gap-6">
        {/* Waypoint progress dots */}
        {isMulti && (
          <div className="flex gap-2">
            {Array.from({ length: totalWaypoints }).map((_, i) => (
              <div
                key={i}
                className={`h-2 rounded-full transition-all ${
                  i < waypointIndex
                    ? 'w-6 bg-gray-400'
                    : i === waypointIndex
                    ? 'w-8 bg-green-500'
                    : 'w-6 bg-gray-200'
                }`}
              />
            ))}
          </div>
        )}

        <div className="w-24 h-24 bg-green-100 rounded-full flex items-center justify-center">
          <span className="text-5xl">
            {currentWaypoint ? currentWaypoint.emoji : '✅'}
          </span>
        </div>

        <div className="text-center">
          <h2 className="text-2xl font-bold text-gray-900">{title}</h2>
          <p className="text-sm text-gray-400 mt-2 leading-relaxed">{sub}</p>
          {isMulti && (
            <p className="text-xs text-gray-400 mt-1">
              남은 목적지: {totalWaypoints - waypointIndex - 1}개
            </p>
          )}
        </div>

        {/* Countdown */}
        <div className="flex flex-col items-center gap-2 w-full max-w-xs">
          <p className="text-sm text-gray-500">
            <span className="font-bold text-gray-900 text-lg">{countdown}</span>초 후 자동으로 시작됩니다
          </p>
          <div className="w-full h-1.5 bg-gray-200 rounded-full overflow-hidden">
            <div
              className="h-full bg-gray-900 rounded-full transition-all duration-1000"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>
      </div>

      {/* Buttons */}
      <div className="grid grid-cols-2 gap-3 mt-6">
        <button
          onClick={onRetry}
          className="bg-white border border-gray-200 rounded-2xl py-5 text-base font-bold text-gray-700 active:scale-95 transition-transform"
        >
          RETRY
        </button>
        <button
          onClick={onOk}
          className="bg-gray-900 text-white rounded-2xl py-5 text-base font-bold active:scale-95 transition-transform"
        >
          {okLabel}
        </button>
      </div>
    </div>
  )
}
