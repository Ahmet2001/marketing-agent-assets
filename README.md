# Marketing Agent Assets

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Architecture](https://img.shields.io/badge/architecture-app%20%E2%86%94%20worker%20%E2%86%94%20agent-6f42c1)](./future_work.md)

Open-source building blocks for marketing systems that need to turn approved content into channel-ready assets and publish them safely. Use the deployable worker, platform toolboxes, LLM skills, and shared schemas independently—or combine them as the foundation for a marketing agent.

> Status: the worker, toolbox, schema, example, and skill layers are available. The marketing agent is planned, not implemented.

## Why this exists

Most marketing automation projects mix strategy, model prompts, tokens, browser sessions, publishing, and application data in one process. This repository keeps those concerns separate:

- **App** remains the source of truth for users, content, approvals, media, and rendering/video-generation capabilities.
- **Worker environment** provides bounded operational access to the app and external publishing APIs.
- **Agent** will reason over approved data and skills, then request validated actions rather than receiving secrets or unrestricted infrastructure access.

```text
App ⇄ Social-media worker environment ⇄ Marketing agent
```

Read the [future architecture and delivery plan](./future_work.md) for the responsibility map, security boundaries, and agent roadmap.

## What is included

| Area | What it provides |
| --- | --- |
| [`social-media-worker/`](./social-media-worker) | Node.js queue worker for video publishing and Instagram carousels. |
| [`toolboxes/`](./toolboxes) | Official-API and supervised-browser capabilities for X, Instagram, Reddit, and YouTube. |
| [`skills/`](./skills) | LLM decision guides for strategy, repurposing, publishing, engagement, and analysis. |
| [`schemas/`](./schemas) | Shared JSON contracts for assets, publish requests, and publish results. |
| [`examples/`](./examples) | Small, portable examples for campaigns, scheduling, and cross-platform content. |
| [`future_work.md`](./future_work.md) | Planned app → worker environment → agent transition. |

## Quick start: publish with the worker

The worker is intentionally independent of any specific app. Your backend creates a queue job with an HTTPS asset URL; the worker claims and publishes it.

```bash
git clone https://github.com/Ahmet2001/marketing-agent-assets.git
cd marketing-agent-assets/social-media-worker
cp .env.example .env
npm install
```

Apply [`migrations/001_publish_jobs.sql`](./social-media-worker/migrations/001_publish_jobs.sql) to the Supabase database used by the default adapter, configure the required platform credentials in `.env`, then run:

```bash
npm start
```

Create a video publishing job:

```json
{
  "action": "video.publish",
  "videoUrl": "https://cdn.example.com/launch.mp4",
  "title": "Launch day",
  "caption": "We are live.",
  "platforms": ["instagram", "youtube"],
  "privacyStatus": "public",
  "credentialRef": "brand-primary"
}
```

For a 2–10 slide Instagram carousel, submit `action: "instagram.carousel"` with HTTPS JPEG `imageUrls`. See the [cross-platform example](./examples/cross-platform-content/instagram-carousel.json) and the worker [README](./social-media-worker/README.md).

## Toolboxes: API first, browser supervised

Every platform toolbox is physically split into two modules:

```text
toolboxes/<platform>/
├── api/toolbox.py       # official API surface; production integration path
├── browser/toolbox.py   # Selenium; human-supervised local use only
├── manifest.yaml        # environment names, OAuth scopes, rate limits, actions
└── README.md
```

Use only `api/toolbox.py` in production workflows. Browser modules require an interactive signed-in session and must not be attached to a background worker. Check each platform’s `manifest.yaml` before enabling an action.

## Skills: decision quality, not execution

Skills are compact LLM instruction assets. They guide a marketing agent or another LLM integration; the worker does **not** load skills during publishing.

- [`social-content-strategy`](./skills/social-content-strategy/SKILL.md) — positioning, pillars, cadence, and experiments.
- [`content-repurposing`](./skills/content-repurposing/SKILL.md) — transform approved assets into clips, carousel narratives, and briefs.
- [`cross-platform-publishing`](./skills/cross-platform-publishing/SKILL.md) — adapt content and prepare schema-valid publish requests.
- [`community-engagement`](./skills/community-engagement/SKILL.md) — triage responses and escalate sensitive interactions.
- [`campaign-analysis`](./skills/campaign-analysis/SKILL.md) — interpret metrics and propose the next test.

## Shared contracts

Use the schemas as the boundary between applications, workers, toolboxes, and future agents:

- [`asset.schema.json`](./schemas/asset.schema.json) — approved media asset metadata.
- [`publish_request.schema.json`](./schemas/publish_request.schema.json) — actions a worker may execute.
- [`publish_result.schema.json`](./schemas/publish_result.schema.json) — normalized execution outcome.

Credentials, database access, and private signed URLs must never enter an LLM prompt or a public job payload.

## Current bridge and roadmap

The future agent will manage content creation, video-generation workflows, and publication decisions. Until it exists, the worker owns only a narrow, explainable algorithmic bridge: validation, media preparation, platform-format checks, queue execution, retries, and results.

It must not become an autonomous strategy or engagement engine. See [future_work.md](./future_work.md) for the phased migration plan.

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](./CONTRIBUTING.md) before opening a change. In particular, classify actions as API or browser, document OAuth and rate-limit implications, and never commit secrets or user data.

## License and source notice

This repository is licensed under the [MIT License](./LICENSE). Before reusing or contributing source modules, read [SOURCE_NOTICE.md](./SOURCE_NOTICE.md). Integrators are responsible for platform terms, user consent, app review, and authorization for every external write.
