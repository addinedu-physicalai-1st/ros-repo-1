import type { KitchenState } from '../../hooks/useKitchenSync'

interface Props {
  kitchenState: KitchenState | null
}

export default function IdleScreen({ kitchenState }: Props) {
  return (
    <div className="flex flex-col items-center justify-center flex-1 gap-6 py-12 px-6">
      {/* Status icon */}
      <div
        className="w-28 h-28 rounded-full flex items-center justify-center"
        style={{ background: '#2e3352' }}
      >
        <span className="text-5xl">⏳</span>
      </div>

      <div className="text-center">
        <h2 className="text-2xl font-bold text-white mb-2">대기 중</h2>
        <p className="text-sm" style={{ color: '#64748b' }}>
          주방에서 로봇을 호출하면 알림이 표시됩니다
        </p>
      </div>

      {/* Current task info if available */}
      {kitchenState && (
        <div
          className="rounded-xl px-6 py-4 w-full max-w-xs border"
          style={{ background: '#1a1e2e', borderColor: '#2e3352' }}
        >
          <p className="text-xs font-semibold mb-3 uppercase tracking-widest" style={{ color: '#64748b' }}>
            현재 작업
          </p>
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span style={{ color: '#64748b' }}>태스크 ID</span>
              <span className="font-mono text-white">#{kitchenState.task_id.slice(-6)}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span style={{ color: '#64748b' }}>메뉴</span>
              <span className="text-white">{kitchenState.menu_name}</span>
            </div>
            <div className="flex justify-between text-sm">
              <span style={{ color: '#64748b' }}>진열대</span>
              <span className="text-white">{kitchenState.disp_id}</span>
            </div>
          </div>
        </div>
      )}

      {/* Idle indicator */}
      <div className="flex items-center gap-2">
        <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
        <span className="text-xs" style={{ color: '#64748b' }}>로봇 대기 중</span>
      </div>
    </div>
  )
}
