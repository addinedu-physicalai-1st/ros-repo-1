import { useEffect, useState } from 'react'
import type { MenuItem } from '../types'

interface Props {
  onNext: () => void
  currentWaypoint?: MenuItem | null
  waypointIndex?: number
  totalWaypoints?: number
}

export default function GuideStartingScreen({
  onNext,
  currentWaypoint,
  waypointIndex = 0,
  totalWaypoints = 1,
}: Props) {
  const [dots, setDots] = useState('')

  useEffect(() => {
    const timer = setTimeout(() => onNext(), 3000)
    return () => clearTimeout(timer)
  }, [])

  useEffect(() => {
    const id = setInterval(() => setDots(d => d.length >= 3 ? '' : d + '.'), 500)
    return () => clearInterval(id)
  }, [])

  const isMulti = totalWaypoints > 1

  return (
    <div className="flex flex-col min-h-full bg-gray-900 items-center justify-center px-8 gap-6">
      {isMulti && (
        <div className="flex gap-2 mb-2">
          {Array.from({ length: totalWaypoints }).map((_, i) => (
            <div
              key={i}
              className={`h-2 rounded-full transition-all ${
                i < waypointIndex
                  ? 'w-6 bg-white/30'
                  : i === waypointIndex
                  ? 'w-8 bg-white'
                  : 'w-6 bg-white/15'
              }`}
            />
          ))}
        </div>
      )}

      <div className="w-24 h-24 bg-white/10 rounded-full flex items-center justify-center">
        <span className="text-5xl">
          {currentWaypoint ? currentWaypoint.emoji : '🤖'}
        </span>
      </div>

      <div className="text-center">
        {isMulti && (
          <p className="text-sm text-gray-400 mb-2">
            {waypointIndex + 1} / {totalWaypoints} 번째 목적지
          </p>
        )}
        <p className="text-3xl font-bold text-white">
          안내를 시작합니다{dots}
        </p>
        {currentWaypoint && (
          <p className="text-lg text-gray-300 mt-2 font-medium">
            {currentWaypoint.name}
          </p>
        )}
        <p className="text-sm text-gray-400 mt-3">잠시 후 로봇을 따라오세요</p>
      </div>
    </div>
  )
}
