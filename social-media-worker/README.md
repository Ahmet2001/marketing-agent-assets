# Social Media Publisher Worker

An application-agnostic Node.js worker that publishes a video to Instagram Reels, YouTube, and TikTok. It does not know your users, lessons, storage provider, or backend routes: your application places a standard job in a queue and supplies an HTTPS video URL.

## Quick start

1. Use Node.js 18+ and run `npm install`.
2. Apply [`migrations/001_publish_jobs.sql`](./migrations/001_publish_jobs.sql) to the database used by the default Supabase adapter.
3. Copy `.env.example` to `.env`, then set `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, and credentials for the platforms you will use.
4. Start it with `npm start`.

The default adapter reads the `publish_jobs` table. It requires a Supabase **server/secret** key; never put that key in a browser application.

## Job contract

Insert a queue job from your backend. `videoUrl` must be an HTTPS URL that the selected platforms can download. A signed S3/R2/Supabase URL is fine if its expiry exceeds the time needed to upload the video.

```sql
insert into publish_jobs (payload) values (
  '{
    "videoUrl": "https://cdn.example.com/videos/lesson.mp4",
    "title": "How vector addition works",
    "description": "A short explanation of vector addition.",
    "caption": "Vector addition in one minute #math",
    "platforms": ["youtube", "instagram"],
    "privacyStatus": "private",
    "credentialRef": "account_42"
  }'::jsonb
);
```

Required fields for the default `video.publish` action are `videoUrl` and `platforms`. `platforms` can contain `instagram`, `youtube`, and/or `tiktok`; `privacyStatus` is `private`, `unlisted`, or `public` (defaults to `private`). YouTube requires `title`.

For an Instagram carousel, use `action: "instagram.carousel"` and provide 2–10 HTTPS JPEG `imageUrls`; `platforms` is set to Instagram automatically:

```json
{
  "action": "instagram.carousel",
  "imageUrls": ["https://cdn.example.com/card-1.jpg", "https://cdn.example.com/card-2.jpg"],
  "caption": "Swipe through the lesson",
  "credentialRef": "account_42"
}
```

The worker writes platform outcomes to `results`, and changes the job status to `done` or `failed`. A job that partially publishes is marked `failed`, with successful platform results preserved for safe follow-up handling.

## Storage and security

The worker receives a URL rather than storage credentials, so it works with any storage provider. Set `ALLOWED_VIDEO_HOSTS` in production to a comma-separated allowlist such as `media.example.com,cdn.example.com`. The worker accepts HTTPS URLs only.

Do not put OAuth tokens in a job payload. For a single brand account, use environment variables. For a multi-tenant app, set `CREDENTIALS_PROVIDER_URL`: the worker POSTs `{ jobId, credentialRef, platforms }` to that private endpoint and uses the returned credentials only in memory. Protect that endpoint with `CREDENTIALS_PROVIDER_TOKEN` or your own network authentication.

## Custom queue adapter

Set `QUEUE_ADAPTER_MODULE` to an ESM module that exports:

```js
export async function claimNextJob() { /* return { id, payload } or null */ }
export async function finishJob({ jobId, results }) {}
export async function failJob({ jobId, results, error }) {}
```

This lets applications use PostgreSQL, BullMQ, SQS, or an internal API without changing the publishing code.

## Kara Tahta reference integration

The former Kara Tahta-specific scheduler, storage integration, and migration history are kept in [`examples/karatahta`](./examples/karatahta). They are a reference only, not part of the generic worker runtime. Its scheduler should be adapted separately because it calls Kara Tahta's lesson/card generation endpoints.

The legacy TikTok setup notes are in [`examples/karatahta/TIKTOK_KURULUM.md`](./examples/karatahta/TIKTOK_KURULUM.md). Never commit a real `.env` file.
