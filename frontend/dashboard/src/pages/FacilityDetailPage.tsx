import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getFacility, type StockItem } from '../api/facilities'
import type { Alert } from '../api/alerts'
import { formatDistanceToNow } from 'date-fns'

const SEVERITY_BADGE: Record<string, string> = {
  CRITICAL: 'bg-red-100 text-red-800',
  HIGH: 'bg-orange-100 text-orange-800',
  MEDIUM: 'bg-yellow-100 text-yellow-800',
  LOW: 'bg-blue-100 text-blue-800',
}

function HealthScoreGauge({ score }: { score: number }) {
  const color =
    score >= 70 ? 'text-green-700' : score >= 45 ? 'text-yellow-600' : 'text-red-700'
  const bgColor =
    score >= 70 ? 'bg-green-100' : score >= 45 ? 'bg-yellow-100' : 'bg-red-100'
  const barColor =
    score >= 70 ? 'bg-green-600' : score >= 45 ? 'bg-yellow-500' : 'bg-red-600'
  const label =
    score >= 70 ? 'Good' : score >= 45 ? 'At Risk' : 'Critical'

  return (
    <div className={`${bgColor} rounded-2xl p-6 text-center`}>
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Health Score</p>
      <p className={`text-6xl font-black ${color}`}>{score}</p>
      <p className={`text-sm font-semibold ${color} mt-1`}>{label}</p>
      <div className="mt-4 w-full bg-white rounded-full h-3">
        <div
          className={`${barColor} h-3 rounded-full transition-all`}
          style={{ width: `${score}%` }}
        />
      </div>
    </div>
  )
}

function StockStatusBadge({ item }: { item: StockItem }) {
  if (item.days_of_stock <= 7) {
    return <span className="bg-red-100 text-red-800 text-xs font-bold px-2 py-0.5 rounded-full">Critical ({item.days_of_stock}d)</span>
  }
  if (item.days_of_stock <= 14) {
    return <span className="bg-yellow-100 text-yellow-800 text-xs font-bold px-2 py-0.5 rounded-full">Low ({item.days_of_stock}d)</span>
  }
  return <span className="bg-green-100 text-green-800 text-xs font-bold px-2 py-0.5 rounded-full">OK ({item.days_of_stock}d)</span>
}

export default function FacilityDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  const { data: facility, isLoading, error } = useQuery({
    queryKey: ['facility', id],
    queryFn: () => getFacility(id!),
    enabled: !!id,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        Loading facility data...
      </div>
    )
  }

  if (error || !facility) {
    return (
      <div className="text-center py-16">
        <p className="text-red-600 font-medium">Failed to load facility.</p>
        <button onClick={() => navigate('/facilities')} className="mt-4 text-teal-600 underline text-sm">
          Back to Facilities
        </button>
      </div>
    )
  }

  const breakdown = facility.health_score_breakdown ?? {}

  return (
    <div className="space-y-6 max-w-5xl">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => navigate('/facilities')}
          className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
          Back
        </button>
        <div>
          <h1 className="text-xl font-bold text-gray-900">{facility.name}</h1>
          <p className="text-sm text-gray-500">{facility.code} &middot; {facility.facility_type}</p>
        </div>
      </div>

      {/* Top row: Score + Key stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <HealthScoreGauge score={facility.health_score} />

        <div className="sm:col-span-2 grid grid-cols-2 gap-4">
          {[
            { label: 'Bed Capacity', value: facility.bed_capacity ?? '—' },
            { label: 'Active Alerts', value: facility.active_alerts },
            { label: 'Facility Type', value: facility.facility_type },
            { label: 'Coordinates', value: `${facility.lat.toFixed(4)}, ${facility.lng.toFixed(4)}` },
          ].map((stat) => (
            <div key={stat.label} className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{stat.label}</p>
              <p className="text-lg font-bold text-gray-900 mt-1">{stat.value}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Score breakdown */}
      {Object.keys(breakdown).length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
          <h2 className="font-semibold text-gray-800 mb-4">Score Breakdown</h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            {Object.entries(breakdown).map(([key, val]) => (
              <div key={key} className="text-center">
                <p className="text-xs text-gray-500 capitalize">{key.replace(/_/g, ' ')}</p>
                <p className="text-2xl font-bold text-teal-700 mt-1">{val}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Stock table */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
        <h2 className="font-semibold text-gray-800 mb-3">Stock Summary</h2>
        {facility.stock_summary.length === 0 ? (
          <p className="text-gray-400 text-sm">No stock data available.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                  <th className="px-3 py-2">Medicine</th>
                  <th className="px-3 py-2">Current Stock</th>
                  <th className="px-3 py-2">Reorder Level</th>
                  <th className="px-3 py-2">Days of Stock</th>
                  <th className="px-3 py-2">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {facility.stock_summary.map((item: StockItem) => (
                  <tr key={item.medicine_id} className="hover:bg-gray-50">
                    <td className="px-3 py-2.5 font-medium text-gray-900">{item.medicine_name}</td>
                    <td className="px-3 py-2.5 text-gray-700">{item.total_stock.toLocaleString()}</td>
                    <td className="px-3 py-2.5 text-gray-500">{item.reorder_level.toLocaleString()}</td>
                    <td className="px-3 py-2.5">
                      <span className={`font-semibold ${
                        item.days_of_stock <= 7 ? 'text-red-700' :
                        item.days_of_stock <= 14 ? 'text-yellow-700' : 'text-green-700'
                      }`}>
                        {item.days_of_stock}
                      </span>
                    </td>
                    <td className="px-3 py-2.5">
                      <StockStatusBadge item={item} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Recent alerts */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
        <h2 className="font-semibold text-gray-800 mb-3">Recent Alerts</h2>
        {facility.recent_alerts.length === 0 ? (
          <p className="text-green-700 text-sm font-medium">No recent alerts for this facility.</p>
        ) : (
          <div className="space-y-2">
            {facility.recent_alerts.slice(0, 5).map((alert: Alert) => (
              <div key={alert.id} className="flex items-start gap-3 p-3 rounded-lg bg-gray-50 border border-gray-100">
                <span className={`mt-0.5 text-xs font-bold px-2 py-0.5 rounded-full whitespace-nowrap ${SEVERITY_BADGE[alert.severity] ?? 'bg-gray-100 text-gray-800'}`}>
                  {alert.severity}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900">{alert.title}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{alert.body}</p>
                </div>
                <div className="text-right shrink-0">
                  <span className={`text-xs font-medium ${
                    alert.status === 'PENDING' ? 'text-orange-600' :
                    alert.status === 'RESOLVED' ? 'text-green-600' : 'text-gray-500'
                  }`}>
                    {alert.status}
                  </span>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {formatDistanceToNow(new Date(alert.created_at), { addSuffix: true })}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
