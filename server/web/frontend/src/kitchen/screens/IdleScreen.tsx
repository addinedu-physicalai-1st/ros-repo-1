interface Props {
  onCallRobot: () => void
}

export default function IdleScreen({ onCallRobot }: Props) {
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-8 px-6 py-12">
      {/* Icon */}
      <div
        className="w-24 h-24 rounded-full flex items-center justify-center text-5xl"
        style={{ background: '#2e3250' }}
      >
        🍽️
      </div>

      {/* Status */}
      <div className="text-center">
        <p className="text-2xl font-bold text-white">메뉴 준비 완료</p>
        <p className="text-sm mt-2" style={{ color: '#a0aec0' }}>
          진열장으로 보낼 로봇을 호출하세요
        </p>
      </div>

      {/* CTA */}
      <button
        onClick={onCallRobot}
        className="w-full max-w-xs py-4 rounded-2xl text-lg font-bold transition-opacity active:opacity-80"
        style={{ background: '#4c6ef5', color: '#fff' }}
      >
        로봇 호출
      </button>
    </div>
  )
}
