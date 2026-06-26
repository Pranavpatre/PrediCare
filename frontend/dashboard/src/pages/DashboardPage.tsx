import { useQuery } from '@tanstack/react-query'
import { getFacilities } from '../api/facilities'
import { getAlerts } from '../api/alerts'
import FacilityMap from '../components/FacilityMap'
import AlertCard from '../components/AlertCard'
import { useAlertWebSocket } from '../hooks/useWebSocket'
import { useTranslation } from 'react-i18next'

export default function DashboardPage() {
  const { t } = useTranslation()
  useAlertWebSocket()

  const { data: facilities = [], isLoading: facilitiesLoading } = useQuery({
    queryKey: ['facilities'],
    queryFn: getFacilities,
    refetchInterval: 60_000,
  })

  const { data: alertsData, isLoading: alertsLoading } = useQuery({
    queryKey: ['alerts', 'PENDING'],
    queryFn: () => getAlerts({ status: 'PENDING' }),
    refetchInterval: 30_000,
  })

  const alerts = alertsData?.items ?? []
  const criticalCount = alerts.filter((a) => a.severity === 'CRITICAL').length
  const avgScore = facilities.length
    ? Math.round(facilities.reduce((s, f) => s + f.health_score, 0) / facilities.length)
    : 0

  const scoreColor = (score: number) =>
    score >= 70 ? 'text-green-700' : score >= 45 ? 'text-yellow-700' : 'text-red-700'

  return (
    <div className="space-y-6">
      {/* KPI strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          {
            label: t('kpi.active_alerts'),
            value: alerts.length,
            color: alerts.length > 0 ? 'text-red-700' : 'text-green-700',
          },
          {
            label: t('kpi.critical'),
            value: criticalCount,
            color: criticalCount > 0 ? 'text-red-700' : 'text-gray-700',
          },
          {
            label: t('kpi.avg_score'),
            value: `${avgScore}/100`,
            color: scoreColor(avgScore),
          },
          {
            label: t('kpi.facilities'),
            value: facilities.length,
            color: 'text-teal-700',
          },
        ].map((kpi) => (
          <div key={kpi.label} className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{kpi.label}</p>
            <p className={`text-2xl font-bold mt-1 ${kpi.color}`}>{kpi.value}</p>
          </div>
        ))}
      </div>

      {/* Map + Alert feed */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-white rounded-xl border border-gray-200 shadow-sm p-4">
          <h2 className="font-semibold text-gray-800 mb-3">{t('dashboard.district_map')}</h2>
          {facilitiesLoading ? (
            <div className="h-96 flex items-center justify-center text-gray-400">Loading map...</div>
          ) : (
            <FacilityMap facilities={facilities} />
          )}
          <div className="flex gap-4 mt-3 text-xs text-gray-500">
            <span className="flex items-center gap-1">
              <span className="w-3 h-3 rounded-full inline-block bg-green-700"></span> Good (&gt;70)
            </span>
            <span className="flex items-center gap-1">
              <span className="w-3 h-3 rounded-full inline-block bg-yellow-700"></span> At Risk (45–70)
            </span>
            <span className="flex items-center gap-1">
              <span className="w-3 h-3 rounded-full inline-block bg-red-700"></span> Critical (&lt;45)
            </span>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 overflow-y-auto max-h-[520px]">
          <h2 className="font-semibold text-gray-800 mb-3 flex items-center gap-2">
            {t('dashboard.alert_feed')}
            {alerts.length > 0 && (
              <span className="bg-red-100 text-red-800 text-xs font-bold px-2 py-0.5 rounded-full">
                {alerts.length}
              </span>
            )}
          </h2>
          {alertsLoading && <p className="text-gray-400 text-sm">Loading alerts...</p>}
          {!alertsLoading && alerts.length === 0 && (
            <p className="text-green-700 text-sm font-medium">No pending alerts</p>
          )}
          {alerts
            .slice()
            .sort((a, b) => {
              const order: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 }
              return (order[a.severity] ?? 4) - (order[b.severity] ?? 4)
            })
            .map((alert) => (
              <AlertCard key={alert.id} alert={alert} />
            ))}
        </div>
      </div>

      {/* Bottom-5 facilities */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
        <h2 className="font-semibold text-gray-800 mb-3">{t('dashboard.bottom_facilities')}</h2>
        {facilitiesLoading ? (
          <p className="text-gray-400 text-sm">Loading...</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide border-b border-gray-100">
                  <th className="pb-2 pr-4">Facility</th>
                  <th className="pb-2 pr-4">Type</th>
                  <th className="pb-2 pr-4">Score</th>
                  <th className="pb-2 pr-4">Status</th>
                  <th className="pb-2">Alerts</th>
                </tr>
              </thead>
              <tbody>
                {[...facilities]
                  .sort((a, b) => a.health_score - b.health_score)
                  .slice(0, 5)
                  .map((f) => (
                    <tr key={f.id} className="border-b border-gray-50 last:border-0 hover:bg-gray-50 transition-colors">
                      <td className="py-2.5 pr-4 font-medium text-gray-900">{f.name}</td>
                      <td className="py-2.5 pr-4 text-gray-500">{f.facility_type}</td>
                      <td className="py-2.5 pr-4">
                        <span className={`font-bold ${scoreColor(f.health_score)}`}>
                          {f.health_score}
                        </span>
                        <span className="text-gray-400 text-xs">/100</span>
                      </td>
                      <td className="py-2.5 pr-4 text-lg">
                        {f.traffic_light === 'GREEN' ? (
                          <span title="Good">&#128994;</span>
                        ) : f.traffic_light === 'YELLOW' ? (
                          <span title="At Risk">&#128993;</span>
                        ) : (
                          <span title="Critical">&#128308;</span>
                        )}
                      </td>
                      <td className="py-2.5">
                        {f.active_alerts > 0 ? (
                          <span className="bg-red-100 text-red-800 text-xs font-bold px-2 py-0.5 rounded-full">
                            {f.active_alerts}
                        </span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
