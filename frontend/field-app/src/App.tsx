import { useEffect } from 'react'
import { Routes, Route, Navigate, Outlet, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { LANGUAGES } from './i18n'
import { useAuthStore } from './stores/authStore'
import { syncPendingData } from './sync/syncService'
import OfflineBanner from './components/OfflineBanner'
import BottomNav from './components/BottomNav'
import HelpModal from './components/HelpModal'
import LoginPage from './pages/LoginPage'
import DailyEntryPage from './pages/DailyEntryPage'
import StockEntryPage from './pages/StockEntryPage'
import NotificationsPage from './pages/NotificationsPage'
import LogsPage from './pages/LogsPage'
import HelpPage from './pages/HelpPage'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token)
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

function LanguageToggle() {
  const { t, i18n } = useTranslation()
  return (
    <div className="flex items-center justify-end gap-2 px-4 py-2 bg-white border-b border-gray-100">
      <Link
        to="/help"
        aria-label={t('help.navLabel')}
        className="w-8 h-8 flex items-center justify-center rounded-full border border-gray-200 bg-gray-50 text-gray-600 font-bold text-sm hover:bg-gray-100 transition-colors"
      >
        ?
      </Link>
      <select
        value={i18n.language}
        onChange={(e) => i18n.changeLanguage(e.target.value)}
        aria-label="Language"
        className="text-xs font-semibold px-2.5 py-1.5 rounded-md border border-gray-200 bg-gray-50 text-gray-700 focus:outline-none focus:border-teal-500"
      >
        {LANGUAGES.map((l) => (
          <option key={l.code} value={l.code}>
            {l.label}
          </option>
        ))}
      </select>
    </div>
  )
}

function WorkerHeader() {
  const { name, facilityName } = useAuthStore()
  if (!name && !facilityName) return null
  return (
    <div className="px-4 pt-2 bg-white">
      <p className="text-sm font-semibold text-gray-800">{name}</p>
      {facilityName && <p className="text-xs text-gray-400">{facilityName}</p>}
    </div>
  )
}

function AppLayout() {
  return (
    <div className="pb-16">
      <WorkerHeader />
      <LanguageToggle />
      <Outlet />
      <HelpModal />
    </div>
  )
}

export default function App() {
  // UI text stays on the default language (English) until the worker manually
  // picks one via the toggle — languagePref is still used for voice input,
  // where matching the worker's actual spoken language is a correctness need
  // rather than a display preference.

  // Auto-flush the offline queue the moment connectivity comes back, so the
  // manual "Sync Now" button is a reassurance/fallback, not a required step.
  useEffect(() => {
    const handleOnline = () => { syncPendingData() }
    window.addEventListener('online', handleOnline)
    return () => window.removeEventListener('online', handleOnline)
  }, [])

  return (
    <>
      <OfflineBanner />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <AppLayout />
            </ProtectedRoute>
          }
        >
          <Route index element={<Navigate to="/daily" replace />} />
          <Route path="daily" element={<DailyEntryPage />} />
          <Route path="stock" element={<StockEntryPage />} />
          <Route path="notifications" element={<NotificationsPage />} />
          <Route path="logs" element={<LogsPage />} />
          <Route path="help" element={<HelpPage />} />
        </Route>
        {/* Catch-all */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <BottomNav />
    </>
  )
}
