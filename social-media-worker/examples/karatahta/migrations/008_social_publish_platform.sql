alter table social_publish_jobs
  add column if not exists target_platform text not null default 'both'
  check (target_platform in ('instagram', 'youtube', 'both'));

create index if not exists social_publish_jobs_platform_status_created_idx
  on social_publish_jobs(target_platform, status, created_at);
