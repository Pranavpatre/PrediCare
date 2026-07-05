import { useEffect, useState, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { format } from 'date-fns'
import { db } from '../db/localDb'

interface LogEntry {
  id: string
  icon: string
  description: string
  recordedAt: string
  synced: boolean
}

export default function LogsPage() {
  const { t } = useTranslation()
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedDate, setSelectedDate] = useState('all')

  const load = useCallback(async () => {
    try {
      const [footfallRows, attendanceRows, ledgerRows, stockRows, medicines] = await Promise.all([
        db.pendingFootfall.toArray(),
        db.pendingAttendance.toArray(),
        db.pendingLedger.toArray(),
        db.pendingStockUpdates.toArray(),
        db.medicines.toArray(),
      ])
      const medMap = new Map(medicines.map((m) => [m.id, m.name]))
      const rows: LogEntry[] = []

      footfallRows.forEach((r) => rows.push({
        id: `footfall-${r.id}`,
        icon: '🧑‍⚕️',
        description: t('logs.patientCount', { count: r.footfall_count }),
        recordedAt: r.recorded_at,
        synced: r.synced,
      }))

      attendanceRows.forEach((r) => rows.push({
        id: `attendance-${r.id}`,
        icon: '👨‍⚕️',
        description: t('logs.attendance', {
          status: r.present ? t('attendance.present') : t('attendance.absent'),
        }),
        recordedAt: r.recorded_at,
        synced: r.synced,
      }))

      ledgerRows.forEach((r) => {
        let description = ''
        let icon = '📋'
        if (r.kind === 'footfall') {
          const p = r.payload as { general: number; maternal: number; emergency: number }
          description = t('logs.footfallTally', {
            general: p.general, maternal: p.maternal, emergency: p.emergency,
          })
          icon = '🧍'
        } else if (r.kind === 'beds') {
          description = t('logs.bedsUpdated')
          icon = '🛏️'
        } else if (r.kind === 'tests') {
          description = t('logs.testsUpdated')
          icon = '🧪'
        }
        rows.push({ id: `ledger-${r.id}`, icon, description, recordedAt: r.recorded_at, synced: r.synced })
      })

      stockRows.forEach((r) => {
        const medName = medMap.get(r.medicine_id) || `#${r.medicine_id}`
        const change = r.quantity_change > 0 ? `+${r.quantity_change}` : String(r.quantity_change)
        rows.push({
          id: `stock-${r.id}`,
          icon: '💊',
          description: t('logs.stockUpdate', { medicine: medName, change }),
          recordedAt: r.recorded_at,
          synced: r.synced,
        })
      })

      rows.sort((a, b) => new Date(b.recordedAt).getTime() - new Date(a.recordedAt).getTime())
      setEntries(rows)
    } catch (err) {
      console.error('[logs] failed to load:', err)
      setEntries([])
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => { load() }, [load])

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-gray-400 text-sm">…</p>
      </div>
    )
  }

  const dates = Array.from(new Set(entries.map((e) => format(new Date(e.recordedAt), 'yyyy-MM-dd')))).sort().reverse()
  const filteredEntries = selectedDate === 'all'
    ? entries
    : entries.filter((e) => format(new Date(e.recordedAt), 'yyyy-MM-dd') === selectedDate)

  return (
    <div className="min-h-screen bg-gray-50 max-w-lg mx-auto pb-4">
      <div className="sticky top-0 bg-white border-b border-gray-100 px-4 py-3 z-10 flex items-center justify-between gap-2">
        <h1 className="text-xl font-bold text-teal-600">{t('logs.title')}</h1>
        {dates.length > 0 && (
          <select
            value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)}
            aria-label={t('logs.filterByDate')}
            className="text-xs font-semibold px-2.5 py-1.5 rounded-md border border-gray-200 bg-gray-50 text-gray-700 focus:outline-none focus:border-teal-500"
          >
            <option value="all">{t('logs.allDates')}</option>
            {dates.map((d) => (
              <option key={d} value={d}>{format(new Date(d), 'dd MMM yyyy')}</option>
            ))}
          </select>
        )}
      </div>

      <div className="p-4 space-y-3">
        {entries.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 space-y-3">
            <span className="text-5xl" aria-hidden>📜</span>
            <p className="text-gray-400 text-sm font-medium">{t('logs.empty')}</p>
            <p className="text-gray-300 text-xs text-center">{t('logs.emptyHint')}</p>
          </div>
        ) : filteredEntries.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 space-y-3">
            <span className="text-5xl" aria-hidden>📜</span>
            <p className="text-gray-400 text-sm font-medium">{t('logs.emptyForDate')}</p>
          </div>
        ) : (
          filteredEntries.map((e) => (
            <div key={e.id} className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-start gap-2">
                  <span className="text-lg" aria-hidden>{e.icon}</span>
                  <div>
                    <p className="text-sm font-medium text-gray-800">{e.description}</p>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {format(new Date(e.recordedAt), 'dd MMM yyyy, HH:mm')}
                    </p>
                  </div>
                </div>
                <span
                  className={`text-xs font-bold px-2 py-0.5 rounded-full shrink-0 ${
                    e.synced ? 'bg-green-100 text-green-700' : 'bg-orange-100 text-orange-700'
                  }`}
                >
                  {e.synced ? t('logs.synced') : t('logs.pending')}
                </span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
