interface Props {
  menuName: string
  onLoadDone: () => void
}

export default function RobotAtKitchenScreen({ menuName, onLoadDone }: Props) {
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-8 px-6 py-12">
      {/* Arrival icon */}
      <div
        className="w-24 h-24 rounded-full flex items-center justify-center text-5xl"
        style={{ background: '#1e3a2e' }}
      >
        ✅
      </div>

      {/* Status */}
      <div className="text-center">
        <p className="text-3xl font-bold" style={{ color: '#51cf66' }}>로봇 도착!</p>
        {menuName && (
          <p className="text-sm mt-1 font-medium" style={{ color: '#51cf66', opacity: 0.8 }}>
            {menuName}
          </p>
        )}
        <p className="text-sm mt-2" style={{ color: '#a0aec0' }}>
          음식을 로봇에 적재해 주세요
        </p>
      </div>

      {/* Confirm load */}
      <button
        onClick={onLoadDone}
        className="w-full max-w-xs py-4 rounded-2xl text-lg font-bold transition-opacity active:opacity-80"
        style={{ background: '#51cf66', color: '#1a2e1e' }}
      >
        적재 완료 — 진열장으로 출발
      </button>
    </div>
  )
}
