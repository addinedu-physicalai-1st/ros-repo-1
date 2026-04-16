interface Props {
  menuName: string
  onComplete: () => void
  onRetry: () => void
}

export default function RobotBackScreen({ menuName, onComplete, onRetry }: Props) {
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-8 px-6 py-12">
      {/* Return icon */}
      <div
        className="w-24 h-24 rounded-full flex items-center justify-center text-5xl"
        style={{ background: '#1e2240' }}
      >
        🏠
      </div>

      {/* Status */}
      <div className="text-center">
        <p className="text-2xl font-bold text-white">로봇 귀환 완료</p>
        {menuName && (
          <p className="text-sm mt-1 font-medium" style={{ color: '#a0aec0' }}>
            {menuName}
          </p>
        )}
        <p className="text-sm mt-2" style={{ color: '#a0aec0' }}>
          다음 작업을 선택하세요
        </p>
      </div>

      {/* Actions */}
      <div className="flex flex-col gap-3 w-full max-w-xs">
        <button
          onClick={onComplete}
          className="w-full py-4 rounded-2xl text-lg font-bold transition-opacity active:opacity-80"
          style={{ background: '#51cf66', color: '#1a2e1e' }}
        >
          완료 (대기 장소 복귀)
        </button>
        <button
          onClick={onRetry}
          className="w-full py-3 rounded-2xl text-sm font-semibold border transition-opacity active:opacity-70"
          style={{ borderColor: '#ff922b', color: '#ff922b', background: 'transparent' }}
        >
          재시도
        </button>
      </div>
    </div>
  )
}
