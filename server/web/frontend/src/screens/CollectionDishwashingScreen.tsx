interface Props {
  onUnloadDone: () => void
}

export default function CollectionDishwashingScreen({ onUnloadDone }: Props) {
  return (
    <div className="flex flex-col min-h-screen bg-[#f7f5f2] px-5 pt-12 pb-8">
      <div className="flex-1 flex flex-col items-center justify-center gap-6">
        {/* Icon */}
        <div className="w-28 h-28 bg-orange-100 rounded-full flex items-center justify-center shadow-sm">
          <span className="text-6xl">🍽️</span>
        </div>

        {/* Message */}
        <div className="text-center">
          <h2 className="text-3xl font-bold text-gray-900">
            로봇이 설거지장에<br />도착했습니다
          </h2>
          <p className="text-sm text-gray-400 mt-3 leading-relaxed">
            로봇 위의 그릇을 내려주세요<br />
            완료되면 아래 버튼을 눌러주세요
          </p>
        </div>

        {/* Status indicator */}
        <div className="bg-white rounded-2xl px-6 py-4 border border-gray-100 shadow-sm w-full max-w-xs">
          <div className="flex items-center gap-3">
            <div className="w-2.5 h-2.5 rounded-full bg-orange-400 animate-pulse" />
            <p className="text-sm font-medium text-gray-700">그릇 하차 대기 중</p>
          </div>
        </div>
      </div>

      {/* Unload done button */}
      <button
        onClick={onUnloadDone}
        className="w-full bg-gray-900 text-white rounded-2xl py-7 flex flex-col items-center gap-2 active:scale-95 transition-transform shadow-md mt-6"
      >
        <span className="text-3xl">✅</span>
        <span className="text-xl font-bold">하차 완료</span>
        <span className="text-sm text-gray-300">그릇을 모두 내렸습니다</span>
      </button>
    </div>
  )
}
