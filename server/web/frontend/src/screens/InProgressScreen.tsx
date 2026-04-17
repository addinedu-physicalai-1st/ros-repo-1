import type { Flow, MenuItem } from '../types'

interface Props {
  flow: Flow
  onOk: () => void
  onRetry: () => void
  currentWaypoint?: MenuItem | null
  waypointIndex?: number
  totalWaypoints?: number
}

export default function InProgressScreen({
  flow,
  onOk,
  onRetry,
  currentWaypoint,
  waypointIndex = 0,
  totalWaypoints = 1,
}: Props) {
  const isMulti = flow === 'menu' && totalWaypoints > 1
  const isLastWaypoint = waypointIndex >= totalWaypoints - 1

  const title = flow === 'menu'
    ? isMulti
      ? `${waypointIndex + 1}번째 목적지 이동중`
      : '이동중'
    : '안내 진행 중'

  const sub = flow === 'menu'
    ? currentWaypoint
      ? `"${currentWaypoint.name}" 위치로 이동하고 있습니다`
      : '로봇이 목적지로 이동하고 있습니다'
    : '로봇이 화장실까지 안내하고 있습니다'

  const okLabel = flow === 'menu' && isMulti && !isLastWaypoint ? '다음 목적지 →' : '완료'
  const retryLabel = flow === 'menu' ? '재이동 요청' : '재안내 요청'

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
                    ? 'w-8 bg-gray-900'
                    : 'w-6 bg-gray-200'
                }`}
              />
            ))}
          </div>
        )}

        {/* Animated robot */}
        <div className="relative w-28 h-28">
          <div className="absolute inset-0 rounded-full bg-gray-900/10 animate-ping" />
          <div className="absolute inset-0 rounded-full bg-white border-2 border-gray-200 flex items-center justify-center">
            <span className="text-5xl">
              {currentWaypoint ? currentWaypoint.emoji : '🤖'}
            </span>
          </div>
        </div>

        <div className="text-center">
          {isMulti && (
            <p className="text-xs font-bold text-gray-400 mb-1">
              {waypointIndex + 1} / {totalWaypoints}
            </p>
          )}
          <h2 className="text-3xl font-bold text-gray-900">{title}</h2>
          <p className="text-sm text-gray-400 mt-2 leading-relaxed">{sub}</p>
        </div>

        <div className="bg-white rounded-2xl px-6 py-4 border border-gray-100 shadow-sm w-full max-w-xs">
          <div className="flex items-center gap-3">
            <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
            <p className="text-sm text-gray-600">로봇이 이동 중입니다</p>
          </div>
          {isMulti && !isLastWaypoint && (
            <p className="text-xs text-gray-400 mt-1 ml-5">
              다음: {totalWaypoints - waypointIndex - 1}개 목적지 남음
            </p>
          )}
        </div>
      </div>

      {/* Buttons */}
      <div className="grid grid-cols-2 gap-3 mt-6">
        <button
          onClick={onRetry}
          className="bg-white border border-gray-200 rounded-2xl py-5 flex flex-col items-center gap-1 active:scale-95 transition-transform"
        >
          <span className="text-base font-bold text-gray-700">RETRY</span>
          <span className="text-xs text-gray-400">{retryLabel}</span>
        </button>
        <button
          onClick={onOk}
          className="bg-gray-900 text-white rounded-2xl py-5 flex flex-col items-center gap-1 active:scale-95 transition-transform"
        >
          <span className="text-base font-bold">{okLabel}</span>
          <span className="text-xs text-gray-300">
            {flow === 'menu' && !isLastWaypoint ? '다음 위치로 이동' : '안내 종료'}
          </span>
        </button>
      </div>
    </div>
  )
}
