import type { Claim } from "./data"

export type Filters = {
  who: Set<string>
  tool: Set<string>
  proj: Set<string>
  type: Set<string>
  conf: Set<string>
  gen: boolean
}

export const EMPTY_FILTERS: Filters = {
  who: new Set(), tool: new Set(), proj: new Set(), type: new Set(), conf: new Set(), gen: false,
}

// An empty set means "no constraint", same as an unticked rail.
const ok = (set: Set<string>, v: string) => set.size === 0 || set.has(v)

export function matches(f: Filters, who: string, r: { tool?: string; project?: string }) {
  return ok(f.who, who) && ok(f.tool, r.tool ?? "") && ok(f.proj, r.project ?? "")
}

export function matchesClaim(f: Filters, who: string, r: Claim) {
  return matches(f, who, r) && ok(f.type, r.type) && ok(f.conf, r.confidence)
    && (!f.gen || !!r.generalises)
}

export function toggled(set: Set<string>, v: string): Set<string> {
  const next = new Set(set)
  if (next.has(v)) next.delete(v); else next.add(v)
  return next
}
