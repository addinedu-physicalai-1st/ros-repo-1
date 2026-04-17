import type { Flow, MenuItem } from '../types'

interface Props {
  flow: Flow
  currentWaypoint?: MenuItem | null
  waypointIndex?: number
  totalWaypoints?: number
}

export default function CallingRobotScreen({
  flow,
  currentWaypoint,
  waypointIndex = 0,
  totalWaypoints = 1,
}: Props) {
  const isMulti = flow === 'menu' && totalWaypoints > 1
  const label = flow === 'menu' ? '로봇 대기중...' : '로봇 호출 중...'
  const sub = flow === 'menu'
    ? currentWaypoint
      ? `"${currentWaypoint.name}" 위치로 이동할 로봇을 배차하고 있습니다`
      : '메뉴 위치로 이동할 로봇을 배차하고 있습니다'
    : '화장실 안내 로봇을 배차하고 있습니다'

  return (
    <div className="flex flex-col min-h-screen bg-[#f7f5f2] items-center justify-center px-8 gap-6">
      {/* Waypoint progress badge */}
      {isMulti && (
        <div className="flex gap-2 mb-2">
          {Array.from({ length: totalWaypoints }).map((_, i) => (
            <div
              key={i}
              className={`h-2 rounded-full transition-all ${
                i < waypointIndex
                  ? 'w-6 bg-gray-400'
                  : i === waypointIndex
                  ? 'w-8 bg-gray-900'
                  : 'w-6 bg-gray-200'
              }`}
            />
          ))}
        </div>
      )}

      {/* Spinner */}
      <div className="relative w-24 h-24">
        <div className="absolute inset-0 rounded-full border-4 border-gray-200" />
        <div className="absolute inset-0 rounded-full border-4 border-gray-900 border-t-transparent animate-spin" />
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-3xl">
            {currentWaypoint ? currentWaypoint.emoji : '🤖'}
          </span>
        </div>
      </div>

      <div className="text-center">
        {isMulti && (
          <p className="text-xs font-bold text-gray-400 mb-1">
            {waypointIndex + 1} / {totalWaypoints} 번째 목적지
          </p>
        )}
        <p className="text-2xl font-bold text-gray-900">{label}</p>
        <p className="text-sm text-gray-400 mt-2 leading-relaxed">{sub}</p>
      </div>
    </div>
  )
}
