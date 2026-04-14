// Mock API — replace with real fetch() calls when server is ready

export const mockDispatchRobot = (_type: string, _menuId?: string): Promise<void> =>
  new Promise(r => setTimeout(r, 500))

export const mockWaitArrival = (): Promise<void> =>
  new Promise(r => setTimeout(r, 3000))

export const mockStartGuide = (): Promise<void> =>
  new Promise(r => setTimeout(r, 300))

export const mockRetryDispatch = (_type: string, _menuId?: string): Promise<void> =>
  new Promise(r => setTimeout(r, 500))

export const mockEndGuide = (): Promise<void> =>
  new Promise(r => setTimeout(r, 300))

// ── Accompany flow mocks ──────────────────────────────────────────────────────

/** Simulates POST /api/request { type: "accompany" } -> { task_id } */
export const mockAccompanyRequest = (): Promise<{ task_id: string }> =>
  new Promise(resolve =>
    setTimeout(() => {
      console.log('[Mock] POST /api/request { type: "accompany" } -> { task_id: "mock-accompany-1" }')
      resolve({ task_id: 'mock-accompany-1' })
    }, 500),
  )

/**
 * Simulates WebSocket broadcast: robot arrives at table (first call).
 * Returns a cleanup function to cancel the pending timer.
 */
export const mockWaitAccompanyArrival = (onArrived: () => void): (() => void) => {
  console.log('[Mock] WebSocket: waiting for robot to arrive at table...')
  const timer = setTimeout(() => {
    console.log('[Mock] WebSocket: { event: "status", robot_status: 3 (ARRIVED), task: "mock-accompany-1" }')
    onArrived()
  }, 3000)
  return () => clearTimeout(timer)
}

/**
 * Simulates WebSocket broadcast: robot returns to table after accompany.
 * Returns a cleanup function to cancel the pending timer.
 */
export const mockWaitReturnArrival = (onArrived: () => void): (() => void) => {
  console.log('[Mock] WebSocket: waiting for robot to return to table...')
  const timer = setTimeout(() => {
    console.log('[Mock] WebSocket: { event: "status", robot_status: 3 (ARRIVED), task: "mock-accompany-1" } (return)')
    onArrived()
  }, 3000)
  return () => clearTimeout(timer)
}

/** Simulates POST /api/tasks/{taskId}/respond with a given status */
export const mockRespondAccompanyTask = (
  taskId: string,
  status: 'ok' | 'retry' | 'return' | 'resume' | 'complete',
): Promise<{ ok: boolean }> =>
  new Promise(resolve =>
    setTimeout(() => {
      console.log(`[Mock] POST /api/tasks/${taskId}/respond { status: "${status}" } -> { ok: true }`)
      resolve({ ok: true })
    }, 300),
  )

const getTableId = (): string => {
  const params = new URLSearchParams(window.location.search)
  return params.get('table') || '3'
}

export const sendRequest = async (type: string): Promise<{ ok: boolean }> => {
  const table = getTableId()
  try {
    const res = await fetch('/api/request', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ table, type, timestamp: new Date().toISOString() }),
    })
    return { ok: res.ok }
  } catch {
    return { ok: false }
  }
}
