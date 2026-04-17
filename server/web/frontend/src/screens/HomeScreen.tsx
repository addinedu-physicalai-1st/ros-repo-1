import { sendRequest } from '../api/client'
import type { ToastMessage } from '../components/Toast'

interface Props {
  tableId: string
  onGuide: () => void
  onAccompany: () => void
  onCollect: () => void
  onToast: (msg: ToastMessage) => void
}

export default function HomeScreen({ tableId, onGuide, onAccompany, onCollect, onToast }: Props) {
  const handleStaff = async () => {
    const { ok } = await sendRequest('staff')
    onToast({
      id: Date.now(),
      text: ok ? '✓ 직원 호출이 전송되었습니다' : '[데모] 직원 호출 전송됨',
      type: 'success',
    })
  }

  return (
    <div className="flex flex-col min-h-screen bg-[#f7f5f2] px-5 pt-10 pb-8 gap-4">
      {/* Header */}
      <div className="text-center mb-2">
        <div className="inline-block bg-white border border-gray-200 rounded-full px-4 py-1 text-xs text-gray-400 mb-3">
          테이블 {tableId}번
        </div>
        <h1 className="text-2xl font-bold text-gray-900 tracking-tight">무엇을 도와드릴까요?</h1>
        <p className="text-sm text-gray-400 mt-1">버튼을 눌러 서비스를 요청하세요</p>
      </div>

      {/* 안내 — full width, tall */}
      <button
        onClick={onGuide}
        className="w-full bg-gray-900 text-white rounded-2xl py-8 flex flex-col items-center gap-2 active:scale-95 transition-transform shadow-md"
      >
        <span className="text-4xl">🧭</span>
        <span className="text-xl font-bold">안내</span>
        <span className="text-sm text-gray-300">화장실 또는 메뉴 위치 안내</span>
      </button>

      {/* 동행 + 수거 */}
      <div className="grid grid-cols-2 gap-3">
        <button
          onClick={onAccompany}
          className="bg-white border border-gray-200 rounded-2xl py-7 flex flex-col items-center gap-2 active:scale-95 transition-transform"
        >
          <span className="text-3xl">🤖</span>
          <span className="text-base font-bold text-gray-900">동행</span>
          <span className="text-xs text-gray-400 text-center leading-snug">로봇이 함께 동행합니다</span>
        </button>
        <button
          onClick={onCollect}
          className="bg-white border border-gray-200 rounded-2xl py-7 flex flex-col items-center gap-2 active:scale-95 transition-transform"
        >
          <span className="text-3xl">♻️</span>
          <span className="text-base font-bold text-gray-900">수거</span>
          <span className="text-xs text-gray-400 text-center leading-snug">사용한 그릇을 수거해요</span>
        </button>
      </div>

      {/* 직원 호출 — full width */}
      <button
        onClick={handleStaff}
        className="w-full bg-white border border-gray-200 rounded-2xl py-6 flex flex-col items-center gap-2 active:scale-95 transition-transform"
      >
        <span className="text-3xl">🔔</span>
        <span className="text-base font-bold text-gray-900">직원 호출</span>
        <span className="text-xs text-gray-400">직원이 바로 방문합니다</span>
      </button>
    </div>
  )
}
