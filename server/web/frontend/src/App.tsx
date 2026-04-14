import { useEffect, useRef, useState } from 'react'
import type { Screen, Flow, MenuItem } from './types'
import { sendRequest, respondTask } from './api/client'
import { useTaskEvents } from './hooks/useTaskEvents'
import {
  mockAccompanyRequest,
  mockWaitAccompanyArrival,
  mockWaitReturnArrival,
  mockRespondAccompanyTask,
} from './api/mock'

import Toast from './components/Toast'
import type { ToastMessage } from './components/Toast'
import HomeScreen from './screens/HomeScreen'
import GuideMenuScreen from './screens/GuideMenuScreen'
import RestroomOptionsScreen from './screens/RestroomOptionsScreen'
import MenuSelectionScreen from './screens/MenuSelectionScreen'
import MenuOptionsScreen from './screens/MenuOptionsScreen'
import CallingRobotScreen from './screens/CallingRobotScreen'
import RobotArrivedScreen from './screens/RobotArrivedScreen'
import GuideStartingScreen from './screens/GuideStartingScreen'
import InProgressScreen from './screens/InProgressScreen'
import GuideCompleteScreen from './screens/GuideCompleteScreen'
import AccompanyCallingScreen from './screens/AccompanyCallingScreen'
import AccompanyArrivedScreen from './screens/AccompanyArrivedScreen'
import AccompanyActiveScreen from './screens/AccompanyActiveScreen'
import AccompanyReturningScreen from './screens/AccompanyReturningScreen'
import AccompanyReturnedScreen from './screens/AccompanyReturnedScreen'
import AccompanyCompleteScreen from './screens/AccompanyCompleteScreen'

const getTableId = (): string => {
  const params = new URLSearchParams(window.location.search)
  return params.get('table') || '3'
}

