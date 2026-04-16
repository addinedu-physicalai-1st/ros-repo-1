/** Real API helpers for the table UI — replaces api/mock.ts */

const getTableId = (): string => {
  const params = new URLSearchParams(window.location.search)
  return params.get('table') || '3'
}

/**
 * POST /api/request — create a task and return the server-assigned task_id.
 * `type` examples: "menu:DISP_01", "toilet", "staff", …
 * `destId` is an optional override for the destination place_id (used for
 *   menu guidance where the destination is the display, not the table).
 */
export const sendRequest = async (
  type: string,
  destId?: string,
): Promise<{ ok: boolean; task_id?: string }> => {
  const table = getTableId()
  try {
    const body: Record<string, unknown> = {
      table,
      type,
      timestamp: new Date().toISOString(),
    }
    if (destId) body.dest_id = destId
    const res = await fetch('/api/request', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const json = await res.json()
    return { ok: res.ok, task_id: json.task_id }
  } catch {
    return { ok: false }
  }
}

export interface RespondPayload {
  status: 'ok' | 'retry' | 'timeout' | 'collect_done' | 'unload_done'
  next_dest?: string
}

/**
 * POST /api/tasks/{taskId}/respond — forward the user's OK / RETRY / TIMEOUT
 * decision to the control server.
 */
export const respondTask = async (
  taskId: string,
  payload: RespondPayload,
): Promise<{ ok: boolean }> => {
  try {
    const res = await fetch(`/api/tasks/${taskId}/respond`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    return { ok: res.ok }
  } catch {
    return { ok: false }
  }
}

export interface MenuItem {
  menu_id: number
  name: string
  place_id: string
  is_available: boolean
}

/** GET /api/menu-items — fetch available menu items */
export const fetchMenuItems = async (): Promise<{ menu_items: MenuItem[] }> => {
  try {
    const res = await fetch('/api/menu-items')
    if (!res.ok) return { menu_items: [] }
    return await res.json()
  } catch {
    return { menu_items: [] }
  }
}

export interface MenuItemRaw {
  menu_id: number
  name: string
  place_id: string
  is_available: boolean
}

/** POST /api/kitchen — create TABLE_TO_DISPLAY task (robot goes to kitchen first) */
export const createKitchenTask = async (
  dispId: string,
): Promise<{ ok: boolean; task_id?: string; detail?: string }> => {
  try {
    const res = await fetch('/api/kitchen', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'menu_ready', disp_id: dispId }),
    })
    const json = await res.json()
    return { ok: res.ok, task_id: json.task_id, detail: json.detail }
  } catch (e: unknown) {
    return { ok: false, detail: String(e) }
  }
}

/** POST /api/tasks/{taskId}/cancel — cancel task and return robot to waiting area */
export const cancelTask = async (taskId: string): Promise<{ ok: boolean }> => {
  try {
    const res = await fetch(`/api/tasks/${taskId}/cancel`, { method: 'POST' })
    return { ok: res.ok }
  } catch {
    return { ok: false }
  }
}
