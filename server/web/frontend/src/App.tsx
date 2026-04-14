import { useState } from 'react'
import type { Screen, Flow, MenuItem } from './types'
import { mockDispatchRobot } from './api/mock'

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

const getTableId = (): string => {
  const params = new URLSearchParams(window.location.search)
  return params.get('table') || '3'
}

export default function App() {
  const [screen, setScreen] = useState<Screen>('home')
  const [flow, setFlow] = useState<Flow>(null)
  const [toast, setToast] = useState<ToastMessage | null>(null)

  // Multi-waypoint state (menu flow)
  const [selectedMenus, setSelectedMenus] = useState<MenuItem[]>([])
  const [waypointIndex, setWaypointIndex] = useState(0)

  const tableId = getTableId()
  const go = (s: Screen) => setScreen(s)

  // Derived helpers
  const currentWaypoint = selectedMenus[waypointIndex] ?? null
  const totalWaypoints = selectedMenus.length

  // ── Toilet flow ──────────────────────────────────────────────
  const startToiletRobotGuide = async () => {
    go('callingRobot')
    await mockDispatchRobot('toilet')
  }

  // ── Menu flow ────────────────────────────────────────────────
  const startMenuRobotGuide = async (menus: MenuItem[], index = 0) => {
    go('callingRobot')
    await mockDispatchRobot('menu', menus[index]?.id)
  }

  // Advance to next waypoint or finish
  const handleMenuInProgressOk = () => {
    if (waypointIndex + 1 < totalWaypoints) {
      const nextIndex = waypointIndex + 1
      setWaypointIndex(nextIndex)
      startMenuRobotGuide(selectedMenus, nextIndex)
    } else {
      go('guideComplete')
    }
  }

  // Reset all menu state
  const resetMenuState = () => {
    setSelectedMenus([])
    setWaypointIndex(0)
    setFlow(null)
  }

  const renderScreen = () => {
    switch (screen) {
      case 'home':
        return (
          <HomeScreen
            tableId={tableId}
            onGuide={() => { setFlow(null); go('guideMenu') }}
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
            onArrived={() => go('robotArrived')}
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
            onRetry={() => go('callingRobot')}
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
            onOk={flow === 'menu' ? handleMenuInProgressOk : () => go('guideComplete')}
            onRetry={() => go('guideStarting')}
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
