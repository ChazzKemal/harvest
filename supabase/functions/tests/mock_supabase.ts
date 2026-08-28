// Test double for jsr:@supabase/supabase-js. The scenario object drives it.
export type Scenario = {
  user: { id: string; email: string | null } | null;
  apiKeyRow: { key: string | null; revoked: boolean } | null;
  allowedRow: { email: string } | null;
  issues: unknown[];
};

export const scenario: Scenario = {
  user: null,
  apiKeyRow: null,
  allowedRow: null,
  issues: [],
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
      // deno-lint-ignore no-explicit-any
      const result: any = table === "api_keys"
        ? scenario.apiKeyRow
        : table === "allowed_emails"
        ? scenario.allowedRow
        : null;
      return {
        select: (_cols: string) => ({
          eq: (_col: string, _val: unknown) => ({
            maybeSingle: () => Promise.resolve({ data: result, error: null }),
          }),
        }),
        insert: (row: unknown) => {
          scenario.issues.push(row);
          return Promise.resolve({ data: null, error: null });
        },
      };
    },
  };
}
