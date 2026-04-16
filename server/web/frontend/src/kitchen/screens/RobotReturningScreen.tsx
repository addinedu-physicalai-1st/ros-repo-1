export default function RobotReturningScreen() {
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-8 px-6 py-12">
      {/* Pulsing return icon */}
      <div className="relative">
        <div
          className="absolute inset-0 rounded-full animate-ping opacity-30"
          style={{ background: '#4c6ef5' }}
        />
        <div
          className="relative w-24 h-24 rounded-full flex items-center justify-center text-4xl"
          style={{ background: '#1e2240' }}
        >
          🔄
        </div>
      </div>

      {/* Status */}
      <div className="text-center">
        <p className="text-2xl font-bold text-white animate-pulse">로봇 귀환 중</p>
        <p className="text-sm mt-2" style={{ color: '#a0aec0' }}>
          로봇이 주방으로 돌아오고 있습니다
        </p>
      </div>
    </div>
  )
}
