interface Props {
  menuName: string
  dispId: string
}

export default function RobotGoingDispScreen({ menuName, dispId }: Props) {
  const staffUrl = `${window.location.origin}/static/staff/index.html`

  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-8 px-6 py-12">
      {/* Pulsing display icon */}
      <div className="relative">
        <div
          className="absolute inset-0 rounded-full animate-ping opacity-30"
          style={{ background: '#ff922b' }}
        />
        <div
          className="relative w-24 h-24 rounded-full flex items-center justify-center text-4xl"
          style={{ background: '#2e2415' }}
        >
          🏪
        </div>
      </div>

      {/* Status */}
      <div className="text-center">
        <p className="text-2xl font-bold animate-pulse" style={{ color: '#ff922b' }}>
          진열장 이동 중
        </p>
        {menuName && (
          <p className="text-sm mt-1 font-medium" style={{ color: '#ff922b', opacity: 0.8 }}>
            {menuName}
          </p>
        )}
        <p className="text-sm mt-1" style={{ color: '#a0aec0' }}>
          목적지: <span className="font-semibold text-white">{dispId}</span>
        </p>
        <p className="text-sm mt-2" style={{ color: '#a0aec0' }}>
          로봇이 진열장으로 이동하고 있습니다
        </p>
      </div>

      {/* Link to staff page */}
      <a
        href={staffUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="text-sm underline underline-offset-2 transition-opacity hover:opacity-70"
        style={{ color: '#4c6ef5' }}
      >
        스태프 페이지에서 확인 →
      </a>
    </div>
  )
}
