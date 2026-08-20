alter table social_publish_jobs
  drop constraint if exists social_publish_jobs_target_platform_check;

alter table social_publish_jobs
  add constraint social_publish_jobs_target_platform_check
  check (target_platform in ('instagram', 'youtube', 'tiktok', 'both'));

alter table social_publish_jobs
  add column if not exists tiktok_result jsonb;
