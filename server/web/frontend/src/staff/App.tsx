import { useState, useEffect, useCallback, useRef } from 'react'
import type { StaffScreen, ActivityEntry } from './types'
import type { KitchenState } from '../hooks/useKitchenSync'
import { useKitchenSync, readKitchenSync } from '../hooks/useKitchenSync'
import { useWebSocket } from '../hooks/useWebSocket'
import { respondTask } from '../api/client'
import Toast from '../components/Toast'
import type { ToastMessage } from '../components/Toast'

import Header from './components/Header'
import ActivityLog from './components/ActivityLog'
import IdleScreen from './screens/IdleScreen'
import RobotArrivingScreen from './screens/RobotArrivingScreen'
import RobotArrivedScreen from './screens/RobotArrivedScreen'
import WaitingUnloadScreen from './screens/WaitingUnloadScreen'
import RobotDepartingScreen from './screens/RobotDepartingScreen'

const LS_KEY = 'kitchen_task_state'

function getInitialScreen(): StaffScreen {
  const params = new URLSearchParams(window.location.search)
  const s = params.get('screen')
  if (
    s === 'idle' ||
    s === 'robot_arriving' ||
    s === 'robot_arrived' ||
    s === 'waiting_unload' ||
    s === 'robot_departing'
  ) {
    return s
  }

  // Derive from current kitchen state
  const state = readKitchenSync()
  if (!state) return 'idle'
  if (state.stage === 2) return 'robot_arriving'
  if (state.stage === 3) return 'robot_departing'
  return 'idle'
}

function nowTime(): string {
  return new Date().toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

let logIdCounter = 0
function makeEntry(text: string): ActivityEntry {
  return { id: ++logIdCounter, time: nowTime(), text }
}

export default function App() {
  const [screen, setScreen] = useState<StaffScreen>(getInitialScreen)
  const [kitchenState, setKitchenState] = useState<KitchenState | null>(readKitchenSync)
  const [log, setLog] = useState<ActivityEntry[]>([makeEntry('직원 패널 시작됨')])
  const [toast, setToast] = useState<ToastMessage | null>(null)
  const [wsConnected, setWsConnected] = useState(false)

  const screenRef = useRef(screen)
  useEffect(() => { screenRef.current = screen }, [screen])

  const kitchenStateRef = useRef(kitchenState)
  useEffect(() => { kitchenStateRef.current = kitchenState }, [kitchenState])

  const addLog = useCallback((text: string) => {
    setLog(prev => [...prev, makeEntry(text)])
  }, [])

  const go = useCallback((s: StaffScreen) => {
    setScreen(s)
  }, [])

  // Cross-window sync: listen for kitchen state changes
  useKitchenSync(useCallback((state: KitchenState | null) => {
    if (!state) {
      setKitchenState(null)
      go('idle')
      addLog('태스크 초기화됨 (주방 신호)')
      return
    }

    setKitchenState(state)

    if (state.stage === 1) {
      go('idle')
      addLog('대기 상태로 전환됨')
    } else if (state.stage === 2) {
      go('robot_arriving')
      addLog(`로봇 이동 시작 → ${state.disp_id}`)
    }
    // stage 3 is set by staff page itself (unload done), so we don't react here
  }, [go, addLog]))

  // WebSocket: only active when robot is on its way (stage 2)
  const wsActive = screen === 'robot_arriving' && (kitchenState?.stage ?? 0) === 2

  useWebSocket(useCallback((data: Record<string, unknown>) => {
    if (
      data.event === 'status' &&
      data.current_task === kitchenStateRef.current?.task_id &&
      data.robot_status === 3 &&
      screenRef.current === 'robot_arriving'
    ) {
      go('robot_arrived')
      addLog('로봇 도착 확인됨')
    }

    // Track WS connectivity via any message
    setWsConnected(true)
  }, [go, addLog]), wsActive)

  // Also track WS connect / disconnect via a separate passive hook for header dot
  // We do this by subscribing even when not in arriving state, just to check connectivity
  useWebSocket(useCallback((_data: Record<string, unknown>) => {
    setWsConnected(true)
  }, []), true)

  // Button handlers

  const handleConfirmArrival = useCallback(() => {
    go('waiting_unload')
    addLog('도착 확인됨 → 음식 진열 대기')
  }, [go, addLog])

  const handleUnloadDone = useCallback(async () => {
    const state = kitchenStateRef.current
    if (!state) return

    const res = await respondTask(state.task_id, { status: 'ok', next_dest: 'KITCHEN' })

    if (!res.ok) {
      setToast({ id: Date.now(), text: '서버 응답 실패', type: 'error' })
      return
    }

    // Notify kitchen page via localStorage
    const updatedState: KitchenState = { ...state, stage: 3 }
    localStorage.setItem(LS_KEY, JSON.stringify(updatedState))
    setKitchenState(updatedState)

    go('robot_departing')
    addLog('음식 진열 완료 → 로봇 귀환 중')
    setToast({ id: Date.now(), text: '진열 완료! 로봇 귀환 중', type: 'success' })
  }, [go, addLog])

  const renderScreen = () => {
    switch (screen) {
      case 'idle':
        return <IdleScreen kitchenState={kitchenState} />

      case 'robot_arriving':
        return <RobotArrivingScreen kitchenState={kitchenState} />

      case 'robot_arrived':
        return (
          <RobotArrivedScreen
            kitchenState={kitchenState}
            onConfirmArrival={handleConfirmArrival}
          />
        )

      case 'waiting_unload':
        return (
          <WaitingUnloadScreen
            kitchenState={kitchenState}
            onUnloadDone={handleUnloadDone}
          />
        )

      case 'robot_departing':
        return <RobotDepartingScreen kitchenState={kitchenState} />

      default:
        return null
    }
  }

  return (
    <div
      className="min-h-screen flex flex-col"
      style={{ background: '#1a1e2e', color: '#e2e8f0' }}
    >
      <Header kitchenState={kitchenState} wsConnected={wsConnected} />

      {/* Main content */}
      <div className="flex-1 flex flex-col w-full max-w-md mx-auto px-4 pb-6">
        {renderScreen()}
        <ActivityLog entries={log} />
      </div>

      <Toast message={toast} />
    </div>
  )
}
