interface Props {
  onReturnToTable: () => void
  onComplete: () => void
}

export default function AccompanyActiveScreen({ onReturnToTable, onComplete }: Props) {
  return (
    <div className="flex flex-col min-h-screen bg-[#f7f5f2] px-5 pt-12 pb-8">
      <div className="flex-1 flex flex-col items-center justify-center gap-6">
        {/* Animated robot icon */}
        <div className="relative w-32 h-32">
          <div className="absolute inset-0 rounded-full bg-gray-900/5 animate-ping" />
          <div className="absolute inset-0 rounded-full bg-white border-2 border-gray-200 flex items-center justify-center shadow-sm">
            <span className="text-6xl">🤖</span>
          </div>
        </div>

        {/* Status message */}
        <div className="text-center">
          <p className="text-xs font-bold text-gray-400 tracking-widest uppercase mb-2">Active</p>
          <h2 className="text-2xl font-bold text-gray-900 leading-snug">
            동행 서비스
            <br />
            진행 중입니다
          </h2>
          <p className="text-sm text-gray-400 mt-3 leading-relaxed">
            로봇이 함께 이동하고 있습니다
          </p>
        </div>

        {/* Live indicator */}
        <div className="bg-white rounded-2xl px-6 py-4 border border-gray-100 shadow-sm w-full max-w-xs">
          <div className="flex items-center gap-3">
            <div className="w-2.5 h-2.5 rounded-full bg-blue-500 animate-pulse" />
            <p className="text-sm font-medium text-gray-700">동행 중 · 로봇이 옆에 있습니다</p>
          </div>
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex flex-col gap-3 mt-6">
        <button
          onClick={onReturnToTable}
          className="w-full bg-white border-2 border-gray-200 rounded-2xl py-6 flex flex-col items-center gap-1 active:scale-95 transition-transform"
        >
          <span className="text-2xl">↩️</span>
          <span className="text-lg font-bold text-gray-800">자리로 복귀</span>
          <span className="text-xs text-gray-400">로봇이 테이블로 먼저 돌아갑니다</span>
        </button>
        <button
          onClick={onComplete}
          className="w-full bg-gray-900 text-white rounded-2xl py-6 flex flex-col items-center gap-1 active:scale-95 transition-transform shadow-md"
        >
          <span className="text-2xl">🏁</span>
          <span className="text-lg font-bold">동행 완료</span>
          <span className="text-xs text-gray-300">서비스를 종료하고 로봇을 복귀시킵니다</span>
        </button>
      </div>
    </div>
  )
}
