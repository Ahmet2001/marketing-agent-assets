-- Zamanlanmis icerik uretimi: content_pool.txt'ten (Railway Bucket) sirayla
-- fikir cekip "kart -> Instagram carousel" veya "tam ders -> YouTube +
-- Instagram" yayinlayan scheduler'in durumu. Scheduler dongusu
-- workers/socialPublisher.js icinde calisir (bkz. services/scheduler.js).
create table if not exists scheduler_jobs (
  job_type text primary key check (job_type in ('cards_carousel', 'lesson_video')),
  enabled boolean not null default false,
  interval_minutes integer not null default 1440,
  content_pool_cursor integer not null default 0,
  next_run_at timestamptz,
  last_run_at timestamptz,
  last_status text,
  last_error text,
  last_result jsonb,
  updated_at timestamptz not null default now()
);

insert into scheduler_jobs (job_type, enabled, interval_minutes)
values ('cards_carousel', false, 1440), ('lesson_video', false, 1440)
on conflict (job_type) do nothing;

alter table scheduler_jobs enable row level security;
