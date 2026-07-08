import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { getRefills, getCapacity, downloadRefillsCsv } from '../api/planning'
import { getStates, getDistricts } from '../api/facilities'
import { useAuthStore } from '../stores/authStore'
import { formatNumber } from '../lib/format'

const selectClass =
  'border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white focus:ring-2 focus:ring-teal-500 focus:border-transparent outline-none min-w-40'

const URGENCY: Record<string, string> = {
  HIGH: 'bg-red-100 text-red-700',
  MEDIUM: 'bg-yellow-100 text-yellow-700',
  LOW: 'bg-gray-100 text-gray-600',
}

// Pre-emptive planning: which facilities will run short (seasonally adjusted)
// within the horizon, what to order and by when (downloadable for suppliers),
// plus longer-term beds/doctors gaps.
export default function PlanningPage() {
  const { t } = useTranslation()
  const { role, stateId: uState } = useAuthStore()
  const isNational = role === 'SUPERADMIN'
  const isState = role === 'STATE_ADMIN'
  const isScoped = !isNational && !isState  // district officer → auto-scoped

  const [stateId, setStateId] = useState<number | undefined>(isState ? uState ?? undefined : undefined)
  const [districtId, setDistrictId] = useState<number | undefined>(undefined)
  const [downloading, setDownloading] = useState(false)

  const scope = isScoped ? {} : { state_id: stateId, district_id: districtId }
  const ready = isScoped || stateId != null || districtId != null
  const scopeKey = [isScoped, stateId, districtId]

  const { data: states = [] } = useQuery({ queryKey: ['states'], queryFn: getStates, enabled: isNational })
  const { data: districts = [] } = useQuery({
    queryKey: ['districts', stateId], queryFn: () => getDistricts(stateId), enabled: !isScoped,
  })

  const { data: refills, isLoading } = useQuery({
    queryKey: ['planning-refills', ...scopeKey],
    queryFn: () => getRefills(scope), enabled: ready, refetchInterval: 300_000,
  })
  const { data: capacity = [] } = useQuery({
    queryKey: ['planning-capacity', ...scopeKey],
    queryFn: () => getCapacity(scope), enabled: ready,
  })

  const items = refills?.items ?? []
  const highCount = items.filter((i) => i.urgency === 'HIGH').length

  const onDownload = async () => {
    setDownloading(true)
    try { await downloadRefillsCsv(scope) } finally { setDownloading(false) }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-gray-900">{t('planning.title', 'Planning')}</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {t('planning.subtitle', 'Pre-emptive stock & capacity actionables — order before the shortage.')}
          </p>
        </div>
        <button
          onClick={onDownload}
          disabled={!ready || !items.length || downloading}
          className="bg-teal-600 text-white font-semibold px-4 py-2.5 rounded-lg hover:bg-teal-700 disabled:opacity-40 transition-colors text-sm"
        >
          {downloading ? t('planning.preparing', 'Preparing…') : t('planning.download_csv', '⬇ Download supplier CSV')}
        </button>
      </div>

      {/* Scope pickers (national picks state+district; state admin narrows by district) */}
      {!isScoped && (
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 flex flex-wrap gap-4">
          {isNational && (
            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1">{t('facilities.state')}</label>
              <select className={selectClass} value={stateId ?? ''}
                onChange={(e) => { setStateId(e.target.value ? Number(e.target.value) : undefined); setDistrictId(undefined) }}>
                <option value="">{t('facilities.all_states')}</option>
                {states.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
          )}
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">{t('facilities.district')}</label>
            <select className={selectClass} value={districtId ?? ''}
              onChange={(e) => setDistrictId(e.target.value ? Number(e.target.value) : undefined)}>
              <option value="">{t('facilities.all_districts')}</option>
              {districts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </div>
        </div>
      )}

      {!ready ? (
        <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400 text-sm">
          {t('planning.select_scope', 'Select a state or district to generate the plan.')}
        </div>
      ) : (
        <>
          {/* Refills — the pre-emptive order list */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold text-gray-800">
                {t('planning.refills_title', 'Stock refills needed')}
                {refills && (
                  <span className="ml-2 text-xs font-normal text-gray-400">
                    {t('planning.horizon_note', { defaultValue: 'next {{d}} days', d: refills.horizon_days })}
                    {highCount > 0 && ` · ${highCount} ${t('planning.urgent', 'urgent')}`}
                  </span>
                )}
              </h2>
            </div>
            {isLoading ? (
              <p className="text-gray-400 text-sm p-4">{t('facilities.loading')}</p>
            ) : items.length === 0 ? (
              <p className="text-gray-400 text-sm p-4">{t('planning.no_refills', 'No refills projected in this window — all facilities are covered.')}</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 border-b border-gray-200">
                    <tr className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                      <th className="px-3 py-2">{t('planning.col_facility', 'Facility')}</th>
                      <th className="px-3 py-2">{t('planning.col_item', 'Item')}</th>
                      <th className="px-3 py-2 text-right">{t('planning.col_current', 'In stock')}</th>
                      <th className="px-3 py-2 text-right">{t('planning.col_order', 'Order qty')}</th>
                      <th className="px-3 py-2">{t('planning.col_deliver', 'Deliver by')}</th>
                      <th className="px-3 py-2">{t('planning.col_urgency', 'Urgency')}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {items.map((i, idx) => (
                      <tr key={`${i.facility_id}-${i.item}-${idx}`} className="hover:bg-gray-50">
                        <td className="px-3 py-2">
                          <span className="font-medium text-gray-900">{i.facility}</span>
                          <span className="block text-xs text-gray-400 truncate max-w-56" title={i.address}>{i.address || i.district}</span>
                        </td>
                        <td className="px-3 py-2 text-gray-700">{i.item} <span className="text-xs text-gray-400">{i.category}</span></td>
                        <td className="px-3 py-2 text-right text-gray-600">{formatNumber(i.current_stock)} {i.unit}</td>
                        <td className="px-3 py-2 text-right font-semibold text-gray-900">{formatNumber(i.order_qty)}</td>
                        <td className="px-3 py-2 text-gray-700">{i.deliver_by}</td>
                        <td className="px-3 py-2"><span className={`text-xs font-bold px-2 py-0.5 rounded-full ${URGENCY[i.urgency]}`}>{i.urgency}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Long-term capacity concerns */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 space-y-3">
            <h2 className="font-semibold text-gray-800">
              {t('planning.capacity_title', 'Longer-term capacity concerns')}
              <span className="ml-2 text-xs font-normal text-gray-400">{t('planning.capacity_note', 'beds & doctors')}</span>
            </h2>
            {capacity.length === 0 ? (
              <p className="text-gray-400 text-sm p-2">{t('planning.no_capacity', 'No structural bed/doctor gaps flagged.')}</p>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {capacity.map((c) => (
                  <div key={`${c.facility_id}-${c.concern}`} className="border border-gray-200 rounded-xl p-3">
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-gray-900">{c.facility}</span>
                      <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${c.concern === 'BEDS' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'}`}>
                        {c.concern === 'BEDS' ? t('planning.beds', '🛏 Beds') : t('planning.doctors', '🩺 Doctors')}
                      </span>
                    </div>
                    <p className="text-sm text-gray-600 mt-1">{c.detail}</p>
                    <p className="text-xs text-gray-400 mt-0.5">{c.metric} · {c.address || c.district}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
