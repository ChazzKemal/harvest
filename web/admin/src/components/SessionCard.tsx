import { ChevronRight } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ago, type Chat } from "@/lib/data"
import { Empty } from "./Empty"
import { Thread } from "./Thread"

function Diff({ diff }: { diff: string }) {
  if (!diff.trim()) return <Empty>No code changes recorded for this session.</Empty>
  return (
    <ScrollArea className="max-h-[460px] overflow-auto rounded-lg border bg-background">
      <pre className="p-3.5 font-mono text-xs leading-normal">
        {diff.split("\n").slice(0, 2000).map((l, i) => {
          const cls = /^(diff |@@|index |--- |\+\+\+ )/.test(l) ? "text-sky-400"
                    : l.startsWith("+") ? "text-emerald-400"
                    : l.startsWith("-") ? "text-red-400" : ""
          return <span key={i} className={cls}>{l}{"\n"}</span>
        })}
      </pre>
    </ScrollArea>
  )
}

export function SessionCard({ chat, who }: { chat: Chat; who: string }) {
  const turns = chat.turns ?? []
  const asked = turns.filter(t => t.role === "user")
  const title = asked.length
    ? (asked[0].text ?? "").trim().split("\n")[0].slice(0, 90) : "no prompt recorded"
  const files = chat.files ?? []

  return (
    <Collapsible className="group mb-3 rounded-xl border bg-card">
      <CollapsibleTrigger className="flex w-full flex-col gap-1.5 px-4 py-3.5 text-left">
        <div className="flex flex-wrap items-center gap-2">
          <ChevronRight className="size-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-90" />
          <Badge variant="outline">{who}</Badge>
          <b className="font-medium">{chat.tool || "no tool"}</b>
          <Badge variant="secondary" className="font-mono text-[10.5px]">{ago(chat.started_at)}</Badge>
          {files.length > 0 && <>
            <Badge variant="secondary" className="font-mono text-[10.5px]">{files.length} file(s)</Badge>
            <Badge variant="secondary" className="font-mono text-[10.5px]">
              <span className="text-emerald-400">+{chat.added ?? 0}</span>&nbsp;
              <span className="text-red-400">−{chat.removed ?? 0}</span>
            </Badge>
          </>}
          {(chat.commits ?? []).length > 0 && <Badge>committed</Badge>}
        </div>
        <div className="pl-6 text-sm">{title}</div>
      </CollapsibleTrigger>
      <CollapsibleContent className="border-t px-4 pb-4 pt-3">
        <Tabs defaultValue="talk">
          <TabsList variant="line">
            <TabsTrigger value="talk">Conversation</TabsTrigger>
            <TabsTrigger value="code">What changed</TabsTrigger>
          </TabsList>
          <TabsContent value="talk" className="pt-3"><Thread turns={turns} /></TabsContent>
          <TabsContent value="code" className="space-y-3 pt-3">
            {files.length > 0 && (
              <div className="text-sm text-muted-foreground">{files.slice(0, 20).join(", ")}</div>
            )}
            <Diff diff={chat.diff ?? ""} />
          </TabsContent>
        </Tabs>
      </CollapsibleContent>
    </Collapsible>
  )
}
