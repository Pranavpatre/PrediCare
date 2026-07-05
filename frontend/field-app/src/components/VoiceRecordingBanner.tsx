/**
 * Fixed, high-contrast banner shown whenever voice input is actively
 * recording — unmissable regardless of scroll position, unlike a small
 * icon/text change that's easy to miss while holding the mic button.
 */
export default function VoiceRecordingBanner({ show, label }: { show: boolean; label: string }) {
  if (!show) return null
  return (
    <div className="fixed top-0 left-0 right-0 z-50 bg-red-600 text-white px-4 py-3 flex items-center justify-center gap-2 shadow-lg">
      <span className="relative flex h-3 w-3">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-white opacity-75" />
        <span className="relative inline-flex rounded-full h-3 w-3 bg-white" />
      </span>
      <span className="text-sm font-bold tracking-wide">{label}</span>
    </div>
  )
}
