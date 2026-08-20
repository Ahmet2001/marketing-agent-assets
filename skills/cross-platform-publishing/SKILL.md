---
name: cross-platform-publishing
description: Adapt approved content for Instagram, YouTube, TikTok, X, and Reddit while preserving the core message and respecting each platform’s format and community context. Use when preparing a publish plan or publish request.
---

# Cross-Platform Publishing

Adapt the message; do not duplicate it unchanged across channels.

## Workflow

1. Identify the canonical asset and its claim, audience, CTA, and approval status.
2. Select only platforms that fit the audience and format.
3. Produce a channel-specific hook, format, copy, CTA, and measurement intent.
4. State whether the action is a draft, requires human approval, or is ready to become a publish request.

## Output contract

When a post is approved for execution, produce payloads compatible with `schemas/publish_request.schema.json`. Use `video.publish` for video and `instagram.carousel` for 2–10 HTTPS JPEG images. Never include OAuth credentials in a payload.

## Boundaries

- Check platform manifest constraints before proposing an API action.
- X and Reddit community interaction must be contextual; do not turn a video caption into an unsolicited reply or post.
- The social-media worker executes approved jobs; it does not decide strategy or approval.
