# Karatahta MCP Worker

An MCP server that exposes a backend's content-generation capabilities as
tools an AI agent can call directly: generate a lesson video, check on one
still rendering, or generate a set of teaching cards. Standalone sibling to
[`social-media-worker`](../social-media-worker) and
[`scheduler_worker`](../scheduler_worker) -- those publish/schedule content,
this one lets an agent *request* content on demand.

Runs as a stateless Streamable HTTP MCP server (`POST /mcp`), so any
MCP-over-HTTP client can connect once it has the URL and access token.

## Quick start

1. Use Node.js 18+ and run `npm install`.
2. Copy `.env.example` to `.env` and fill it in (see below).
3. Start it with `npm start`. It listens on `PORT` (default 8090) at `/mcp`.
4. Point your MCP client at `http://<host>:<port>/mcp` with header
   `Authorization: Bearer <MCP_SERVER_ACCESS_TOKEN>`.

## Tools

- **`generate_lesson_video`** -- `{ topic }` or `{ question }`, optional
  `student_level`/`target_video_minutes`/`target_segment_count`. Blocks
  (polling the backend) for up to `MCP_LESSON_WAIT_MS` (default 4 minutes)
  waiting for the render to finish, returning `{ status: "done", videoUrl,
  lessonId, jobId }`. If it's still running when the wait budget runs out,
  returns `{ status: "running", jobId, lessonId }` instead of hanging --
  the job keeps rendering server-side regardless.
- **`check_lesson_status`** -- `{ job_id }`. One-shot status check for a
  `jobId` returned above (progress, or the final `videoUrl` once done).
- **`generate_cards`** -- `{ topic }` or `{ question }`, optional
  `include_images` (default `false` -- card PNGs are base64 data URLs,
  large enough that most callers only want title/explanation text).
  Resolves quickly (seconds); not job-based like lesson videos.

## Backend contract

`services/karatahtaClient.js` expects `BACKEND_INTERNAL_URL` to expose:

- `POST /api/question-plan`, `POST /api/full-video`, `POST /api/generate-lesson`
- `GET /api/jobs/:id`
- `POST /api/cards/generate` (NDJSON stream: `{type:"card"|"session"|"error"|"done"}`)

authenticated via `X-Scheduler-Token: <MCP_BACKEND_TOKEN>` -- the same
shared-secret mechanism `scheduler_worker` uses; the backend must resolve
that header to a real user identity server-side (Kara Tahta's
`services/requestAuth.js` does this already). Point `BACKEND_INTERNAL_URL`
at any backend sharing this exact contract.

## Security

Two separate secrets, two separate directions:

- `MCP_SERVER_ACCESS_TOKEN` gates **inbound** calls -- who's allowed to call
  this MCP server at all. Required; the server refuses every request
  (fails closed) if it's unset.
- `MCP_BACKEND_TOKEN` is this worker's **outbound** credential to the target
  backend -- effectively "this worker acts as user `SCHEDULER_USER_ID`."

Never reuse one value for both.
