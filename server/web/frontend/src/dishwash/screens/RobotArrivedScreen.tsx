interface Props {
  onArrived: () => void
  onNotArrived: () => void
}

export default function RobotArrivedScreen({ onArrived, onNotArrived }: Props) {
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-8 px-6 py-12">
      <div
        className="w-24 h-24 rounded-full flex items-center justify-center text-5xl"
        style={{ background: '#1e2e3a' }}
      >
        🤖
      </div>
      <div className="text-center">
        <p className="text-2xl font-bold text-white">로봇 도착 보고</p>
        <p className="text-sm mt-2" style={{ color: '#a0aec0' }}>
          로봇이 그릇을 들고 도착했다고 보고되었습니다
        </p>
        <p className="text-sm mt-1" style={{ color: '#a0aec0' }}>
          실제로 도착했나요?
        </p>
      </div>

      <div className="flex flex-col gap-3 w-full max-w-xs">
        <button
          onClick={onArrived}
          className="w-full py-4 rounded-2xl text-lg font-bold transition-opacity active:opacity-80"
          style={{ background: '#51cf66', color: '#1a2e1e' }}
        >
          도착함
        </button>
        <button
          onClick={onNotArrived}
          className="w-full py-4 rounded-2xl text-lg font-bold border transition-opacity active:opacity-70"
          style={{ borderColor: '#ff6b6b', color: '#ff6b6b', background: 'transparent' }}
        >
          도착 안함
        </button>
      </div>
    </div>
  )
}
