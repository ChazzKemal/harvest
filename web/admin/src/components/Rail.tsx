import { Checkbox } from "@/components/ui/checkbox"
import { Separator } from "@/components/ui/separator"
import { count, TYPE_LABELS, type Record } from "@/lib/data"
import { toggled, type Filters } from "@/lib/filters"

type Props = {
  d: Record
  f: Filters
  onChange: (f: Filters) => void
  showKnowledge: boolean
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-5">
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</h4>
      {children}
    </div>
  )
}

function Boxes({ counts, on, toggle, labels }: {
  counts: [string, number][]
  on: Set<string>
  toggle: (v: string) => void
  labels?: { [k: string]: string }
}) {
  return <div className="space-y-1">
    {counts.map(([k, n]) => (
      <label key={k} className="flex cursor-pointer items-center gap-2.5 py-0.5 text-sm text-muted-foreground hover:text-foreground">
        <Checkbox checked={on.has(k)} onCheckedChange={() => toggle(k)} />
        <span className="truncate">{labels?.[k] ?? k}</span>
        <span className="ml-auto text-xs tabular-nums text-muted-foreground/70">{n}</span>
      </label>
    ))}
  </div>
}

export function Rail({ d, f, onChange, showKnowledge }: Props) {
  const everything = [...d.claims, ...d.corrections, ...d.asks, ...d.chats]
  const set = (k: "who" | "tool" | "proj" | "type" | "conf") => (v: string) =>
    onChange({ ...f, [k]: toggled(f[k], v) })
  return <>
    <Section title="Record">
      {[["People", d.engineers.length], ["Sessions", d.chats.length], ["Claims", d.claims.length],
        ["Corrections", d.corrections.length], ["Requests", d.asks.length]].map(([k, n]) => (
        <div key={k} className="flex justify-between py-1 text-sm text-muted-foreground">
          <span>{k}</span><b className="font-semibold tabular-nums text-foreground">{n}</b>
        </div>
      ))}
    </Section>
    <Separator className="mb-5" />
    <Section title="Person">
      <Boxes counts={count(everything, r => d.names[r.engineer] ?? "unknown")} on={f.who} toggle={set("who")} />
    </Section>
    <Section title="Tool">
      <Boxes counts={count(everything, r => r.tool)} on={f.tool} toggle={set("tool")} />
    </Section>
    <Section title="Project">
      <Boxes counts={count(everything, r => r.project)} on={f.proj} toggle={set("proj")} />
    </Section>
    {showKnowledge && <>
      <Separator className="mb-5" />
      <Section title="Type">
        <Boxes counts={count(d.claims, r => r.type)} on={f.type} toggle={set("type")} labels={TYPE_LABELS} />
      </Section>
      <Section title="Confidence">
        <Boxes counts={count(d.claims, r => r.confidence)} on={f.conf} toggle={set("conf")} />
      </Section>
      <Section title="Scope">
        <label className="flex cursor-pointer items-center gap-2.5 py-0.5 text-sm text-muted-foreground hover:text-foreground">
          <Checkbox checked={f.gen} onCheckedChange={v => onChange({ ...f, gen: v === true })} />
          Only claims that generalise
        </label>
      </Section>
    </>}
  </>
}
