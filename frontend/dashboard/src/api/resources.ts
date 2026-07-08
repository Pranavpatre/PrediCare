import { apiClient } from './client'

// ── Per-facility resource views (medicine stock, tests, beds, doctor days) ──
// These power the admin "Stock" tab and let field-entered data (stock levels,
// test availability, bed occupancy, attendance) surface in the admin app.

export interface StockRow {
  medicine_id: number
  name: string
  category: string
  unit: string
  reorder_level: number
  current_stock: number
  status: 'OK' | 'WATCH' | 'LOW'
}

export const getFacilityStock = async (facilityId: string) => {
  const { data } = await apiClient.get<StockRow[]>(`/medicines/stock/${facilityId}`)
  return data
}

export interface TestRow {
  test_id: number
  test_name: string | null
  available: boolean
}

export const getFacilityTests = async (facilityId: string) => {
  const { data } = await apiClient.get<{ facility_id: string; tests: TestRow[] }>(
    `/ledger/tests/${facilityId}`,
  )
  return data.tests
}

export interface BedRow {
  bed_type: string
  total_beds: number
  occupied_beds: number
}

export const getFacilityBeds = async (facilityId: string) => {
  const { data } = await apiClient.get<{ facility_id: string; beds: BedRow[] }>(
    `/ledger/beds/${facilityId}`,
  )
  return data.beds
}

export interface AttendanceDay {
  date: string
  present: number
  total: number
}

export const getAttendanceHistory = async (facilityId: string, days = 14) => {
  const { data } = await apiClient.get<AttendanceDay[]>(
    `/attendance/facility/${facilityId}/history`,
    { params: { days } },
  )
  return data
}
