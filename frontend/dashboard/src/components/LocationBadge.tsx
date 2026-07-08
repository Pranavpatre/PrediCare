import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { useAuthStore } from '../stores/authStore'

// Shows the admin's CURRENT working scope (district, state) and lets them update
// it to their real GPS location on click. Always visible (falls back to the
// assigned district/state), so the user always sees which state/district the
// dashboard is scoped to — and can retap if auto-detect was blocked.
export default function LocationBadge() {
  const { t } = useTranslation()
  const qc = useQueryClient()
  const { districtName, stateName, setLocation } = useAuthStore()
  const [locating, setLocating] = useState(false)
  const [error, setError] = useState(false)

  const detect = () => {
    if (!navigator.geolocation) { setError(true); return }
    setLocating(true); setError(false)
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          const { data } = await apiClient.post('/auth/me/location', {
            lat: pos.coords.latitude, lng: pos.coords.longitude,
          })
          setLocation({
            districtId: data.district_id, districtName: data.district_name,
            stateId: data.state_id, stateName: data.state_name,
          })
          qc.invalidateQueries()  // re-scope dashboard to the new location
        } catch { setError(true) } finally { setLocating(false) }
      },
      () => { setError(true); setLocating(false) },
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 60000 },
    )
  }

  const label = locating
    ? t('location.locating', 'Locating…')
    : districtName
      ? `${districtName}${stateName ? `, ${stateName}` : ''}`
      : t('location.detect', 'Use my location')

  return (
    <button
      onClick={detect}
      title={error
        ? t('location.blocked', 'Location blocked — enable location for this site, then tap again')
        : t('location.tap', 'Tap to set the dashboard to your current location')}
      className={`flex items-center gap-1 rounded-full text-xs font-semibold px-2.5 py-1 max-w-[18rem] truncate transition-colors ${
        error ? 'bg-red-50 text-red-600' : 'bg-teal-50 text-teal-700 hover:bg-teal-100'
      }`}
    >
      📍 {label}
    </button>
  )
}
