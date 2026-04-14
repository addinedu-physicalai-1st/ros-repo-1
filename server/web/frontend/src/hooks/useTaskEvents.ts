import { useEffect, useRef } from 'react'

/**
 * Subscribes to the web server WebSocket and fires `onArrived` when the
 * robot assigned to `taskId` reports ARRIVED (robot_status === 3).
 *
 * The hook reconnects automatically if the WebSocket closes unexpectedly.
 * Cleans up on unmount or when `taskId` changes to null.
 */
export function useTaskEvents(
  taskId: string | null,
  onArrived: () => void,
) {
  // Keep a stable ref to the callback so the effect doesn't re-run when it changes
  const onArrivedRef = useRef(onArrived)
  useEffect(() => { onArrivedRef.current = onArrived }, [onArrived])

  useEffect(() => {
    if (!taskId) return

    let ws: WebSocket | null = null
    let cancelled = false
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      if (cancelled) return
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
      ws = new WebSocket(`${proto}//${location.host}/ws`)

      ws.onmessage = (e: MessageEvent) => {
        try {
          const msg = JSON.parse(e.data as string)
          if (
            msg.event === 'status' &&
            msg.robot_status === 3 &&          // ARRIVED
            msg.current_task === taskId
          ) {
            onArrivedRef.current()
          }
        } catch {
          // ignore malformed messages
        }
      }

      ws.onclose = () => {
        if (!cancelled) {
          retryTimer = setTimeout(connect, 3000)
        }
      }

      ws.onerror = () => {
        ws?.close()
      }
    }

    connect()

    return () => {
      cancelled = true
      if (retryTimer !== null) clearTimeout(retryTimer)
      ws?.close()
    }
  }, [taskId])
}
