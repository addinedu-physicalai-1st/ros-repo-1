export default function IdleScreen() {
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-8 px-6 py-12">
      <div
        className="w-24 h-24 rounded-full flex items-center justify-center text-5xl"
        style={{ background: '#1e2240' }}
      >
        🍽️
      </div>
      <div className="text-center">
        <p className="text-2xl font-bold text-white">대기 중</p>
        <p className="text-sm mt-2" style={{ color: '#a0aec0' }}>
          로봇의 그릇 수거 보고를 기다리고 있습니다
        </p>
      </div>
    </div>
  )
}
