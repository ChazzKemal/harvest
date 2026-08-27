-- Harvest knowledge store.
--
-- One rule shapes this whole file: an engineer reads only their own rows.
-- The admin view reads everything, and does it by connecting with the secret
-- key (sb_secret_…), which carries BYPASSRLS and skips every policy below.
-- So the policies here describe the ENGINEER's access, not yours.
--
-- Apply with:  psql "$SUPABASE_DB_URL" -f supabase/schema.sql
-- Idempotent — safe to re-run as the schema grows.

create extension if not exists pgcrypto;

-- Who is writing. One row per person, id matches their auth user.
create table if not exists engineers (
  id          uuid primary key references auth.users(id) on delete cascade,
  name        text not null,
  email       text unique not null,
  created_at  timestamptz not null default now()
);

-- A session that happened on someone's machine.
create table if not exists sessions (
  id          uuid primary key default gen_random_uuid(),
  engineer    uuid not null references engineers(id) on delete cascade,
  session_id  text not null,
  checkpoint  text,
  agent       text,
  model       text,
  -- tool and project are what the admin view filters on. They were derived
  -- from touched files before; here they are first-class so a filter is an
  -- index lookup rather than a guess at query time.
  tool        text,
  project     text,
  started_at  timestamptz,
  captured_at timestamptz not null default now(),
  unique (engineer, session_id)
);

-- What the session taught us. Shape mirrors claims.jsonl.
create table if not exists claims (
  id          uuid primary key default gen_random_uuid(),
  engineer    uuid not null references engineers(id) on delete cascade,
  session_id  text not null,
  type        text not null,
  claim       text not null,
  evidence    text default '',
  why         text default '',
  -- Kept because the MCP filters on them: only high-confidence claims that
  -- generalise should ever be fed to an agent building for someone else.
  confidence  text,
  generalises boolean default false,
  tool        text,
  project     text,
  claimed_on  date,
  created_at  timestamptz not null default now()
);

-- What people want built. Two sources, deliberately distinguished:
--   deliberate = false  -> Harvest inferred it from a session (high volume, noisy)
--   deliberate = true   -> someone typed it into a tool's feature box (rare, high intent)
-- Collapsing these loses the distinction that makes the second one worth having.
create table if not exists asks (
  id          uuid primary key default gen_random_uuid(),
  engineer    uuid references engineers(id) on delete cascade,
  session_id  text,
  ask         text not null,
  deliberate  boolean not null default false,
  tool        text,
  project     text,
  asked_on    date,
  created_at  timestamptz not null default now()
);

-- Where the agent assumed wrong and the person put it right. Rendered into the
-- reports before; kept as data here because "where did people get stuck" is a
-- question you answer by counting and filtering these, not by reading prose.
create table if not exists corrections (
  id            uuid primary key default gen_random_uuid(),
  engineer      uuid not null references engineers(id) on delete cascade,
  session_id    text not null,
  agent_assumed text not null,
  person_said   text not null,
  evidence      text default '',
  tool          text,
  project       text,
  corrected_on  date,
  created_at    timestamptz not null default now()
);

create index if not exists sessions_tool_idx  on sessions (tool);
create index if not exists claims_tool_idx    on claims (tool);
create index if not exists claims_eng_idx     on claims (engineer);
create index if not exists asks_tool_idx      on asks (tool);
create index if not exists asks_deliberate_idx on asks (deliberate);
create index if not exists corrections_tool_idx on corrections (tool);

-- ---------------------------------------------------------------- policies
-- Enabling RLS denies everything by default; each policy below re-opens one
-- narrow path. A table with RLS on and no policy is readable by nobody except
-- the secret key — which is the safe direction to fail in.

alter table engineers enable row level security;
alter table sessions  enable row level security;
alter table claims    enable row level security;
alter table asks      enable row level security;
alter table corrections enable row level security;

-- Force RLS even for the table owner, so a mistaken connection as the owning
-- role cannot quietly read everything. The secret key still bypasses.
alter table engineers force row level security;
alter table sessions  force row level security;
alter table claims    force row level security;
alter table asks      force row level security;
alter table corrections force row level security;

drop policy if exists engineers_read_self on engineers;
create policy engineers_read_self on engineers
  for select using (id = auth.uid());

-- Read: your own rows only. This is the line that carries the whole requirement.
drop policy if exists sessions_read_own on sessions;
create policy sessions_read_own on sessions
  for select using (engineer = auth.uid());

drop policy if exists claims_read_own on claims;
create policy claims_read_own on claims
  for select using (engineer = auth.uid());

drop policy if exists asks_read_own on asks;
create policy asks_read_own on asks
  for select using (engineer = auth.uid());

-- Write: your own rows only. WITH CHECK stops someone inserting a row
-- attributed to a colleague, which would otherwise be trivial — the engineer
-- column is just a value they send.
drop policy if exists corrections_read_own on corrections;
create policy corrections_read_own on corrections
  for select using (engineer = auth.uid());

