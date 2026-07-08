import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '../stores/authStore'

// Patient referral lives in the field app: the field worker creates a referral
// when a patient needs to go to the district hospital, and can retrieve an
// incoming referral (by code or phone+OTP) to share with the duty doctor.
const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

type Mode = 'new' | 'retrieve'

interface Referral {
  id: string; code: string; status: string; reason?: string | null
  from_facility?: string; to_facility?: string | null
  patient: { name: string; phone: string; sex?: string | null; year_of_birth?: number | null }
  clinical_summary?: Record<string, unknown> | null
  visit_notes?: { id: string; note: Record<string, string>; facility?: string; created_at?: string }[]
}

export default function ReferralsPage() {
  const { t } = useTranslation()
  const { token } = useAuthStore()
  const hdr = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }
  const [mode, setMode] = useState<Mode>('new')

  // create
  const [name, setName] = useState(''); const [phone, setPhone] = useState('')
  const [reason, setReason] = useState(''); const [created, setCreated] = useState<Referral | null>(null)
  const [busy, setBusy] = useState(false); const [err, setErr] = useState<string | null>(null)

  const create = async () => {
    setErr(null); setBusy(true); setCreated(null)
    try {
      const r = await fetch(`${API}/api/v1/referrals`, {
        method: 'POST', headers: hdr,
        body: JSON.stringify({ patient: { name: name.trim(), phone: phone.trim() }, reason: reason.trim() || undefined }),
      })
      if (!r.ok) throw new Error((await r.json())?.detail || 'Failed to create referral')
      setCreated(await r.json()); setName(''); setPhone(''); setReason('')
    } catch (e) { setErr(e instanceof Error ? e.message : 'Error') } finally { setBusy(false) }
  }

  // retrieve
  const [code, setCode] = useState(''); const [rPhone, setRPhone] = useState(''); const [otp, setOtp] = useState('')
  const [otpSent, setOtpSent] = useState(false); const [found, setFound] = useState<Referral | null>(null)
  const [info, setInfo] = useState<string | null>(null)

  const byCode = async () => {
    setErr(null); setInfo(null); setFound(null); setBusy(true)
    try {
      const r = await fetch(`${API}/api/v1/referrals/by-code/${code.trim().toUpperCase()}`, { headers: hdr })
      const d = await r.json()
      if (!r.ok) throw new Error(d?.detail || 'Not found')
      if (d.consent_required) setInfo(d.message || 'Consent required — use phone + OTP')
      else setFound(d)
    } catch (e) { setErr(e instanceof Error ? e.message : 'Error') } finally { setBusy(false) }
  }
  const sendOtp = async () => {
    setErr(null); setBusy(true)
    try {
      const r = await fetch(`${API}/api/v1/referrals/lookup/otp/request`, { method: 'POST', headers: hdr, body: JSON.stringify({ phone: rPhone.trim() }) })
      if (!r.ok) throw new Error('Failed to send OTP'); setOtpSent(true); setInfo('OTP sent (demo: 000000)')
    } catch (e) { setErr(e instanceof Error ? e.message : 'Error') } finally { setBusy(false) }
  }
  const verifyOtp = async () => {
    setErr(null); setInfo(null); setBusy(true); setFound(null)
    try {
      const r = await fetch(`${API}/api/v1/referrals/lookup/otp/verify`, { method: 'POST', headers: hdr, body: JSON.stringify({ phone: rPhone.trim(), otp: otp.trim() }) })
      const d = await r.json(); if (!r.ok) throw new Error(d?.detail || 'Invalid OTP')
      setFound((d.results && d.results[0]) || null); if (!d.results?.length) setInfo('No referral found for this phone')
    } catch (e) { setErr(e instanceof Error ? e.message : 'Error') } finally { setBusy(false) }
  }

  const input = 'w-full border-2 border-gray-200 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-teal-500'
  const btn = 'w-full py-3 rounded-xl bg-teal-600 text-white font-semibold disabled:opacity-40 hover:bg-teal-700 transition-colors'

  return (
    <div className="min-h-screen bg-gray-50 p-4 pb-20 max-w-2xl mx-auto space-y-4">
      <h1 className="text-xl font-bold text-teal-600 pt-2">{t('nav.referrals', 'Referrals')}</h1>
      <div className="flex gap-2">
        {(['new', 'retrieve'] as Mode[]).map((m) => (
          <button key={m} onClick={() => { setMode(m); setErr(null); setInfo(null) }}
            className={`flex-1 py-2 rounded-lg text-sm font-semibold ${mode === m ? 'bg-teal-600 text-white' : 'bg-white text-gray-600 border border-gray-200'}`}>
            {m === 'new' ? t('referral.new', 'New referral') : t('referral.retrieve', 'Retrieve')}
          </button>
        ))}
      </div>

      {err && <div className="bg-red-50 text-red-700 text-sm rounded-lg px-3 py-2">{err}</div>}
      {info && <div className="bg-amber-50 text-amber-700 text-sm rounded-lg px-3 py-2">{info}</div>}

      {mode === 'new' && (
        <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-5 space-y-3">
          <p className="text-xs text-gray-500">{t('referral.new_hint', 'Refer a patient to the district hospital. Share the code with the patient.')}</p>
          <input className={input} placeholder={t('referral.patient_name', 'Patient name')} value={name} onChange={(e) => setName(e.target.value)} />
          <input className={input} placeholder={t('referral.patient_phone', 'Patient phone')} value={phone} onChange={(e) => setPhone(e.target.value)} />
          <input className={input} placeholder={t('referral.reason_h', 'Reason')} value={reason} onChange={(e) => setReason(e.target.value)} />
          <button onClick={create} disabled={busy || !name.trim() || !phone.trim()} className={btn}>{busy ? '…' : t('referral.create', 'Create referral')}</button>
          {created && (
            <div className="mt-2 rounded-xl bg-teal-50 border border-teal-200 p-4 text-center">
              <p className="text-xs text-teal-700">{t('referral.code_label', 'Referral code')}</p>
              <p className="text-3xl font-bold tracking-widest text-teal-800 font-mono my-1">{created.code}</p>
              <p className="text-xs text-gray-500">{t('referral.code_share', 'Share this code with the patient / district hospital.')}</p>
            </div>
          )}
        </section>
      )}

      {mode === 'retrieve' && (
        <section className="bg-white rounded-2xl shadow-sm border border-gray-100 p-5 space-y-3">
          <div className="flex gap-2">
            <input className={`${input} font-mono uppercase`} placeholder={t('referral.tab_code', 'Code')} value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} />
            <button onClick={byCode} disabled={!code || busy} className="px-4 rounded-xl bg-teal-600 text-white text-sm font-semibold disabled:opacity-40">{t('referral.open', 'Open')}</button>
          </div>
          <div className="text-center text-xs text-gray-400">{t('referral.or', 'or')}</div>
          <div className="flex gap-2">
            <input className={input} placeholder={t('referral.patient_phone', 'Patient phone')} value={rPhone} onChange={(e) => setRPhone(e.target.value)} />
            {!otpSent
              ? <button onClick={sendOtp} disabled={!rPhone || busy} className="px-4 rounded-xl bg-teal-600 text-white text-sm font-semibold disabled:opacity-40">{t('referral.send_otp', 'Send OTP')}</button>
              : <button onClick={verifyOtp} disabled={!otp || busy} className="px-4 rounded-xl bg-teal-600 text-white text-sm font-semibold disabled:opacity-40">{t('referral.unlock', 'Unlock')}</button>}
          </div>
          {otpSent && <input className={`${input} font-mono tracking-widest`} placeholder="000000" value={otp} onChange={(e) => setOtp(e.target.value)} />}

          {found && (
            <div className="mt-2 rounded-xl border border-gray-200 p-4 space-y-2">
              <p className="font-bold text-gray-900">{found.patient.name} <span className="text-xs font-normal text-gray-400">{found.patient.phone}</span></p>
              <p className="text-xs text-gray-500">{found.from_facility} → {found.to_facility || t('referral.any_dh', 'any district hospital')} · {found.status}</p>
              {found.reason && <p className="text-sm text-gray-700"><b>{t('referral.reason_h', 'Reason')}:</b> {found.reason}</p>}
              {found.clinical_summary && Object.keys(found.clinical_summary).length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {Object.entries(found.clinical_summary).map(([k, v]) => (
                    <span key={k} className="text-xs bg-gray-50 border border-gray-200 rounded px-2 py-0.5">{k.replace(/_/g, ' ')}: {String(v)}</span>
                  ))}
                </div>
              )}
              <p className="text-xs text-teal-700">{t('referral.share_doctor', 'Share these details with the duty doctor.')}</p>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
