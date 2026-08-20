create table if not exists social_publish_jobs (
  id uuid primary key default gen_random_uuid(),
  lesson_id uuid not null references lessons(id) on delete cascade,
  video_id uuid not null references lesson_videos(id) on delete cascade,
  user_id uuid not null references profiles(id) on delete cascade,
  status text not null default 'queued' check (status in ('queued', 'processing', 'done', 'failed')),
  caption text,
  title text,
  description text,
  privacy_status text not null default 'private' check (privacy_status in ('private', 'unlisted', 'public')),
  attempts int not null default 0,
  instagram_result jsonb,
  youtube_result jsonb,
  error text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  updated_at timestamptz not null default now()
);

create index if not exists social_publish_jobs_status_created_idx
  on social_publish_jobs(status, created_at);

alter table social_publish_jobs enable row level security;

drop policy if exists "Users manage own social publish jobs" on social_publish_jobs;
create policy "Users manage own social publish jobs"
  on social_publish_jobs for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
