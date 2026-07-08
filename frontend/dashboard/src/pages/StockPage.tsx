import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  getFacilityStock, getFacilityTests, getFacilityBeds, getAttendanceHistory,
} from '../api/resources'
import { browseFacilities, getStates, getDistricts } from '../api/facilities'
import { formatNumber } from '../lib/format'
import { useAuthStore } from '../stores/authStore'

const selectClass =
  'border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white focus:ring-2 focus:ring-teal-500 focus:border-transparent outline-none min-w-40'

const STATUS_STYLE: Record<string, string> = {
  OK: 'bg-green-100 text-green-700',
  WATCH: 'bg-yellow-100 text-yellow-700',
  LOW: 'bg-red-100 text-red-700',
}

// Admin resource view: surfaces field-entered data (medicine stock, test
// availability, bed occupancy, doctor attendance) per facility.
export default function StockPage() {
  const { t } = useTranslation()
  const { role, stateId: uState, districtId: uDistrict } = useAuthStore()
  const isNational = role === 'SUPERADMIN'

  const [stateId, setStateId] = useState<number | undefined>(isNational ? undefined : uState ?? undefined)
  const [districtId, setDistrictId] = useState<number | undefined>(isNational ? undefined : uDistrict ?? undefined)
  const [facilityId, setFacilityId] = useState<string>('')
  const [search, setSearch] = useState('')
  const [lowOnly, setLowOnly] = useState(false)
  const [category, setCategory] = useState('ALL')

  const { data: states = [] } = useQuery({ queryKey: ['states'], queryFn: getStates })
  const { data: districts = [] } = useQuery({ queryKey: ['districts', stateId], queryFn: () => getDistricts(stateId) })
  const { data: facList } = useQuery({
    queryKey: ['stock-fac', stateId, districtId],
    queryFn: () => browseFacilities({ state_id: stateId, district_id: districtId, page_size: 500 }),
    enabled: stateId != null || districtId != null || !isNational,
  })
  const facilities = facList?.items ?? []

  // Auto-pick the first facility in scope when the list changes.
  useEffect(() => {
    if (facilities.length && !facilities.some((f) => f.id === facilityId)) {
      setFacilityId(facilities[0].id)
    }
  }, [facilities, facilityId])

  const enabled = !!facilityId
  const { data: stock = [], isLoading: stockLoading } = useQuery({
    queryKey: ['fac-stock', facilityId], queryFn: () => getFacilityStock(facilityId), enabled,
  })
  const { data: tests = [] } = useQuery({ queryKey: ['fac-tests', facilityId], queryFn: () => getFacilityTests(facilityId), enabled })
  const { data: beds = [] } = useQuery({ queryKey: ['fac-beds', facilityId], queryFn: () => getFacilityBeds(facilityId), enabled })
  const { data: attendance = [] } = useQuery({ queryKey: ['fac-att', facilityId], queryFn: () => getAttendanceHistory(facilityId, 14), enabled })

  const categories = useMemo(
    () => ['ALL', ...Array.from(new Set(stock.map((s) => s.category))).sort()],
    [stock],
  )
  const rows = stock.filter((s) =>
    (category === 'ALL' || s.category === category) &&
    (!lowOnly || s.status === 'LOW') &&
    s.name.toLowerCase().includes(search.trim().toLowerCase()),
  )
  const lowCount = stock.filter((s) => s.status === 'LOW').length
  const testsAvail = tests.filter((x) => x.available).length

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-900">{t('stockview.title')}</h1>
        <span className="text-sm text-gray-500">{t('stockview.subtitle')}</span>
      </div>

      {/* Facility picker */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 flex flex-wrap gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">{t('facilities.state')}</label>
          <select className={selectClass} value={stateId ?? ''} onChange={(e) => { setStateId(e.target.value ? Number(e.target.value) : undefined); setDistrictId(undefined); setFacilityId('') }}>
            <option value="">{t('facilities.all_states')}</option>
            {states.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">{t('facilities.district')}</label>
          <select className={selectClass} value={districtId ?? ''} onChange={(e) => { setDistrictId(e.target.value ? Number(e.target.value) : undefined); setFacilityId('') }}>
            <option value="">{t('facilities.all_districts')}</option>
            {districts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </div>
        <div className="flex-1 min-w-56">
          <label className="block text-xs font-medium text-gray-500 mb-1">{t('stockview.facility')}</label>
          <select className={`${selectClass} w-full`} value={facilityId} onChange={(e) => setFacilityId(e.target.value)}>
            {facilities.length === 0 && <option value="">{t('stockview.pick_scope')}</option>}
            {facilities.map((f) => <option key={f.id} value={f.id}>{f.name} · {f.facility_type} · {f.district_name}</option>)}
          </select>
        </div>
      </div>

      {!facilityId ? (
        <div className="bg-white rounded-xl border border-gray-200 p-8 text-center text-gray-400">{t('stockview.pick_scope')}</div>
      ) : (
      <>
        {/* KPI strip */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Kpi label={t('stockview.total_items')} value={formatNumber(stock.length)} />
          <Kpi label={t('stockview.low_items')} value={formatNumber(lowCount)} tone={lowCount ? 'red' : 'green'} />
          <Kpi label={t('stockview.tests_available')} value={`${testsAvail}/${tests.length}`} />
          <Kpi label={t('stockview.beds_occupied')} value={beds.reduce((a, b) => a + b.occupied_beds, 0) + '/' + beds.reduce((a, b) => a + b.total_beds, 0)} />
        </div>

        {/* Medicine stock table */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4 space-y-3">
          <h2 className="font-semibold text-gray-800">{t('stockview.medicine_stock')}</h2>
          <div className="flex flex-wrap gap-3 items-center">
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t('stockview.search')}
              className="border border-gray-300 rounded-lg px-3 py-2 text-sm flex-1 min-w-48 focus:ring-2 focus:ring-teal-500 outline-none" />
            <select className={selectClass} value={category} onChange={(e) => setCategory(e.target.value)}>
              {categories.map((c) => <option key={c} value={c}>{c === 'ALL' ? t('status.all') : c}</option>)}
            </select>
            <label className="flex items-center gap-1.5 text-sm text-gray-600">
              <input type="checkbox" checked={lowOnly} onChange={(e) => setLowOnly(e.target.checked)} /> {t('stockview.low_only')}
            </label>
          </div>
          {stockLoading ? (
            <p className="text-gray-400 text-sm p-4">{t('facilities.loading')}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                    <th className="px-3 py-2">{t('stockview.col_medicine')}</th>
                    <th className="px-3 py-2">{t('stockview.col_category')}</th>
                    <th className="px-3 py-2 text-right">{t('stockview.col_stock')}</th>
                    <th className="px-3 py-2 text-right">{t('stockview.col_reorder')}</th>
                    <th className="px-3 py-2">{t('stockview.col_status')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {rows.map((r) => (
                    <tr key={r.medicine_id} className="hover:bg-gray-50">
                      <td className="px-3 py-2 font-medium text-gray-900">{r.name}</td>
                      <td className="px-3 py-2 text-gray-500">{r.category}</td>
                      <td className="px-3 py-2 text-right font-semibold text-gray-800">{formatNumber(r.current_stock)} <span className="text-xs text-gray-400">{r.unit}</span></td>
                      <td className="px-3 py-2 text-right text-gray-500">{formatNumber(r.reorder_level)}</td>
                      <td className="px-3 py-2"><span className={`text-xs font-bold px-2 py-0.5 rounded-full ${STATUS_STYLE[r.status]}`}>{t(`stockview.status_${r.status.toLowerCase()}`)}</span></td>
                    </tr>
                  ))}
                  {rows.length === 0 && <tr><td colSpan={5} className="px-3 py-6 text-center text-gray-400">{t('facilities.empty')}</td></tr>}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Test availability */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
            <h2 className="font-semibold text-gray-800 mb-3">{t('stockview.test_availability')}</h2>
            <div className="flex flex-wrap gap-2">
              {tests.map((x) => (
                <span key={x.test_id} className={`text-xs font-semibold px-2.5 py-1 rounded-full ${x.available ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                  {x.test_name} {x.available ? '✓' : '✕'}
                </span>
              ))}
              {tests.length === 0 && <p className="text-gray-400 text-sm">—</p>}
            </div>
            <h3 className="font-semibold text-gray-700 text-sm mt-4 mb-2">{t('stockview.bed_matrix')}</h3>
            <div className="space-y-1">
              {beds.map((b) => (
                <div key={b.bed_type} className="flex justify-between text-sm">
                  <span className="text-gray-600">{b.bed_type}</span>
                  <span className="font-medium text-gray-800">{b.occupied_beds}/{b.total_beds}</span>
                </div>
              ))}
              {beds.length === 0 && <p className="text-gray-400 text-sm">—</p>}
            </div>
          </div>

          {/* Doctor availability (date-wise) */}
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
            <h2 className="font-semibold text-gray-800 mb-3">{t('stockview.doctor_availability')}</h2>
            {attendance.length === 0 ? (
              <p className="text-gray-400 text-sm">{t('stockview.no_attendance')}</p>
            ) : (
              <div className="space-y-1.5">
                {attendance.map((d) => (
                  <div key={d.date} className="flex items-center justify-between text-sm">
                    <span className="text-gray-600">{new Date(d.date).toLocaleDateString()}</span>
                    <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${d.present > 0 ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                      {d.present > 0 ? t('stockview.present') : t('stockview.absent')} ({d.present}/{d.total})
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </>
      )}
    </div>
  )
}

function Kpi({ label, value, tone }: { label: string; value: string; tone?: 'red' | 'green' }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
      <p className="text-xs text-gray-500">{label}</p>
      <p className={`text-2xl font-bold ${tone === 'red' ? 'text-red-600' : tone === 'green' ? 'text-green-600' : 'text-gray-900'}`}>{value}</p>
    </div>
  )
}
