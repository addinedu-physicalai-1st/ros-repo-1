import { useState } from 'react'
import BackButton from '../components/BackButton'
import MapOverlay from '../components/MapOverlay'
import type { MenuItem } from '../types'

interface Props {
  selectedMenus: MenuItem[]
  onRobotGuide: () => void
  onBack: () => void
}

export default function MenuOptionsScreen({ selectedMenus, onRobotGuide, onBack }: Props) {
  const [showMap, setShowMap] = useState(false)
  // Map preview shows first menu's location
  const firstMenu = selectedMenus[0]

  return (
    <div className="flex flex-col min-h-full bg-[#f7f5f2] px-5 pt-8 pb-8">
      <BackButton onClick={onBack} />

      <div className="flex-1 flex flex-col justify-center gap-5 mt-4">
        {/* Selected menu list */}
        <div>
          <p className="text-sm text-gray-400 mb-2">선택하신 메뉴 ({selectedMenus.length}개)</p>
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
            {selectedMenus.map((item, idx) => (
              <div
                key={item.id}
                className={`flex items-center gap-4 px-4 py-3 ${idx < selectedMenus.length - 1 ? 'border-b border-gray-100' : ''}`}
              >
                <div className="w-7 h-7 rounded-full bg-gray-900 text-white text-xs font-bold flex items-center justify-center flex-shrink-0">
                  {idx + 1}
                </div>
                <span className="text-xl">{item.emoji}</span>
                <span className="text-base font-bold text-gray-900">{item.name}</span>
              </div>
            ))}
          </div>
          <p className="text-xs text-gray-400 mt-2 text-center">번호 순서대로 로봇이 안내합니다</p>
        </div>

        <button
          onClick={onRobotGuide}
          className="w-full bg-gray-900 text-white rounded-2xl py-8 flex flex-col items-center gap-3 active:scale-95 transition-transform shadow-md"
        >
          <span className="text-4xl">🤖</span>
          <span className="text-xl font-bold">로봇 안내 시작</span>
          <span className="text-sm text-gray-300">순서대로 메뉴 위치를 안내해요</span>
        </button>

        <button
          onClick={() => setShowMap(true)}
          className="w-full bg-white border border-gray-200 rounded-2xl py-6 flex flex-col items-center gap-2 active:scale-95 transition-transform shadow-sm"
        >
          <span className="text-3xl">📍</span>
          <span className="text-base font-bold text-gray-900">위치 보기</span>
          <span className="text-xs text-gray-400">첫 번째 목적지 지도 확인</span>
        </button>
      </div>

      {showMap && firstMenu && (
        <MapOverlay
          title={`${firstMenu.emoji} ${firstMenu.name} 위치`}
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
