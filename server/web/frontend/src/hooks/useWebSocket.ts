import { useEffect, useRef } from 'react'

type WsMessageHandler = (data: Record<string, unknown>) => void

/**
 * Generic WebSocket hook — connects to /ws and calls onMessage for every parsed JSON event.
 * Auto-reconnects on close. active=false to disable.
 */
export function useWebSocket(onMessage: WsMessageHandler, active = true): void {
  const onMessageRef = useRef(onMessage)
  useEffect(() => { onMessageRef.current = onMessage }, [onMessage])

  useEffect(() => {
    if (!active) return

    let ws: WebSocket | null = null
    let cancelled = false
    let retryTimer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      if (cancelled) return
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
      ws = new WebSocket(`${proto}//${location.host}/ws`)

      ws.onmessage = (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data as string)
          onMessageRef.current(data)
        } catch { /* ignore */ }
      }

      ws.onclose = () => {
        if (!cancelled) retryTimer = setTimeout(connect, 3000)
      }

      ws.onerror = () => ws?.close()
    }

    connect()
    return () => {
      cancelled = true
      if (retryTimer !== null) clearTimeout(retryTimer)
      ws?.close()
    }
  }, [active])
}
