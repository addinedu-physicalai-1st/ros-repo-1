import { useState, useEffect, useCallback, useRef } from 'react'
import type { KitchenScreen, ActivityEntry } from './types'
import {
  fetchMenuItems,
  createKitchenTask,
  cancelTask,
  respondTask,
} from '../api/client'
import type { MenuItem } from '../api/client'
import { writeKitchenSync, readKitchenSync } from '../hooks/useKitchenSync'
import { useWebSocket } from '../hooks/useWebSocket'

import Toast from '../components/Toast'
import type { ToastMessage } from '../components/Toast'
import Header from './components/Header'
import ActivityLog from './components/ActivityLog'
import MenuModal from './components/MenuModal'
import IdleScreen from './screens/IdleScreen'
import RobotComingScreen from './screens/RobotComingScreen'
import RobotArrivedConfirmScreen from './screens/RobotArrivedConfirmScreen'
import RobotAtKitchenScreen from './screens/RobotAtKitchenScreen'
import RobotGoingDispScreen from './screens/RobotGoingDispScreen'
import RobotReturningScreen from './screens/RobotReturningScreen'
import RobotBackScreen from './screens/RobotBackScreen'
import CompletedScreen from './screens/CompletedScreen'

// ── URL param helpers ────────────────────────────────────────────────────────
function getParam(key: string): string | null {
  return new URLSearchParams(window.location.search).get(key)
}

function getInitialScreen(): KitchenScreen {
  const s = getParam('screen') as KitchenScreen | null
  const valid: KitchenScreen[] = [
    'idle', 'robot_coming', 'robot_arrived_confirm', 'robot_at_kitchen',
    'robot_going_disp', 'robot_returning', 'robot_back', 'completed', 'failed',
  ]
  return s && valid.includes(s) ? s : 'idle'
}

