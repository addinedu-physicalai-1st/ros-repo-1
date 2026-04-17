interface Props {
  onCollectDone: () => void
}

export default function CollectingScreen({ onCollectDone }: Props) {
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-8 px-6 py-12">
      <div
        className="w-24 h-24 rounded-full flex items-center justify-center text-5xl"
        style={{ background: '#1e3a2e' }}
      >
        ✅
      </div>
      <div className="text-center">
        <p className="text-2xl font-bold" style={{ color: '#51cf66' }}>로봇 도착 확인</p>
        <p className="text-sm mt-2" style={{ color: '#a0aec0' }}>
          그릇을 모두 수거했나요?
        </p>
      </div>

      <button
        onClick={onCollectDone}
        className="w-full max-w-xs py-4 rounded-2xl text-lg font-bold transition-opacity active:opacity-80"
        style={{ background: '#51cf66', color: '#1a2e1e' }}
      >
        수거 완료
      </button>
    </div>
  )
}
