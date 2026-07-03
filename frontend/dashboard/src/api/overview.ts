import { apiClient } from './client'

export interface StateBeds {
  state_ut: string
  phc_beds: number | null
  chc_beds: number | null
  sub_district_beds: number | null
  district_hospital_beds: number | null
  medical_college_beds: number | null
  total_beds: number | null
  as_on_date: string | null
}

export interface NationalSummary {
  states_reported: number
  phc_beds: number
  chc_beds: number
  sub_district_beds: number
  district_hospital_beds: number
  medical_college_beds: number
  total_beds: number
  as_on_date: string | null
}

export const getStateInfrastructure = async () => {
  const { data } = await apiClient.get<StateBeds[]>('/overview/state-infrastructure')
  return data
}

export const getNationalSummary = async () => {
  const { data } = await apiClient.get<NationalSummary>('/overview/national-summary')
  return data
}
