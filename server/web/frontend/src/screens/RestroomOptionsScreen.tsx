import { useState } from 'react'
import BackButton from '../components/BackButton'
import MapOverlay from '../components/MapOverlay'

interface Props {
  onRobotGuide: () => void
  onBack: () => void
}

export default function RestroomOptionsScreen({ onRobotGuide, onBack }: Props) {
  const [showMap, setShowMap] = useState(false)

  return (
    <div className="flex flex-col min-h-screen bg-[#f7f5f2] px-5 pt-8 pb-8">
      <BackButton onClick={onBack} />

      <div className="flex-1 flex flex-col justify-center gap-5 mt-4">
        <div className="text-center mb-4">
          <span className="text-5xl">🚻</span>
          <h2 className="text-2xl font-bold text-gray-900 mt-3">화장실 안내</h2>
          <p className="text-sm text-gray-400 mt-1">안내 방식을 선택해 주세요</p>
        </div>

        <button
          onClick={onRobotGuide}
          className="w-full bg-gray-900 text-white rounded-2xl py-9 flex flex-col items-center gap-3 active:scale-95 transition-transform shadow-md"
        >
          <span className="text-4xl">🤖</span>
          <span className="text-xl font-bold">로봇 안내</span>
          <span className="text-sm text-gray-300">로봇이 직접 화장실까지 안내해요</span>
        </button>

        <button
          onClick={() => setShowMap(true)}
          className="w-full bg-white border border-gray-200 rounded-2xl py-9 flex flex-col items-center gap-3 active:scale-95 transition-transform shadow-sm"
        >
          <span className="text-4xl">🗺️</span>
          <span className="text-xl font-bold text-gray-900">지도 보기</span>
          <span className="text-sm text-gray-400">지도로 위치를 직접 확인해요</span>
        </button>
      </div>

      {showMap && (
        <MapOverlay
          title="🚻 화장실 위치"
          onClose={() => setShowMap(false)}
          onRobotGuide={() => {
            setShowMap(false)
            onRobotGuide()
          }}
        />
      )}
    </div>
  )
}
