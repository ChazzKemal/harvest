export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed p-7 text-center text-sm text-muted-foreground">
      {children}
    </div>
  )
}
