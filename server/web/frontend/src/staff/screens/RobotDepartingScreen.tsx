import type { KitchenState } from '../../hooks/useKitchenSync'

interface Props {
  kitchenState: KitchenState | null
}

export default function RobotDepartingScreen({ kitchenState }: Props) {
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-6 py-12 px-6">
      {/* Departing animation */}
      <div className="relative w-28 h-28">
        <div
          className="absolute inset-0 rounded-full animate-ping opacity-20"
          style={{ background: '#51cf66' }}
        />
        <div
          className="absolute inset-0 rounded-full flex items-center justify-center"
          style={{ background: '#1b3a2d' }}
        >
          <span className="text-5xl">↩️</span>
        </div>
      </div>

      <div className="text-center">
        <h2 className="text-2xl font-bold mb-2" style={{ color: '#51cf66' }}>
          로봇 귀환 중
        </h2>
        <p className="text-sm" style={{ color: '#64748b' }}>
          로봇이 주방으로 귀환하고 있습니다
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
              <span style={{ color: '#64748b' }}>진열 완료</span>
              <span
                className="font-semibold px-2 py-0.5 rounded"
                style={{ background: '#1b3a2d', color: '#51cf66' }}
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

      {/* Returning indicator */}
      <div className="flex items-center gap-2">
        <span className="w-2 h-2 rounded-full animate-pulse" style={{ background: '#51cf66' }} />
        <span className="text-xs" style={{ color: '#64748b' }}>귀환 중…</span>
      </div>
    </div>
  )
}
