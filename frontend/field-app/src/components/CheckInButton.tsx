import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import clsx from 'clsx'
import { useAuthStore } from '../stores/authStore'

// Geofenced check-in, hoisted out of the Daily Entry page into the top header
// bar so it's reachable from anywhere in the app. Confirms the worker is
// physically on-site (within the facility geofence) using device GPS.
export default function CheckInButton() {
  const { t } = useTranslation()
  const { facilityId, token } = useAuthStore()
  const [checking, setChecking] = useState(false)
  const [status, setStatus] = useState<{ within: boolean; distance: number } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

  const handleCheckIn = () => {
    setError(null); setStatus(null)
    if (!navigator.geolocation) { setError(t('checkin.errorGeoUnavailable')); return }
    if (!navigator.onLine) { setError(t('checkin.errorNeedsNetwork')); return }
    setChecking(true)
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          const res = await fetch(`${API}/api/v1/attendance/check-in`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
            body: JSON.stringify({ lat: pos.coords.latitude, lng: pos.coords.longitude, facility_id: facilityId }),
          })
          if (!res.ok) throw new Error(t('checkin.errorFailed'))
          const data = await res.json()
          setStatus({ within: data.within_geofence, distance: Math.round(data.distance_m ?? 0) })
        } catch (e) {
          setError(e instanceof Error ? e.message : t('checkin.errorFailed'))
        } finally { setChecking(false) }
      },
      (err) => { setError(err.message || t('checkin.errorNoLocation')); setChecking(false) },
      { enableHighAccuracy: true, timeout: 10000 },
    )
  }

  return (
    <div className="relative">
      <button
        onClick={handleCheckIn}
        disabled={checking}
        className="flex items-center gap-1.5 rounded-full bg-teal-600 text-white text-xs font-semibold px-3 py-1.5 disabled:opacity-50 hover:bg-teal-700 transition-colors"
      >
        📍 {checking ? t('checkin.locating') : t('checkin.btn')}
      </button>
      {(status || error) && (
        <div className="absolute right-0 mt-1 z-50 w-56 rounded-lg shadow-lg border border-gray-100 bg-white p-2 text-xs">
          {status && (
            <p className={clsx('font-medium', status.within ? 'text-green-700' : 'text-red-700')}>
              {status.within ? `✓ ${t('checkin.within', { distance: status.distance })}` : `⚠ ${t('checkin.outside', { distance: status.distance })}`}
            </p>
          )}
          {error && <p className="text-red-600">{error}</p>}
          <button onClick={() => { setStatus(null); setError(null) }} className="mt-1 text-gray-400 hover:text-gray-600">✕</button>
        </div>
      )}
    </div>
  )
}
