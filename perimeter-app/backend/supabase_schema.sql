-- =====================================================================
-- Perimeter — Supabase schema
-- Run this ONCE in the Supabase dashboard: SQL Editor -> paste -> Run.
--
-- Notes:
--   * All timestamps are TIMESTAMPTZ (UTC) to keep dwell math consistent.
--   * UNIQUE constraints on (event_id, user_id) make attendance and
--     check-ins idempotent — a flood of concurrent pings cannot create
--     duplicate rows or double-confirm someone.
--   * RLS is enabled with NO policies on every table. That means the
--     `anon`/`authenticated` roles (and therefore the anon key) can
--     access nothing. Only the service_role key — held by the backend —
--     can read/write, which it does by bypassing RLS. Even if the anon
--     key leaks, the data is safe.
-- =====================================================================

-- Events --------------------------------------------------------------------
create table if not exists public.events (
    id                bigint generated always as identity primary key,
    name              text not null check (char_length(name) between 1 and 100),
    polygon_json      jsonb not null,
    threshold_seconds integer not null default 60
                      check (threshold_seconds between 10 and 86400),
    created_at        timestamptz not null default now()
);

-- Active (unconfirmed) presence streaks -------------------------------------
create table if not exists public.check_ins (
    id            bigint generated always as identity primary key,
    event_id      bigint not null references public.events(id) on delete cascade,
    user_id       text not null check (char_length(user_id) between 1 and 64),
    entered_at    timestamptz not null,
    last_ping_at  timestamptz not null,
    last_lat      double precision not null,
    last_lng      double precision not null,
    last_accuracy double precision,
    unique (event_id, user_id)
);

-- Confirmed attendance ------------------------------------------------------
create table if not exists public.attendance_records (
    id           bigint generated always as identity primary key,
    event_id     bigint not null references public.events(id) on delete cascade,
    user_id      text not null check (char_length(user_id) between 1 and 64),
    confirmed_at timestamptz not null default now(),
    entered_at   timestamptz not null,
    unique (event_id, user_id)
);

-- Indexes for the hot query paths -------------------------------------------
create index if not exists idx_check_ins_event_user
    on public.check_ins (event_id, user_id);
create index if not exists idx_check_ins_last_ping
    on public.check_ins (event_id, last_ping_at);
create index if not exists idx_attendance_event
    on public.attendance_records (event_id);

-- Row-level security --------------------------------------------------------
alter table public.events              enable row level security;
alter table public.check_ins           enable row level security;
alter table public.attendance_records  enable row level security;

-- Deliberately NO policies: only service_role (backend) can access these.
-- If you later want the anon key to read events, add:
--   create policy "read events" on public.events
--     for select to anon using (true);