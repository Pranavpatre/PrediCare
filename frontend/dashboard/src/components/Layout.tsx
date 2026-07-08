import { Outlet, NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '../stores/authStore'
import NavTour from './NavTour'
import LocationBadge from './LocationBadge'

const LANGUAGES = [
  { code: 'en', label: 'EN' },
  { code: 'hi', label: 'हि' },
  { code: 'mr', label: 'म' },
  { code: 'gu', label: 'ગુ' },
  { code: 'pa', label: 'ਪੰ' },
  { code: 'ta', label: 'த' },
  { code: 'ml', label: 'മ' },
  { code: 'te', label: 'తె' },
  { code: 'kn', label: 'ಕ' },
  { code: 'bn', label: 'বা' },
]

export default function Layout() {
  const { t, i18n } = useTranslation()
  const { name, role, logout, startNavTour } = useAuthStore()
  const isPhcAdmin = role === 'PHC_ADMIN'
  // Patient referral (create + retrieve) belongs in the field-worker app — that's
  // where patients physically check in. Admins monitor, they don't refer, so the
  // referral tabs are intentionally not in the dashboard nav. (Routes remain
  // reachable by direct URL for support/debugging.)

  const navClass = ({ isActive }: { isActive: boolean }) =>
    `px-4 py-2 rounded-md text-sm font-medium transition-colors ${
      isActive ? 'bg-teal-600 text-white' : 'text-gray-700 hover:bg-gray-100'
    }`

  return (
    <div className="min-h-screen flex flex-col">
      <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <span className="flex items-center gap-2">
            <img src="/favicon.svg" alt="" className="w-7 h-7 rounded-md" />
            <span className="font-bold text-teal-700 text-lg tracking-tight">PrediCare</span>
          </span>
          {isPhcAdmin ? (
            // PHC_ADMIN is scoped to one facility — the district-wide
            // dashboard/facilities/redistribution pages aren't queryable
            // for them, so only show their facility view + the assistant.
            <NavLink to="/my-facility" className={navClass}><span aria-hidden>🏥</span> {t('nav.myFacility')}</NavLink>
          ) : (
            <>
              <NavLink to="/dashboard" className={navClass}><span aria-hidden>📊</span> {t('nav.dashboard')}</NavLink>
              <NavLink to="/facilities" className={navClass}><span aria-hidden>🏥</span> {t('nav.facilities')}</NavLink>
              <NavLink to="/stock" className={navClass}><span aria-hidden>💊</span> {t('nav.stock')}</NavLink>
              <NavLink to="/planning" className={navClass}><span aria-hidden>🧭</span> {t('nav.planning')}</NavLink>
            </>
          )}
          <NavLink to="/assistant" className={navClass}><span aria-hidden>🤖</span> {t('nav.assistant')}</NavLink>
          {/* Diagnostics is an internal/dev tool — reachable directly at
              /diagnostics but intentionally not shown in the end-user nav. */}
        </div>
        <div className="flex items-center gap-3">
          <LocationBadge />
          {/* Language switcher */}
          <div className="flex items-center gap-1">
            {LANGUAGES.map((lang) => (
              <button
                key={lang.code}
                onClick={() => i18n.changeLanguage(lang.code)}
                className={`text-xs px-2 py-1 rounded transition-colors ${
                  i18n.language === lang.code
                    ? 'bg-teal-100 text-teal-700 font-semibold'
                    : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
                }`}
              >
                {lang.label}
              </button>
            ))}
          </div>
          {!isPhcAdmin && (
            <button
              onClick={startNavTour}
              title={t('tour.navLabel')}
              className="w-7 h-7 flex items-center justify-center rounded-full border border-gray-200 bg-gray-50 text-gray-600 font-bold text-xs hover:bg-gray-100 transition-colors"
            >
              ?
            </button>
          )}
          <span className="text-sm text-gray-600 border-l border-gray-200 pl-3">{name}</span>
          <button
            onClick={logout}
            className="text-sm text-red-600 hover:text-red-800 font-medium transition-colors"
          >
            {t('nav.logout')}
          </button>
        </div>
      </nav>
      <main className="flex-1 p-6">
        <Outlet />
      </main>
      {!isPhcAdmin && <NavTour />}
    </div>
  )
}
