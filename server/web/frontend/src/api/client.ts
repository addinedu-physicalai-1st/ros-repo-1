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
  status: 'ok' | 'retry' | 'timeout'
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
