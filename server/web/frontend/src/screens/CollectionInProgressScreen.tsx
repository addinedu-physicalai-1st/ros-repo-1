interface Props {
  onCollectDone: () => void
}

export default function CollectionInProgressScreen({ onCollectDone }: Props) {
  return (
    <div className="flex flex-col min-h-full bg-[#f7f5f2] px-5 pt-12 pb-8">
      <div className="flex-1 flex flex-col items-center justify-center gap-6">
        {/* Animated robot */}
        <div className="relative w-28 h-28">
          <div className="absolute inset-0 rounded-full bg-gray-900/10 animate-ping" />
          <div className="absolute inset-0 rounded-full bg-white border-2 border-gray-200 flex items-center justify-center">
            <span className="text-5xl">♻️</span>
          </div>
        </div>

        <div className="text-center">
          <h2 className="text-3xl font-bold text-gray-900">수거 진행 중</h2>
          <p className="text-sm text-gray-400 mt-2 leading-relaxed">
            수거가 완료되면 아래 버튼을 눌러주세요
          </p>
        </div>

        {/* Status indicator */}
        <div className="bg-white rounded-2xl px-6 py-4 border border-gray-100 shadow-sm w-full max-w-xs">
          <div className="flex items-center gap-3">
            <div className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
            <p className="text-sm text-gray-600">로봇이 수거를 기다리고 있습니다</p>
          </div>
        </div>
      </div>

      {/* Collect done button */}
      <button
        onClick={onCollectDone}
        className="w-full bg-gray-900 text-white rounded-2xl py-7 flex flex-col items-center gap-2 active:scale-95 transition-transform shadow-md mt-6"
      >
        <span className="text-3xl">✅</span>
        <span className="text-xl font-bold">수거 완료</span>
        <span className="text-sm text-gray-300">그릇 수거가 완료되었습니다</span>
      </button>
    </div>
  )
}