function nowTime(): string {
  return new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export default function App() {
  const [screen, setScreen] = useState<KitchenScreen>(getInitialScreen)
  const [toast, setToast] = useState<ToastMessage | null>(null)
  const [wsConnected, setWsConnected] = useState(false)
  const [log, setLog] = useState<ActivityEntry[]>([])
  const logIdRef = useRef(0)

  // Task state
  const [taskId, setTaskId] = useState<string | null>(null)
  const [dispId, setDispId] = useState<string>('')
  const [menuName, setMenuName] = useState<string>('')
  const [errorMsg, setErrorMsg] = useState<string>('')

  // Menu modal
  const [modalOpen, setModalOpen] = useState(false)
  const [menuItems, setMenuItems] = useState<MenuItem[]>([])
  const [menuLoading, setMenuLoading] = useState(false)

  // Track WS connection state via a ref trick: reconnect fires in useWebSocket
  const wsRef = useRef<boolean>(false)

  // ── Activity log helper ──────────────────────────────────────────────────
  const addLog = useCallback(
    (text: string, color: ActivityEntry['color'] = 'gray') => {
      setLog(prev => {
        const entry: ActivityEntry = {
          id: ++logIdRef.current,
          text,
          color,
          time: nowTime(),
        }
        const next = [...prev, entry]
        return next.length > 20 ? next.slice(next.length - 20) : next
      })
    },
    [],
  )

  // ── Clear state helper ───────────────────────────────────────────────────
  const clearTaskState = useCallback(() => {
    writeKitchenSync(null)
    setTaskId(null)
    setDispId('')
    setMenuName('')
    setErrorMsg('')
  }, [])

  // ── Restore state from localStorage on mount ─────────────────────────────
  useEffect(() => {
    const saved = readKitchenSync()
    if (!saved) return
    setTaskId(saved.task_id)
    setDispId(saved.disp_id)
    setMenuName(saved.menu_name)
    switch (saved.stage) {
      case 1: setScreen('robot_coming'); break
      case 2: setScreen('robot_going_disp'); break
      case 3: setScreen('robot_returning'); break
    }
    addLog('저장된 상태 복원됨', 'blue')
  }, [addLog])

  // ── Cross-window sync: staff page sets stage=3 → robot_returning ──────────
  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key !== 'kitchen_task_state') return
      if (!e.newValue) return
      try {
        const data = JSON.parse(e.newValue)
        if (data.stage === 3) {
          setScreen(prev => {
            if (prev === 'robot_going_disp') {
              addLog('진열장 도착 확인 — 로봇 귀환 중', 'blue')
              return 'robot_returning'
            }
            return prev
          })
        }
      } catch { /* ignore */ }
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [addLog])

  // ── WebSocket events ─────────────────────────────────────────────────────
  const handleWsMessage = useCallback(
    (data: Record<string, unknown>) => {
      // Connection confirmed
      if (!wsRef.current) {
        wsRef.current = true
        setWsConnected(true)
      }

      if (data.event === 'status' && data.current_task === taskId) {
        const robotStatus = data.robot_status as number | undefined
        if (robotStatus === 3) {
          setScreen(prev => {
            if (prev === 'robot_coming') {
              addLog('로봇 도착 보고 수신', 'blue')
              return 'robot_arrived_confirm'
            }
            if (prev === 'robot_returning') {
              addLog('로봇 귀환 완료', 'green')
              return 'robot_back'
            }
            return prev
          })
        }
      }
    },
    [taskId, addLog],
  )

  useWebSocket(
    handleWsMessage,
    true,
    useCallback(() => setWsConnected(true), []),
    useCallback(() => setWsConnected(false), []),
  )

  useEffect(() => {
    wsRef.current = false
  }, [])

  // ── Open menu modal ──────────────────────────────────────────────────────
  const openMenuModal = async () => {
    setModalOpen(true)
    setMenuLoading(true)
    addLog('메뉴 목록 조회 중...', 'gray')
    const res = await fetchMenuItems()
    setMenuItems(res.menu_items)
    setMenuLoading(false)
    addLog(`메뉴 ${res.menu_items.length}개 로드`, 'blue')
  }

  // ── Call robot (after menu selection) ───────────────────────────────────
  const handleMenuSelect = async (item: MenuItem) => {
    setModalOpen(false)
    addLog(`로봇 호출 중 — ${item.name} (${item.place_id})`, 'blue')
    const res = await createKitchenTask(item.place_id)
    if (!res.ok || !res.task_id) {
      const msg = res.detail ?? '로봇 호출 실패'
      setErrorMsg(msg)
      setScreen('failed')
      addLog(`오류: ${msg}`, 'red')
      setToast({ id: Date.now(), text: msg, type: 'error' })
      return
    }
    const tid = res.task_id
    setTaskId(tid)
    setDispId(item.place_id)
    setMenuName(item.name)
    writeKitchenSync({
      task_id: tid,
      disp_id: item.place_id,
      menu_name: item.name,
      robot_id: '',
      stage: 1,
    })
    setScreen('robot_coming')
    addLog(`로봇 출발 — task ${tid}`, 'green')
  }

  // ── Cancel task ──────────────────────────────────────────────────────────
  const handleCancel = async () => {
    if (taskId) {
      addLog('작업 취소 중...', 'orange')
      await cancelTask(taskId)
      addLog('작업 취소됨', 'orange')
    }
    clearTaskState()
    setScreen('idle')
  }

  // ── Arrival confirmed (robot at kitchen) ────────────────────────────────
  const handleArrivalConfirmed = () => {
    addLog('로봇 주방 도착 확인', 'green')
    setScreen('robot_at_kitchen')
  }

  // ── Arrival denied — cancel and return to idle ───────────────────────────
  const handleArrivalDenied = async () => {
    addLog('도착 안함 — 관제서버에 보고 중...', 'orange')
    if (taskId) {
      const res = await respondTask(taskId, { status: 'timeout' })
      if (!res.ok) {
        setToast({ id: Date.now(), text: '서버 보고 실패', type: 'error' })
        addLog('서버 보고 실패', 'red')
      } else {
        addLog('도착 실패 보고 완료', 'orange')
      }
    }
    clearTaskState()
    setScreen('idle')
  }

  // ── Load done (robot at kitchen) ─────────────────────────────────────────
  const handleLoadDone = async () => {
    if (!taskId) return
    addLog('적재 완료 신호 전송...', 'blue')
    const res = await respondTask(taskId, { status: 'ok', next_dest: dispId })
    if (!res.ok) {
      setToast({ id: Date.now(), text: '전송 실패, 다시 시도하세요', type: 'error' })
      addLog('전송 실패', 'red')
      return
    }
    // Update sync stage to 2
    writeKitchenSync({ task_id: taskId, disp_id: dispId, menu_name: menuName, robot_id: '', stage: 2 })
    setScreen('robot_going_disp')
    addLog('로봇 진열장으로 출발', 'green')
  }

  // ── Complete task (robot back) ───────────────────────────────────────────
  const handleComplete = async () => {
    if (!taskId) return
    addLog('완료 신호 전송...', 'blue')
    const res = await respondTask(taskId, { status: 'ok' })
    if (!res.ok) {
      setToast({ id: Date.now(), text: '전송 실패, 다시 시도하세요', type: 'error' })
      addLog('전송 실패', 'red')
      return
    }
    clearTaskState()
    setScreen('completed')
    addLog('업무 완료!', 'green')
  }

  // ── Retry task ───────────────────────────────────────────────────────────
  const handleRetry = async () => {
    if (!taskId) return
    addLog('재시도 신호 전송...', 'orange')
    const res = await respondTask(taskId, { status: 'retry' })
    if (!res.ok) {
      setToast({ id: Date.now(), text: '전송 실패, 다시 시도하세요', type: 'error' })
      addLog('전송 실패', 'red')
      return
    }
    setScreen('robot_coming')
    addLog('재시도 — 로봇 호출 중', 'orange')
  }

  // ── Next task (from completed) ───────────────────────────────────────────
  const handleNextTask = () => {
    clearTaskState()
    setScreen('idle')
    addLog('새 업무 시작 대기', 'gray')
  }

  // ── Render ───────────────────────────────────────────────────────────────
  const renderScreen = () => {
    switch (screen) {
      case 'idle':
        return <IdleScreen onCallRobot={openMenuModal} />

      case 'robot_coming':
        return <RobotComingScreen menuName={menuName} onCancel={handleCancel} />

      case 'robot_arrived_confirm':
        return (
          <RobotArrivedConfirmScreen
            menuName={menuName}
            onArrived={handleArrivalConfirmed}
            onNotArrived={handleArrivalDenied}
          />
        )

      case 'robot_at_kitchen':
        return <RobotAtKitchenScreen menuName={menuName} onLoadDone={handleLoadDone} />

      case 'robot_going_disp':
        return <RobotGoingDispScreen menuName={menuName} dispId={dispId} />

      case 'robot_returning':
        return <RobotReturningScreen />

      case 'robot_back':
        return (
          <RobotBackScreen
            menuName={menuName}
            onComplete={handleComplete}
            onRetry={handleRetry}
          />
        )

      case 'completed':
        return <CompletedScreen onNext={handleNextTask} />

      case 'failed':
        return (
          <div className="flex flex-col items-center justify-center flex-1 gap-6 px-6 py-12">
            <div
              className="w-24 h-24 rounded-full flex items-center justify-center text-5xl"
              style={{ background: '#2e1a1a' }}
            >
              ⚠️
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold" style={{ color: '#ff6b6b' }}>오류 발생</p>
              {errorMsg && (
                <p className="text-sm mt-2 px-4 py-2 rounded-lg" style={{ color: '#ff6b6b', background: '#2e1a1a' }}>
                  {errorMsg}
                </p>
              )}
            </div>
            <button
              onClick={handleNextTask}
              className="w-full max-w-xs py-4 rounded-2xl text-lg font-bold transition-opacity active:opacity-80"
              style={{ background: '#4c6ef5', color: '#fff' }}
            >
              처음으로
            </button>
          </div>
        )

      default:
        return null
    }
  }

  return (
    <div
      className="flex flex-col min-h-screen w-full"
      style={{ background: '#1a1e2e' }}
    >
      <Header wsConnected={wsConnected} />

      {/* Main content */}
      <div
        className="flex flex-col flex-1 mx-4 my-4 rounded-2xl overflow-hidden"
        style={{ background: '#242840' }}
      >
        {renderScreen()}
      </div>

      {/* Activity log */}
      <ActivityLog entries={log} />

      {/* Menu modal */}
      <MenuModal
        open={modalOpen}
        items={menuItems}
        loading={menuLoading}
        onSelect={handleMenuSelect}
        onClose={() => setModalOpen(false)}
      />

      <Toast message={toast} />
    </div>
  )
}
