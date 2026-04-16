interface Props {
  onStart: () => void
}

export default function WelcomeScreen({ onStart }: Props) {
  return (
    <div
      className="flex flex-col items-center justify-center w-full h-full cursor-pointer select-none"
      onClick={onStart}
    >
      <div
        className="flex flex-col items-center justify-center rounded-3xl px-16 py-20 text-center"
        style={{ background: 'rgba(255,255,255,0.08)', backdropFilter: 'blur(16px)' }}
      >
        <div className="text-8xl mb-6">🍽️</div>
        <h1 className="text-5xl font-bold text-white mb-3 tracking-tight">
          Rostoran
        </h1>
        <p className="text-2xl text-purple-200 mb-2 font-medium">
          뷔페에 오신 것을 환영합니다
        </p>
        <p className="text-purple-300 text-lg mt-2">Welcome to Rostoran buffet</p>
        <div
          className="mt-12 px-8 py-3 rounded-full text-white text-base font-semibold tracking-wide"
          style={{ background: 'rgba(124,92,191,0.6)', border: '1px solid rgba(124,92,191,0.8)' }}
        >
          화면을 터치하여 시작하세요
        </div>
      </div>
    </div>
  )
}
