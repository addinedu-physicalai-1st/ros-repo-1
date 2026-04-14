import BackButton from '../components/BackButton'

interface Props {
  onRestroom: () => void
  onMenu: () => void
  onBack: () => void
}

export default function GuideMenuScreen({ onRestroom, onMenu, onBack }: Props) {
  return (
    <div className="flex flex-col min-h-full bg-[#f7f5f2] px-5 pt-8 pb-8">
      <BackButton onClick={onBack} />

      <div className="flex-1 flex flex-col justify-center gap-5 mt-4">
        <div className="text-center mb-4">
          <h2 className="text-2xl font-bold text-gray-900">안내 종류 선택</h2>
          <p className="text-sm text-gray-400 mt-1">원하시는 안내를 선택해 주세요</p>
        </div>

        <button
          onClick={onRestroom}
          className="w-full bg-white border border-blue-100 rounded-2xl py-10 flex flex-col items-center gap-3 active:scale-95 transition-transform shadow-sm"
        >
          <span className="text-5xl">🚻</span>
          <span className="text-xl font-bold text-gray-900">화장실 안내</span>
          <span className="text-sm text-gray-400">화장실 위치를 알려드려요</span>
        </button>

        <button
          onClick={onMenu}
          className="w-full bg-white border border-amber-100 rounded-2xl py-10 flex flex-col items-center gap-3 active:scale-95 transition-transform shadow-sm"
        >
          <span className="text-5xl">🍽️</span>
          <span className="text-xl font-bold text-gray-900">메뉴 안내</span>
          <span className="text-sm text-gray-400">메뉴 위치를 알려드려요</span>
        </button>
      </div>
    </div>
  )
}
