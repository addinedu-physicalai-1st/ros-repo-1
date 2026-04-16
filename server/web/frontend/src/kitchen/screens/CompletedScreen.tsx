interface Props {
  onNext: () => void
}

export default function CompletedScreen({ onNext }: Props) {
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-8 px-6 py-12">
      {/* Success icon */}
      <div
        className="w-24 h-24 rounded-full flex items-center justify-center text-5xl"
        style={{ background: '#1e3a2e' }}
      >
        🎉
      </div>

      {/* Status */}
      <div className="text-center">
        <p className="text-3xl font-bold" style={{ color: '#51cf66' }}>업무 완료!</p>
        <p className="text-sm mt-2" style={{ color: '#a0aec0' }}>
          성공적으로 완료되었습니다
        </p>
      </div>

      {/* Next */}
      <button
        onClick={onNext}
        className="w-full max-w-xs py-4 rounded-2xl text-lg font-bold transition-opacity active:opacity-80"
        style={{ background: '#4c6ef5', color: '#fff' }}
      >
        다음 업무 시작
      </button>
    </div>
  )
}
