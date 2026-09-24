// Test double for jsr:@supabase/supabase-js. The scenario object drives it.
export type Scenario = {
  user: { id: string; email: string | null } | null;
  allowedRow: { email: string } | null;
  // Every write, in order: which table, what, and (for updates) which rows.
  writes: { table: string; op: "insert" | "update"; row: unknown; where?: [string, unknown] }[];
  // Make writes to this table fail.
  failTable: string | null;
};

export const scenario: Scenario = {
  user: null,
  allowedRow: null,
  writes: [],
  failTable: null,
};

export function createClient(_url: string, _key: string) {
  return {
    auth: {
      getUser: (_token: string) =>
        Promise.resolve(
          scenario.user
            ? { data: { user: scenario.user }, error: null }
            : { data: { user: null }, error: { message: "bad token" } },
        ),
    },
    from(table: string) {
      const outcome = () =>
        Promise.resolve(
          scenario.failTable === table
            ? { data: null, error: { message: "write failed" } }
            : { data: null, error: null },
        );
      return {
        select: (_cols: string) => ({
          eq: (_col: string, _val: unknown) => ({
            maybeSingle: () =>
              Promise.resolve({
                data: table === "allowed_emails" ? scenario.allowedRow : null,
                error: null,
              }),
          }),
        }),
        insert: (row: unknown) => {
          if (scenario.failTable !== table) scenario.writes.push({ table, op: "insert", row });
          return outcome();
        },
        update: (row: unknown) => ({
          eq: (col: string, val: unknown) => {
            if (scenario.failTable !== table) {
              scenario.writes.push({ table, op: "update", row, where: [col, val] });
            }
            return outcome();
          },
        }),
      };
    },
  };
}
