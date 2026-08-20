create table if not exists publish_jobs (
  id uuid primary key default gen_random_uuid(),
  owner_ref text,
  status text not null default 'queued' check (status in ('queued', 'processing', 'done', 'failed')),
  payload jsonb not null,
  results jsonb not null default '{}'::jsonb,
  error text,
  attempts integer not null default 0,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  updated_at timestamptz not null default now()
);

create index if not exists publish_jobs_status_created_idx on publish_jobs(status, created_at);
alter table publish_jobs enable row level security;

-- Safe with multiple worker replicas: locked rows are skipped instead of
-- allowing two workers to claim the same queued job.
create or replace function claim_publish_job()
returns publish_jobs
language plpgsql
as $$
declare claimed publish_jobs;
begin
  with candidate as (
    select id from publish_jobs where status = 'queued'
    order by created_at asc for update skip locked limit 1
  )
  update publish_jobs job set
    status = 'processing', attempts = job.attempts + 1,
    started_at = now(), updated_at = now(), error = null
  from candidate where job.id = candidate.id
  returning job.* into claimed;
  return claimed;
end;
$$;
