interface Props {
  menuName: string
  onCancel: () => void
}

export default function RobotComingScreen({ menuName, onCancel }: Props) {
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-8 px-6 py-12">
      {/* Pulsing robot */}
      <div className="relative">
        <div
          className="absolute inset-0 rounded-full animate-ping opacity-30"
          style={{ background: '#4c6ef5' }}
        />
        <div
          className="relative w-24 h-24 rounded-full flex items-center justify-center text-4xl"
          style={{ background: '#2e3250' }}
        >
          🤖
        </div>
      </div>

      {/* Status */}
      <div className="text-center">
        <p className="text-2xl font-bold text-white animate-pulse">로봇 이동 중</p>
        {menuName && (
          <p className="text-sm mt-1 font-medium" style={{ color: '#4c6ef5' }}>
            {menuName}
          </p>
        )}
        <p className="text-sm mt-2" style={{ color: '#a0aec0' }}>
          로봇이 주방으로 이동하고 있습니다
        </p>
      </div>

      {/* Cancel */}
      <button
        onClick={onCancel}
        className="w-full max-w-xs py-3 rounded-2xl text-sm font-semibold border transition-opacity active:opacity-70"
        style={{ borderColor: '#ff6b6b', color: '#ff6b6b', background: 'transparent' }}
      >
        취소 (대기 장소로 복귀)
      </button>
    </div>
  )
}
