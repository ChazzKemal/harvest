import { createClient } from "@supabase/supabase-js"

// Publishable key only: what lets an admin see everyone's rows is the admins
// table plus RLS, not anything in this bundle.
export const sb = createClient(
  "https://qxdtkrsyozmpbecyccjb.supabase.co",
  "sb_publishable_WBkhbCcAdTk1QEAW82N0bg_HL8RX5bz",
)

export type Turn = {
  role: "user" | "assistant" | "tool" | "reasoning"
  text?: string
  output?: string
  kind?: string
  ts?: string
}

type Attributed = { engineer: string; tool?: string; project?: string }
type Batched = { session_id?: string; batch?: string; created_at?: string }

export type Engineer = { id: string; name?: string; email?: string }
export type Chat = Attributed & {
  id: string
  started_at?: string
  turns?: Turn[]
  files?: string[]
  added?: number
  removed?: number
  commits?: string[]
  diff?: string
}
export type Claim = Attributed & Batched & {
  id: string
  type: string
  confidence: string
  generalises?: boolean
  claim: string
  why?: string
}
export type Correction = Attributed & Batched & {
  id: string
  corrected_on?: string
  agent_assumed?: string
  person_said?: string
  evidence?: string
}
export type Ask = Attributed & {
  id: string
  session_id?: string
  ask?: string
  deliberate?: boolean
  asked_on?: string
}

export type Record = {
  engineers: Engineer[]
  names: { [id: string]: string }
  claims: Claim[]
  corrections: Correction[]
  asks: Ask[]
  chats: Chat[]
}

export const TYPE_LABELS: { [k: string]: string } = {
  data_semantics: "What the data means",
  hygiene_rule: "Data hygiene",
  implicit_constraint: "Unmodelled constraints",
  objective_tradeoff: "What good looks like",
  acceptance_heuristic: "How they judge an answer",
  exception_override: "Manual overrides",
  vocabulary: "Vocabulary",
}

async function rows<T>(table: string): Promise<T[]> {
  const out: T[] = []
  for (let from = 0; ; from += 1000) {
    const { data, error } = await sb.from(table).select("*").range(from, from + 999)
    if (error) { console.error(table, error); break }
    out.push(...(data as T[]))
    if (data.length < 1000) break
  }
  return out
}

// Sessions get re-summarised; only the newest batch per session counts.
function latestBatch<T extends Batched>(rs: T[]): T[] {
  const newest: { [sid: string]: string } = {}
  for (const r of rs) {
    const sid = r.session_id ?? ""
    const w = r.created_at ?? ""
    if (w > (newest[sid] ?? "")) newest[sid] = w
  }
  const keep = new Set(rs.filter(r => (r.created_at ?? "") === newest[r.session_id ?? ""])
                         .map(r => r.batch))
  const batched = new Set(rs.filter(r => r.batch).map(r => r.session_id))
  return rs.filter(r => r.batch ? keep.has(r.batch) : !batched.has(r.session_id))
}

export async function load(): Promise<Record> {
  const [engineers, claims, corrections, asks, chats] = await Promise.all([
    rows<Engineer>("engineers"), rows<Claim>("claims"), rows<Correction>("corrections"),
    rows<Ask>("asks"), rows<Chat>("chats"),
  ])
  const names = Object.fromEntries(engineers.map(e => [e.id, e.name || e.email || "unknown"]))
  return { engineers, names, claims: latestBatch(claims),
           corrections: latestBatch(corrections), asks, chats }
}

export const ago = (iso?: string) => iso ? iso.slice(0, 16).replace("T", " ") : ""

export function count<T>(rs: T[], f: (r: T) => string | undefined): [string, number][] {
  const c: { [k: string]: number } = {}
  for (const r of rs) { const k = f(r); if (k) c[k] = (c[k] ?? 0) + 1 }
  return Object.entries(c).sort((a, b) => b[1] - a[1])
}
