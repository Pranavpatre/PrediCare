import { Routes, Route, Navigate, Outlet } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { LANGUAGES } from './i18n'
import { useAuthStore } from './stores/authStore'
import OfflineBanner from './components/OfflineBanner'
import BottomNav from './components/BottomNav'
import LoginPage from './pages/LoginPage'
import DailyEntryPage from './pages/DailyEntryPage'
import StockEntryPage from './pages/StockEntryPage'
import NotificationsPage from './pages/NotificationsPage'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token)
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

function LanguageToggle() {
  const { i18n } = useTranslation()
  return (
    <div className="flex items-center justify-end gap-1 px-4 py-2 bg-white border-b border-gray-100">
      {LANGUAGES.map((l) => (
        <button
          key={l.code}
          onClick={() => i18n.changeLanguage(l.code)}
          className={`text-xs font-semibold px-2.5 py-1 rounded-md transition-colors ${
            i18n.language === l.code ? 'bg-teal-600 text-white' : 'bg-gray-100 text-gray-600'
          }`}
        >
          {l.label}
        </button>
      ))}
    </div>
  )
}

function AppLayout() {
  return (
    <div className="pb-16">
      <LanguageToggle />
      <Outlet />
    </div>
  )
}

export default function App() {
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
        </Route>
        {/* Catch-all */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <BottomNav />
    </>
  )
}
