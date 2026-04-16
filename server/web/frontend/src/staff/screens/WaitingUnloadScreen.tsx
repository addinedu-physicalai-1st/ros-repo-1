import type { KitchenState } from '../../hooks/useKitchenSync'

interface Props {
  kitchenState: KitchenState | null
  onUnloadDone: () => void
}

export default function WaitingUnloadScreen({ kitchenState, onUnloadDone }: Props) {
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-6 py-12 px-6">
      {/* Icon */}
      <div
        className="w-28 h-28 rounded-full flex items-center justify-center"
        style={{ background: '#1e2e3a' }}
      >
        <span className="text-5xl">📦</span>
      </div>

      <div className="text-center">
        <h2 className="text-2xl font-bold text-white mb-2">음식 진열 중</h2>
        <p className="text-sm" style={{ color: '#64748b' }}>
          로봇에서 음식을 진열대에 올려주세요
        </p>
      </div>

      {/* Task info */}
      {kitchenState && (
        <div
          className="rounded-xl px-6 py-4 w-full max-w-xs border"
          style={{ background: '#1a1e2e', borderColor: '#2e3352' }}
        >
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span style={{ color: '#64748b' }}>진열 위치</span>
              <span
                className="font-semibold px-2 py-0.5 rounded"
                style={{ background: '#2e3352', color: '#a5b4fc' }}
              >
                {kitchenState.disp_id}
              </span>
            </div>
            <div className="flex justify-between text-sm">
              <span style={{ color: '#64748b' }}>메뉴</span>
              <span className="text-white">{kitchenState.menu_name}</span>
            </div>
          </div>
        </div>
      )}

      {/* Progress dots */}
      <div className="flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-blue-400 animate-pulse" />
        <span className="text-xs" style={{ color: '#64748b' }}>진열 대기 중…</span>
      </div>

      {/* Done button */}
      <button
        onClick={onUnloadDone}
        className="w-full max-w-xs py-4 rounded-2xl text-base font-bold text-white active:scale-95 transition-transform"
        style={{ background: '#4c6ef5' }}
      >
        음식 진열 완료
      </button>
    </div>
  )
}
