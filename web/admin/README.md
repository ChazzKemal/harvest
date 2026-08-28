# Web admin panel

The admin record (`out/admin.html`) as a live website: same views, same styling,
but readable from any device on the internet. One static file — `index.html`.

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
   - Framework preset: **Other**. Root Directory: `web/admin`. No build command.
   - Deploy. You get a URL like `https://<project>.vercel.app`.
4. Let Supabase redirect back to it: Supabase dashboard → Authentication →
   URL Configuration → add the Vercel URL to **Redirect URLs**.

Then open the URL from any device, sign in with your admin Google account,
and the record loads. Non-admin sign-ins are told they are not approved.

If the Supabase project ever changes, update `SUPABASE_URL` and
`SUPABASE_PUBLISHABLE_KEY` at the top of the `<script>` in `index.html` —
both are public client values, not secrets.
