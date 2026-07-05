import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import HelpContent from '../components/HelpContent'

export default function HelpPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-gray-50 p-4 space-y-4 max-w-lg mx-auto pb-20">
      <div className="flex items-center justify-between pt-2">
        <div>
          <h1 className="text-xl font-bold text-teal-600">{t('help.title')}</h1>
          <p className="text-sm text-gray-500 mt-0.5">{t('help.subtitle')}</p>
        </div>
        <button
          onClick={() => navigate(-1)}
          className="shrink-0 w-10 h-10 rounded-full bg-white border border-gray-200 text-gray-600 font-bold text-lg shadow-sm hover:bg-gray-100 transition-colors"
          aria-label={t('help.close')}
        >
          ✕
        </button>
      </div>

      <HelpContent />
    </div>
  )
}
