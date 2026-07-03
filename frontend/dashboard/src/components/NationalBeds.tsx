import { useQuery } from '@tanstack/react-query'
import { getStateInfrastructure, getNationalSummary } from '../api/overview'

const fmt = (n: number | null) => (n == null ? '—' : n.toLocaleString('en-IN'))

export default function NationalBeds() {
  const { data: states = [], isLoading } = useQuery({
    queryKey: ['state-infrastructure'],
    queryFn: getStateInfrastructure,
  })
  const { data: summary } = useQuery({
    queryKey: ['national-summary'],
    queryFn: getNationalSummary,
  })

  if (isLoading) {
    return <div className="text-gray-400 text-sm p-4">Loading national bed infrastructure…</div>
  }
  if (states.length === 0) return null

  const tiles = summary
    ? [
        { label: 'PHC beds', value: summary.phc_beds },
        { label: 'CHC beds', value: summary.chc_beds },
        { label: 'Sub-district/SDH', value: summary.sub_district_beds },
        { label: 'District hospital', value: summary.district_hospital_beds },
        { label: 'Medical college', value: summary.medical_college_beds },
        { label: 'Total beds', value: summary.total_beds },
      ]
    : []

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="font-semibold text-gray-800">State/UT Bed Infrastructure</h2>
        <span className="text-xs text-gray-400">
          Real data · data.gov.in{summary?.as_on_date ? ` · as on ${summary.as_on_date}` : ''}
        </span>
      </div>

      {/* National summary tiles */}
      {tiles.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-4">
          {tiles.map((t) => (
            <div key={t.label} className="bg-teal-50 border border-teal-100 rounded-lg p-3 text-center">
              <p className="text-[11px] font-medium text-teal-700 uppercase tracking-wide">{t.label}</p>
              <p className="text-lg font-bold text-teal-900 mt-0.5">{fmt(t.value)}</p>
            </div>
          ))}
        </div>
      )}

      {/* Per-state table (sorted by total beds desc, from the API) */}
      <div className="overflow-x-auto max-h-[360px] overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200 sticky top-0">
            <tr className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
              <th className="px-3 py-2">State / UT</th>
              <th className="px-3 py-2 text-right">PHC</th>
              <th className="px-3 py-2 text-right">CHC</th>
              <th className="px-3 py-2 text-right">SDH</th>
              <th className="px-3 py-2 text-right">DH</th>
              <th className="px-3 py-2 text-right">Med. College</th>
              <th className="px-3 py-2 text-right font-bold">Total</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {states.map((s) => (
              <tr key={s.state_ut} className="hover:bg-gray-50">
                <td className="px-3 py-2 font-medium text-gray-900">{s.state_ut}</td>
                <td className="px-3 py-2 text-right text-gray-600">{fmt(s.phc_beds)}</td>
                <td className="px-3 py-2 text-right text-gray-600">{fmt(s.chc_beds)}</td>
                <td className="px-3 py-2 text-right text-gray-600">{fmt(s.sub_district_beds)}</td>
                <td className="px-3 py-2 text-right text-gray-600">{fmt(s.district_hospital_beds)}</td>
                <td className="px-3 py-2 text-right text-gray-600">{fmt(s.medical_college_beds)}</td>
                <td className="px-3 py-2 text-right font-bold text-gray-900">{fmt(s.total_beds)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
