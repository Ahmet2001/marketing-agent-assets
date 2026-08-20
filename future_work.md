# Future work: App, Worker Environment, and Marketing Agent

## Goal

Evolve the current publishing-focused system into a three-part marketing workflow without turning the social-media worker into an opaque agent.

```text
App ⇄ Social-media worker environment ⇄ Marketing agent
```

The app remains the system of record. The worker environment provides bounded operational access to app-owned assets and data. The agent reasons over the approved context and requests explicit actions.

## Responsibility map

| Component | Owns | Does not own |
| --- | --- | --- |
| App | Users, authorization, source content, media storage, rendering/video-generation services, approval state, durable records | Marketing reasoning or direct platform automation policy |
| Social-media worker environment | App asset collection, approved data collection, media validation/preparation, job execution, platform API calls, retries, durable action results | Long-horizon strategy, uncontrolled planning, credentials in prompts |
| Marketing agent | Content strategy, content creation, repurposing, video-generation requests, campaign reasoning, publish recommendations | Direct secret access, unapproved external writes, source-of-truth ownership |

## Current bridge

The agent is not implemented yet. For now, the worker performs a small algorithmic subset of operational work so the system remains useful:

- validates and normalizes publish payloads;
- selects deterministic media preparation paths;
- enforces platform-specific format constraints;
- serializes/retries queue execution and records outcomes.

This bridge must remain deterministic, auditable, and narrow. It must not grow into content strategy, broad content generation, or autonomous engagement.

## Planned worker environment interface

The agent should access the app through explicit worker capabilities rather than direct database credentials.

1. `collect_assets` — return approved asset metadata using `schemas/asset.schema.json`.
2. `collect_platform_data` — retrieve only requested metrics, comments, or account data through manifest-approved API actions.
3. `prepare_media` — validate URLs, create short-lived access links, and prepare required output formats.
4. `request_video_generation` — ask the app's video-generation/rendering capability for a scoped job; the agent supplies a brief, not executable infrastructure commands.
5. `execute_publish` — accept a schema-valid, approved `publish_request` and return a `publish_result`.

Each capability should declare input schema, output schema, authorization requirement, rate-limit behavior, and audit event shape.

## Planned agent workflow

1. Receive a goal and user-approved campaign constraints from the app.
2. Ask the worker environment for the minimum relevant assets and data.
3. Load the relevant skill(s) and send only approved context to the selected LLM.
4. Produce content drafts, repurposing plans, or a video-generation brief.
5. Present external-write actions for approval when required.
6. Send approved, schema-valid actions to the worker environment.
7. Read normalized results and suggest the next iteration.

## Approval and security rules

- Platform tokens, database credentials, and private signed URLs never enter an LLM prompt.
- The app checks user ownership and approval before issuing a worker capability token or accepting a publish request.
- The worker validates action schemas and platform constraints again at execution time.
- Browser/Selenium toolbox actions remain local supervised-only; production agent workflows use only official API capabilities.
- Every external write records an actor, approval source, request payload fingerprint, result, and error state.

## Delivery phases

### Phase 1 — Stabilize contracts

- Version worker-environment request/result schemas.
- Add asset and data collection capabilities with least-privilege access.
- Define audit records, idempotency keys, and approval states.

### Phase 2 — Agent foundation

- Create `agents/marketing-agent` with router, state, scheduler, schemas, prompts, and `AGENT.md`.
- Make skill selection explicit and scoped to the requested workflow.
- Start with read-only strategy and content-draft workflows.

### Phase 3 — Controlled generation and publishing

- Connect approved video-generation requests to the app.
- Add approval-gated publish recommendations.
- Let the agent request worker execution through schema-valid jobs.

### Phase 4 — Reduce bridge logic

- Move content-oriented heuristics from the worker to the agent where they can be explained, reviewed, and evaluated.
- Keep only deterministic validation, collection, preparation, retry, and execution logic in the worker.

## Open decisions

- Which model providers may receive approved marketing context?
- What approval threshold applies to each platform and action type?
- How are per-user credentials stored and resolved by the worker environment?
- Which app data collection capabilities are necessary for the first agent release?
- What evaluation dataset defines acceptable content, video briefs, and publishing behavior?
