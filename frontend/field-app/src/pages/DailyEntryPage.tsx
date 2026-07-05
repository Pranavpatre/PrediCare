import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { format } from 'date-fns'
import { db } from '../db/localDb'
import { useAuthStore } from '../stores/authStore'
import { useVoiceInput, parseSpokenNumber, VOICE_LANG_MAP } from '../hooks/useVoiceInput'
import { syncPendingData, queueLedger } from '../sync/syncService'
import InfoNote from '../components/InfoNote'
import VoiceRecordingBanner from '../components/VoiceRecordingBanner'
import clsx from 'clsx'

function generateClientId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

export default function DailyEntryPage() {
  const { t } = useTranslation()
  const { facilityId, userId, token, languagePref } = useAuthStore()
  const today = format(new Date(), 'yyyy-MM-dd')

  // Geofenced check-in state
  const [checkingIn, setCheckingIn] = useState(false)
  const [checkInStatus, setCheckInStatus] = useState<{ within: boolean; distance: number } | null>(null)
  const [checkInError, setCheckInError] = useState<string | null>(null)

  // Bed matrix + test checklist state
  const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'
  const authHdr = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }
  const [beds, setBeds] = useState<{ bed_type: string; total_beds: number; occupied_beds: number }[]>([])
  const [bedsSaved, setBedsSaved] = useState(false)
  const [tests, setTests] = useState<{ test_id: number; test_name: string | null; available: boolean }[]>([])
  const [testsSaved, setTestsSaved] = useState(false)

  // Rapid footfall tally (general / maternal / emergency)
  const [tally, setTally] = useState({ general: 0, maternal: 0, emergency: 0 })
  const [tallySaved, setTallySaved] = useState(false)
  const bump = (k: 'general' | 'maternal' | 'emergency', d: number) =>
    setTally((t) => ({ ...t, [k]: Math.max(0, t[k] + d) }))
  const saveTally = async () => {
    if (!facilityId) return
    await queueLedger('footfall', facilityId, tally)   // offline-first: queue + sync if online
    setTallySaved(true); setTimeout(() => setTallySaved(false), 3000)
    refreshPending()
  }

  useEffect(() => {
    if (!facilityId || !token) return
    fetch(`${API}/api/v1/ledger/beds/${facilityId}`, { headers: authHdr })
      .then((r) => r.ok ? r.json() : null).then((d) => d && setBeds(d.beds)).catch(() => {})
    fetch(`${API}/api/v1/ledger/tests/${facilityId}`, { headers: authHdr })
      .then((r) => r.ok ? r.json() : null).then((d) => d && setTests(d.tests)).catch(() => {})
    fetch(`${API}/api/v1/ledger/footfall/${facilityId}`, { headers: authHdr })
      .then((r) => r.ok ? r.json() : null)
      .then((d) => d && setTally({ general: d.general, maternal: d.maternal, emergency: d.emergency }))
      .catch(() => {})
  }, [facilityId, token])

  const setOccupied = (bedType: string, delta: number) =>
    setBeds((prev) => prev.map((b) => b.bed_type === bedType
      ? { ...b, occupied_beds: Math.max(0, Math.min(b.total_beds, b.occupied_beds + delta)) } : b))

  const saveBeds = async () => {
    if (!facilityId) return
    await queueLedger('beds', facilityId, beds)
    setBedsSaved(true); setTimeout(() => setBedsSaved(false), 3000)
    refreshPending()
  }

  const toggleTest = (testId: number) =>
    setTests((prev) => prev.map((t) => t.test_id === testId ? { ...t, available: !t.available } : t))

  const saveTests = async () => {
    if (!facilityId) return
    await queueLedger('tests', facilityId, tests)
    setTestsSaved(true); setTimeout(() => setTestsSaved(false), 3000)
    refreshPending()
  }

  // Patient count state
  const [patientCount, setPatientCount] = useState<string>('')
  const [footfallSaved, setFootfallSaved] = useState(false)
  const [footfallError, setFootfallError] = useState<string | null>(null)

  // Doctor attendance state — starts unset (neither button highlighted) so
  // the UI never implies attendance was recorded before the worker actually
  // taps something.
  const [doctorPresent, setDoctorPresent] = useState<boolean | null>(null)
  const [attendanceSaved, setAttendanceSaved] = useState(false)

  // Pending count
  const [pendingCount, setPendingCount] = useState(0)

  // Sync
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState<string | null>(null)

  const { isListening, transcript, error: voiceError, startListening, stopListening, reset: resetVoice } =
    useVoiceInput(VOICE_LANG_MAP[languagePref] || 'en-IN')

  // Parse voice transcript into patient count
  useEffect(() => {
    if (!transcript) return
    const parsed = parseSpokenNumber(transcript)
    if (parsed !== null) {
      setPatientCount(String(parsed))
      setFootfallError(null)
    } else {
      setFootfallError(t('patient.errorParse', { transcript }))
    }
    resetVoice()
  }, [transcript, resetVoice])

  // Load pending count on mount and after saves
  const refreshPending = async () => {
    const [f, a, l] = await Promise.all([
      db.pendingFootfall.filter((r) => !r.synced).count(),
      db.pendingAttendance.filter((r) => !r.synced).count(),
      db.pendingLedger.filter((r) => !r.synced).count(),
    ])
    setPendingCount(f + a + l)
  }

  useEffect(() => { refreshPending() }, [])

  const handleSaveFootfall = async () => {
    if (!facilityId || !userId) return
    const count = parseInt(patientCount, 10)
    if (isNaN(count) || count < 0) {
      setFootfallError(t('patient.errorInvalid'))
      return
    }
    setFootfallError(null)
    await db.pendingFootfall.add({
      facility_id: facilityId,
      date: today,
      footfall_count: count,
      recorded_at: new Date().toISOString(),
      client_id: generateClientId(),
      synced: false,
    })
    setFootfallSaved(true)
    setTimeout(() => setFootfallSaved(false), 3000)
    setPatientCount('')
    // Offline-first: always queue locally, then flush immediately if online —
    // same contract as queueLedger (beds/tests/tally), so this doesn't sit as
    // "pending" until a manual Sync Now tap like the rest of the screen.
    if (navigator.onLine) await syncPendingData()
    refreshPending()
  }

  const handleToggleAttendance = async (present: boolean) => {
    if (!facilityId || !userId) return
    setDoctorPresent(present)
    await db.pendingAttendance.add({
      facility_id: facilityId,
      user_id: userId,
      date: today,
      present,
      recorded_at: new Date().toISOString(),
      client_id: generateClientId(),
      synced: false,
    })
    setAttendanceSaved(true)
    setTimeout(() => setAttendanceSaved(false), 3000)
    if (navigator.onLine) await syncPendingData()
    refreshPending()
  }

  const handleGeoCheckIn = () => {
    setCheckInError(null)
    setCheckInStatus(null)
    if (!navigator.geolocation) {
      setCheckInError(t('checkin.errorGeoUnavailable'))
      return
    }
    if (!navigator.onLine) {
      setCheckInError(t('checkin.errorNeedsNetwork'))
      return
    }
    setCheckingIn(true)
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
          const res = await fetch(`${API_URL}/api/v1/attendance/check-in`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
            body: JSON.stringify({
              lat: pos.coords.latitude,
              lng: pos.coords.longitude,
              facility_id: facilityId,
            }),
          })
          if (!res.ok) throw new Error(t('checkin.errorFailed'))
          const data = await res.json()
          setCheckInStatus({ within: data.within_geofence, distance: Math.round(data.distance_m ?? 0) })
        } catch (e) {
          setCheckInError(e instanceof Error ? e.message : t('checkin.errorFailed'))
        } finally {
          setCheckingIn(false)
        }
      },
      (err) => {
        setCheckInError(err.message || t('checkin.errorNoLocation'))
        setCheckingIn(false)
      },
      { enableHighAccuracy: true, timeout: 10000 },
    )
  }

  const handleSync = async () => {
    if (!navigator.onLine) {
      setSyncMsg(t('sync.noInternet'))
      setTimeout(() => setSyncMsg(null), 3000)
      return
    }
    setSyncing(true)
    const result = await syncPendingData()
    setSyncing(false)
    setSyncMsg(
      t('sync.result', {
        synced: result.synced,
        errorsSuffix: result.errors > 0 ? `, ${result.errors} failed` : '',
      }),
    )
    setTimeout(() => setSyncMsg(null), 4000)
    refreshPending()
  }

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col w-full max-w-6xl mx-auto">
      <VoiceRecordingBanner show={isListening} label={t('voice.recording')} />
      {/* Header */}
      <div className="flex items-center justify-between px-4 pt-4">
        <h1 className="text-xl font-bold text-teal-600">{t('daily.title')}</h1>
        <div className="flex items-center gap-2">
          {pendingCount > 0 && (
            <span className="bg-orange-500 text-white text-xs font-bold px-2 py-0.5 rounded-full">
              {pendingCount} {t('daily.pending')}
            </span>
          )}
          <span className="text-sm text-gray-500">{format(new Date(), 'dd MMM yyyy')}</span>
        </div>
      </div>

      {/* All sections are visible at once, spread across the page in a grid
          instead of stacked in one narrow centered column — reduces total
          scroll on wide screens and keeps related actions spatially grouped. */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 p-4 pb-20 items-start">
      <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-5 space-y-4 lg:col-span-2 lg:row-start-1">
        <h2 className="text-base font-semibold text-gray-800">{t('patient.title')}</h2>
        <InfoNote>{t('info.patient')}</InfoNote>

        <div className="flex gap-3 items-center">
          <input
            type="number"
            min="0"
            value={patientCount}
            onChange={(e) => { setPatientCount(e.target.value); setFootfallError(null) }}
            placeholder="0"
            className="flex-1 text-3xl font-bold text-center border-2 border-gray-200 rounded-xl py-3 px-4 focus:outline-none focus:border-teal-500 transition-colors"
          />
          <button
            onPointerDown={startListening}
            onPointerUp={stopListening}
            className={clsx(
              'w-14 h-14 rounded-full flex items-center justify-center text-2xl shadow transition-all',
              isListening
                ? 'bg-red-500 text-white scale-110 animate-pulse'
                : 'bg-teal-600 text-white hover:bg-teal-700',
            )}
            title={isListening ? 'Listening…' : 'Hold to speak'}
            aria-label="Voice input"
          >
            {isListening ? '⏹' : '🎤'}
          </button>
        </div>

        {voiceError && <p className="text-sm text-red-500">{voiceError}</p>}
        {footfallError && <p className="text-sm text-red-500">{footfallError}</p>}
        {isListening && (
          <p className="text-sm text-blue-500 animate-pulse">{t('patient.listening')}</p>
        )}

        <button
          onClick={handleSaveFootfall}
          disabled={!patientCount}
          className="w-full py-3 rounded-xl bg-teal-600 text-white font-semibold disabled:opacity-40 hover:bg-teal-700 transition-colors"
        >
          {footfallSaved ? t('tests.saved') : t('patient.save')}
        </button>
      </section>

      {/* Rapid Footfall Tally */}
      <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-5 space-y-4 lg:col-start-1 lg:row-start-2">
        <h2 className="text-base font-semibold text-gray-800">{t('footfall.title')}</h2>
        <InfoNote>{t('info.footfall')}</InfoNote>
        {([
          ['general', t('footfall.general')],
          ['maternal', t('footfall.maternal')],
          ['emergency', t('footfall.emergency')],
        ] as const).map(([key, label]) => (
          <div key={key} className="flex items-center justify-between">
            <span className="text-sm font-medium text-gray-800">{label}</span>
            <div className="flex items-center gap-2">
              <button onClick={() => bump(key, -1)}
                className="w-9 h-9 rounded-lg bg-gray-100 text-gray-700 font-bold text-lg">−</button>
              <span className="w-10 text-center font-bold text-gray-900 text-lg">{tally[key]}</span>
              <button onClick={() => bump(key, 1)}
                className="w-9 h-9 rounded-lg bg-teal-100 text-teal-700 font-bold text-lg">+</button>
            </div>
          </div>
        ))}
        <button onClick={saveTally}
          className="w-full py-2.5 rounded-xl bg-teal-600 text-white font-semibold hover:bg-teal-700 transition-colors">
          {tallySaved ? t('footfall.saved') : `${t('footfall.save')} (${tally.general + tally.maternal + tally.emergency})`}
        </button>
      </section>

      {/* Geofenced Check-In Section — placed top-right on wide screens */}
      <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-5 space-y-4 lg:col-start-3 lg:row-start-1">
        <h2 className="text-base font-semibold text-gray-800">{t('checkin.title')}</h2>
        <p className="text-xs text-gray-500 -mt-2">{t('checkin.hint')}</p>
        <button
          onClick={handleGeoCheckIn}
          disabled={checkingIn}
          className="w-full py-3 rounded-xl bg-teal-600 text-white font-semibold disabled:opacity-40 hover:bg-teal-700 transition-colors"
        >
          {checkingIn ? t('checkin.locating') : `📍 ${t('checkin.btn')}`}
        </button>
        {checkInStatus && (
          <div
            className={clsx(
              'rounded-xl p-3 text-sm font-medium',
              checkInStatus.within
                ? 'bg-green-50 text-green-700 border border-green-200'
                : 'bg-red-50 text-red-700 border border-red-200',
            )}
          >
            {checkInStatus.within
              ? `✓ ${t('checkin.within', { distance: checkInStatus.distance })}`
              : `⚠ ${t('checkin.outside', { distance: checkInStatus.distance })}`}
          </div>
        )}
        {checkInError && <p className="text-sm text-red-500">{checkInError}</p>}
      </section>

      {/* Bed Matrix Section */}
      {beds.length > 0 && (
        <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-5 space-y-4 lg:col-start-2 lg:row-start-2">
          <h2 className="text-base font-semibold text-gray-800">{t('beds.title')}</h2>
          <InfoNote>{t('info.beds')}</InfoNote>
          {beds.map((b) => (
            <div key={b.bed_type} className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-800">{b.bed_type}</p>
                <p className="text-xs text-gray-400">{b.occupied_beds} / {b.total_beds} occupied</p>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => setOccupied(b.bed_type, -1)}
                  className="w-9 h-9 rounded-lg bg-gray-100 text-gray-700 font-bold text-lg disabled:opacity-30"
                  disabled={b.total_beds === 0}>−</button>
                <span className="w-8 text-center font-bold text-gray-900">{b.occupied_beds}</span>
                <button onClick={() => setOccupied(b.bed_type, 1)}
                  className="w-9 h-9 rounded-lg bg-gray-100 text-gray-700 font-bold text-lg disabled:opacity-30"
                  disabled={b.total_beds === 0}>+</button>
              </div>
            </div>
          ))}
          <button onClick={saveBeds}
            className="w-full py-2.5 rounded-xl bg-teal-600 text-white font-semibold hover:bg-teal-700 transition-colors">
            {bedsSaved ? t('beds.saved') : t('beds.save')}
          </button>
        </section>
      )}
      {beds.length === 0 && (
        <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-8 text-center lg:col-start-2 lg:row-start-2">
          <p className="text-gray-400 text-sm">{t('beds.title')}…</p>
        </section>
      )}

      {/* Doctor Attendance Section — after bed matrix, kept toward the right */}
      <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-5 space-y-4 lg:col-start-3 lg:row-start-2">
        <h2 className="text-base font-semibold text-gray-800">{t('attendance.title')}</h2>
        <InfoNote>{t('info.attendance')}</InfoNote>
        <div className="flex gap-3">
          <button
            onClick={() => handleToggleAttendance(true)}
            className={clsx(
              'flex-1 py-3 rounded-xl font-semibold text-sm transition-all',
              doctorPresent === true
                ? 'bg-green-600 text-white shadow-sm'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200',
            )}
          >
            {t('attendance.present')}
          </button>
          <button
            onClick={() => handleToggleAttendance(false)}
            className={clsx(
              'flex-1 py-3 rounded-xl font-semibold text-sm transition-all',
              doctorPresent === false
                ? 'bg-red-500 text-white shadow-sm'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200',
            )}
          >
            {t('attendance.absent')}
          </button>
        </div>
        {attendanceSaved && (
          <p className="text-sm text-green-600 font-medium">{t('attendance.saved')}</p>
        )}
      </section>

      {/* Test Availability Checklist */}
      {tests.length > 0 && (
        <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-5 space-y-3 lg:col-span-2 lg:row-start-3">
          <h2 className="text-base font-semibold text-gray-800">{t('tests.title')}</h2>
          <InfoNote>{t('info.tests')}</InfoNote>
          {tests.map((tst) => (
            <div key={tst.test_id} className="flex items-center justify-between">
              <span className="text-sm text-gray-800">{tst.test_name}</span>
              <button onClick={() => toggleTest(tst.test_id)}
                className={clsx('px-4 py-1.5 rounded-full text-xs font-bold transition-all',
                  tst.available ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700')}>
                {tst.available ? t('tests.available') : t('tests.unavailable')}
              </button>
            </div>
          ))}
          <button onClick={saveTests}
            className="w-full py-2.5 rounded-xl bg-teal-600 text-white font-semibold hover:bg-teal-700 transition-colors">
            {testsSaved ? t('tests.saved') : t('tests.save')}
          </button>
        </section>
      )}
      {tests.length === 0 && (
        <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-8 text-center lg:col-span-2 lg:row-start-3">
          <p className="text-gray-400 text-sm">{t('tests.title')}…</p>
        </section>
      )}

      {/* Sync Section */}
      <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-5 space-y-2 lg:col-start-3 lg:row-start-3">
        <InfoNote>{t('info.sync')}</InfoNote>
        <button
          onClick={handleSync}
          disabled={syncing || pendingCount === 0}
          className="w-full py-3 rounded-xl bg-blue-600 text-white font-semibold disabled:opacity-40 hover:bg-blue-700 transition-colors"
        >
          {syncing ? t('sync.syncing') : `${t('sync.now')}${pendingCount > 0 ? ` (${pendingCount})` : ''}`}
        </button>
        {syncMsg && <p className="text-sm text-gray-600 mt-2 text-center">{syncMsg}</p>}
      </section>
      </div>
    </div>
  )
}