export default function App() {
  const [screen, setScreen] = useState<Screen>('home')
  const [flow, setFlow] = useState<Flow>(null)
  const [toast, setToast] = useState<ToastMessage | null>(null)

  // Task state
  const [taskId, setTaskId] = useState<string | null>(null)

  // Multi-waypoint state (menu flow)
  const [selectedMenus, setSelectedMenus] = useState<MenuItem[]>([])
  const [waypointIndex, setWaypointIndex] = useState(0)

  const tableId = getTableId()
  const go = (s: Screen) => setScreen(s)

  // Derived helpers
  const currentWaypoint = selectedMenus[waypointIndex] ?? null
  const totalWaypoints = selectedMenus.length

  // WebSocket: fires when the robot assigned to our task reports ARRIVED
  useTaskEvents(
    screen === 'callingRobot' ? taskId : null,
    () => go('robotArrived'),
  )

  // ── Accompany flow state ──────────────────────────────────────────────────
  const [accompanyTaskId, setAccompanyTaskId] = useState<string | null>(null)
  // Holds the cleanup function for the active mock WS arrival listener
  const accompanyCleanupRef = useRef<(() => void) | null>(null)

  // Cancel any pending mock WS timer on unmount / flow reset
  useEffect(() => {
    return () => {
      accompanyCleanupRef.current?.()
    }
  }, [])

  const cancelAccompanyListener = () => {
    accompanyCleanupRef.current?.()
    accompanyCleanupRef.current = null
  }

  // [화면 1 -> 2] 동행 버튼: POST /api/request then wait for arrival WS event
  const startAccompanyFlow = async () => {
    cancelAccompanyListener()
    go('accompanyCallingRobot')
    const { task_id } = await mockAccompanyRequest()
    setAccompanyTaskId(task_id)
    const cleanup = mockWaitAccompanyArrival(() => go('accompanyArrived'))
    accompanyCleanupRef.current = cleanup
  }

  // [화면 3 RETRY] re-dispatch and wait again
  const handleAccompanyRetry = async () => {
    if (!accompanyTaskId) return
    cancelAccompanyListener()
    await mockRespondAccompanyTask(accompanyTaskId, 'retry')
    go('accompanyCallingRobot')
    const cleanup = mockWaitAccompanyArrival(() => go('accompanyArrived'))
    accompanyCleanupRef.current = cleanup
  }

  // [화면 3 OK] accept -> accompany active
  const handleAccompanyOk = async () => {
    if (!accompanyTaskId) return
    await mockRespondAccompanyTask(accompanyTaskId, 'ok')
    go('accompanyActive')
  }

  // [화면 4 자리로 복귀] send return command, wait for return arrival
  const handleAccompanyReturn = async () => {
    if (!accompanyTaskId) return
    cancelAccompanyListener()
    await mockRespondAccompanyTask(accompanyTaskId, 'return')
    go('accompanyReturning')
    const cleanup = mockWaitReturnArrival(() => go('accompanyReturned'))
    accompanyCleanupRef.current = cleanup
  }

  // [화면 4 동행 완료 / 화면 6 완료] service complete
  const handleAccompanyComplete = async () => {
    cancelAccompanyListener()
    if (!accompanyTaskId) return
    await mockRespondAccompanyTask(accompanyTaskId, 'complete')
    go('accompanyComplete')
  }

  // [화면 6 동행] resume accompany from returned state
  const handleAccompanyResume = async () => {
    if (!accompanyTaskId) return
    await mockRespondAccompanyTask(accompanyTaskId, 'resume')
    go('accompanyActive')
  }

  // Reset accompany state when returning home
  const resetAccompanyState = () => {
    cancelAccompanyListener()
    setAccompanyTaskId(null)
  }

  // ── Toilet flow ──────────────────────────────────────────────────
  const startToiletRobotGuide = async () => {
    go('callingRobot')
    const toiDest = 'TOILET_01'
    const res = await sendRequest('toilet', toiDest)
    if (res.task_id) {
      setTaskId(res.task_id)
    } else if (!res.ok) {
      setToast({ id: Date.now(), text: '로봇 요청 실패', type: 'error' })
      go('restroomOptions')
    }
  }

  // ── Menu flow ────────────────────────────────────────────────────
  const startMenuRobotGuide = async (menus: MenuItem[], index = 0) => {
    go('callingRobot')
    const dest = menus[index]?.id ?? ''
    const res = await sendRequest(`menu:${dest}`, dest)
    if (res.task_id) {
      setTaskId(res.task_id)
    } else if (!res.ok) {
      setToast({ id: Date.now(), text: '로봇 요청 실패', type: 'error' })
      go('menuOptions')
    }
  }

  // ── Task respond helpers ─────────────────────────────────────────
  const handleRetry = async () => {
    if (!taskId) return
    await respondTask(taskId, { status: 'retry' })
    go('callingRobot')
  }

  // Called from InProgressScreen OK button
  const handleMenuInProgressOk = async () => {
    const nextIndex = waypointIndex + 1
    if (nextIndex < totalWaypoints && taskId) {
      const nextDest = selectedMenus[nextIndex]?.id ?? ''
      await respondTask(taskId, { status: 'ok', next_dest: nextDest })
      setWaypointIndex(nextIndex)
      go('callingRobot')
    } else {
      if (taskId) {
        await respondTask(taskId, { status: 'ok' })
      }
      go('guideComplete')
    }
  }

  const handleToiletInProgressOk = async () => {
    if (taskId) {
      await respondTask(taskId, { status: 'ok' })
    }
    go('guideComplete')
  }

  // Reset all menu/task state when returning home
  const resetMenuState = () => {
    setSelectedMenus([])
    setWaypointIndex(0)
    setFlow(null)
    setTaskId(null)
  }

  const renderScreen = () => {
    switch (screen) {
      case 'home':
        return (
          <HomeScreen
            tableId={tableId}
            onGuide={() => { setFlow(null); go('guideMenu') }}
            onAccompany={startAccompanyFlow}
            onToast={setToast}
          />
        )

      case 'guideMenu':
        return (
          <GuideMenuScreen
            onRestroom={() => { setFlow('toilet'); go('restroomOptions') }}
            onMenu={() => { setFlow('menu'); go('menuSelection') }}
            onBack={() => go('home')}
          />
        )

      case 'restroomOptions':
        return (
          <RestroomOptionsScreen
            onRobotGuide={startToiletRobotGuide}
            onBack={() => go('guideMenu')}
          />
        )

      case 'menuSelection':
        return (
          <MenuSelectionScreen
            onSelect={items => {
              setSelectedMenus(items)
              setWaypointIndex(0)
              go('menuOptions')
            }}
            onBack={() => go('guideMenu')}
          />
        )

      case 'menuOptions':
        return (
          <MenuOptionsScreen
            selectedMenus={selectedMenus}
            onRobotGuide={() => startMenuRobotGuide(selectedMenus, 0)}
            onBack={() => go('menuSelection')}
          />
        )

      case 'callingRobot':
        return (
          <CallingRobotScreen
            flow={flow}
            currentWaypoint={flow === 'menu' ? currentWaypoint : null}
            waypointIndex={waypointIndex}
            totalWaypoints={totalWaypoints}
          />
        )

      case 'robotArrived':
        return (
          <RobotArrivedScreen
            flow={flow}
            onOk={() => go('guideStarting')}
            onRetry={handleRetry}
            currentWaypoint={flow === 'menu' ? currentWaypoint : null}
            waypointIndex={waypointIndex}
            totalWaypoints={totalWaypoints}
          />
        )

      case 'guideStarting':
        return (
          <GuideStartingScreen
            onNext={() => go('inProgress')}
            currentWaypoint={flow === 'menu' ? currentWaypoint : null}
            waypointIndex={waypointIndex}
            totalWaypoints={totalWaypoints}
          />
        )

      case 'inProgress':
        return (
          <InProgressScreen
            flow={flow}
            onOk={flow === 'menu' ? handleMenuInProgressOk : handleToiletInProgressOk}
            onRetry={handleRetry}
            currentWaypoint={flow === 'menu' ? currentWaypoint : null}
            waypointIndex={waypointIndex}
            totalWaypoints={totalWaypoints}
          />
        )

      case 'guideComplete':
        return (
          <GuideCompleteScreen
            flow={flow}
            onHome={() => { resetMenuState(); go('home') }}
          />
        )

      // ── Accompany flow ────────────────────────────────────────────────────
      case 'accompanyCallingRobot':
        return <AccompanyCallingScreen />

      case 'accompanyArrived':
        return (
          <AccompanyArrivedScreen
            onOk={handleAccompanyOk}
            onRetry={handleAccompanyRetry}
          />
        )

      case 'accompanyActive':
        return (
          <AccompanyActiveScreen
            onReturnToTable={handleAccompanyReturn}
            onComplete={handleAccompanyComplete}
          />
        )

      case 'accompanyReturning':
        return <AccompanyReturningScreen />

      case 'accompanyReturned':
        return (
          <AccompanyReturnedScreen
            onAccompanyAgain={handleAccompanyResume}
            onComplete={handleAccompanyComplete}
          />
        )

      case 'accompanyComplete':
        return (
          <AccompanyCompleteScreen
            onHome={() => { resetAccompanyState(); go('home') }}
          />
        )

      default:
        return null
    }
  }

  return (
    <div className="relative w-full min-h-screen bg-[#f7f5f2]">
      <div className="w-full max-w-md mx-auto min-h-screen">
        {renderScreen()}
      </div>
      <Toast message={toast} />
    </div>
  )
}
