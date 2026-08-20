# Marketing Agent Assets

Reusable, platform-aware building blocks for marketing systems. This repository separates publishing runtime code, platform toolboxes, shared contracts, and examples so adopters can use only the parts they need.

## Contents

- `social-media-worker/` — deployable Node.js queue worker for video publishing and Instagram carousels.
- `toolboxes/` — Python platform capabilities for X, Instagram, Reddit, and YouTube.
- `skills/` — reusable LLM decision guides for strategy, repurposing, publishing, engagement, and analysis.
- `schemas/` — versioned JSON contracts shared by producers, workers, and toolboxes.
- `examples/` — portable request examples.
- `agents/` — reserved for the later orchestration phase; no agent implementation is included yet.

## Toolbox safety boundary

Each toolbox manifest classifies actions as `api` or `browser`.

- `api` actions use an official platform API and are suitable for server-side integration when the application's OAuth scopes, review status, rate limits, and user authorization allow it.
- `browser` actions depend on Selenium and an interactive signed-in browser session. They are local, supervised-only tools and must not be enabled in a background production worker.

Each toolbox now has physical `api/toolbox.py` and `browser/toolbox.py` modules. The root `toolbox.py` is an API compatibility entry point; `legacy_combined_toolbox.py` is retained only for migration/reference and must not be used by new integrations.

## Contracts

Use [publish_request.schema.json](./schemas/publish_request.schema.json) to create work and [publish_result.schema.json](./schemas/publish_result.schema.json) to store its result. `asset.schema.json` defines the reusable media records referenced by requests.

## Current and target architecture

Today, the application creates approved publishing jobs and the social-media worker executes them. The future system has three cooperating components:

```text
App → Social-media worker → Marketing agent
```

- **App** owns users, source content, approval, and product-specific integrations.
- **Social-media worker** connects to the app through environment configuration and job contracts. It handles deterministic operational work: collecting configured content assets/data, validating media, preparing a job, and publishing approved video or carousel content. Until the agent exists, the worker also handles a deliberately small, algorithmic subset of operational decisions.
- **Marketing agent** is the planned reasoning layer. It will read approved toolbox data and skills, then handle content strategy, content creation, video-generation briefs, and publishing plans. It will create validated jobs for the worker rather than holding platform credentials in prompts.

The worker is not the strategy engine. Its temporary algorithmic responsibilities should shrink as the agent is introduced.

## Skills

Skills are LLM instruction assets, not servers or worker code. They guide an agent (or another LLM integration) when it analyzes evidence or produces plans. The worker does not load them while publishing.

- `social-content-strategy` — positioning, content pillars, cadence, and experiments.
- `content-repurposing` — derivatives such as clips, carousel narratives, and channel briefs.
- `cross-platform-publishing` — channel adaptation and validated publish-request preparation.
- `community-engagement` — safe response triage and human escalation.
- `campaign-analysis` — KPI interpretation and next experiments.

## Status

The worker, schemas, examples, toolboxes, and five initial skills are included. The agent implementation is intentionally deferred; its detailed state, scheduler, router, and prompt design belong in the later `future_work.md` planning stage.

## License and platform terms

Repository code is MIT licensed. Integrators remain responsible for platform terms, app review, OAuth consent, rate limits, and obtaining permission before any write action.

Read [SOURCE_NOTICE.md](./SOURCE_NOTICE.md) before making the repository public.
