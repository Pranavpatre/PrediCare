import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getNearestFacilities } from '../api/facilities'
import { useAuthStore } from '../stores/authStore'

// Shows the admin's auto-detected location (district, state) in the top bar,
// derived from device GPS → nearest facility's district. Silent no-op if the
// browser denies/lacks geolocation — the nav simply doesn't show a badge.
export default function LocationBadge() {
  const { t } = useTranslation()
  const token = useAuthStore((s) => s.token)
  const [label, setLabel] = useState<string | null>(null)
  const [locating, setLocating] = useState(false)

  useEffect(() => {
    if (!navigator.geolocation || !token) return
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          const near = await getNearestFacilities(pos.coords.latitude, pos.coords.longitude, 1)
          const n = near[0]
          if (n?.district_name) setLabel(n.district_name)
          else if (n?.name) setLabel(n.name)
        } catch { /* keep silent */ } finally { setLocating(false) }
      },
      () => setLocating(false),
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 300000 },
    )
  }, [token])

  if (!label && !locating) return null

  return (
    <span
      title={t('location.detected', 'Your detected location')}
      className="flex items-center gap-1 rounded-full bg-teal-50 text-teal-700 text-xs font-semibold px-2.5 py-1 max-w-[16rem] truncate"
    >
      📍 {locating && !label ? t('location.locating', 'Locating…') : label}
    </span>
  )
}
