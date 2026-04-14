interface Props {
  onOk: () => void
  onRetry: () => void
}

export default function AccompanyArrivedScreen({ onOk, onRetry }: Props) {
  return (
    <div className="flex flex-col min-h-full bg-[#f7f5f2] px-5 pt-12 pb-8">
      <div className="flex-1 flex flex-col items-center justify-center gap-6">
        {/* Icon */}
        <div className="w-28 h-28 bg-green-100 rounded-full flex items-center justify-center shadow-sm">
          <span className="text-6xl">🤖</span>
        </div>

        {/* Message */}
        <div className="text-center">
          <h2 className="text-3xl font-bold text-gray-900">로봇이 도착했습니다</h2>
          <p className="text-sm text-gray-400 mt-3 leading-relaxed">
            로봇이 테이블에 도착하였습니다
            <br />
            동행을 시작하려면 OK를 눌러주세요
          </p>
        </div>

        {/* Status indicator */}
        <div className="bg-white rounded-2xl px-6 py-4 border border-gray-100 shadow-sm w-full max-w-xs">
          <div className="flex items-center gap-3">
            <div className="w-2.5 h-2.5 rounded-full bg-green-500 animate-pulse" />
            <p className="text-sm font-medium text-gray-700">동행 로봇 대기 중</p>
          </div>
        </div>
      </div>

      {/* Buttons */}
      <div className="grid grid-cols-2 gap-3 mt-6">
        <button
          onClick={onRetry}
          className="bg-white border border-gray-200 rounded-2xl py-6 flex flex-col items-center gap-1 active:scale-95 transition-transform"
        >
          <span className="text-xl">🔄</span>
          <span className="text-base font-bold text-gray-700">RETRY</span>
          <span className="text-xs text-gray-400">다시 호출하기</span>
        </button>
        <button
          onClick={onOk}
          className="bg-gray-900 text-white rounded-2xl py-6 flex flex-col items-center gap-1 active:scale-95 transition-transform shadow-md"
        >
          <span className="text-xl">✅</span>
          <span className="text-base font-bold">OK</span>
          <span className="text-xs text-gray-300">동행 시작</span>
        </button>
      </div>
    </div>
  )
}
