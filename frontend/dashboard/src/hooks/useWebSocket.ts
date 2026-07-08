import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useAuthStore } from '../stores/authStore'

// Prefer an explicit VITE_WS_URL; otherwise derive the websocket origin from
// the API URL (http→ws, https→wss) so production doesn't fall back to
// ws://localhost:8000 (which fails on every page). Falls back to localhost only
// in local dev where neither var is set.
const WS_URL =
  import.meta.env.VITE_WS_URL ||
  (import.meta.env.VITE_API_URL
    ? String(import.meta.env.VITE_API_URL).replace(/^http/, 'ws')
    : 'ws://localhost:8000')

export function useAlertWebSocket() {
  const queryClient = useQueryClient()
  const token = useAuthStore((s) => s.token)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    if (!token) return
    const ws = new WebSocket(`${WS_URL}/ws/alerts`)
    wsRef.current = ws

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data as string)
      if (msg.type === 'new_alert' || msg.type === 'alert_resolved' || msg.type === 'plan_approved') {
        queryClient.invalidateQueries({ queryKey: ['alerts'] })
        queryClient.invalidateQueries({ queryKey: ['facilities'] })
        queryClient.invalidateQueries({ queryKey: ['health-scores'] })
      }
    }

    ws.onerror = () => console.warn('WebSocket error')
    ws.onclose = () => {
      setTimeout(() => { wsRef.current = null }, 5000)
    }

    return () => ws.close()
  }, [token, queryClient])
}
