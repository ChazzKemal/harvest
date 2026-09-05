import { useEffect, useRef, useState } from "react"
import type { Session } from "@supabase/supabase-js"
import { Boxes, Diamond, HelpCircle, Lightbulb, LogOut, MessageSquare, SlidersHorizontal } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet"
import { Rail } from "./components/Rail"
import { AsksView, KnowledgeView, SessionsView, StuckView } from "./components/views"
import { load, sb, type Record } from "./lib/data"
import { EMPTY_FILTERS, type Filters } from "./lib/filters"

type View = "sessions" | "stuck" | "asks" | "knowledge"
const NAV: { id: View; label: string; icon: typeof Boxes; n: (d: Record) => number }[] = [
  { id: "sessions", label: "Sessions", icon: MessageSquare, n: d => d.chats.length },
  { id: "stuck", label: "Where people got stuck", icon: HelpCircle, n: d => d.corrections.length },
  { id: "asks", label: "What people asked for", icon: Lightbulb, n: d => d.asks.length },
  { id: "knowledge", label: "What is known", icon: Boxes, n: d => d.claims.length },
]

type State =
  | { kind: "gate"; email?: string }
  | { kind: "loading" }
  | { kind: "ready"; email: string; d: Record }

function Brand() {
  return (
    <div className="flex items-center gap-2.5 font-semibold tracking-tight">
      <span className="grid size-6 place-items-center rounded-md bg-orange-500 text-[11px] text-white">
        <Diamond className="size-3.5" />
      </span>
      Harvest
    </div>
  )
}

function Gate({ email }: { email?: string }) {
  const signIn = () => sb.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: location.origin + location.pathname },
  })
  return (
    <div className="grid min-h-screen place-items-center p-6">
      <Card className="w-full max-w-md text-center">
        <CardHeader className="items-center">
          <div className="mb-2 flex justify-center"><Brand /></div>
          <CardTitle className="text-2xl">The record</CardTitle>
          <CardDescription>
            {email ? <>
              Signed in as <b className="text-foreground">{email}</b>, which is not an admin.<br />
              An admin can approve it: <code className="font-mono text-xs">insert into admins (email) values ('...');</code>
            </> : "Sign in to read it. Only approved admins see anything."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={signIn} size="lg">{email ? "Try another account" : "Sign in with Google"}</Button>
        </CardContent>
      </Card>
    </div>
  )
}

export default function App() {
  const [state, setState] = useState<State>({ kind: "gate" })
  const [view, setView] = useState<View>("sessions")
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS)

  const started = useRef(false)

  useEffect(() => {
    const start = async (session: Session) => {
      if (started.current) return
      started.current = true
      setState({ kind: "loading" })
      const { data: admin, error } = await sb.rpc("is_admin")
      if (error || !admin) {
        setState({ kind: "gate", email: session.user.email })
        await sb.auth.signOut()
        started.current = false
        return
      }
      setState({ kind: "ready", email: session.user.email ?? "", d: await load() })
    }
    // INITIAL_SESSION covers a stored session, SIGNED_IN the OAuth return.
    // Deferred: supabase-js holds an internal lock while this callback runs,
    // so awaiting another auth-bound call inside it deadlocks.
    const { data: sub } = sb.auth.onAuthStateChange((_e, session) => {
      if (session) setTimeout(() => start(session), 0)
    })
    return () => sub.subscription.unsubscribe()
  }, [])

  if (state.kind === "gate") return <Gate email={state.email} />
  if (state.kind === "loading")
    return <div className="grid min-h-screen place-items-center text-sm text-muted-foreground">Loading the record…</div>

  const { d, email } = state
  const current = NAV.find(n => n.id === view)!
  const rail = <Rail d={d} f={filters} onChange={setFilters} showKnowledge={view === "knowledge"} />

  return (
    <div className="grid min-h-screen lg:grid-cols-[240px_minmax(0,1fr)_270px]">
      <aside className="hidden border-r bg-card p-3 lg:sticky lg:top-0 lg:block lg:h-screen">
        <div className="px-2 pb-5 pt-1"><Brand /></div>
        <div className="px-2 pb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">Everyone</div>
        <nav className="space-y-0.5">
          {NAV.map(n => (
            <Button key={n.id} variant={view === n.id ? "secondary" : "ghost"} size="sm"
                    className="w-full justify-start gap-2.5 font-normal" onClick={() => setView(n.id)}>
              <n.icon className="size-4 text-muted-foreground" />
              {n.label}
              <span className="ml-auto text-xs tabular-nums text-muted-foreground/70">{n.n(d)}</span>
            </Button>
          ))}
        </nav>
      </aside>

      <main className="min-w-0 pb-20">
        <header className="sticky top-0 z-10 flex items-center gap-2 border-b bg-background/95 px-4 py-3 text-sm backdrop-blur lg:px-8">
          <span className="lg:hidden"><Brand /></span>
          <b className="hidden font-medium lg:inline">All engineers</b>
          <span className="hidden text-muted-foreground/60 lg:inline">/</span>
          <span className="text-muted-foreground">{current.label}</span>
          <span className="ml-auto hidden text-xs text-muted-foreground/70 sm:inline">{email}</span>
          <Sheet>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" className="lg:hidden"><SlidersHorizontal className="size-4" /></Button>
            </SheetTrigger>
            <SheetContent side="right" className="overflow-y-auto p-5">
              <SheetTitle className="mb-4">Filters</SheetTitle>
              <nav className="mb-5 space-y-0.5">
                {NAV.map(n => (
                  <Button key={n.id} variant={view === n.id ? "secondary" : "ghost"} size="sm"
                          className="w-full justify-start gap-2.5 font-normal" onClick={() => setView(n.id)}>
                    <n.icon className="size-4 text-muted-foreground" />{n.label}
                    <span className="ml-auto text-xs tabular-nums text-muted-foreground/70">{n.n(d)}</span>
                  </Button>
                ))}
              </nav>
              <Separator className="mb-5" />
              {rail}
            </SheetContent>
          </Sheet>
          <Button variant="ghost" size="sm" className="text-muted-foreground"
                  onClick={async () => { await sb.auth.signOut(); location.reload() }}>
            <LogOut className="size-4" /><span className="hidden sm:inline">sign out</span>
          </Button>
        </header>
        <div className="max-w-4xl px-4 py-6 lg:px-8">
          {view === "sessions" && <SessionsView d={d} f={filters} />}
          {view === "stuck" && <StuckView d={d} f={filters} />}
          {view === "asks" && <AsksView d={d} f={filters} />}
          {view === "knowledge" && <KnowledgeView d={d} f={filters} />}
        </div>
      </main>

      <aside className="hidden border-l p-5 lg:sticky lg:top-0 lg:block lg:h-screen lg:overflow-y-auto">{rail}</aside>
    </div>
  )
}
