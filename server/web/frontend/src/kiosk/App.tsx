import { useState, useCallback } from 'react'
import type { Screen, PayMethod, People } from './types'
import { calcTotal, randomTable } from './types'
import WelcomeScreen from './screens/WelcomeScreen'
import SelectionScreen from './screens/SelectionScreen'
import PaymentScreen from './screens/PaymentScreen'
import TrackingScreen from './screens/TrackingScreen'

function getInitialScreen(): Screen {
  const param = new URLSearchParams(window.location.search).get('screen')
  if (param === 'selection' || param === 'payment' || param === 'tracking') return param
  return 'welcome'
}

const DEFAULT_PEOPLE: People = { adult: 0, child: 0, infant: 0 }

export default function App() {
  const [screen, setScreen] = useState<Screen>(getInitialScreen)
  const [people, setPeople] = useState<People>(DEFAULT_PEOPLE)
  const [assignedTable, setAssignedTable] = useState<string>('')

  const goWelcome = useCallback(() => {
    setScreen('welcome')
    setPeople(DEFAULT_PEOPLE)
    setAssignedTable('')
  }, [])

  const handleStart = useCallback(() => {
    setScreen('selection')
  }, [])

  const handleIdleReset = useCallback(() => {
    goWelcome()
  }, [goWelcome])

  const handleSelectionNext = useCallback(() => {
    setScreen('payment')
  }, [])

  const handlePay = useCallback(
    async (method: PayMethod) => {
      const table = randomTable()
      setAssignedTable(table)

      try {
        await fetch('/api/checkout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            table,
            people,
            total: calcTotal(people),
            payMethod: method,
            timestamp: new Date().toISOString(),
          }),
        })
      } catch {
        // proceed to tracking regardless of network errors
      }

      setScreen('tracking')
    },
    [people],
  )

  return (
    <div className="w-full h-full flex items-center justify-center p-6">
      {screen === 'welcome' && <WelcomeScreen onStart={handleStart} />}

      {screen === 'selection' && (
        <SelectionScreen
          people={people}
          onChange={setPeople}
          onNext={handleSelectionNext}
          onIdleReset={handleIdleReset}
        />
      )}

      {screen === 'payment' && (
        <PaymentScreen
          people={people}
          onBack={() => setScreen('selection')}
          onPay={handlePay}
        />
      )}

      {screen === 'tracking' && (
        <TrackingScreen assignedTable={assignedTable} onDone={goWelcome} />
      )}
    </div>
  )
}
