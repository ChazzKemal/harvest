# Web admin panel

The admin record (`out/admin.html`) as a live website: same views, readable from
any device on the internet. Built with Vite + React + Tailwind + [shadcn/ui](https://ui.shadcn.com).

It is safe to host publicly because it holds no secrets. The page signs the
visitor in with Google (Supabase auth) and queries with the publishable key;
the `*_read_admin` row-level-security policies in `supabase/schema.sql` open
the tables only to emails listed in the `admins` table. Everyone else — signed
in or not — gets nothing back from the database.

## One-time setup

1. Apply the current `supabase/schema.sql` in the Supabase SQL editor
   (idempotent — it adds the `admins` table and admin read policies).
2. Approve yourself:
   ```sql
   insert into admins (email) values ('you@company.com');
   ```
3. Deploy on Vercel (free tier):
   - vercel.com → Add New → Project → import this GitHub repo.
   - Framework preset: **Vite**. Root Directory: `web/admin`.
     (Build command `npm run build`, output `dist` — Vercel fills these in.)
   - Deploy. You get a URL like `https://<project>.vercel.app`.
4. Let Supabase redirect back to it: Supabase dashboard → Authentication →
   URL Configuration → add the Vercel URL to **Redirect URLs**.

Then open the URL from any device, sign in with your admin Google account,
and the record loads. Non-admin sign-ins are told they are not approved.

## Working on it

```sh
cd web/admin
npm install
npm run dev      # http://localhost:3000 — add it to Supabase Redirect URLs once
npm run build    # typecheck + production bundle in dist/
```

Layout: `src/App.tsx` (sign-in gate, shell, navigation), `src/components/views.tsx`
(the four views), `src/components/SessionCard.tsx` + `Thread.tsx` (a session's
conversation and diff), `src/lib/data.ts` (Supabase client, types, loading),
`src/lib/filters.ts`. Add shadcn components with `npx shadcn@latest add <name>`.

If the Supabase project ever changes, update the URL and publishable key at the
top of `src/lib/data.ts` — both are public client values, not secrets.
