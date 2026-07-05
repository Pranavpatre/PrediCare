import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { formatDistanceToNow } from 'date-fns'
import { db } from '../db/localDb'
import { fetchAndCacheNotifications } from '../sync/syncService'
import InfoNote from '../components/InfoNote'

interface Notification {
  id: string
  channel: string
  body: string
  template_key?: string | null
  template_params?: Record<string, string | number> | null
  created_at: string
  read: boolean
}

// Renders via i18n (reactively following the worker's currently selected
// language) when the server sent structured template data; otherwise falls
// back to the plain `body` text, which is only ever in one fixed language.
function notificationBody(n: Notification, t: (key: string, opts?: Record<string, unknown>) => string): string {
  if (n.template_key) return t(`notif.msg.${n.template_key}`, n.template_params ?? {})
  return n.body
}

export default function NotificationsPage() {
  const { t } = useTranslation()
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [loading, setLoading] = useState(true)

  const loadNotifications = useCallback(async () => {
    try {
      // Same issue as medicines: nothing previously populated the local
      // cache from the server, so this always read an empty table.
      await fetchAndCacheNotifications()
      const items = await db.notifications.orderBy('created_at').reverse().toArray()
      setNotifications(items)
    } catch (err) {
      console.error('[notifications] failed to load:', err)
      setNotifications([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadNotifications()
  }, [loadNotifications])

  const handleMarkRead = async (id: string) => {
    await db.notifications.update(id, { read: true })
    setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)))
  }

  const handleMarkAllRead = async () => {
    const unread = notifications.filter((n) => !n.read)
    await Promise.all(unread.map((n) => db.notifications.update(n.id, { read: true })))
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })))
  }

  const unreadCount = notifications.filter((n) => !n.read).length

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-gray-400 text-sm">{t('notif.loading')}</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50 max-w-lg mx-auto">
      {/* Header */}
      <div className="sticky top-0 bg-white border-b border-gray-100 px-4 py-3 flex items-center justify-between z-10">
        <div className="flex items-center gap-2">
          <h1 className="text-xl font-bold text-teal-600">{t('notif.title')}</h1>
          {unreadCount > 0 && (
            <span className="bg-teal-600 text-white text-xs font-bold px-2 py-0.5 rounded-full">
              {unreadCount}
            </span>
          )}
        </div>
        {unreadCount > 0 && (
          <button
            onClick={handleMarkAllRead}
            className="text-sm text-teal-600 font-medium hover:underline"
          >
            {t('notif.markAllRead')}
          </button>
        )}
      </div>

      {/* List */}
      <div className="p-4 space-y-3">
        <InfoNote>{t('info.notifications')}</InfoNote>
        {notifications.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 space-y-3">
            <span className="text-5xl" aria-hidden>🔔</span>
            <p className="text-gray-400 text-sm font-medium">{t('notif.empty')}</p>
            <p className="text-gray-300 text-xs text-center">
              {t('notif.emptyHint')}
            </p>
          </div>
        ) : (
          notifications.map((n) => (
            <button
              key={n.id}
              onClick={() => !n.read && handleMarkRead(n.id)}
              className={`w-full text-left rounded-2xl border p-4 space-y-1 transition-all ${
                n.read
                  ? 'bg-white border-gray-100 opacity-70'
                  : 'bg-white border-teal-200 shadow-sm'
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <p
                  className={`text-sm font-semibold leading-snug ${
                    n.read ? 'text-gray-600' : 'text-gray-900'
                  }`}
                >
                  {!n.read && (
                    <span className="inline-block w-2 h-2 bg-teal-500 rounded-full mr-2 align-middle" />
                  )}
                  {t(`notif.channel.${n.channel}`, n.channel)}
                </p>
                <span className="text-xs text-gray-400 whitespace-nowrap shrink-0">
                  {formatDistanceToNow(new Date(n.created_at), { addSuffix: true })}
                </span>
              </div>
              <p className="text-sm text-gray-500 leading-relaxed pl-4">{notificationBody(n, t)}</p>
              {!n.read && (
                <p className="text-xs text-teal-500 pl-4 font-medium">{t('notif.tapToRead')}</p>
              )}
            </button>
          ))
        )}
      </div>
    </div>
  )
}
