import Dexie, { type EntityTable } from 'dexie'

interface PendingStockUpdate {
  id?: number
  facility_id: string
  medicine_id: number
  quantity_change: number
  reason: string
  recorded_at: string
  client_id: string
  synced: boolean
}

interface PendingFootfall {
  id?: number
  facility_id: string
  date: string
  footfall_count: number
  recorded_at: string
  client_id: string
  synced: boolean
}

interface PendingAttendance {
  id?: number
  facility_id: string
  user_id: string
  date: string
  present: boolean
  recorded_at: string
  client_id: string
  synced: boolean
}

// Generic offline outbox for ledger writes (footfall tally / beds / tests).
// Each row is PUT to its /ledger endpoint when online.
interface PendingLedger {
  id?: number
  kind: 'footfall' | 'beds' | 'tests'
  facility_id: string
  payload: unknown            // request body for the /ledger/<kind> PUT
  recorded_at: string
  client_id: string
  synced: boolean
}

interface CachedMedicine {
  id: number
  name: string
  reorder_level: number
  unit: string
  category: string
}

interface CachedNotification {
  id: string
  channel: string
  body: string
  template_key?: string | null
  template_params?: Record<string, string | number> | null
  created_at: string
  read: boolean
}

class SmartHealthDB extends Dexie {
  pendingStockUpdates!: EntityTable<PendingStockUpdate, 'id'>
  pendingFootfall!: EntityTable<PendingFootfall, 'id'>
  pendingAttendance!: EntityTable<PendingAttendance, 'id'>
  pendingLedger!: EntityTable<PendingLedger, 'id'>
  medicines!: EntityTable<CachedMedicine, 'id'>
  notifications!: EntityTable<CachedNotification, 'id'>

  constructor() {
    super('smarthealth')
    this.version(1).stores({
      pendingStockUpdates: '++id, facility_id, synced',
      pendingFootfall: '++id, facility_id, date, synced',
      pendingAttendance: '++id, facility_id, date, synced',
      medicines: 'id',
      notifications: 'id, read',
    })
    // v2 adds the generic ledger outbox (footfall tally / beds / tests).
    this.version(2).stores({
      pendingLedger: '++id, kind, facility_id, synced',
    })
    // v3 indexes created_at — NotificationsPage calls orderBy('created_at'),
    // which Dexie throws on for a non-indexed field, leaving the page stuck
    // on its loading state forever since the error was never caught.
    this.version(3).stores({
      notifications: 'id, read, created_at',
    })
    // v4 indexes category so the stock page can group medicines by it.
    this.version(4).stores({
      medicines: 'id, category',
    })
  }
}

export const db = new SmartHealthDB()
export type { PendingStockUpdate, PendingFootfall, PendingAttendance, PendingLedger, CachedMedicine }
