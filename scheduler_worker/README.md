# Scheduler Worker

An always-on worker that periodically pulls the next idea from a content
pool and drives a backend's own content-generation + publish endpoints on a
schedule -- "post a lesson video and an Instagram card carousel about X
every day," unattended. It is a standalone sibling to
[`social-media-worker`](../social-media-worker): that package publishes an
already-rendered video/images, this one is what decides *when* to generate
and publish something new.

It runs as its own process, deliberately separate from any publish-jobs
worker, so scaling the publisher to multiple replicas never duplicates this
loop's `setInterval` tick (which must run exactly once).

## Quick start

1. Use Node.js 18+ and run `npm install`.
2. Apply [`migrations/001_scheduler_jobs.sql`](./migrations/001_scheduler_jobs.sql) to your Supabase project.
3. Copy `.env.example` to `.env` and fill it in (see below).
4. Start it with `npm start`.

## Backend contract

This worker expects `BACKEND_INTERNAL_URL` to point at a backend that
exposes this exact endpoint set (Kara Tahta's own contract -- see
`services/scheduler.js` for the literal request/response shapes):

- `POST /api/cards/generate` -- NDJSON stream of `{type:"card"|"session"|"error"|"done", ...}`
- `POST /api/cards/sessions/:id/publish-instagram`
- `POST /api/generate-lesson` -- returns `{ id, lessonId }`
- `GET /api/jobs/:id` -- polled until `status` is `"done"` or `"failed"`
- `POST /api/social-publish` -- returns `{ publishJobId }`

All requests carry `X-Scheduler-Token: <SCHEDULER_INTERNAL_TOKEN>` instead of
a user session; the backend must resolve that shared secret to the identity
in `SCHEDULER_USER_ID`. If your backend doesn't share this exact contract,
either adapt `services/scheduler.js`'s three `run*` functions to your own
endpoints, or don't use this worker.

## Content pool

Ideas/topics live one-per-line in a plain-text object (`system/content_pool.txt`
by an S3-compatible bucket, e.g. Railway Bucket or Cloudflare R2 -- set the
`MEDIA_S3_*` variables). Each `job_type` (`cards_carousel`, `lesson_video`,
`combo`) advances through the list independently via its own
`scheduler_jobs.content_pool_cursor`, wrapping around when it reaches the end.

## Enabling/disabling jobs

Jobs are off by default (`enabled=false` in `scheduler_jobs`). Toggle them
from your own backend/admin tooling by updating that row directly, or by
exposing your own `/api/scheduler/start|stop`-style endpoints backed by the
same table (see Kara Tahta's `routes/scheduler.js` in
[`examples/karatahta`](../social-media-worker/examples/karatahta) in the
sibling package for a reference implementation) -- this worker itself has
no HTTP surface, it only polls `scheduler_jobs` on `SCHEDULER_TICK_MS`.

## Job types

- `cards_carousel`: generates a card sequence for the next pool idea, then
  publishes it as an Instagram carousel.
- `lesson_video`: generates a full video for the next pool idea, polls until
  it's done, then publishes it (YouTube + Instagram per your backend's
  `/api/social-publish`).
- `combo`: runs `lesson_video`, waits `SCHEDULER_COMBO_GAP_MS` (default 10
  minutes) so the video has time to actually appear, then runs
  `cards_carousel` for the same idea -- two posts, one topic, spaced apart.

## Custom stores

`services/schedulerStore.js` and `services/contentPool.js` are the only
places touching Supabase/S3 directly. Swap either file's implementation
(keep the same exported function signatures) to use a different database or
object store without touching `services/scheduler.js`.
