import { useState, useCallback, useRef } from 'react'
import type { DishwashScreen, ActivityEntry } from './types'
import { respondTask } from '../api/client'
import { useWebSocket } from '../hooks/useWebSocket'
import Toast from '../components/Toast'
import type { ToastMessage } from '../components/Toast'
import Header from './components/Header'
import ActivityLog from './components/ActivityLog'
import IdleScreen from './screens/IdleScreen'
import RobotArrivedScreen from './screens/RobotArrivedScreen'
import CollectingScreen from './screens/CollectingScreen'

function getInitialScreen(): DishwashScreen {
  const s = new URLSearchParams(window.location.search).get('screen') as DishwashScreen | null
  const valid: DishwashScreen[] = ['idle', 'robot_arrived', 'collecting']
  return s && valid.includes(s) ? s : 'idle'
}

function nowTime(): string {
  return new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

let logIdCounter = 0

export default function App() {
  const [screen, setScreen] = useState<DishwashScreen>(getInitialScreen)
  const [wsConnected, setWsConnected] = useState(false)
  const [log, setLog] = useState<ActivityEntry[]>([])
  const [toast, setToast] = useState<ToastMessage | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)

  const screenRef = useRef(screen)
  screenRef.current = screen

  const addLog = useCallback((text: string, color: ActivityEntry['color'] = 'gray') => {
    setLog(prev => {
      const entry: ActivityEntry = { id: ++logIdCounter, text, color, time: nowTime() }
      const next = [...prev, entry]
      return next.length > 20 ? next.slice(next.length - 20) : next
    })
  }, [])

  // WebSocket: listen for robot arrival at dishwashing station
  const handleWsMessage = useCallback((data: Record<string, unknown>) => {
    setWsConnected(true)

    if (
      data.event === 'status' &&
      data.robot_status === 3 &&
      screenRef.current === 'idle'
    ) {
      const tid = data.current_task as string | undefined
      if (tid) {
        setTaskId(tid)
        addLog('로봇 도착 보고 수신', 'blue')
        setScreen('robot_arrived')
      }
    }
  }, [addLog])

  useWebSocket(
    handleWsMessage,
    true,
    useCallback(() => setWsConnected(true), []),
    useCallback(() => setWsConnected(false), []),
  )

  // "도착함" — show collecting screen
  const handleArrived = useCallback(() => {
    addLog('도착 확인됨', 'green')
    setScreen('collecting')
  }, [addLog])

  // "도착 안함" — report timeout to server and return to idle
  const handleNotArrived = useCallback(async () => {
    addLog('도착 안함 — 관제서버에 보고 중...', 'orange')
    if (taskId) {
      const res = await respondTask(taskId, { status: 'timeout' })
      if (!res.ok) {
        setToast({ id: Date.now(), text: '서버 보고 실패', type: 'error' })
        addLog('서버 보고 실패', 'red')
      } else {
        addLog('도착 실패 보고 완료', 'orange')
        setToast({ id: Date.now(), text: '도착 실패 보고 완료', type: 'error' })
      }
    }
    setTaskId(null)
    setScreen('idle')
  }, [taskId, addLog])

  // "수거 완료" — report unload_done to server and return to idle
  const handleCollectDone = useCallback(async () => {
    addLog('수거 완료 신호 전송 중...', 'blue')
    if (taskId) {
      const res = await respondTask(taskId, { status: 'unload_done' })
      if (!res.ok) {
        setToast({ id: Date.now(), text: '전송 실패, 다시 시도하세요', type: 'error' })
        addLog('전송 실패', 'red')
        return
      }
    }
    addLog('수거 완료!', 'green')
    setToast({ id: Date.now(), text: '수거 완료! 로봇 복귀 중', type: 'success' })
    setTaskId(null)
    setScreen('idle')
  }, [taskId, addLog])

  const renderScreen = () => {
    switch (screen) {
      case 'idle':
        return <IdleScreen />
      case 'robot_arrived':
        return <RobotArrivedScreen onArrived={handleArrived} onNotArrived={handleNotArrived} />
      case 'collecting':
        return <CollectingScreen onCollectDone={handleCollectDone} />
      default:
        return null
    }
  }

  return (
    <div className="flex flex-col min-h-screen w-full" style={{ background: '#1a1e2e' }}>
      <Header wsConnected={wsConnected} />

      <div
        className="flex flex-col flex-1 mx-4 my-4 rounded-2xl overflow-hidden"
        style={{ background: '#242840' }}
      >
        {renderScreen()}
      </div>

      <ActivityLog entries={log} />
      <Toast message={toast} />
    </div>
  )
}
