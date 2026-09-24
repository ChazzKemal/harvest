import { ChevronDown } from "lucide-react"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { ago, type Turn } from "@/lib/data"
import { Empty } from "./Empty"

function Steps({ steps }: { steps: Turn[] }) {
  const tools = steps.filter(x => x.role === "tool")
  const says = steps.filter(x => x.role === "assistant")
  return (
    <Collapsible className="mb-3">
      <CollapsibleTrigger className="group flex w-full items-center gap-2 rounded-lg border bg-card px-4 py-2.5 text-left text-sm text-muted-foreground hover:text-foreground">
        {says.length} messages, {tools.length} tool calls
        <ChevronDown className="ml-auto size-4 transition-transform group-data-[state=open]:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent>
        {steps.map((x, i) => {
          if (x.role === "tool") return (
            <div key={i} className="ml-3.5 mt-2 border-l pl-3.5 py-1.5">
              <b className="font-medium">{x.kind === "exec" ? "ran" : "edited"}</b>{" "}
              <code className="font-mono text-xs break-all">{(x.text ?? "").slice(0, 400)}</code>
              {x.output && (
                <pre className="mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11.5px] text-muted-foreground/70">
                  {x.output.slice(0, 1200)}
                </pre>
              )}
            </div>
          )
          if (x.role === "reasoning" && x.text) return (
            <div key={i} className="ml-3.5 mt-2 border-l pl-3.5 py-1.5 text-sm italic text-muted-foreground/70">
              {x.text.slice(0, 600)}
            </div>
          )
          return null
        })}
      </CollapsibleContent>
    </Collapsible>
  )
}

export function Thread({ turns }: { turns: Turn[] }) {
  if (!turns.length) return <Empty>No transcript kept for this session.</Empty>

  const blocks: React.ReactNode[] = []
  let pending: Turn[] = []
  const flush = () => {
    if (!pending.length) return
    const key = blocks.length
    if (pending.some(x => x.role === "tool" || x.role === "reasoning"))
      blocks.push(<Steps key={`s${key}`} steps={pending} />)
    pending.filter(x => x.role === "assistant").forEach((x, i) =>
      blocks.push(
        <div key={`a${key}-${i}`} className="relative mb-3.5">
          <span className="absolute -left-11 top-0 grid size-6.5 place-items-center rounded-full border border-emerald-500/30 bg-emerald-950/60 text-[11px] font-semibold text-emerald-400">◈</span>
          <div className="whitespace-pre-wrap break-words py-0.5 text-sm leading-relaxed">{x.text}</div>
        </div>,
      ))
    pending = []
  }
  turns.forEach((t, i) => {
    if (t.role === "user") {
      flush()
      blocks.push(
        <div key={`u${i}`} className="relative mb-3.5">
          <span className="absolute -left-11 top-0 grid size-6.5 place-items-center rounded-full border border-orange-500/40 bg-orange-950/60 text-[11px] font-semibold text-orange-400">U</span>
          <div className="rounded-lg border bg-card px-4 py-3">
            <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">{t.text}</div>
            <div className="mt-2 text-xs text-muted-foreground/70">{ago(t.ts)}</div>
          </div>
        </div>,
      )
    } else pending.push(t)
  })
  flush()

  return (
    <div className="relative pl-11 before:absolute before:bottom-2 before:left-[15px] before:top-2 before:w-px before:bg-border">
      {blocks}
    </div>
  )
}
