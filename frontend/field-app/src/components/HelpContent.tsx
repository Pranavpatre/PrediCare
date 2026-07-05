import { useTranslation } from 'react-i18next'

export const HELP_SECTIONS: { icon: string; titleKey: string; descKey: string }[] = [
  { icon: '📋', titleKey: 'patient.title', descKey: 'info.patient' },
  { icon: '🔢', titleKey: 'footfall.title', descKey: 'info.footfall' },
  { icon: '📍', titleKey: 'checkin.title', descKey: 'checkin.hint' },
  { icon: '🩺', titleKey: 'attendance.title', descKey: 'info.attendance' },
  { icon: '🛏️', titleKey: 'beds.title', descKey: 'info.beds' },
  { icon: '🧪', titleKey: 'tests.title', descKey: 'info.tests' },
  { icon: '💊', titleKey: 'stock.title', descKey: 'info.stock' },
  { icon: '🔔', titleKey: 'notif.title', descKey: 'info.notifications' },
  { icon: '📜', titleKey: 'logs.title', descKey: 'help.logsDesc' },
  { icon: '🔄', titleKey: 'sync.now', descKey: 'info.sync' },
  { icon: '🎤', titleKey: 'help.voiceTitle', descKey: 'help.voiceDesc' },
  { icon: '🌐', titleKey: 'help.languageTitle', descKey: 'help.languageDesc' },
]

export default function HelpContent() {
  const { t } = useTranslation()
  return (
    <div className="space-y-3">
      {HELP_SECTIONS.map(({ icon, titleKey, descKey }) => (
        <div
          key={titleKey}
          className="bg-white rounded-2xl shadow-sm border border-gray-100 p-4 flex items-start gap-4"
        >
          <span className="text-3xl leading-none shrink-0" aria-hidden>
            {icon}
          </span>
          <div>
            <h2 className="text-base font-semibold text-gray-800">{t(titleKey)}</h2>
            <p className="text-sm text-gray-500 mt-1">{t(descKey)}</p>
          </div>
        </div>
      ))}
    </div>
  )
}
