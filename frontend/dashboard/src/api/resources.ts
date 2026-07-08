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
  // Present when the reorder level came from the district-customized demand
  // model rather than the global default.
  demand_based?: boolean
  required_stock?: number | null
  expected_daily_demand?: number | null
}

export const getFacilityStock = async (facilityId: string) => {
  const { data } = await apiClient.get<StockRow[]>(`/medicines/stock/${facilityId}`)
  return data
}

// How a facility's dynamic reorder levels were derived (own footfall, worst-case
// load, position vs district peers). Powers the "Demand basis" panel.
export interface DemandProfile {
  facility_id: string
  has_profile: boolean
  sample_days: number
  mean_daily_footfall: number
  p95_daily_footfall: number
  district_footfall_share: number
  population_factor: number
  basis: 'facility' | 'district_fallback' | 'default'
  computed_at: string | null
}

export const getDemandProfile = async (facilityId: string) => {
  const { data } = await apiClient.get<DemandProfile>(
    `/facilities/${facilityId}/demand-profile`,
  )
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

export interface DoctorRow {
  id: string
  name: string
  specialty: string | null
  present_today: boolean
}

export const getDoctors = async (facilityId: string) => {
  const { data } = await apiClient.get<DoctorRow[]>(`/doctors/facility/${facilityId}`)
  return data
}
