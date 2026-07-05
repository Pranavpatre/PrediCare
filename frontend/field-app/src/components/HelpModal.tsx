import { useTranslation } from 'react-i18next'
import { useAuthStore } from '../stores/authStore'
import HelpContent from './HelpContent'

export default function HelpModal() {
  const { t } = useTranslation()
  const justLoggedIn = useAuthStore((s) => s.justLoggedIn)
  const dismissLoginHelp = useAuthStore((s) => s.dismissLoginHelp)

  if (!justLoggedIn) return null

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div className="bg-gray-50 w-full sm:max-w-lg sm:rounded-2xl rounded-t-2xl max-h-[85vh] overflow-y-auto p-4 space-y-4">
        <div className="flex items-center justify-between pt-1">
          <div>
            <h1 className="text-xl font-bold text-teal-600">{t('help.title')}</h1>
            <p className="text-sm text-gray-500 mt-0.5">{t('help.subtitle')}</p>
          </div>
          <button
            onClick={dismissLoginHelp}
            className="shrink-0 w-10 h-10 rounded-full bg-white border border-gray-200 text-gray-600 font-bold text-lg shadow-sm hover:bg-gray-100 transition-colors"
            aria-label={t('help.close')}
          >
            ✕
          </button>
        </div>

        <HelpContent />

        <button
          onClick={dismissLoginHelp}
          className="w-full py-3 rounded-xl bg-teal-600 text-white font-semibold hover:bg-teal-700 transition-colors"
        >
          {t('help.close')}
        </button>
      </div>
    </div>
  )
}
