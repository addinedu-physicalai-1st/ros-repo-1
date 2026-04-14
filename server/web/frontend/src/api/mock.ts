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
