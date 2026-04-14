interface Props {
  title: string
  onClose: () => void
  onRobotGuide?: () => void
}

export default function MapOverlay({ title, onClose, onRobotGuide }: Props) {
  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex flex-col items-center justify-center p-5">
      <div className="bg-white rounded-2xl overflow-hidden w-full max-w-sm shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
          <div>
            <p className="font-bold text-gray-900">{title}</p>
            <p className="text-xs text-gray-400 mt-0.5">지도에서 위치를 확인하세요</p>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center text-gray-500 active:opacity-60"
          >
            ✕
          </button>
        </div>

        {/* Map placeholder */}
        <div className="w-full aspect-[4/3] bg-gray-100 flex flex-col items-center justify-center gap-3 text-gray-400">
          <span className="text-5xl opacity-50">🗺️</span>
          <p className="text-xs text-center leading-relaxed px-4">
            이곳에 내부 지도가 표시됩니다
            <br />
            <strong className="text-gray-500">map.png</strong> 파일을 같은 폴더에 넣어주세요
          </p>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100">
          <button
            onClick={onClose}
            className="text-sm text-gray-500 font-medium active:opacity-60"
          >
            닫기
          </button>
          {onRobotGuide && (
            <button
              onClick={onRobotGuide}
              className="bg-gray-900 text-white text-sm font-bold px-4 py-2 rounded-xl active:opacity-80"
            >
              🤖 로봇 안내
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
