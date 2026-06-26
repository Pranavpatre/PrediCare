import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  getPlans,
  approvePlan,
  deferPlan,
  createPlan,
  type RedistributionPlan,
  type LineItem,
} from '../api/redistribution'
import { formatDistanceToNow } from 'date-fns'
import clsx from 'clsx'

const STATUS_BADGE: Record<string, string> = {
  PENDING: 'bg-yellow-100 text-yellow-800',
  APPROVED: 'bg-green-100 text-green-800',
  DEFERRED: 'bg-gray-100 text-gray-600',
}

const URGENCY_COLOR: Record<string, string> = {
  HIGH: 'text-red-700 font-semibold',
  MEDIUM: 'text-yellow-700',
  LOW: 'text-gray-600',
}

function DeferModal({
  onConfirm,
  onCancel,
  isPending,
}: {
  onConfirm: (reason: string) => void
  onCancel: () => void
  isPending: boolean
}) {
  const [reason, setReason] = useState('')
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-sm">
        <h3 className="text-lg font-bold text-gray-900 mb-2">Defer Plan</h3>
        <p className="text-sm text-gray-500 mb-4">Please provide a reason for deferring this redistribution plan.</p>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. Logistics unavailable this week..."
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm resize-none h-24 focus:ring-2 focus:ring-teal-500 focus:border-transparent outline-none"
        />
        <div className="flex gap-3 mt-4">
          <button
            onClick={onCancel}
            className="flex-1 py-2 rounded-lg border border-gray-300 text-sm font-medium text-gray-600 hover:bg-gray-50 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => onConfirm(reason || 'Deferred from dashboard')}
            disabled={isPending}
            className="flex-1 py-2 rounded-lg bg-yellow-500 text-white text-sm font-semibold hover:bg-yellow-600 disabled:opacity-50 transition-colors"
          >
            {isPending ? 'Deferring...' : 'Defer Plan'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function RedistributionPage() {
  const qc = useQueryClient()
  const [selectedPlan, setSelectedPlan] = useState<RedistributionPlan | null>(null)
  const [deferTarget, setDeferTarget] = useState<string | null>(null)

  const { data: plans = [], isLoading } = useQuery({
    queryKey: ['redistribution-plans'],
    queryFn: getPlans,
    refetchInterval: 60_000,
  })

  const createMutation = useMutation({
    mutationFn: createPlan,
    onSuccess: (newPlan) => {
      qc.invalidateQueries({ queryKey: ['redistribution-plans'] })
      setSelectedPlan(newPlan)
    },
  })

  const approveMutation = useMutation({
    mutationFn: approvePlan,
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ['redistribution-plans'] })
      qc.invalidateQueries({ queryKey: ['facilities'] })
      if (selectedPlan?.id === updated.id) setSelectedPlan(updated)
    },
  })

  const deferMutation = useMutation({
    mutationFn: ({ planId, reason }: { planId: string; reason: string }) => deferPlan(planId, reason),
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ['redistribution-plans'] })
      if (selectedPlan?.id === updated.id) setSelectedPlan(updated)
      setDeferTarget(null)
    },
  })

  const formatCurrency = (inr: number) =>
    new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(inr)

  // Keep selected plan in sync with latest data
  const activePlan = selectedPlan
    ? plans.find((p) => p.id === selectedPlan.id) ?? selectedPlan
    : null

  return (
    <div className="space-y-6">
      {deferTarget && (
        <DeferModal
          isPending={deferMutation.isPending}
          onConfirm={(reason) => deferMutation.mutate({ planId: deferTarget, reason })}
          onCancel={() => setDeferTarget(null)}
        />
      )}

      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Medicine Redistribution</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            AI-generated transfer plans to balance stock across facilities
          </p>
        </div>
        <button
          onClick={() => createMutation.mutate()}
          disabled={createMutation.isPending}
          className="bg-teal-600 text-white font-semibold px-4 py-2.5 rounded-lg hover:bg-teal-700 disabled:opacity-50 transition-colors text-sm flex items-center gap-2"
        >
          {createMutation.isPending ? (
            <>
              <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
              </svg>
              Generating...
            </>
          ) : (
            'Run New Plan'
          )}
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Plans list */}
        <div className="lg:col-span-2 space-y-3">
          <h2 className="text-sm font-semibold text-gray-600 uppercase tracking-wide">Plans</h2>
          {isLoading && <p className="text-gray-400 text-sm">Loading plans...</p>}
          {!isLoading && plans.length === 0 && (
            <div className="bg-white rounded-xl border border-gray-200 p-6 text-center text-gray-400 text-sm">
              No plans yet. Click &ldquo;Run New Plan&rdquo; to generate one.
            </div>
          )}
          {plans.map((plan: RedistributionPlan) => (
            <div
              key={plan.id}
              onClick={() => setSelectedPlan(plan)}
              className={clsx(
                'bg-white rounded-xl border shadow-sm p-4 cursor-pointer transition-all',
                activePlan?.id === plan.id
                  ? 'border-teal-500 ring-2 ring-teal-200'
                  : 'border-gray-200 hover:border-gray-300',
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <span className={clsx('text-xs font-bold px-2 py-0.5 rounded-full', STATUS_BADGE[plan.status])}>
                    {plan.status}
                  </span>
                  <p className="text-sm font-semibold text-gray-900 mt-1.5">
                    {plan.total_items} transfer{plan.total_items !== 1 ? 's' : ''}
                  </p>
                  <p className="text-xs text-green-700 font-medium mt-0.5">
                    Saves {formatCurrency(plan.estimated_saving_inr)}
                  </p>
                </div>
                <p className="text-xs text-gray-400 shrink-0">
                  {formatDistanceToNow(new Date(plan.created_at), { addSuffix: true })}
                </p>
              </div>

              {plan.status === 'PENDING' && (
                <div className="flex gap-2 mt-3" onClick={(e) => e.stopPropagation()}>
                  <button
                    onClick={() => approveMutation.mutate(plan.id)}
                    disabled={approveMutation.isPending && approveMutation.variables === plan.id}
                    className="flex-1 bg-teal-600 text-white text-xs font-semibold py-1.5 px-3 rounded-md hover:bg-teal-700 disabled:opacity-50 transition-colors"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => setDeferTarget(plan.id)}
                    className="flex-1 bg-white text-gray-700 text-xs font-semibold py-1.5 px-3 rounded-md border border-gray-300 hover:bg-gray-50 transition-colors"
                  >
                    Defer
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Plan detail */}
        <div className="lg:col-span-3">
          {!activePlan ? (
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-8 text-center text-gray-400">
              <svg className="w-12 h-12 mx-auto mb-3 text-gray-200" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              <p className="text-sm">Select a plan to view its line items</p>
            </div>
          ) : (
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="font-semibold text-gray-900">
                    Plan Details
                    <span className={clsx('ml-2 text-xs font-bold px-2 py-0.5 rounded-full', STATUS_BADGE[activePlan.status])}>
                      {activePlan.status}
                    </span>
                  </h2>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {activePlan.total_items} transfers &middot; Total savings: {formatCurrency(activePlan.estimated_saving_inr)}
                  </p>
                </div>
                {activePlan.status === 'PENDING' && (
                  <div className="flex gap-2">
                    <button
                      onClick={() => approveMutation.mutate(activePlan.id)}
                      disabled={approveMutation.isPending}
                      className="bg-teal-600 text-white text-xs font-semibold py-1.5 px-3 rounded-md hover:bg-teal-700 disabled:opacity-50 transition-colors"
                    >
                      {approveMutation.isPending ? 'Approving...' : 'Approve All'}
                    </button>
                    <button
                      onClick={() => setDeferTarget(activePlan.id)}
                      className="bg-white text-gray-700 text-xs font-semibold py-1.5 px-3 rounded-md border border-gray-300 hover:bg-gray-50 transition-colors"
                    >
                      Defer
                    </button>
                  </div>
                )}
              </div>

              {activePlan.line_items.length === 0 ? (
                <p className="text-gray-400 text-sm text-center py-8">No line items in this plan.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 border-b border-gray-200">
                      <tr className="text-left text-xs font-medium text-gray-500 uppercase tracking-wide">
                        <th className="px-3 py-2">Medicine</th>
                        <th className="px-3 py-2">From</th>
                        <th className="px-3 py-2">To</th>
                        <th className="px-3 py-2">Qty</th>
                        <th className="px-3 py-2">Dist.</th>
                        <th className="px-3 py-2">Urgency</th>
                        <th className="px-3 py-2">Saving</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {activePlan.line_items.map((item: LineItem) => (
                        <tr key={item.id} className="hover:bg-gray-50">
                          <td className="px-3 py-2.5 font-medium text-gray-900 max-w-28 truncate">{item.medicine_name}</td>
                          <td className="px-3 py-2.5 text-gray-600 max-w-28 truncate">{item.from_facility_name}</td>
                          <td className="px-3 py-2.5 text-gray-600 max-w-28 truncate">{item.to_facility_name}</td>
                          <td className="px-3 py-2.5 font-semibold text-gray-900">{item.quantity.toLocaleString()}</td>
                          <td className="px-3 py-2.5 text-gray-500">{item.distance_km} km</td>
                          <td className="px-3 py-2.5">
                            <span className={clsx('text-xs', URGENCY_COLOR[item.urgency] ?? 'text-gray-600')}>
                              {item.urgency}
                            </span>
                          </td>
                          <td className="px-3 py-2.5 text-green-700 font-medium text-xs">
                            {formatCurrency(item.estimated_saving_inr)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot className="bg-gray-50 border-t border-gray-200">
                      <tr>
                        <td colSpan={6} className="px-3 py-2 text-xs font-semibold text-gray-700 text-right">
                          Total Savings:
                        </td>
                        <td className="px-3 py-2 text-sm font-bold text-green-700">
                          {formatCurrency(activePlan.estimated_saving_inr)}
                        </td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