drop policy if exists sessions_write_own on sessions;
create policy sessions_write_own on sessions
  for insert with check (engineer = auth.uid());

drop policy if exists claims_write_own on claims;
create policy claims_write_own on claims
  for insert with check (engineer = auth.uid());

drop policy if exists asks_write_own on asks;
create policy asks_write_own on asks
  for insert with check (engineer = auth.uid());

drop policy if exists corrections_write_own on corrections;
create policy corrections_write_own on corrections
  for insert with check (engineer = auth.uid());

-- No UPDATE and no DELETE policy anywhere, deliberately. The store is
-- append-only: nobody can rewrite or erase their own history, including by
-- accident. Corrections are new rows. You can still fix things with the
-- secret key when you genuinely need to.

-- ---------------------------------------------------------------- API keys
-- Read only by the issue-key function, which uses the secret key. No policy is
-- defined for either table, so with RLS on, nobody signed in can read them —
-- including the person whose key it is. That is deliberate: the key reaches
-- them through the endpoint, not through a query they could run themselves.
create table if not exists api_keys (
  engineer   uuid primary key references engineers(id) on delete cascade,
  key        text not null,
  revoked    boolean not null default false,
  created_at timestamptz not null default now()
);

-- Who may be issued a key at all. Default-deny: signing in creates an account,
-- but the issue-key function hands out nothing unless the person's email is in
-- this table (or they have their own api_keys row). Approve someone with:
--   insert into allowed_emails (email) values ('person@company.com');
-- The check is on the lowercased address, which the constraint below enforces
-- at insert time so an approval can never silently fail to match.
create table if not exists allowed_emails (
  email      text primary key check (email = lower(email)),
  added_at   timestamptz not null default now()
);

create table if not exists key_issues (
  id         uuid primary key default gen_random_uuid(),
  engineer   uuid not null references engineers(id) on delete cascade,
  issued_at  timestamptz not null default now()
);

alter table api_keys       enable row level security;
alter table key_issues     enable row level security;
alter table allowed_emails enable row level security;
alter table api_keys       force row level security;
alter table key_issues     force row level security;
alter table allowed_emails force row level security;

-- ------------------------------------------------------------- new sign-ins
-- Google creates an auth user; nothing creates the matching engineers row, and
-- every table's foreign key points at it — so without this the first upload
-- from a new person fails. Provisioning by hand used to cover this; sign-in
-- replaced it, and this replaces the provisioning.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = ''
as $$
begin
  insert into public.engineers (id, name, email)
  values (new.id,
          coalesce(new.raw_user_meta_data->>'name',
                   new.raw_user_meta_data->>'full_name',
                   new.email),
          new.email)
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ------------------------------------------------------------------- chats
-- The conversation itself, and the diff it produced. Everything else here is
-- extracted knowledge; this is the raw material.
--
-- Worth being deliberate about: these are people's actual transcripts and their
-- actual code. Uploading them is what lets the record show what happened rather
-- than only what was concluded — and it is also the moment their work leaves
-- their laptop. Same read rule as everything else: their own rows only.
create table if not exists chats (
  id          uuid primary key default gen_random_uuid(),
  engineer    uuid not null references engineers(id) on delete cascade,
  session_id  text not null,
  agent       text,
  model       text,
  tool        text,
  project     text,
  started_at  timestamptz,
  duration_s  integer,
  files       jsonb default '[]'::jsonb,
  commits     jsonb default '[]'::jsonb,
  added       integer default 0,
  removed     integer default 0,
  turns       jsonb default '[]'::jsonb,
  diff        text default '',
  updated_at  timestamptz not null default now(),
  unique (engineer, session_id)
);

create index if not exists chats_tool_idx on chats (tool);

alter table chats enable row level security;
alter table chats force row level security;

drop policy if exists chats_read_own on chats;
create policy chats_read_own on chats
  for select using (engineer = auth.uid());

drop policy if exists chats_write_own on chats;
create policy chats_write_own on chats
  for insert with check (engineer = auth.uid());

-- Chats are the one thing that legitimately changes after the fact: a session
-- reported mid-flight later gains its commits and diff. So unlike the rest of
-- the store, this table allows an update — of your own rows only.
drop policy if exists chats_update_own on chats;
create policy chats_update_own on chats
  for update using (engineer = auth.uid()) with check (engineer = auth.uid());

-- ----------------------------------------------------------------- batches
-- Re-running extraction on a session REPLACES its claims locally, but the store
-- is append-only, so the old ones stay. Without a way to tell which extraction
-- a row came from, the record shows superseded claims beside current ones.
--
-- One batch id per upload run. History is kept — the newest batch is what the
-- views show, and the older ones remain if anyone ever wants to look back.
alter table claims      add column if not exists batch uuid;
alter table corrections add column if not exists batch uuid;

create index if not exists claims_batch_idx      on claims (session_id, batch);
create index if not exists corrections_batch_idx on corrections (session_id, batch);
