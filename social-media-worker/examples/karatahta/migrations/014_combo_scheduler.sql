-- Tek bir zamanlanmis dongude ayni konuyu once tam ders videosu (YouTube +
-- Instagram) olarak, 10 dakika sonra da ayni konudan kartlar->Instagram
-- carousel olarak yayinlayan birlesik "combo" is turu (bkz. services/scheduler.js
-- runCombo). cards_carousel/lesson_video ayri ayri da kullanilabilir kalir.
alter table scheduler_jobs
  drop constraint if exists scheduler_jobs_job_type_check;

alter table scheduler_jobs
  add constraint scheduler_jobs_job_type_check
  check (job_type in ('cards_carousel', 'lesson_video', 'combo'));

insert into scheduler_jobs (job_type, enabled, interval_minutes)
values ('combo', false, 180)
on conflict (job_type) do nothing;
