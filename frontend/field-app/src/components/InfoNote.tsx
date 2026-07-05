export default function InfoNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-start gap-1.5 text-xs text-gray-400 -mt-1">
      <span aria-hidden>ⓘ</span>
      <span>{children}</span>
    </p>
  )
}
