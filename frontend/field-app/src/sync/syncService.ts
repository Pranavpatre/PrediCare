import axios from 'axios'
import { db } from '../db/localDb'
import { useAuthStore } from '../stores/authStore'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

function genClientId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

/**
 * Offline-first write for a ledger action (footfall tally / beds / tests):
 * always queue locally, then flush immediately if online. Guarantees the entry
 * survives with no network and syncs on reconnect — same contract as the
 * stock/attendance queues.
 */
export async function queueLedger(
  kind: 'footfall' | 'beds' | 'tests',
  facilityId: string,
  payload: unknown,
): Promise<{ online: boolean }> {
  await db.pendingLedger.add({
    kind,
    facility_id: facilityId,
    payload,
    recorded_at: new Date().toISOString(),
    client_id: genClientId(),
    synced: false,
  })
  if (navigator.onLine) {
    await flushLedger()
    return { online: true }
  }
  return { online: false }
}

/** Flush queued ledger writes to their /ledger endpoints. */
export async function flushLedger(): Promise<{ synced: number; errors: number }> {
  const token = useAuthStore.getState().token
  if (!token || !navigator.onLine) return { synced: 0, errors: 0 }
  const client = axios.create({
    baseURL: `${API_URL}/api/v1`,
    headers: { Authorization: `Bearer ${token}` },
  })
  const pending = await db.pendingLedger.filter((r) => !r.synced).toArray()
  let synced = 0
  let errors = 0
  for (const item of pending) {
    try {
      await client.put(`/ledger/${item.kind}/${item.facility_id}`, item.payload)
      await db.pendingLedger.update(item.id!, { synced: true as unknown as boolean })
      synced++
    } catch {
      errors++
    }
  }
  return { synced, errors }
}

export async function syncPendingData(): Promise<{ synced: number; errors: number }> {
  const token = useAuthStore.getState().token
  if (!token || !navigator.onLine) return { synced: 0, errors: 0 }

  const client = axios.create({
    baseURL: `${API_URL}/api/v1`,
    headers: { Authorization: `Bearer ${token}` },
  })

  // Flush the ledger outbox (footfall tally / beds / tests) alongside the batch push.
  const ledger = await flushLedger()

  const [stockUpdates, footfall, attendance] = await Promise.all([
    db.pendingStockUpdates.filter((r) => !r.synced).toArray(),
    db.pendingFootfall.filter((r) => !r.synced).toArray(),
    db.pendingAttendance.filter((r) => !r.synced).toArray(),
  ])

  if (!stockUpdates.length && !footfall.length && !attendance.length) {
    return { synced: ledger.synced, errors: ledger.errors }
  }

  let synced = ledger.synced
  let errors = ledger.errors

  try {
    const payload = {
      stock_updates: stockUpdates.map(({ id: _id, synced: _s, ...rest }) => rest),
      footfall: footfall.map(({ id: _id, synced: _s, ...rest }) => rest),
      attendance: attendance.map(({ id: _id, synced: _s, ...rest }) => rest),
      last_sync_at: new Date().toISOString(),
    }

    const { data } = await client.post('/sync/push', payload)
    synced = data.accepted ?? stockUpdates.length + footfall.length + attendance.length

    // Mark as synced in local DB
    await Promise.all([
      ...stockUpdates.map((r) =>
        db.pendingStockUpdates.update(r.id!, { synced: true as unknown as boolean }),
      ),
      ...footfall.map((r) =>
        db.pendingFootfall.update(r.id!, { synced: true as unknown as boolean }),
      ),
      ...attendance.map((r) =>
        db.pendingAttendance.update(r.id!, { synced: true as unknown as boolean }),
      ),
    ])
  } catch {
    errors = stockUpdates.length + footfall.length + attendance.length
  }

  return { synced, errors }
}

export async function fetchAndCacheMedicines(): Promise<void> {
  const token = useAuthStore.getState().token
  if (!token || !navigator.onLine) return
  try {
    const { data } = await axios.get(`${API_URL}/api/v1/medicines`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const medicines = Array.isArray(data) ? data : (data?.medicines ?? [])
    await db.medicines.bulkPut(medicines)
  } catch {
    /* silent — offline or server unavailable */
  }
}

export async function fetchAndCacheNotifications(): Promise<void> {
  const token = useAuthStore.getState().token
  if (!token || !navigator.onLine) return
  try {
    const { data } = await axios.get(`${API_URL}/api/v1/notifications`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    const notifications = Array.isArray(data) ? data : (data?.notifications ?? [])
    // Preserve local read status
    const existing = await db.notifications.toArray()
    const readSet = new Set(existing.filter((n) => n.read).map((n) => n.id))
    const merged = notifications.map((n: { id: string; read: boolean }) => ({
      ...n,
      read: readSet.has(n.id) ? true : n.read,
    }))
    await db.notifications.bulkPut(merged)
  } catch {
    /* silent */
  }
}
