import { ChevronDown } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Progress } from "@/components/ui/progress"
import { count, TYPE_LABELS, type Ask, type Chat, type Claim, type Correction, type Record } from "@/lib/data"
import { matches, matchesClaim, type Filters } from "@/lib/filters"
import { Empty } from "./Empty"
import { SessionCard } from "./SessionCard"

function Group({ label, n, children }: { label: string; n: number; children: React.ReactNode }) {
  if (n === 0) return null
  return (
    <Collapsible defaultOpen className="group/g mb-2">
      <CollapsibleTrigger className="mb-2.5 mt-5 flex items-center gap-2 text-[15px] font-semibold">
        {label}
        <span className="text-xs font-normal text-muted-foreground/70">{n}</span>
        <ChevronDown className="size-4 text-muted-foreground transition-transform group-data-[state=closed]/g:-rotate-90" />
      </CollapsibleTrigger>
      <CollapsibleContent>{children}</CollapsibleContent>
    </Collapsible>
  )
}

const Chip = ({ children }: { children: React.ReactNode }) =>
  <Badge variant="secondary" className="font-mono text-[10.5px]">{children}</Badge>

const Head = ({ children }: { children: React.ReactNode }) =>
  <div className="mb-2 flex flex-wrap items-center gap-2">{children}</div>

type ViewProps = { d: Record; f: Filters }

export function SessionsView({ d, f }: ViewProps) {
  const visible = d.chats.filter(r => matches(f, d.names[r.engineer] ?? "unknown", r))
  if (!visible.length)
    return <Empty>No sessions yet. They appear once someone has used a tool and signed in.</Empty>
  const sorted = [...visible].sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? ""))
  // Grouped by tool; sessions without one keep their own sub-groups by
  // engineer and project instead of collapsing into one bucket.
  const groups: { [k: string]: Chat[] } = {}
  for (const r of sorted) {
    const key = r.tool ||
      `No tool — ${d.names[r.engineer] ?? "unknown"}${r.project ? " · " + r.project : ""}`
    ;(groups[key] ??= []).push(r)
  }
  return Object.entries(groups)
    .sort((a, b) => (+a[0].startsWith("No tool") - +b[0].startsWith("No tool")) || b[1].length - a[1].length)
    .map(([label, rs]) => (
      <Group key={label} label={label} n={rs.length}>
        {rs.map(r => <SessionCard key={r.id} chat={r} who={d.names[r.engineer] ?? "unknown"} />)}
      </Group>
    ))
}

export function StuckView({ d, f }: ViewProps) {
  const visible = d.corrections.filter(r => matches(f, d.names[r.engineer] ?? "unknown", r))
  if (!visible.length)
    return <Empty>No corrections recorded yet. They appear once sessions have been summarised.</Empty>
  const byTool = count(visible, r => r.tool).slice(0, 10)
  const peak = Math.max(1, ...byTool.map(([, n]) => n))
  const sorted = [...visible].sort((a, b) => (b.corrected_on ?? "").localeCompare(a.corrected_on ?? ""))
  return <>
    <div className="mb-6 space-y-2">
      {byTool.map(([t, n]) => (
        <div key={t} className="flex items-center gap-3 text-sm">
          <span className="w-40 truncate">{t}</span>
          <Progress value={n / peak * 100} className="flex-1" />
          <span className="w-7 text-right tabular-nums text-muted-foreground">{n}</span>
        </div>
      ))}
    </div>
    {sorted.map((r: Correction) => (
      <Card key={r.id} className="mb-3">
        <CardContent>
          <Head>
            <b className="font-medium">{r.tool || "no tool"}</b>
            <Chip>{d.names[r.engineer] ?? "unknown"}</Chip>
            <Chip>{r.corrected_on}</Chip>
          </Head>
          <div className="text-sm text-muted-foreground">assumed — {r.agent_assumed}</div>
          <div className="mt-1 text-sm">they said — <b className="font-medium text-orange-400">{r.person_said}</b></div>
          {r.evidence && (
            <blockquote className="mt-2 border-l-2 pl-3 text-sm italic text-muted-foreground">{r.evidence}</blockquote>
          )}
        </CardContent>
      </Card>
    ))}
  </>
}

export function AsksView({ d, f }: ViewProps) {
  const visible = d.asks.filter(r => matches(f, d.names[r.engineer] ?? "unknown", r))
  if (!visible.length) return <Empty>Nothing asked for yet.</Empty>
  // One card per session, its asks as bullets, duplicates dropped.
  const bySession: { [k: string]: Ask[] } = {}
  for (const r of visible) (bySession[`${r.session_id ?? r.id}|${r.engineer}`] ??= []).push(r)
  return Object.values(bySession)
    .sort((a, b) => (+!!b[0].deliberate - +!!a[0].deliberate) ||
                    (b[0].asked_on ?? "").localeCompare(a[0].asked_on ?? ""))
    .map(rs => {
      const r = rs[0]
      const seen = new Set<string>()
      const bullets = rs.filter(x => {
        const t = (x.ask ?? "").trim().toLowerCase()
        if (!t || seen.has(t)) return false
        seen.add(t); return true
      })
      return (
        <Card key={`${r.session_id ?? r.id}|${r.engineer}`} className="mb-3">
          <CardContent>
            <Head>
              <Badge variant={r.deliberate ? "default" : "outline"}>
                {r.deliberate ? "asked for" : "from a session"}
              </Badge>
              <b className="font-medium">{r.tool || "no tool"}</b>
              <Chip>{d.names[r.engineer] ?? "unknown"}</Chip>
              <Chip>{r.asked_on}</Chip>
            </Head>
            <ul className="ml-4 list-disc space-y-1 text-sm">
              {bullets.map(x => <li key={x.id}>{x.ask}</li>)}
            </ul>
          </CardContent>
        </Card>
      )
    })
}

export function KnowledgeView({ d, f }: ViewProps) {
  const visible = d.claims.filter(r => matchesClaim(f, d.names[r.engineer] ?? "unknown", r))
  if (!visible.length) return <Empty>No claims yet.</Empty>
  const groups: { [k: string]: Claim[] } = {}
  for (const r of visible) (groups[r.tool || "no tool"] ??= []).push(r)
  return Object.entries(groups).sort((a, b) => b[1].length - a[1].length)
    .map(([tool, rs]) => (
      <Group key={tool} label={tool} n={rs.length}>
        {rs.map(r => (
          <Card key={r.id} className="mb-3">
            <CardContent>
              <Head>
                <b className="font-medium">{TYPE_LABELS[r.type] ?? r.type}</b>
                <Chip>{d.names[r.engineer] ?? "unknown"}</Chip>
                <Chip>{r.confidence}</Chip>
                {r.generalises && <Badge>generalises</Badge>}
              </Head>
              <div className="text-sm">{r.claim}</div>
              {r.why && <div className="mt-1 text-sm text-muted-foreground">why — {r.why}</div>}
            </CardContent>
          </Card>
        ))}
      </Group>
    ))
}
