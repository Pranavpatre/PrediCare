import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '../stores/authStore'

// Instead of a manual geofenced "check-in", just show which PHC/CHC the worker
// is currently at, derived from device GPS → nearest facility. Falls back to the
// worker's assigned facility if location is unavailable.
const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function LocationBadge() {
  const { t } = useTranslation()
  const { token, facilityName } = useAuthStore()
  const [name, setName] = useState<string | null>(null)
  const [locating, setLocating] = useState(false)

  useEffect(() => {
    if (!navigator.geolocation || !token) return
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          const res = await fetch(
            `${API}/api/v1/facilities/nearest?lat=${pos.coords.latitude}&lng=${pos.coords.longitude}&limit=1`,
            { headers: { Authorization: `Bearer ${token}` } },
          )
          if (res.ok) {
            const list = await res.json()
            if (list[0]?.name) setName(list[0].name)
          }
        } catch { /* keep fallback */ } finally { setLocating(false) }
      },
      () => setLocating(false),
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 300000 },
    )
  }, [token])

  const label = name || facilityName || ''
  if (!label && !locating) return null

  return (
    <span
      title={t('location.at')}
      className="flex items-center gap-1 rounded-full bg-teal-50 text-teal-700 text-xs font-semibold px-2.5 py-1 max-w-[45vw] truncate"
    >
      📍 {locating && !name ? t('checkin.locating') : label}
    </span>
  )
}
