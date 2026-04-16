import { useEffect, useCallback } from 'react'

const LS_KEY = 'kitchen_task_state'

export interface KitchenState {
  task_id: string
  disp_id: string
  menu_name: string
  robot_id: string
  stage: number  // 1=robot going to kitchen, 2=robot going to display, 3=robot returning
}

/** Write kitchen task state to localStorage (for cross-window sync with staff page) */
export const writeKitchenSync = (state: KitchenState | null): void => {
  if (state === null) {
    localStorage.removeItem(LS_KEY)
  } else {
    localStorage.setItem(LS_KEY, JSON.stringify(state))
  }
}

/** Read current kitchen task state from localStorage */
export const readKitchenSync = (): KitchenState | null => {
  try {
    const raw = localStorage.getItem(LS_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

/**
 * Hook for staff page: listen for kitchen state changes via localStorage storage events.
 * onUpdate fires when the kitchen page updates the shared state.
 */
export function useKitchenSync(onUpdate: (state: KitchenState | null) => void): void {
  const onUpdateRef = useCallback(onUpdate, [onUpdate])

  useEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key !== LS_KEY) return
      try {
        const data = e.newValue ? JSON.parse(e.newValue) : null
        onUpdateRef(data)
      } catch {
        onUpdateRef(null)
      }
    }
    window.addEventListener('storage', handler)
    return () => window.removeEventListener('storage', handler)
  }, [onUpdateRef])
}
