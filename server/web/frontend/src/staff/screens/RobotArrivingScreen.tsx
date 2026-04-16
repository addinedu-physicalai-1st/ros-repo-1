import type { KitchenState } from '../../hooks/useKitchenSync'

interface Props {
  kitchenState: KitchenState | null
}

export default function RobotArrivingScreen({ kitchenState }: Props) {
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-6 py-12 px-6">
      {/* Pulsing animation */}
      <div className="relative w-28 h-28">
        <div
          className="absolute inset-0 rounded-full animate-ping opacity-30"
          style={{ background: '#4c6ef5' }}
        />
        <div
          className="absolute inset-0 rounded-full flex items-center justify-center"
          style={{ background: '#2e3352' }}
        >
          <span className="text-5xl">🚚</span>
        </div>
      </div>

      <div className="text-center">
        <h2 className="text-2xl font-bold text-white mb-2">로봇 이동 중</h2>
        <p className="text-sm" style={{ color: '#64748b' }}>
          로봇이 진열대로 이동하고 있습니다
        </p>
      </div>

      {/* Destination info */}
      {kitchenState && (
        <div
          className="rounded-xl px-6 py-4 w-full max-w-xs border"
          style={{ background: '#1a1e2e', borderColor: '#2e3352' }}
        >
          <p className="text-xs font-semibold mb-3 uppercase tracking-widest" style={{ color: '#64748b' }}>
            목적지 정보
          </p>
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
            <div className="flex justify-between text-sm">
              <span style={{ color: '#64748b' }}>로봇</span>
              <span className="text-white">{kitchenState.robot_id}</span>
            </div>
          </div>
        </div>
      )}

      {/* Moving indicator */}
      <div className="flex items-center gap-2">
        <span
          className="w-2 h-2 rounded-full animate-pulse"
          style={{ background: '#4c6ef5' }}
        />
        <span className="text-xs" style={{ color: '#64748b' }}>이동 중…</span>
      </div>
    </div>
  )
}
