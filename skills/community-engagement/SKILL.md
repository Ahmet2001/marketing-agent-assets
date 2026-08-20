---
name: community-engagement
description: Triage community interactions and draft safe, brand-aligned responses using approved platform data. Use for comment prioritization, response drafts, escalation, and moderation guidance—not unsupervised engagement automation.
---

# Community Engagement

Prioritize helpful, context-aware responses over interaction volume.

## Triage

Classify each item as one of: answerable question, constructive feedback, praise, support/privacy issue, abuse/spam, legal or policy issue, or high-risk claim.

## Output

For every proposed response, provide:

- recommended action: reply, hide/report, escalate, or no action;
- a concise draft in the brand voice;
- the reason and any uncertainty;
- whether human approval is required.

## Escalation and execution

- Require human approval for complaints involving payments, safety, health, legal claims, personal data, account access, or hostile escalation.
- Use only `api` actions in production. Browser actions in toolbox manifests remain supervised local-only.
- Never auto-follow, auto-vote, mass-reply, or bypass platform moderation controls.
