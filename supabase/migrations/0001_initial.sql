create table if not exists public.users (
  id bigserial primary key,
  telegram_user_id bigint not null unique,
  username varchar(255),
  created_at timestamp without time zone not null default now()
);

create table if not exists public.jobs (
  id bigserial primary key,
  user_id bigint not null references public.users(id),
  telegram_chat_id bigint not null,
  status varchar(32) not null default 'UPLOADED',
  source_audio_path text not null,
  source_audio_storage_key text,
  duration_seconds double precision,
  aspect_ratio varchar(16),
  style varchar(128),
  intensity varchar(32) not null default 'balanced',
  subtitle_style varchar(32) not null default 'dynamic',
  music_style varchar(32) not null default 'none',
  selected_provider varchar(32),
  selected_model varchar(255),
  transcript_json text,
  script_json text,
  plan_json text,
  estimated_cost numeric(10,6) not null default 0,
  reserved_cost numeric(10,6) not null default 0,
  actual_cost numeric(10,6) not null default 0,
  output_path text,
  output_storage_key text,
  created_at timestamp without time zone not null default now(),
  completed_at timestamp without time zone
);
create index if not exists ix_jobs_telegram_chat_id on public.jobs(telegram_chat_id);

create table if not exists public.scenes (
  id bigserial primary key,
  job_id bigint not null references public.jobs(id) on delete cascade,
  scene_index integer not null,
  duration_seconds integer not null,
  importance double precision not null default 0.5,
  provider varchar(32) not null default 'fal',
  model varchar(255) not null,
  prompt text not null,
  negative_prompt text not null default '',
  request_id varchar(255) unique,
  estimated_cost numeric(10,6) not null default 0,
  actual_cost numeric(10,6) not null default 0,
  ledger_id bigint,
  status varchar(32) not null default 'PLANNED',
  output_url text,
  output_storage_key text,
  constraint uq_job_scene unique(job_id, scene_index)
);
create index if not exists ix_scenes_job_id on public.scenes(job_id);

create table if not exists public.cost_ledger (
  id bigserial primary key,
  job_id bigint not null references public.jobs(id) on delete cascade,
  operation varchar(64) not null,
  provider varchar(32) not null,
  model varchar(255) not null,
  estimated_max_cost numeric(10,6) not null default 0,
  reserved_cost numeric(10,6) not null default 0,
  actual_cost numeric(10,6) not null default 0,
  currency varchar(8) not null default 'USD',
  status varchar(32) not null default 'RESERVED',
  created_at timestamp without time zone not null default now()
);
create index if not exists ix_cost_ledger_job_id on public.cost_ledger(job_id);

create table if not exists public.project_budget (
  id bigint primary key,
  spent numeric(10,6) not null default 0,
  reserved numeric(10,6) not null default 0,
  "limit" numeric(10,6) not null default 10
);
insert into public.project_budget(id, spent, reserved, "limit")
values (1, 0, 0, 10.00)
on conflict (id) do nothing;

create table if not exists public.telegram_updates (
  update_id bigint primary key,
  received_at timestamp without time zone not null default now()
);

-- Database is backend-only. Deny PostgREST access to anon/authenticated users.
alter table public.users enable row level security;
alter table public.jobs enable row level security;
alter table public.scenes enable row level security;
alter table public.cost_ledger enable row level security;
alter table public.project_budget enable row level security;
alter table public.telegram_updates enable row level security;

-- Private media bucket used through the server-side service role only.
insert into storage.buckets (id, name, public, file_size_limit)
values ('bot-media', 'bot-media', false, 104857600)
on conflict (id) do update set public = false;

-- Defense in depth: enforce the two budget invariants in PostgreSQL too.
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'ck_jobs_cost_hard_cap') then
    alter table public.jobs add constraint ck_jobs_cost_hard_cap
      check (estimated_cost >= 0 and reserved_cost >= 0 and actual_cost >= 0 and actual_cost + reserved_cost <= 5.00);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'ck_project_budget_hard_cap') then
    alter table public.project_budget add constraint ck_project_budget_hard_cap
      check (spent >= 0 and reserved >= 0 and "limit" >= 0 and spent + reserved <= "limit");
  end if;
  if not exists (select 1 from pg_constraint where conname = 'fk_scenes_ledger') then
    alter table public.scenes add constraint fk_scenes_ledger
      foreign key (ledger_id) references public.cost_ledger(id) on delete set null;
  end if;
end $$;

create index if not exists ix_scenes_ledger_id on public.scenes(ledger_id);
