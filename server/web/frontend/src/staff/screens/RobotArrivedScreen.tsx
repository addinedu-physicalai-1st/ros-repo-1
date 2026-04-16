import type { KitchenState } from '../../hooks/useKitchenSync'

interface Props {
  kitchenState: KitchenState | null
  onConfirmArrival: () => void
}

export default function RobotArrivedScreen({ kitchenState, onConfirmArrival }: Props) {
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-6 py-12 px-6">
      {/* Arrived icon */}
      <div
        className="w-28 h-28 rounded-full flex items-center justify-center"
        style={{ background: '#1b3a2d' }}
      >
        <span className="text-5xl">🤖</span>
      </div>

      <div className="text-center">
        <h2 className="text-2xl font-bold text-white mb-2">로봇 도착!</h2>
        <p className="text-sm" style={{ color: '#64748b' }}>
          로봇이 진열대에 도착했습니다. 도착을 확인하세요.
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
              <span style={{ color: '#64748b' }}>진열대</span>
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

      {/* Confirm button */}
      <button
        onClick={onConfirmArrival}
        className="w-full max-w-xs py-4 rounded-2xl text-base font-bold text-white active:scale-95 transition-transform"
        style={{ background: '#51cf66' }}
      >
        도착 확인 (OK)
      </button>
    </div>
  )
}
